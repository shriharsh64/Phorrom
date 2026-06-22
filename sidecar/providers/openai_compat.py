"""OpenAI-compatible provider adapter (Groq, OpenRouter, Cerebras, … free tiers).

Problem solved: most free LLM gateways expose the OpenAI ``/chat/completions`` + ``/models``
shape, so one adapter covers them all — configured by base URL + key. Key-gated (no key →
unavailable, app still runs). Model catalogs are discovered live, never hardcoded (ADR-0002).

The HTTP client factory is injectable so the adapter is testable offline with
``httpx.MockTransport``.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from .base import Message, Provider, ProviderError, ProviderResponse, estimate_tokens

ClientFactory = Callable[[], httpx.AsyncClient]


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None,
        client_factory: ClientFactory | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._factory = client_factory or (lambda: httpx.AsyncClient())
        self._extra_headers = extra_headers or {}
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json", **self._extra_headers}

    async def available(self) -> bool:
        return bool(self._api_key)

    async def list_models(self) -> list[str]:
        if not self._api_key:
            return []
        try:
            async with self._factory() as client:
                resp = await client.get(f"{self._base}/models", headers=self._headers(),
                                        timeout=10.0)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError):
            return []
        return [m["id"] for m in data.get("data", []) if "id" in m]

    async def generate(self, messages: list[Message], model: str, **opts: Any) -> ProviderResponse:
        if not self._api_key:
            raise ProviderError(f"{self.name} API key not configured")
        body = {"model": model, "messages": [m.model_dump() for m in messages]}
        if "temperature" in opts:
            body["temperature"] = opts["temperature"]
        start = time.perf_counter()
        try:
            async with self._factory() as client:
                resp = await client.post(f"{self._base}/chat/completions", headers=self._headers(),
                                         json=body, timeout=self._timeout)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000.0

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected {self.name} response: {data}") from exc
        usage = data.get("usage", {})
        tokens_in = int(usage.get("prompt_tokens") or estimate_tokens(
            "\n".join(m.content for m in messages)))
        tokens_out = int(usage.get("completion_tokens") or estimate_tokens(text))
        return ProviderResponse(text=text, tokens_in=tokens_in, tokens_out=tokens_out,
                                latency_ms=latency_ms, provider=self.name, model=model)


# --- concrete free-tier gateways -------------------------------------------------------------
def groq_provider(api_key: str | None, client_factory: ClientFactory | None = None) -> OpenAICompatProvider:
    return OpenAICompatProvider("groq", "https://api.groq.com/openai/v1", api_key, client_factory)


def openrouter_provider(
    api_key: str | None, client_factory: ClientFactory | None = None, referer: str | None = None
) -> OpenAICompatProvider:
    headers = {"HTTP-Referer": referer, "X-Title": "Phorrom"} if referer else {"X-Title": "Phorrom"}
    return OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", api_key,
                                client_factory, extra_headers=headers)
