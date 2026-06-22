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
    router: str = "heuristic"          # heuristic | bandit
    seed: int | None = None
    provider: str = "mock"
    model: str = "mock-small"


class FeedbackRequest(BaseModel):
    provider: str
    model: str
    task_type: str
    reward: float                      # observed quality (0..1); reward = quality − λ·cost


def build_orchestrator_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orchestrate")
    async def run(req: OrchestrateRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        return await orchestrate(
            request.app.state.registry, db, req.project_id, req.task,
            budget=req.budget, quotas=req.quotas, execute=req.execute,
            router=req.router, seed=req.seed,
            decomposer_provider=req.provider, decomposer_model=req.model,
        )

    @router.get("/orchestrate/subtasks")
    async def subtasks(request: Request, task_id: int) -> dict:
        return {"subtasks": request.app.state.db.list_subtasks(task_id)}

    @router.post("/orchestrate/feedback")
    async def feedback(req: FeedbackRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        db.update_bandit_arm(req.provider, req.model, req.task_type, req.reward)
        db.audit("user", "router_feedback",
                 {"model": f"{req.provider}/{req.model}", "type": req.task_type, "reward": req.reward})
        return {"ok": True, "arm": next(
            (a for a in db.list_bandit_arms()
             if a["provider"] == req.provider and a["model"] == req.model
             and a["task_type"] == req.task_type), None)}

    @router.get("/orchestrate/bandit")
    async def bandit_arms(request: Request) -> dict:
        return {"arms": request.app.state.db.list_bandit_arms()}

    return router
