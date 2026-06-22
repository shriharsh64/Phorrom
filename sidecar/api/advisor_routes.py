"""Routes for the Resource & Tooling Advisor (#3) and its bridge to Ideation (#2).

Surface:
- POST /advisor/recommend        run the advisor for a project, persist, return overview
- GET  /advisor/overview         resources + learning plan + progress + concepts
- POST /advisor/resources/{id}/status   mark a resource accepted/done/dismissed
- POST /advisor/learning/{id}/status    mark a learning item; flips concept mastery
- POST /ideation/gaps            ideation (#2) records a concept the user struggled with
- GET  /ideation/mastered        mastered concepts, fed back into ideation (#2)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..capabilities import resource_advisor as advisor
from ..capabilities.resource_advisor import ProjectContext
from ..storage.db import Database


class RecommendRequest(BaseModel):
    project_id: int
    context: ProjectContext = Field(default_factory=ProjectContext)
    provider: str = "mock"
    model: str = "mock-small"


class StatusUpdate(BaseModel):
    status: str


class GapRequest(BaseModel):
    project_id: int
    concept: str
    notes: str | None = None
    origin: str = "ideation"


RESOURCE_STATUSES = {"suggested", "accepted", "done", "dismissed"}
LEARNING_STATUSES = {"todo", "in_progress", "done"}


def build_advisor_router() -> APIRouter:
    router = APIRouter()

    @router.post("/advisor/recommend")
    async def recommend(req: RecommendRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        registry = request.app.state.registry
        result = await advisor.advise(
            registry, db, req.project_id, req.context, req.provider, req.model
        )
        return {
            "result": result.model_dump(),
            "overview": advisor.overview(db, req.project_id),
        }

    @router.get("/advisor/overview")
    async def get_overview(request: Request, project_id: int) -> dict:
        db: Database = request.app.state.db
        return advisor.overview(db, project_id)

    @router.post("/advisor/resources/{item_id}/status")
    async def set_resource_status(item_id: int, body: StatusUpdate, request: Request) -> dict:
        if body.status not in RESOURCE_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status '{body.status}'")
        db: Database = request.app.state.db
        if not db.set_resource_status(item_id, body.status):
            raise HTTPException(status_code=404, detail="resource not found")
        db.audit("user", "resource_status", {"id": item_id, "status": body.status})
        return {"id": item_id, "status": body.status}

    @router.post("/advisor/learning/{item_id}/status")
    async def set_learning_status(item_id: int, body: StatusUpdate, request: Request) -> dict:
        if body.status not in LEARNING_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status '{body.status}'")
        db: Database = request.app.state.db
        updated = db.set_learning_status(item_id, body.status)
        if updated is None:
            raise HTTPException(status_code=404, detail="learning item not found")
        db.audit("user", "learning_status", {"id": item_id, "status": body.status})
        # Surface any concept that just became mastered (feeds back to ideation).
        return {"item": updated, "mastered": db.mastered_concepts(updated["project_id"])}

    @router.post("/ideation/gaps")
    async def record_gap(body: GapRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        cid = db.upsert_concept(
            body.project_id, body.concept, status="gap", origin=body.origin, notes=body.notes
        )
        db.audit(body.origin, "concept_gap", {"project_id": body.project_id, "concept": body.concept})
        return {"concept_id": cid, "concept": body.concept, "status": "gap"}

    @router.get("/ideation/mastered")
    async def get_mastered(request: Request, project_id: int) -> dict:
        db: Database = request.app.state.db
        return {"project_id": project_id, "mastered": db.mastered_concepts(project_id)}

    return router
