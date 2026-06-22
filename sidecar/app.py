"""Phorrom sidecar — FastAPI application factory.

Problem solved: the single localhost service the Tauri shell launches and talks to. Wires the
provider registry, the SQLite store, and the API routes together, and enforces a shared
bearer token when one is configured (ADR-0003).

Run standalone for dev:
    PHORROM_DB_PATH=:memory: uvicorn sidecar.app:app --reload
"""

from __future__ import annotations

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .api.advisor_routes import build_advisor_router
from .api.ideation_routes import build_ideation_router
from .api.optimize_routes import build_optimize_router
from .api.orchestrator_routes import build_orchestrator_router
from .api.phase2_routes import build_phase2_router
from .api.research_routes import build_research_router
from .api.routes import build_router
from .config import Config
from .providers.base import Provider
from .providers.gemini import GeminiProvider
from .providers.mock import MockProvider
from .providers.ollama import OllamaProvider
from .providers.registry import ProviderRegistry
from .storage.db import Database


def build_providers(cfg: Config) -> list[Provider]:
    return [
        MockProvider(),
        OllamaProvider(host=cfg.ollama_host),
        GeminiProvider(api_key=cfg.gemini_api_key),
    ]


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    db = Database(cfg.db_path)
    registry = ProviderRegistry(build_providers(cfg))

    app = FastAPI(title="Phorrom Sidecar", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.cfg = cfg
    app.state.db = db
    app.state.registry = registry
    # Factory for outbound HTTP (research sources). Tests replace it with a MockTransport client.
    app.state.http_client_factory = lambda: httpx.AsyncClient()

    async def require_auth(authorization: str | None = Header(default=None)) -> None:
        if cfg.auth_token is None:
            return  # dev mode: auth disabled
        expected = f"Bearer {cfg.auth_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid or missing token")

    app.include_router(build_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_advisor_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_phase2_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_orchestrator_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_ideation_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_research_router(), dependencies=[Depends(require_auth)])
    app.include_router(build_optimize_router(), dependencies=[Depends(require_auth)])
    return app


app = create_app()
