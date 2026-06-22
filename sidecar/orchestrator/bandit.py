"""Contextual-bandit router (Thompson sampling).

Problem solved: the heuristic router uses static capability profiles; this router *learns* each
model's real strength per task type from observed reward (reward = quality − λ·cost, in 0..1).

Model: one Beta(α,β) posterior per arm = (provider, model, task_type). Thompson sampling draws
θ ~ Beta(α,β) for each candidate and prefers the highest draw — balancing exploration and
exploitation. ``observe`` updates the posterior: α += reward, β += (1 − reward).

It plugs into the budgeter via ``sample_quality`` (a Thompson draw), so the token-allocation LP
optimizes over *sampled* qualities — exploration happens inside allocation. Pure and seedable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .decompose import Subtask
from .profiles import get_profile
from .router import Candidate, Router, Scored


@dataclass
class BanditRouter(Router):
    # arm key (provider, model, task_type) -> [alpha, beta]
    arms: dict[tuple[str, str, str], list[float]] = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    cost_lambda: float = 0.15
    prior_strength: float = 4.0  # how strongly the capability profile seeds a fresh arm

    def _arm(self, provider: str, model: str, task_type: str) -> list[float]:
        key = (provider, model, task_type)
        if key not in self.arms:
            # Seed the prior from the static profile so cold-start routing is sensible.
            q = get_profile(provider, model).quality_for(task_type)
            self.arms[key] = [1.0 + self.prior_strength * q,
                              1.0 + self.prior_strength * (1.0 - q)]
        return self.arms[key]

    def mean(self, provider: str, model: str, task_type: str) -> float:
        a, b = self._arm(provider, model, task_type)
        return a / (a + b)

    def sample(self, provider: str, model: str, task_type: str) -> float:
        a, b = self._arm(provider, model, task_type)
        return self.rng.betavariate(a, b)

    def observe(self, provider: str, model: str, task_type: str, reward: float) -> None:
        reward = max(0.0, min(1.0, reward))
        arm = self._arm(provider, model, task_type)
        arm[0] += reward
        arm[1] += 1.0 - reward

    def sample_quality(self, subtask: Subtask, c: Candidate) -> float:
        """Thompson draw used by the budgeter's objective for this subtask×model."""

        return self.sample(c.provider, c.model, subtask.type)

    def rank(self, subtask: Subtask, candidates: list[Candidate]) -> list[Scored]:
        scored: list[Scored] = []
        for c in candidates:
            theta = self.sample(c.provider, c.model, subtask.type)
            prof = get_profile(c.provider, c.model)
            cost_term = self.cost_lambda * (prof.cost_per_ktok * subtask.size_hint / 1000.0)
            scored.append(Scored(c.provider, c.model, round(theta - cost_term, 4),
                                 round(self.mean(c.provider, c.model, subtask.type), 4)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    # --- persistence sync ------------------------------------------------------
    def load_from_db(self, db, candidates: list[Candidate]) -> None:
        from .profiles import TASK_TYPES
        for c in candidates:
            for t in TASK_TYPES:
                a, b = db.get_bandit_arm(c.provider, c.model, t)
                if (a, b) != (1.0, 1.0):  # stored posterior overrides the profile prior
                    self.arms[(c.provider, c.model, t)] = [a, b]
