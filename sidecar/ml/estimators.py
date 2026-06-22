"""Learned token & quality estimators.

Problem solved: replace the static capability-profile guesses with regressors trained on real
run-logs. Two targets: expected tokens (regression) and expected quality (0..1). Small-data
friendly (gradient-boosted trees + a fitted StandardScaler). Until enough samples exist, a
deterministic heuristic (profile + size_hint) is used, so the system always has an estimate.

Inputs : training samples [{type,size_hint,provider,model,tokens,quality}].
Outputs: a fitted estimator with ``predict(type,size,provider,model) -> (tokens, quality)`` and
         holdout metrics (token MAE/R², quality MAE/R²). Persistable via joblib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import encode

MIN_SAMPLES = 12  # below this, training is skipped and the heuristic is used


def heuristic_predict(task_type: str, size_hint: int, provider: str, model: str) -> tuple[float, float]:
    """Profile-based fallback: tokens ~ size_hint, quality from the capability profile."""

    from ..orchestrator.profiles import get_profile
    prof = get_profile(provider, model)
    return float(size_hint), float(prof.quality_for(task_type))


@dataclass
class EstimatorMetrics:
    n_train: int
    n_test: int
    token_mae: float
    token_r2: float
    quality_mae: float
    quality_r2: float


@dataclass
class TokenQualityEstimator:
    trained: bool = False
    metrics: EstimatorMetrics | None = None
    _scaler: Any = field(default=None, repr=False)
    _tok_model: Any = field(default=None, repr=False)
    _qual_model: Any = field(default=None, repr=False)

    def predict(self, task_type: str, size_hint: int, provider: str, model: str) -> tuple[float, float]:
        if not self.trained:
            return heuristic_predict(task_type, size_hint, provider, model)
        x = self._scaler.transform([encode(task_type, size_hint, provider, model)])
        tokens = float(self._tok_model.predict(x)[0])
        quality = float(self._qual_model.predict(x)[0])
        return max(0.0, tokens), min(1.0, max(0.0, quality))

    def fit(self, samples: list[dict], test_frac: float = 0.25, seed: int = 0) -> EstimatorMetrics:
        """Train both regressors on the samples; compute holdout metrics. Raises if too few."""

        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.metrics import mean_absolute_error, r2_score
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        usable = [s for s in samples if s.get("quality") is not None]
        if len(usable) < MIN_SAMPLES:
            raise ValueError(f"need >= {MIN_SAMPLES} labelled samples, got {len(usable)}")

        X = np.array([encode(s["type"], s["size_hint"], s["provider"], s["model"]) for s in usable])
        y_tok = np.array([s["tokens"] for s in usable], dtype=float)
        y_q = np.array([s["quality"] for s in usable], dtype=float)

        Xtr, Xte, ytok_tr, ytok_te, yq_tr, yq_te = train_test_split(
            X, y_tok, y_q, test_size=test_frac, random_state=seed)

        scaler = StandardScaler().fit(Xtr)
        Xtr_s, Xte_s = scaler.transform(Xtr), scaler.transform(Xte)

        tok = GradientBoostingRegressor(random_state=seed).fit(Xtr_s, ytok_tr)
        qual = GradientBoostingRegressor(random_state=seed).fit(Xtr_s, yq_tr)

        m = EstimatorMetrics(
            n_train=len(Xtr), n_test=len(Xte),
            token_mae=float(mean_absolute_error(ytok_te, tok.predict(Xte_s))),
            token_r2=float(r2_score(ytok_te, tok.predict(Xte_s))) if len(Xte) > 1 else 0.0,
            quality_mae=float(mean_absolute_error(yq_te, qual.predict(Xte_s))),
            quality_r2=float(r2_score(yq_te, qual.predict(Xte_s))) if len(Xte) > 1 else 0.0,
        )
        self._scaler, self._tok_model, self._qual_model = scaler, tok, qual
        self.trained = True
        self.metrics = m
        return m

    def save(self, path: str) -> None:
        import joblib
        joblib.dump({"scaler": self._scaler, "tok": self._tok_model, "qual": self._qual_model,
                     "metrics": self.metrics}, path)

    @classmethod
    def load(cls, path: str) -> "TokenQualityEstimator":
        import joblib
        d = joblib.load(path)
        est = cls(trained=True, metrics=d.get("metrics"))
        est._scaler, est._tok_model, est._qual_model = d["scaler"], d["tok"], d["qual"]
        return est
