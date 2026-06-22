"""Route for the Response Optimization Layer (capability #10)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..capabilities import response_optimizer as opt
from ..storage.db import Database


class OptimizeRequest(BaseModel):
    prompt: str
    context: str = ""
    depth: str = "standard"            # brief | standard | deep
    tone: str | None = None
    focus: str | None = None
    project_id: int | None = None
    provider: str = "mock"
    model: str = "mock-small"
    threshold: float = 0.7
    max_iters: int = 3


def build_optimize_router() -> APIRouter:
    router = APIRouter()

    @router.post("/optimize")
    async def optimize(req: OptimizeRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        result = await opt.optimize(
            request.app.state.registry, db, req.prompt, req.context, req.depth, req.tone,
            req.focus, req.project_id, req.provider, req.model, req.threshold, req.max_iters,
        )
        return result.__dict__

    return router
