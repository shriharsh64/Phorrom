"""Phase 2 routes: projects, Problem-Statement Architect (#1), tasks + prioritization (#8),
and the governed File Manager (#9)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..capabilities import problem_architect, progress
from ..capabilities.prioritizer import compute_priorities
from ..files import manager as files
from ..files.manager import PathError
from ..storage.db import Database


# --- request models ---------------------------------------------------------
class CreateProject(BaseModel):
    name: str
    root_path: str | None = None


class SetRoot(BaseModel):
    root_path: str


class ProblemRequest(BaseModel):
    project_id: int
    description: str
    provider: str = "mock"
    model: str = "mock-small"


class CreateTask(BaseModel):
    project_id: int
    title: str
    description: str | None = None
    urgency: float | None = None
    impact: float | None = None
    depends_on: list[int] = Field(default_factory=list)


class TaskStatus(BaseModel):
    status: str


class ReadReq(BaseModel):
    project_id: int
    path: str = ""


class ProposeWrite(BaseModel):
    project_id: int
    path: str
    content: str
    reason: str | None = None


TASK_STATUSES = {"todo", "in_progress", "blocked", "done"}


def _root_or_400(db: Database, project_id: int) -> str:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    root = project.get("root_path")
    if not root:
        raise HTTPException(status_code=409, detail="project has no root_path set")
    return root


def build_phase2_router() -> APIRouter:
    router = APIRouter()

    # --- projects -----------------------------------------------------------
    @router.get("/projects")
    async def list_projects(request: Request) -> dict:
        return {"projects": request.app.state.db.list_projects()}

    @router.post("/projects")
    async def create_project(body: CreateProject, request: Request) -> dict:
        db: Database = request.app.state.db
        pid = db.create_project(body.name, body.root_path)
        return {"id": pid, **(db.get_project(pid) or {})}

    @router.post("/projects/{project_id}/root")
    async def set_root(project_id: int, body: SetRoot, request: Request) -> dict:
        db: Database = request.app.state.db
        if db.get_project(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        db.set_project_root(project_id, body.root_path)
        return {"id": project_id, "root_path": body.root_path}

    # --- problem statement (#1) --------------------------------------------
    @router.post("/problem/define")
    async def define_problem(body: ProblemRequest, request: Request) -> dict:
        db: Database = request.app.state.db
        record = await problem_architect.architect(
            request.app.state.registry, db, body.project_id, body.description,
            body.provider, body.model,
        )
        return {"record": record.model_dump(), "latest": db.latest_problem_record(body.project_id)}

    @router.get("/problem/latest")
    async def latest_problem(request: Request, project_id: int) -> dict:
        return {"record": request.app.state.db.latest_problem_record(project_id)}

    # --- tasks + prioritization (#8) ---------------------------------------
    @router.post("/tasks")
    async def create_task(body: CreateTask, request: Request) -> dict:
        db: Database = request.app.state.db
        tid = db.add_task(body.project_id, body.title, body.description,
                          body.urgency, body.impact, body.depends_on)
        _reprioritize(db, body.project_id)
        return {"id": tid}

    @router.get("/tasks")
    async def list_tasks(request: Request, project_id: int) -> dict:
        db: Database = request.app.state.db
        tasks = db.list_tasks(project_id)
        scores = compute_priorities(tasks)
        for t in tasks:
            t.update(scores.get(t["id"], {}))
        tasks.sort(key=lambda t: t.get("priority", 0), reverse=True)
        return {"tasks": tasks}

    @router.post("/tasks/{task_id}/status")
    async def set_task_status(task_id: int, body: TaskStatus, request: Request) -> dict:
        if body.status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status '{body.status}'")
        db: Database = request.app.state.db
        if not db.set_task_status(task_id, body.status):
            raise HTTPException(status_code=404, detail="task not found")
        return {"id": task_id, "status": body.status}

    # --- progress assessment (#7) ------------------------------------------
    @router.post("/progress/assess")
    async def assess_progress(body: ReadReq, request: Request) -> dict:
        db: Database = request.app.state.db
        return await progress.assess(request.app.state.registry, db, body.project_id)

    @router.get("/progress/latest")
    async def latest_progress(request: Request, project_id: int) -> dict:
        return {"assessment": request.app.state.db.latest_progress_assessment(project_id)}

    # --- governed file manager (#9) ----------------------------------------
    @router.post("/files/list")
    async def files_list(body: ReadReq, request: Request) -> dict:
        db: Database = request.app.state.db
        root = _root_or_400(db, body.project_id)
        try:
            return {"entries": files.list_dir(root, body.path)}
        except PathError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/files/read")
    async def files_read(body: ReadReq, request: Request) -> dict:
        db: Database = request.app.state.db
        root = _root_or_400(db, body.project_id)
        try:
            return files.read_file(root, body.path)
        except PathError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/files/propose")
    async def files_propose(body: ProposeWrite, request: Request) -> dict:
        db: Database = request.app.state.db
        root = _root_or_400(db, body.project_id)
        try:
            return files.propose_write(db, body.project_id, root, body.path, body.content, body.reason)
        except PathError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/files/commit/{write_id}")
    async def files_commit(write_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        pending = db.get_pending_write(write_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="pending write not found")
        root = _root_or_400(db, pending["project_id"])
        try:
            return files.commit_write(db, write_id, root)
        except PathError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.post("/files/reject/{write_id}")
    async def files_reject(write_id: int, request: Request) -> dict:
        db: Database = request.app.state.db
        try:
            return files.reject_write(db, write_id)
        except PathError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    return router


def _reprioritize(db: Database, project_id: int) -> None:
    tasks = db.list_tasks(project_id)
    for tid, score in compute_priorities(tasks).items():
        db.set_task_priority(tid, score["priority"])
