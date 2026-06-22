"""Resilience tests — circuit breaker states + retry/backoff + failover."""

from __future__ import annotations

from typing import Any

import pytest

from sidecar.orchestrator.resilience import CircuitBreaker, ResilientExecutor
from sidecar.orchestrator.router import Candidate
from sidecar.providers.base import Message, Provider, ProviderError, ProviderResponse
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry


class FailingProvider(Provider):
    name = "flaky"

    def __init__(self, fail_times: int = 999) -> None:
        self.calls = 0
        self.fail_times = fail_times

    async def available(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["flaky-1"]

    async def generate(self, messages, model, **opts: Any) -> ProviderResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("simulated outage")
        return ProviderResponse(text="recovered", tokens_in=1, tokens_out=1, latency_ms=1.0,
                                provider=self.name, model=model)


# --------------------------------------------------------------------------- circuit breaker

def test_breaker_opens_after_threshold_then_half_opens() -> None:
    t = [0.0]
    cb = CircuitBreaker(threshold=2, cooldown=10.0, clock=lambda: t[0])
    assert cb.allow("p") and cb.state("p") == "closed"
    cb.record_failure("p")
    assert cb.state("p") == "closed"  # 1 < threshold
    cb.record_failure("p")
    assert cb.state("p") == "open" and cb.allow("p") is False
    t[0] = 11.0  # past cooldown
    assert cb.state("p") == "half_open" and cb.allow("p") is True
    cb.record_success("p")
    assert cb.state("p") == "closed"


# --------------------------------------------------------------------------- executor

async def _nosleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_retry_then_succeed_on_same_provider() -> None:
    flaky = FailingProvider(fail_times=1)  # fails once, then succeeds
    reg = ProviderRegistry([flaky])
    ex = ResilientExecutor(retries=2, sleep=_nosleep)
    out = await ex.generate(reg, [Message(role="user", content="hi")], [Candidate("flaky", "flaky-1")])
    assert out.response.text == "recovered"
    assert out.attempts == 2  # one failure + one success


@pytest.mark.asyncio
async def test_failover_to_next_provider_and_opens_circuit() -> None:
    flaky = FailingProvider(fail_times=999)  # always down
    reg = ProviderRegistry([flaky, MockProvider()])
    cb = CircuitBreaker(threshold=1)
    ex = ResilientExecutor(breaker=cb, retries=0, sleep=_nosleep)
    out = await ex.generate(
        reg, [Message(role="user", content="ping")],
        [Candidate("flaky", "flaky-1"), Candidate("mock", "mock-small")],
    )
    assert out.provider == "mock"               # failed over to a working provider
    assert any("flaky" in f for f in out.failed_over_from)
    assert cb.state("flaky") == "open"          # flaky's circuit tripped


@pytest.mark.asyncio
async def test_open_circuit_is_skipped() -> None:
    flaky = FailingProvider(fail_times=999)
    reg = ProviderRegistry([flaky, MockProvider()])
    cb = CircuitBreaker(threshold=1, cooldown=999)
    cb.record_failure("flaky")  # pre-open the circuit
    ex = ResilientExecutor(breaker=cb, retries=0, sleep=_nosleep)
    out = await ex.generate(
        reg, [Message(role="user", content="x")],
        [Candidate("flaky", "flaky-1"), Candidate("mock", "mock-small")],
    )
    assert out.provider == "mock"
    assert flaky.calls == 0  # never even tried — circuit was open


@pytest.mark.asyncio
async def test_all_fail_raises() -> None:
    reg = ProviderRegistry([FailingProvider(fail_times=999)])
    ex = ResilientExecutor(retries=0, sleep=_nosleep)
    with pytest.raises(ProviderError):
        await ex.generate(reg, [Message(role="user", content="x")], [Candidate("flaky", "flaky-1")])
