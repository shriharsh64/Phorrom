"""HTTP routes for the sidecar.

Problem solved: exposes the Phase-1 surface the frontend needs — health, provider discovery,
and a chat round-trip that persists history + records a run in the token ledger.

Each route reads shared state (db, registry) from ``request.app.state``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    provider: str = "mock"
    model: str = "mock-small"
    project_id: int | None = None


class ChatResponse(BaseModel):
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "phorrom-sidecar"}

    @router.get("/providers")
    async def providers(request: Request) -> dict:
        registry: ProviderRegistry = request.app.state.registry
        return {"providers": await registry.discover()}

    @router.get("/providers/health")
    async def providers_health(request: Request) -> dict:
        registry: ProviderRegistry = request.app.state.registry
        breaker = request.app.state.breaker
        snap = breaker.snapshot()
        out = []
        for info in await registry.discover():
            cb = snap.get(info["provider"], {"state": "closed", "fails": 0})
            out.append({**info, "circuit": cb["state"], "fails": cb["fails"]})
        return {"providers": out}

    @router.get("/dashboard")
    async def dashboard(request: Request) -> dict:
        registry: ProviderRegistry = request.app.state.registry
        db: Database = request.app.state.db
        breaker = request.app.state.breaker
        snap = breaker.snapshot()
        providers = []
        for info in await registry.discover():
            cb = snap.get(info["provider"], {"state": "closed", "fails": 0})
            providers.append({"provider": info["provider"], "available": info["available"],
                              "models": len(info["models"]), "circuit": cb["state"],
                              "fails": cb["fails"]})
        by_provider = db.tokens_by_provider()
        return {"providers": providers, "tokens": {"by_provider": by_provider,
                "total": sum(by_provider.values())}}

    @router.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, request: Request) -> ChatResponse:
        registry: ProviderRegistry = request.app.state.registry
        db: Database = request.app.state.db

        provider = registry.get(req.provider)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{req.provider}'")
        if not await provider.available():
            raise HTTPException(
                status_code=409, detail=f"provider '{req.provider}' is not available"
            )

        # persist the incoming user turn
        last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
        if last_user is not None:
            db.add_chat_message("user", last_user.content, project_id=req.project_id)

        try:
            result = await provider.generate(req.messages, req.model)
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        db.add_chat_message(
            "assistant",
            result.text,
            project_id=req.project_id,
            provider=result.provider,
            model=result.model,
        )
        db.record_run(
            provider=result.provider,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
        )
        db.audit("agent", "chat", {"provider": result.provider, "model": result.model})

        return ChatResponse(
            text=result.text,
            provider=result.provider,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
        )

    @router.get("/chat/history")
    async def history(request: Request, project_id: int | None = None) -> dict:
        db: Database = request.app.state.db
        return {"messages": db.chat_history(project_id=project_id)}

    return router
