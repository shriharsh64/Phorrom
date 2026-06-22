"""Contextual-bandit router tests — learning, exploration, persistence, budgeter integration."""

from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config
from sidecar.orchestrator.bandit import BanditRouter
from sidecar.orchestrator.budgeter import BudgetInputs, solve
from sidecar.orchestrator.decompose import Subtask
from sidecar.orchestrator.router import Candidate
from sidecar.storage.db import Database

CANDS = [Candidate("mock", "mock-small"), Candidate("mock", "mock-large")]


def st(id="t", type="coding") -> Subtask:
    return Subtask(id=id, type=type, size_hint=500, value=0.8, p_required=1.0, quality_sensitivity=1.0)


def test_observe_moves_posterior_mean() -> None:
    r = BanditRouter(rng=random.Random(0))
    before = r.mean("mock", "mock-small", "coding")
    for _ in range(50):
        r.observe("mock", "mock-small", "coding", reward=1.0)
    assert r.mean("mock", "mock-small", "coding") > before
    for _ in range(50):
        r.observe("mock", "mock-large", "coding", reward=0.0)
    assert r.mean("mock", "mock-small", "coding") > r.mean("mock", "mock-large", "coding")


def test_bandit_learns_to_prefer_the_rewarded_model() -> None:
    r = BanditRouter(rng=random.Random(42))
    # Teach it that mock-small is great at coding and mock-large is poor (opposite of profiles).
    for _ in range(80):
        r.observe("mock", "mock-small", "coding", 1.0)
        r.observe("mock", "mock-large", "coding", 0.0)
    picks = [r.pick(st(), CANDS).model for _ in range(40)]
    assert picks.count("mock-small") > picks.count("mock-large")


def test_persistence_roundtrip_through_db() -> None:
    db = Database(":memory:")
    for _ in range(20):
        db.update_bandit_arm("mock", "mock-large", "coding", 1.0)
    r = BanditRouter(rng=random.Random(1))
    r.load_from_db(db, CANDS)
    a, b = r.arms[("mock", "mock-large", "coding")]
    assert a > b  # high rewards → alpha dominates
    db.close()


def test_bandit_quality_feeds_budgeter() -> None:
    r = BanditRouter(rng=random.Random(7))
    inp = BudgetInputs(ready=[st()], candidates=CANDS, budget=5000, quotas={"mock": 9999},
                       quality_fn=r.sample_quality)
    res = solve(inp)
    assert len(res.assignments) == 1  # allocation succeeded using sampled qualities


def _client() -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    return TestClient(create_app(cfg))


def test_orchestrate_bandit_mode_records_arms_and_feedback_endpoint() -> None:
    client = _client()
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    body = client.post("/orchestrate", json={
        "project_id": pid, "task": "ship", "budget": 6000, "execute": True,
        "router": "bandit", "seed": 3,
    }).json()
    assert body["router"] == "bandit"
    arms = client.get("/orchestrate/bandit").json()["arms"]
    assert arms, "executing in bandit mode should have updated at least one arm"

    fb = client.post("/orchestrate/feedback", json={
        "provider": "mock", "model": "mock-large", "task_type": "coding", "reward": 1.0,
    })
    assert fb.status_code == 200 and fb.json()["ok"] is True
