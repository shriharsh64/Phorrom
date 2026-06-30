"""Phase 6 routes: first-run workspace, the new-project wizard, per-feature prompt generation,
and folder autosave.

These power the launcher screen (choose a workspace, create or open a project) and keep each
project's folder in sync with the live DB so it can be backed up to the cloud.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..projects import setup
from ..storage.db import Database

# Setting keys (stored in app_settings).
WS_PATH = "workspace_path"
WS_NAME = "workspace_name"
AUTOSAVE_ENABLED = "autosave_enabled"
AUTOSAVE_INTERVAL = "autosave_interval_sec"
CLOUD_AUTOBACKUP = "cloud_autobackup"


class WorkspaceBody(BaseModel):
    path: str = ""
    name: str = ""


class SettingsBody(BaseModel):
    autosave_enabled: bool | None = None
    autosave_interval_sec: int | None = None
    cloud_autobackup: bool | None = None


class SuggestBody(BaseModel):
    description: str = ""
    deadline: str | None = None


class FeatureItem(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True


class CreateProjectBody(BaseModel):
    name: str
    description: str = ""
    deadline: str | None = None
    features: list[FeatureItem] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


def _settings_payload(db: Database) -> dict:
    path = db.get_setting(WS_PATH)
    return {
        "configured": bool(path),
        "workspace_path": path or setup.default_workspace(),
        "workspace_name": db.get_setting(WS_NAME) or "My Workspace",
        "autosave_enabled": db.get_setting(AUTOSAVE_ENABLED, "true") == "true",
        "autosave_interval_sec": int(db.get_setting(AUTOSAVE_INTERVAL, "120") or 120),
        "cloud_autobackup": db.get_setting(CLOUD_AUTOBACKUP, "false") == "true",
        "default_workspace": setup.default_workspace(),
    }


def build_setup_router() -> APIRouter:
    router = APIRouter()

    # --- settings / first-run workspace ------------------------------------
    @router.get("/settings")
    async def get_settings(request: Request) -> dict:
        return _settings_payload(request.app.state.db)

    @router.post("/settings/workspace")
    async def set_workspace(body: WorkspaceBody, request: Request) -> dict:
        db: Database = request.app.state.db
        path = (body.path or "").strip() or setup.default_workspace()
        try:
            info = setup.ensure_workspace(path, body.name or None)
        except OSError as e:
            raise HTTPException(status_code=400, detail=f"cannot create workspace: {e}") from e
        db.set_setting(WS_PATH, info["path"])
        db.set_setting(WS_NAME, body.name.strip() or info["name"])
        db.audit("user", "set_workspace", {"path": info["path"]})
        return _settings_payload(db)

    @router.post("/settings")
    async def update_settings(body: SettingsBody, request: Request) -> dict:
        db: Database = request.app.state.db
        if body.autosave_enabled is not None:
            db.set_setting(AUTOSAVE_ENABLED, "true" if body.autosave_enabled else "false")
        if body.autosave_interval_sec is not None:
            db.set_setting(AUTOSAVE_INTERVAL, str(max(15, int(body.autosave_interval_sec))))
        if body.cloud_autobackup is not None:
            db.set_setting(CLOUD_AUTOBACKUP, "true" if body.cloud_autobackup else "false")
        return _settings_payload(db)

    # --- new-project wizard helpers ----------------------------------------
    @router.get("/features/catalog")
    async def features_catalog() -> dict:
        return {"features": setup.FEATURES}

    @router.post("/projects/suggest-features")
    async def suggest_features(body: SuggestBody) -> dict:
        return setup.suggest_features(body.description, body.deadline)

    @router.post("/projects/create")
    async def create_project(body: CreateProjectBody, request: Request) -> dict:
        db: Database = request.app.state.db
        workspace = db.get_setting(WS_PATH)
        if not workspace:
            raise HTTPException(status_code=409, detail="workspace not configured")

        try:
            root = setup.scaffold_project(workspace, body.name)
        except OSError as e:
            raise HTTPException(status_code=400, detail=f"cannot create project folder: {e}") from e

        features = [f.model_dump() for f in body.features]
        # Build the project dict first so prompts can reference all its fields.
        project_meta = {
            "name": body.name,
            "description": body.description,
            "deadline": body.deadline,
            "features": features,
            "details": body.details,
        }
        prompts = setup.generate_prompts(project_meta)

        pid = db.create_project(
            body.name, root_path=root, description=body.description, deadline=body.deadline,
            features=features, details=body.details, prompts=prompts,
        )
        project = db.get_project(pid) or {}
        setup.write_project_files(root, project, prompts)
        # Seed a preliminary response in every feature the moment the description is stated.
        from .briefs_routes import generate_for_project
        generate_for_project(db, pid)
        setup.export_project_data(db, pid, root)
        return {"project": project}

    @router.get("/projects/{project_id}")
    async def get_project(project_id: int, request: Request) -> dict:
        project = request.app.state.db.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return {"project": project}

    @router.get("/projects/{project_id}/prompts")
    async def get_prompts(project_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        project = db.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        prompts = project.get("prompts") or setup.generate_prompts(project)
        return {"prompts": prompts, "features": setup.FEATURES}

    @router.post("/projects/{project_id}/prompts/regenerate")
    async def regenerate_prompts(project_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        project = db.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        prompts = setup.generate_prompts(project)
        db.update_project(project_id, prompts=prompts)
        if project.get("root_path"):
            setup.write_project_files(project["root_path"], {**project, "prompts": prompts}, prompts)
        return {"prompts": prompts}

    @router.post("/projects/{project_id}/sync")
    async def sync_project(project_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        project = db.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        root = project.get("root_path")
        if not root:
            raise HTTPException(status_code=409, detail="project has no folder on disk")
        return setup.export_project_data(db, project_id, root)

    return router
