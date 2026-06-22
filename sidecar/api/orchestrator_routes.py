"""Routes for the multi-model orchestrator (Phase 3)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..orchestrator.orchestrator import orchestrate
from ..storage.db import Database


class OrchestrateRequest(BaseModel):
    project_id: int
    task: str
    budget: int = 4000
    quotas: dict[str, int] = Field(default_factory=dict)
    execute: bool = False
    provider: str = "mock"
    model: str = "mock-small"


def build_orchestrator_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orchestrate")
    async def run(req: OrchestrateRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        return await orchestrate(
            request.app.state.registry, db, req.project_id, req.task,
            budget=req.budget, quotas=req.quotas, execute=req.execute,
            decomposer_provider=req.provider, decomposer_model=req.model,
        )

    @router.get("/orchestrate/subtasks")
    async def subtasks(request: Request, task_id: int) -> dict:
        return {"subtasks": request.app.state.db.list_subtasks(task_id)}

    return router
