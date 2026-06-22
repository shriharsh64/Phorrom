"""Model router — score each subtask × model and pick the best feasible model.

Problem solved: assign each subtask to the model whose strengths best fit it, balancing
expected quality against cost and latency. Two routers share one interface: a heuristic scorer
(shipped here) and, later (Phase 4), a contextual bandit that learns from observed rewards.

Inputs : a subtask + the set of available (provider, model) candidates.
Outputs: a ranked list of (provider, model, score) and the best pick.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from .decompose import Subtask
from .profiles import get_profile

_LATENCY_PENALTY = {"fast": 0.0, "medium": 0.05, "slow": 0.12}


@dataclass
class Candidate:
    provider: str
    model: str


@dataclass
class Scored:
    provider: str
    model: str
    score: float
    quality: float


class Router(abc.ABC):
    @abc.abstractmethod
    def rank(self, subtask: Subtask, candidates: list[Candidate]) -> list[Scored]: ...

    def pick(self, subtask: Subtask, candidates: list[Candidate]) -> Scored | None:
        ranked = self.rank(subtask, candidates)
        return ranked[0] if ranked else None


class HeuristicRouter(Router):
    """Score = quality (weighted by the subtask's quality-sensitivity) − cost − latency.

    Low-quality-sensitivity work is pushed toward cheap/local models; high-sensitivity work
    pays for stronger models. λ scales how much cost matters relative to quality.
    """

    def __init__(self, cost_lambda: float = 0.15) -> None:
        self.cost_lambda = cost_lambda

    def rank(self, subtask: Subtask, candidates: list[Candidate]) -> list[Scored]:
        scored: list[Scored] = []
        for c in candidates:
            prof = get_profile(c.provider, c.model)
            quality = prof.quality_for(subtask.type)
            # Quality matters more when the subtask is quality-sensitive.
            quality_term = quality * (0.5 + 0.5 * subtask.quality_sensitivity)
            cost_term = self.cost_lambda * (prof.cost_per_ktok * subtask.size_hint / 1000.0)
            latency_term = _LATENCY_PENALTY.get(prof.latency_class, 0.05)
            score = quality_term - cost_term - latency_term
            scored.append(Scored(c.provider, c.model, round(score, 4), round(quality, 4)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored
