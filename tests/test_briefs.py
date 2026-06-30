"""Tests for feature briefs: preliminary generation, chat-driven updates, importance compression."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.capabilities import briefs as B
from sidecar.config import Config
from sidecar.projects.setup import FEATURE_KEYS


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = Config(db_path=str(tmp_path / "t.sqlite"), auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    c = TestClient(create_app(cfg))
    c.post("/settings/workspace", json={"path": str(tmp_path / "ws"), "name": "W"})
    return c


def _make(client: TestClient) -> int:
    body = {"name": "Recipe AI", "description": "A web app with login and an ML model for recipes.",
            "deadline": "2026-09-15", "features": [{"name": "ML pipeline", "description": "x", "enabled": True}]}
    return client.post("/projects/create", json=body).json()["project"]["id"]


def test_create_seeds_brief_for_every_feature(client: TestClient) -> None:
    pid = _make(client)
    briefs = client.get(f"/projects/{pid}/briefs").json()["briefs"]
    assert set(briefs) == set(FEATURE_KEYS)
    for f in FEATURE_KEYS:
        assert briefs[f]["summary"]  # a preliminary response exists everywhere


def test_chat_update_routes_and_changes_features(client: TestClient) -> None:
    pid = _make(client)
    r = client.post(f"/projects/{pid}/briefs/update", json={
        "user": "Research existing recipe apps and target sub-200ms latency.",
        "assistant": "Key risk: dataset quality. Consider a vector search library.",
    }).json()
    assert "research" in r["changed"]   # routed to research
    assert "advisor" in r["changed"]    # 'library' routes to advisor
    assert "chat" in r["changed"]       # chat always accumulates


def test_importance_compression_caps_and_ranks() -> None:
    existing = [{"text": f"minor point number {i}", "importance": 0.3, "source": "x"} for i in range(10)]
    incoming = [{"text": "Critical security requirement must be met by deadline 2026",
                 "importance": 0.95, "source": "chat"}]
    merged = B.merge_points(existing, incoming, cap=B.MAX_POINTS)
    assert len(merged) == B.MAX_POINTS                  # capped
    assert merged[0]["importance"] == 0.95             # most important first
    assert all(merged[i]["importance"] >= merged[i + 1]["importance"] for i in range(len(merged) - 1))


def test_merge_dedupes_near_duplicates_keeping_higher() -> None:
    existing = [{"text": "Target accuracy is ninety percent", "importance": 0.5, "source": "x"}]
    incoming = [{"text": "Target accuracy is ninety percent overall", "importance": 0.8, "source": "chat"}]
    merged = B.merge_points(existing, incoming)
    assert len(merged) == 1                              # deduped, not duplicated
    assert merged[0]["importance"] == 0.8               # kept the higher-importance phrasing


def test_score_importance_rewards_keywords_and_numbers() -> None:
    assert B.score_importance("must deliver security by deadline 2026") > B.score_importance("we chatted")
