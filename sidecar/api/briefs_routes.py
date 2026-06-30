"""Phase 6 routes: per-feature briefs — the preliminary response in every feature and the
chat-driven, importance-compressed updates that keep them current."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..capabilities import briefs as B
from ..storage.db import Database


class ExchangeBody(BaseModel):
    user: str = ""
    assistant: str = ""


def _persist(db: Database, project_id: int, briefs: dict) -> None:
    for feature, b in briefs.items():
        db.upsert_brief(project_id, feature, b.get("summary", ""), b.get("points", []))


def generate_for_project(db: Database, project_id: int) -> dict:
    """Build + store preliminary briefs for a project (called on create and on demand)."""
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    briefs = B.generate_preliminary(project)
    _persist(db, project_id, briefs)
    return B.serialize(briefs)


def build_briefs_router() -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/briefs/generate")
    async def generate(project_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        return {"briefs": generate_for_project(db, project_id)}

    @router.get("/projects/{project_id}/briefs")
    async def get_briefs(project_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        if db.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        stored = db.list_briefs(project_id)
        if not stored:  # first read before any generation — build them now
            return {"briefs": generate_for_project(db, project_id)}
        return {"briefs": B.serialize(stored)}

    @router.post("/projects/{project_id}/briefs/update")
    async def update(project_id: int, body: ExchangeBody, request: Request) -> dict:
        db: Database = request.app.state.db
        if db.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        current = db.list_briefs(project_id)
        if not current:
            current = B.generate_preliminary(db.get_project(project_id))
            _persist(db, project_id, current)
        changed = B.update_from_exchange(current, body.user, body.assistant)
        if changed:
            _persist(db, project_id, changed)
        return {"briefs": B.serialize(db.list_briefs(project_id)), "changed": list(changed)}

    return router
