"""Model capability profiles — data, not code (ADR-0002).

Problem solved: routing and budgeting need to know each model's strengths (by task type),
cost, latency class, and context window. Free catalogs change constantly and model *names*
must never be hardcoded into logic, so profiles are derived from a small editable default set
plus keyword inference from the model id, and can be overridden per model by the user.

Inputs : a (provider, model) pair + the subtask type.
Outputs: a CapabilityProfile and a 0..1 quality estimate for that model on that task type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TASK_TYPES = ("coding", "reasoning", "summarization", "creative", "long_context", "vision")


@dataclass
class CapabilityProfile:
    provider: str
    model: str
    cost_per_ktok: float                  # 0.0 for local / free-unlimited
    latency_class: str                    # fast|medium|slow
    context_window: int
    unlimited: bool                       # True for local (Ollama) → effectively infinite quota
    strengths: dict[str, float] = field(default_factory=dict)  # task_type -> 0..1

    def quality_for(self, task_type: str) -> float:
        return self.strengths.get(task_type, 0.55)


# Keyword → per-task-type strength nudges, inferred from the model id (lowercased).
_KEYWORD_STRENGTHS: dict[str, dict[str, float]] = {
    "coder": {"coding": 0.92, "reasoning": 0.7},
    "code": {"coding": 0.9, "reasoning": 0.68},
    "reason": {"reasoning": 0.9},
    "r1": {"reasoning": 0.9},
    "think": {"reasoning": 0.88},
    "vision": {"vision": 0.9, "long_context": 0.7},
    "vl": {"vision": 0.88},
    "large": {"reasoning": 0.8, "long_context": 0.78, "creative": 0.75},
    "small": {"summarization": 0.7, "coding": 0.55, "reasoning": 0.5},
    "mini": {"summarization": 0.68, "reasoning": 0.5},
    "flash": {"summarization": 0.72, "long_context": 0.85},
}


def infer_profile(provider: str, model: str) -> CapabilityProfile:
    """Build a reasonable profile from the provider + model id when none is configured."""

    mid = model.lower()
    unlimited = provider == "ollama"
    strengths: dict[str, float] = {t: 0.55 for t in TASK_TYPES}
    for kw, boosts in _KEYWORD_STRENGTHS.items():
        if kw in mid:
            for t, v in boosts.items():
                strengths[t] = max(strengths[t], v)
    # Gemini long-context/vision lean; local models cost nothing.
    if provider == "gemini":
        strengths["long_context"] = max(strengths["long_context"], 0.85)
        strengths["vision"] = max(strengths["vision"], 0.8)
    cost = 0.0 if unlimited else 0.5
    latency = "fast" if ("flash" in mid or "mini" in mid or provider == "groq") else "medium"
    ctx = 1_000_000 if provider == "gemini" else 8192
    return CapabilityProfile(provider, model, cost, latency, ctx, unlimited, strengths)


# Explicit defaults for the built-in mock models so tests are deterministic and the two mock
# models have clearly different strengths (so routing visibly picks different models).
DEFAULT_PROFILES: dict[tuple[str, str], CapabilityProfile] = {
    ("mock", "mock-small"): CapabilityProfile(
        "mock", "mock-small", cost_per_ktok=0.0, latency_class="fast", context_window=8192,
        unlimited=False,
        strengths={"coding": 0.5, "reasoning": 0.45, "summarization": 0.85,
                   "creative": 0.6, "long_context": 0.5, "vision": 0.3},
    ),
    ("mock", "mock-large"): CapabilityProfile(
        "mock", "mock-large", cost_per_ktok=1.0, latency_class="slow", context_window=32768,
        unlimited=False,
        strengths={"coding": 0.9, "reasoning": 0.92, "summarization": 0.7,
                   "creative": 0.85, "long_context": 0.8, "vision": 0.5},
    ),
}


def get_profile(provider: str, model: str) -> CapabilityProfile:
    return DEFAULT_PROFILES.get((provider, model)) or infer_profile(provider, model)
