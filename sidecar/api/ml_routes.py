"""Routes for the learned token/quality estimators (Phase 4 ML)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..ml.estimators import TokenQualityEstimator
from ..storage.db import Database


class EstimateRequest(BaseModel):
    type: str = "reasoning"
    size_hint: int = 500
    provider: str = "mock"
    model: str = "mock-small"


def build_ml_router() -> APIRouter:
    router = APIRouter()

    @router.post("/ml/train")
    async def train(request: Request) -> dict:
        db: Database = request.app.state.db
        samples = db.list_estimator_samples()
        est: TokenQualityEstimator = request.app.state.estimator
        try:
            metrics = est.fit(samples)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        db.audit("user", "train_estimator", {"samples": len(samples)})
        return {"trained": True, "metrics": asdict(metrics)}

    @router.get("/ml/status")
    async def status(request: Request) -> dict:
        db: Database = request.app.state.db
        est: TokenQualityEstimator = request.app.state.estimator
        return {"trained": est.trained, "samples": len(db.list_estimator_samples()),
                "metrics": asdict(est.metrics) if est.metrics else None}

    @router.post("/ml/estimate")
    async def estimate(req: EstimateRequest, request: Request) -> dict:
        est: TokenQualityEstimator = request.app.state.estimator
        tokens, quality = est.predict(req.type, req.size_hint, req.provider, req.model)
        return {"tokens": round(tokens, 1), "quality": round(quality, 4),
                "source": "learned" if est.trained else "heuristic"}

    return router
