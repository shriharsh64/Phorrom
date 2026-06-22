"""Routes for Google Drive cloud backup (capability: sync)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..sync import drive, oauth
from ..storage.db import Database


class BackupRequest(BaseModel):
    passphrase: str


class RestoreRequest(BaseModel):
    file_id: str
    passphrase: str


def build_cloud_router() -> APIRouter:
    router = APIRouter()

    @router.get("/cloud/status")
    async def status() -> dict:
        return oauth.status()

    # Interactive (opens browser + blocks for consent) → sync def runs in a threadpool.
    @router.post("/cloud/connect")
    def connect() -> dict:
        return oauth.authorize()

    @router.post("/cloud/disconnect")
    async def disconnect() -> dict:
        return oauth.signout()

    @router.post("/cloud/backup")
    def backup(body: BackupRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        res = drive.backup(request.app.state.cfg.db_path, body.passphrase)
        if res.get("ok"):
            db.audit("user", "cloud_backup", {"name": res.get("snapshot", {}).get("name")})
        return res

    @router.get("/cloud/snapshots")
    def snapshots() -> dict:
        return drive.list_snapshots()

    @router.post("/cloud/restore")
    def restore(body: RestoreRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        res = drive.restore(body.file_id, body.passphrase, request.app.state.cfg.db_path)
        if res.get("ok"):
            db.audit("user", "cloud_restore", {"file_id": body.file_id})
        return res

    return router
