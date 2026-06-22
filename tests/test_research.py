"""Prior-art research tests — offline via httpx.MockTransport (no network)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config
from sidecar.research import prior_art
from sidecar.research.sources import search_arxiv, search_semantic_scholar
from sidecar.storage.db import Database

ARXIV_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>Soil moisture sensing with low-cost IoT</title>
    <summary>A cheap capacitive sensor approach.</summary>
    <author><name>A. Researcher</name></author>
  </entry>
</feed>"""

S2_JSON = {"data": [
    {"title": "Smart irrigation via reinforcement learning", "year": 2023,
     "abstract": "RL controller for drip irrigation.", "url": "https://s2/abc",
     "authors": [{"name": "B. Scholar"}]},
    {"title": "Soil moisture sensing with low-cost IoT", "year": 2024, "abstract": "dup",
     "url": "https://s2/dup", "authors": []},  # duplicate title (different source)
]}


def _handler(request: httpx.Request) -> httpx.Response:
    if "arxiv.org" in request.url.host:
        return httpx.Response(200, text=ARXIV_XML)
    if "semanticscholar.org" in request.url.host:
        return httpx.Response(200, json=S2_JSON)
    return httpx.Response(404)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


@pytest.mark.asyncio
async def test_arxiv_parsing() -> None:
    async with _client() as c:
        res = await search_arxiv("irrigation", c)
    assert res and res[0].source == "arxiv"
    assert res[0].year == 2024 and res[0].authors == ["A. Researcher"]


@pytest.mark.asyncio
async def test_semantic_scholar_parsing() -> None:
    async with _client() as c:
        res = await search_semantic_scholar("irrigation", c)
    assert any(r.title.startswith("Smart irrigation") for r in res)


@pytest.mark.asyncio
async def test_gather_dedupes_across_sources() -> None:
    async with _client() as c:
        merged = await prior_art.gather("irrigation", c)
    titles = [r.title.lower() for r in merged]
    assert len(titles) == len(set(titles))  # no duplicate titles
    assert len(merged) == 2                  # 1 arxiv + 2 s2, minus 1 dup


@pytest.mark.asyncio
async def test_prior_art_persists_and_is_grounded() -> None:
    from sidecar.providers.mock import MockProvider
    from sidecar.providers.registry import ProviderRegistry
    db = Database(":memory:")
    pid = db.create_project("farm")
    async with _client() as c:
        out = await prior_art.prior_art_search(
            ProviderRegistry([MockProvider()]), db, pid, "smart irrigation", c)
    assert out["n_results"] == 2
    assert out["grounded"] is True            # heuristic over real results is source-grounded
    assert len(db.list_research_results(pid)) == 2
    assert db.latest_research_summary(pid)["query"] == "smart irrigation"
    db.close()


@pytest.mark.asyncio
async def test_no_results_makes_no_claims() -> None:
    from sidecar.providers.mock import MockProvider
    from sidecar.providers.registry import ProviderRegistry
    empty = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    db = Database(":memory:")
    pid = db.create_project("x")
    async with empty as c:
        out = await prior_art.prior_art_search(
            ProviderRegistry([MockProvider()]), db, pid, "obscure topic", c)
    assert out["n_results"] == 0
    assert "No prior-art results" in out["summary"]  # does not fabricate
    db.close()


def test_prior_art_api_with_injected_client() -> None:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    app = create_app(cfg)
    app.state.http_client_factory = _client  # inject offline transport
    client = TestClient(app)
    pid = client.post("/projects", json={"name": "Farm"}).json()["id"]
    body = client.post("/research/prior-art", json={"project_id": pid, "query": "smart irrigation"}).json()
    assert body["n_results"] == 2
    got = client.get("/research/results", params={"project_id": pid}).json()
    assert len(got["results"]) == 2 and got["summary"]["n_results"] == 2
