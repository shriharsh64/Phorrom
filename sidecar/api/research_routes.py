"""Routes for Patent & Prior-Art Research (capability #4)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..research import prior_art
from ..storage.db import Database


class PriorArtRequest(BaseModel):
    project_id: int
    query: str
    limit: int = 5
    provider: str = "mock"
    model: str = "mock-small"


def build_research_router() -> APIRouter:
    router = APIRouter()

    @router.post("/research/prior-art")
    async def run_prior_art(req: PriorArtRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        factory = request.app.state.http_client_factory
        async with factory() as client:
            return await prior_art.prior_art_search(
                request.app.state.registry, db, req.project_id, req.query, client,
                req.provider, req.model, req.limit,
            )

    @router.get("/research/results")
    async def results(request: Request, project_id: int) -> dict:
        db: Database = request.app.state.db
        return {
            "results": db.list_research_results(project_id),
            "summary": db.latest_research_summary(project_id),
        }

    return router
