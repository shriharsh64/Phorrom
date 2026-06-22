"""Deterministic mock provider (ADR-0001).

Problem solved: lets the entire app boot, demo, and be tested with zero API keys and no
network. Token counts and latency are derived deterministically from the input so the
orchestrator/budgeter tests are reproducible.
"""

from __future__ import annotations

from typing import Any

from .base import Message, Provider, ProviderResponse, estimate_tokens


class MockProvider(Provider):
    name = "mock"

    def __init__(self, models: list[str] | None = None, latency_ms: float = 5.0) -> None:
        self._models = models or ["mock-small", "mock-large"]
        self._latency_ms = latency_ms

    async def available(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return list(self._models)

    async def generate(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> ProviderResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        prompt_text = "\n".join(m.content for m in messages)
        # Deterministic canned reply: echoes the last user turn so tests can assert on it.
        reply = f"[mock:{model}] {last_user}".strip()
        return ProviderResponse(
            text=reply,
            tokens_in=estimate_tokens(prompt_text),
            tokens_out=estimate_tokens(reply),
            latency_ms=self._latency_ms,
            provider=self.name,
            model=model,
        )
