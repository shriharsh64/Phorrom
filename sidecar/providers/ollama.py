"""Ollama adapter — local, unlimited, primary for sensitive/heavy work.

Problem solved: run models entirely on the user's machine (offline, private, ₹0). Available
only when the Ollama daemon is reachable on its localhost port; otherwise the adapter simply
reports unavailable and the app falls back to other providers.

Inputs : chat messages + a local model tag (e.g. "llama3.2:1b").
Outputs: ProviderResponse using Ollama's reported token counts when present.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import Message, Provider, ProviderError, ProviderResponse, estimate_tokens

DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 120.0) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError:
            return []
        return [m["name"] for m in data.get("models", []) if "name" in m]

    async def generate(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> ProviderResponse:
        payload = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "options": opts.get("options", {}),
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._host}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"Ollama request failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000.0

        text = data.get("message", {}).get("content", "")
        tokens_in = int(data.get("prompt_eval_count") or estimate_tokens(
            "\n".join(m.content for m in messages)
        ))
        tokens_out = int(data.get("eval_count") or estimate_tokens(text))
        return ProviderResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            provider=self.name,
            model=model,
        )
