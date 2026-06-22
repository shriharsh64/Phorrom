"""Provider registry — discovery + lookup over all configured adapters.

Problem solved: one place the API/orchestrator asks "which providers are usable and what
models do they have?" and "give me the adapter named X". Treats the catalog as data: model
lists come from live ``list_models`` calls, not hardcoded constants (ADR-0002).
"""

from __future__ import annotations

from .base import Provider


class ProviderRegistry:
    def __init__(self, providers: list[Provider]) -> None:
        self._providers: dict[str, Provider] = {p.name: p for p in providers}

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def replace(self, provider: Provider) -> None:
        """Swap in a freshly-configured adapter (e.g. after a key change) at runtime."""
        self._providers[provider.name] = provider

    def names(self) -> list[str]:
        return list(self._providers)

    async def discover(self) -> list[dict]:
        """Return availability + live model catalog for every registered provider."""

        out: list[dict] = []
        for name, provider in self._providers.items():
            available = await provider.available()
            models = await provider.list_models() if available else []
            out.append({"provider": name, "available": available, "models": models})
        return out
