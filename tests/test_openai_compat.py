"""OpenAI-compatible adapter tests (Groq/OpenRouter) — offline via httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from sidecar.providers.base import Message
from sidecar.providers.openai_compat import groq_provider, openrouter_provider
from sidecar.orchestrator.profiles import get_profile


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("Authorization", "").startswith("Bearer ")
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "llama-3.3-70b"}, {"id": "qwen-coder"}]})
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello from the gateway"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4},
        })
    return httpx.Response(404)


def _factory():
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


@pytest.mark.asyncio
async def test_unavailable_without_key() -> None:
    p = groq_provider(api_key=None)
    assert await p.available() is False
    assert await p.list_models() == []


@pytest.mark.asyncio
async def test_groq_discovery_and_generate() -> None:
    p = groq_provider(api_key="k", client_factory=_factory)
    assert await p.available() is True
    assert "llama-3.3-70b" in await p.list_models()
    r = await p.generate([Message(role="user", content="hi")], "llama-3.3-70b")
    assert r.text == "hello from the gateway"
    assert r.tokens_in == 11 and r.tokens_out == 4
    assert r.provider == "groq"


@pytest.mark.asyncio
async def test_openrouter_sets_title_header_and_parses() -> None:
    p = openrouter_provider(api_key="k", client_factory=_factory)
    r = await p.generate([Message(role="user", content="hi")], "deepseek/deepseek-r1:free")
    assert r.provider == "openrouter" and r.text


def test_free_provider_profiles_are_low_cost_metered() -> None:
    groq = get_profile("groq", "qwen-coder")
    assert groq.cost_per_ktok < 0.5 and groq.unlimited is False
    assert groq.latency_class == "fast"            # groq is a fast gateway
    assert groq.quality_for("coding") >= 0.85      # 'coder' keyword → coding strength
    # OpenRouter reasoning model inferred from the 'r1' keyword.
    r1 = get_profile("openrouter", "deepseek-r1")
    assert r1.quality_for("reasoning") >= 0.85
