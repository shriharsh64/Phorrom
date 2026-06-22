"""Resilience: per-provider circuit breaker + retry/backoff + failover.

Problem solved: free tiers rate-limit, time out, and disappear. Execution must degrade
gracefully — retry transient errors, stop hammering a failing provider (open its circuit), and
fail over to the next-best candidate (ultimately a local/free model) instead of erroring out.

- CircuitBreaker: closed → open after N consecutive failures → half-open after a cooldown
  (one trial) → closed on success. Clock is injectable for deterministic tests.
- ResilientExecutor: try ordered candidates, skipping providers whose circuit is open, retrying
  transient ProviderErrors with exponential backoff, recording outcomes, returning the first
  success (with a record of what it failed over from).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..providers.base import Message, ProviderError, ProviderResponse
from ..providers.registry import ProviderRegistry
from .router import Candidate


@dataclass
class CircuitBreaker:
    threshold: int = 3            # consecutive failures before opening
    cooldown: float = 30.0        # seconds the circuit stays open
    clock: Callable[[], float] = time.monotonic
    _fails: dict[str, int] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)

    def allow(self, provider: str) -> bool:
        opened = self._opened_at.get(provider)
        if opened is None:
            return True
        return (self.clock() - opened) >= self.cooldown  # half-open trial after cooldown

    def state(self, provider: str) -> str:
        opened = self._opened_at.get(provider)
        if opened is None:
            return "closed"
        return "half_open" if (self.clock() - opened) >= self.cooldown else "open"

    def record_success(self, provider: str) -> None:
        self._fails.pop(provider, None)
        self._opened_at.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        n = self._fails.get(provider, 0) + 1
        self._fails[provider] = n
        if n >= self.threshold:
            self._opened_at[provider] = self.clock()

    def snapshot(self) -> dict[str, dict]:
        return {p: {"state": self.state(p), "fails": self._fails.get(p, 0)}
                for p in set(self._fails) | set(self._opened_at)}


@dataclass
class ExecOutcome:
    response: ProviderResponse
    provider: str
    model: str
    attempts: int
    failed_over_from: list[str] = field(default_factory=list)


class ResilientExecutor:
    def __init__(
        self,
        breaker: CircuitBreaker | None = None,
        retries: int = 1,
        backoff_base: float = 0.2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.breaker = breaker or CircuitBreaker()
        self.retries = retries
        self.backoff_base = backoff_base
        self._sleep = sleep

    async def generate(
        self, registry: ProviderRegistry, messages: list[Message], candidates: list[Candidate]
    ) -> ExecOutcome:
        """Try candidates in order; return the first success or raise if all fail."""

        failed_over: list[str] = []
        total_attempts = 0
        last_err: Exception | None = None

        for c in candidates:
            if not self.breaker.allow(c.provider):
                failed_over.append(f"{c.provider}/{c.model} (circuit open)")
                continue
            prov = registry.get(c.provider)
            if prov is None or not await prov.available():
                failed_over.append(f"{c.provider}/{c.model} (unavailable)")
                continue

            for attempt in range(self.retries + 1):
                total_attempts += 1
                try:
                    resp = await prov.generate(messages, c.model)
                    self.breaker.record_success(c.provider)
                    return ExecOutcome(resp, c.provider, c.model, total_attempts, failed_over)
                except ProviderError as exc:
                    last_err = exc
                    if attempt < self.retries:
                        await self._sleep(self.backoff_base * (2 ** attempt))  # backoff + retry
                        continue
                    self.breaker.record_failure(c.provider)  # exhausted retries → count failure
                    failed_over.append(f"{c.provider}/{c.model} ({exc})")
                    break

        raise ProviderError(
            f"all candidates failed/exhausted: {failed_over}") from last_err
