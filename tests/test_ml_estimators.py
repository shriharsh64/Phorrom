"""Learned estimator tests — features, heuristic fallback, training/metrics, persistence, API."""

from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config
from sidecar.ml.estimators import MIN_SAMPLES, TokenQualityEstimator
from sidecar.ml.features import FEATURE_NAMES, encode


def test_feature_vector_is_fixed_length_and_typed() -> None:
    vec = encode("coding", 800, "mock", "mock-large")
    assert len(vec) == len(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in vec)


def test_untrained_estimator_uses_heuristic() -> None:
    est = TokenQualityEstimator()
    tokens, quality = est.predict("coding", 700, "mock", "mock-large")
    assert tokens == 700.0                 # heuristic: tokens ~ size_hint
    assert 0.0 <= quality <= 1.0


def test_fit_requires_minimum_samples() -> None:
    est = TokenQualityEstimator()
    with pytest.raises(ValueError):
        est.fit([{"type": "coding", "size_hint": 100, "provider": "mock", "model": "mock-small",
                  "tokens": 120, "quality": 0.5}])


def _synthetic_samples(n: int = 80) -> list[dict]:
    """tokens ≈ 1.3*size + noise; quality depends on model — learnable structure."""

    rng = random.Random(0)
    out = []
    for _ in range(n):
        size = rng.choice([200, 500, 900, 1400])
        model = rng.choice(["mock-small", "mock-large"])
        ttype = rng.choice(["coding", "summarization", "reasoning"])
        tokens = int(1.3 * size + rng.uniform(-30, 30))
        quality = (0.9 if model == "mock-large" else 0.6) + rng.uniform(-0.05, 0.05)
        out.append({"type": ttype, "size_hint": size, "provider": "mock", "model": model,
                    "tokens": tokens, "quality": round(quality, 3)})
    return out


def test_training_learns_and_reports_metrics() -> None:
    est = TokenQualityEstimator()
    m = est.fit(_synthetic_samples())
    assert est.trained
    assert m.n_train + m.n_test >= MIN_SAMPLES
    assert m.token_r2 > 0.5          # token usage is highly learnable from size
    # Learned token estimate tracks the ~1.3*size relationship.
    tokens, _ = est.predict("coding", 1000, "mock", "mock-small")
    assert 1000 < tokens < 1600


def test_persistence_roundtrip(tmp_path) -> None:
    est = TokenQualityEstimator()
    est.fit(_synthetic_samples())
    p = str(tmp_path / "est.joblib")
    est.save(p)
    loaded = TokenQualityEstimator.load(p)
    assert loaded.trained
    a = est.predict("coding", 800, "mock", "mock-large")
    b = loaded.predict("coding", 800, "mock", "mock-large")
    assert a == b


def _client() -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    return TestClient(create_app(cfg))


def test_ml_api_train_status_estimate() -> None:
    client = _client()
    db = client.app.state.db
    for s in _synthetic_samples():
        db.add_estimator_sample(s["type"], s["size_hint"], s["provider"], s["model"],
                                s["tokens"], s["quality"])
    assert client.get("/ml/status").json()["trained"] is False
    trained = client.post("/ml/train").json()
    assert trained["trained"] and "token_r2" in trained["metrics"]
    est = client.post("/ml/estimate", json={"type": "coding", "size_hint": 1000,
                                            "provider": "mock", "model": "mock-large"}).json()
    assert est["source"] == "learned"


def test_ml_train_409_without_samples() -> None:
    client = _client()
    assert client.post("/ml/train").status_code == 409


def test_orchestrate_execute_logs_estimator_samples() -> None:
    client = _client()
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    client.post("/orchestrate", json={"project_id": pid, "task": "ship it", "execute": True})
    assert len(client.app.state.db.list_estimator_samples()) >= 1  # execution logged samples
