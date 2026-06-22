"""Response Optimization tests — pure evaluator + the generate/self-eval/re-steer loop."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.capabilities import response_optimizer as opt
from sidecar.capabilities.response_optimizer import evaluate
from sidecar.config import Config
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry
from sidecar.storage.db import Database


def test_relevance_rewards_keyword_overlap() -> None:
    ctx = "smart irrigation soil moisture sensor scheduling"
    on = evaluate("A soil moisture sensor schedules irrigation.", ctx, "brief")
    off = evaluate("The weather is nice today.", ctx, "brief")
    assert on.relevance > off.relevance
    assert on.on_topic and not off.on_topic


def test_depth_fit_penalizes_too_short_for_deep() -> None:
    short = evaluate("Too short.", "topic words here", "deep")
    assert short.depth_fit < 1.0
    assert any("depth" in d.lower() for d in short.directives)


def test_directives_flag_missing_focus() -> None:
    ev = evaluate("unrelated text", "kalman filtering sensor fusion", "standard")
    assert ev.missing
    assert any("Focus" in d for d in ev.directives)


@pytest.mark.asyncio
async def test_optimize_loop_stops_at_threshold_and_persists() -> None:
    # Responder echoes context keywords → high relevance → passes on first iteration.
    def responder(messages, model):
        return "soil moisture sensor irrigation scheduling controller pipeline " * 30

    db = Database(":memory:")
    pid = db.create_project("p")
    res = await opt.optimize(
        ProviderRegistry([MockProvider(responder=responder)]), db,
        prompt="design soil moisture sensor irrigation scheduling",
        context_text="soil moisture sensor irrigation scheduling controller pipeline",
        depth="standard", project_id=pid, threshold=0.7, max_iters=3,
    )
    assert res.score >= 0.7
    assert res.iterations == 1  # passed immediately, no wasted regenerations
    db.close()


@pytest.mark.asyncio
async def test_optimize_recalibrates_when_below_threshold() -> None:
    # Always-irrelevant responder → never reaches threshold → uses all passes, re-steering.
    db = Database(":memory:")
    pid = db.create_project("p")
    res = await opt.optimize(
        ProviderRegistry([MockProvider(responder=lambda m, md: "totally unrelated")]), db,
        prompt="quantum error correction surface codes",
        context_text="quantum error correction surface codes decoder",
        depth="deep", project_id=pid, threshold=0.9, max_iters=3,
    )
    assert res.iterations == 3                 # exhausted passes trying to improve
    assert len(res.trace) == 3
    assert "Focus more directly on" in res.directives  # recalibrated toward missing focus
    db.close()


def test_optimize_api() -> None:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    client = TestClient(create_app(cfg))
    body = client.post("/optimize", json={
        "prompt": "explain token budgeting", "depth": "brief",
    }).json()
    assert "score" in body and "iterations" in body and "trace" in body
