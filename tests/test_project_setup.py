"""Tests for Phase 6: workspace setup, the new-project wizard, prompt generation, folder sync."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config
from sidecar.projects import setup


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    cfg = Config(db_path=str(tmp_path / "t.sqlite"), auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    return TestClient(create_app(cfg))


def test_settings_unconfigured_then_set_workspace(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/settings").json()["configured"] is False
    ws = str(tmp_path / "ws")
    r = client.post("/settings/workspace", json={"path": ws, "name": "Mine"}).json()
    assert r["configured"] is True
    assert r["workspace_name"] == "Mine"
    assert Path(ws, ".phorrom-workspace.json").is_file()
    # persists across a fresh read
    assert client.get("/settings").json()["workspace_path"] == str(Path(ws).resolve())


def test_create_requires_workspace(client: TestClient) -> None:
    r = client.post("/projects/create", json={"name": "X"})
    assert r.status_code == 409


def test_suggest_features_picks_keywords() -> None:
    out = setup.suggest_features("a web app with login and an ML model")
    names = {f["name"] for f in out["features"]}
    assert "Authentication" in names and "ML pipeline" in names
    assert "Core MVP" in names  # baseline always present


def test_create_project_scaffolds_folder_and_prompts(client: TestClient, tmp_path: Path) -> None:
    ws = str(tmp_path / "ws")
    client.post("/settings/workspace", json={"path": ws, "name": "Mine"})
    body = {
        "name": "Cool App",
        "description": "A react web app with login.",
        "deadline": "2026-09-01",
        "features": [{"name": "Core MVP", "description": "slice", "enabled": True}],
        "details": {"domain": "fintech"},
    }
    proj = client.post("/projects/create", json=body).json()["project"]
    root = proj["root_path"]
    assert proj["deadline"] == "2026-09-01"
    assert set(proj["prompts"]) == set(setup.FEATURE_KEYS)
    # every feature prompt is on disk
    for key in setup.FEATURE_KEYS:
        assert Path(root, "prompts", f"{key}.md").is_file()
    # exports mirror exists
    assert Path(root, "exports", "tasks.json").is_file()
    saved = json.loads(Path(root, "project.json").read_text(encoding="utf-8"))
    assert saved["name"] == "Cool App"


def test_prompts_reference_project_context(client: TestClient, tmp_path: Path) -> None:
    client.post("/settings/workspace", json={"path": str(tmp_path / "ws"), "name": "W"})
    body = {"name": "Predictor", "description": "Forecast sales.", "deadline": "2026-12-01",
            "features": [{"name": "ML pipeline", "description": "x", "enabled": True}]}
    pid = client.post("/projects/create", json=body).json()["project"]["id"]
    prompts = client.get(f"/projects/{pid}/prompts").json()["prompts"]
    assert "Predictor" in prompts["chat"]
    assert "2026-12-01" in prompts["plan"]


def test_sync_writes_exports(client: TestClient, tmp_path: Path) -> None:
    client.post("/settings/workspace", json={"path": str(tmp_path / "ws"), "name": "W"})
    pid = client.post("/projects/create", json={"name": "Z", "description": "d"}).json()["project"]["id"]
    # add a task, then sync, and confirm it lands in the folder
    client.post("/tasks", json={"project_id": pid, "title": "do thing"})
    res = client.post(f"/projects/{pid}/sync").json()
    assert res["ok"] is True
    root = client.get(f"/projects/{pid}").json()["project"]["root_path"]
    tasks = json.loads(Path(root, "exports", "tasks.json").read_text(encoding="utf-8"))
    assert any(t["title"] == "do thing" for t in tasks)
