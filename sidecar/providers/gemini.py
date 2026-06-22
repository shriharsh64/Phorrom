"""Google AI Studio (Gemini) adapter — free tier, long context, multimodal.

Problem solved: an optional cloud accelerator/fallback. Available only when an API key is
supplied (from the OS keychain, never persisted here). With no key the adapter reports
unavailable and is skipped.

Inputs : chat messages + a Gemini model id (e.g. "gemini-1.5-flash").
Outputs: ProviderResponse using Gemini's usageMetadata token counts when present.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import Message, Provider, ProviderError, ProviderResponse, estimate_tokens

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _to_gemini_contents(messages: list[Message]) -> tuple[dict | None, list[dict]]:
    """Split messages into an optional systemInstruction and Gemini 'contents'."""

    system: dict | None = None
    contents: list[dict] = []
    for m in messages:
        if m.role == "system":
            system = {"parts": [{"text": m.content}]}
            continue
        role = "model" if m.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m.content}]})
    return system, contents


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def available(self) -> bool:
        return bool(self._api_key)

    async def list_models(self) -> list[str]:
        if not self._api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{BASE_URL}/models", params={"key": self._api_key}
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError:
            return []
        out: list[str] = []
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and "name" in m:
                out.append(m["name"].removeprefix("models/"))
        return out

    async def generate(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> ProviderResponse:
        if not self._api_key:
            raise ProviderError("Gemini API key not configured")

        system, contents = _to_gemini_contents(messages)
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = system
        if "generationConfig" in opts:
            body["generationConfig"] = opts["generationConfig"]

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{BASE_URL}/models/{model}:generateContent",
                    params={"key": self._api_key},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            raise ProviderError(f"Gemini request failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000.0

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Unexpected Gemini response shape: {data}") from exc

        usage = data.get("usageMetadata", {})
        tokens_in = int(usage.get("promptTokenCount") or estimate_tokens(
            "\n".join(m.content for m in messages)
        ))
        tokens_out = int(usage.get("candidatesTokenCount") or estimate_tokens(text))
        return ProviderResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            provider=self.name,
            model=model,
        )
