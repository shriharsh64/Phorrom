"""Provider abstraction.

Problem solved: give the orchestrator a single, uniform way to call any free generative
model (local or cloud) so routing/budgeting logic never depends on provider-specific code.

Inputs : a list of chat ``Message`` objects + a model id + free-form options.
Outputs: a ``ProviderResponse`` with text and token/latency accounting.

Every adapter (mock, Ollama, Gemini, ...) implements :class:`Provider`. The mock adapter is a
first-class citizen so the whole system runs offline and deterministically in tests (ADR-0001).
"""

from __future__ import annotations

import abc
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    """A single chat turn."""

    role: Role
    content: str


class ProviderResponse(BaseModel):
    """Normalized result of a generation call across all providers."""

    text: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    provider: str
    model: str

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


class ProviderError(RuntimeError):
    """Raised when a provider call fails (network, rate-limit, bad key, ...)."""


class Provider(abc.ABC):
    """Uniform interface every model provider must implement."""

    #: stable short identifier, e.g. "mock", "ollama", "gemini"
    name: str

    @abc.abstractmethod
    async def available(self) -> bool:
        """Whether this provider is usable right now (key present / service reachable)."""

    @abc.abstractmethod
    async def list_models(self) -> list[str]:
        """Live catalog of model ids. Catalogs are data, not code (ADR-0002)."""

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> ProviderResponse:
        """Generate a completion for ``messages`` using ``model``."""


def estimate_tokens(text: str) -> int:
    """Cheap, provider-agnostic token estimate (~4 chars/token).

    Used as a fallback when a provider does not report exact usage. Deliberately simple and
    deterministic so tests and the budgeter behave predictably.
    """

    if not text:
        return 0
    return max(1, len(text) // 4)
