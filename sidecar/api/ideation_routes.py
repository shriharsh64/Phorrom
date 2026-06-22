"""Routes for the Ideation & Concept Engine (#2). Complements /ideation/gaps and
/ideation/mastered (in advisor_routes) which form the bridge to the Resource Advisor (#3)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..capabilities import ideation
from ..storage.db import Database


class IdeateRequest(BaseModel):
    project_id: int
    prompt: str | None = None
    provider: str = "mock"
    model: str = "mock-small"


class IdeaStatus(BaseModel):
    status: str


IDEA_STATUSES = {"suggested", "selected", "dismissed"}


def build_ideation_router() -> APIRouter:
    router = APIRouter()

    @router.post("/ideation/ideate")
    async def run_ideate(req: IdeateRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        result = await ideation.ideate(
            request.app.state.registry, db, req.project_id, req.prompt, req.provider, req.model
        )
        return {"result": result.model_dump(), "ideas": db.list_ideas(req.project_id)}

    @router.get("/ideation/ideas")
    async def list_ideas(request: Request, project_id: int) -> dict:
        return {"ideas": request.app.state.db.list_ideas(project_id)}

    @router.post("/ideation/ideas/{idea_id}/status")
    async def set_idea_status(idea_id: int, body: IdeaStatus, request: Request) -> dict:
        if body.status not in IDEA_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status '{body.status}'")
        db: Database = request.app.state.db
        if not db.set_idea_status(idea_id, body.status):
            raise HTTPException(status_code=404, detail="idea not found")
        db.audit("user", "idea_status", {"id": idea_id, "status": body.status})
        return {"id": idea_id, "status": body.status}

    return router
