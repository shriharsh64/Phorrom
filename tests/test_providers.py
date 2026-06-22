"""Provider-layer tests — all offline against the mock adapter + registry discovery."""

from __future__ import annotations

import pytest

from sidecar.providers.base import Message, estimate_tokens
from sidecar.providers.gemini import GeminiProvider
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry


@pytest.mark.asyncio
async def test_mock_generate_is_deterministic() -> None:
    p = MockProvider()
    msgs = [Message(role="user", content="hello world")]
    r1 = await p.generate(msgs, "mock-small")
    r2 = await p.generate(msgs, "mock-small")
    assert r1.text == r2.text == "[mock:mock-small] hello world"
    assert r1.tokens_in == r2.tokens_in
    assert r1.tokens_out > 0
    assert r1.provider == "mock"


@pytest.mark.asyncio
async def test_mock_always_available_and_lists_models() -> None:
    p = MockProvider()
    assert await p.available() is True
    assert "mock-small" in await p.list_models()


@pytest.mark.asyncio
async def test_gemini_unavailable_without_key() -> None:
    p = GeminiProvider(api_key=None)
    assert await p.available() is False
    assert await p.list_models() == []


@pytest.mark.asyncio
async def test_registry_discovery_marks_availability() -> None:
    reg = ProviderRegistry([MockProvider(), GeminiProvider(api_key=None)])
    discovered = {d["provider"]: d for d in await reg.discover()}
    assert discovered["mock"]["available"] is True
    assert discovered["mock"]["models"]
    assert discovered["gemini"]["available"] is False
    assert discovered["gemini"]["models"] == []


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("a" * 400) == 100
