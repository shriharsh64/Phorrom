"""File & Resource Manager (capability #9).

Problem solved: let the agent read project files for context and write logs/checklists/docs —
but *only* inside the project root, and *only* writes the user has approved with a diff preview.

Inputs : a project root path + a relative path supplied by the agent/user.
Outputs: directory listings, file contents, and a two-step write flow (propose → commit) where
         every committed write is audited.

Security: all paths are resolved and verified to stay within the project root; attempts to
escape (absolute paths, ``..`` traversal, symlinks pointing outside) raise ``PathError``.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from ..storage.db import Database

MAX_READ_BYTES = 400_000


class PathError(ValueError):
    """Raised when a requested path escapes the project root or is otherwise invalid."""


def resolve_in_root(root: str | Path, rel: str) -> Path:
    """Resolve ``rel`` against ``root`` and ensure the result stays inside ``root``."""

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise PathError(f"project root does not exist: {root_path}")
    # Reject absolute paths outright; resolve the rest and confirm containment.
    candidate = (root_path / rel).resolve()
    if not candidate.is_relative_to(root_path):
        raise PathError(f"path escapes project root: {rel}")
    return candidate


def list_dir(root: str | Path, rel: str = "") -> list[dict]:
    target = resolve_in_root(root, rel)
    if not target.is_dir():
        raise PathError(f"not a directory: {rel}")
    root_path = Path(root).resolve()
    entries: list[dict] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        entries.append({
            "name": child.name,
            "path": str(child.relative_to(root_path)).replace("\\", "/"),
            "is_dir": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else None,
        })
    return entries


def read_file(root: str | Path, rel: str) -> dict:
    target = resolve_in_root(root, rel)
    if not target.is_file():
        raise PathError(f"not a file: {rel}")
    raw = target.read_bytes()
    truncated = len(raw) > MAX_READ_BYTES
    text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
    return {"path": rel, "content": text, "truncated": truncated, "size": len(raw)}


def _diff(old: str, new: str, rel: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def propose_write(
    db: Database, project_id: int, root: str | Path, rel: str, content: str, reason: str | None
) -> dict:
    """Stage a write for approval; returns the pending id and a unified diff preview."""

    target = resolve_in_root(root, rel)  # validates containment before staging
    old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    diff = _diff(old, content, rel)
    write_id = db.add_pending_write(project_id, rel, content, diff, reason)
    db.audit("agent", "propose_write", {"id": write_id, "path": rel, "reason": reason})
    return {"id": write_id, "path": rel, "diff": diff, "exists": target.is_file()}


def commit_write(db: Database, write_id: int, root: str | Path) -> dict:
    """Perform a previously-proposed, user-approved write and audit it."""

    pending = db.get_pending_write(write_id)
    if pending is None:
        raise PathError(f"no pending write #{write_id}")
    if pending["status"] != "pending":
        raise PathError(f"write #{write_id} already {pending['status']}")
    target = resolve_in_root(root, pending["rel_path"])  # re-validate at commit time
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(pending["content"], encoding="utf-8")
    db.set_pending_write_status(write_id, "committed")
    db.audit("user", "commit_write", {"id": write_id, "path": pending["rel_path"]})
    return {"id": write_id, "path": pending["rel_path"], "bytes": len(pending["content"])}


def reject_write(db: Database, write_id: int) -> dict:
    pending = db.get_pending_write(write_id)
    if pending is None:
        raise PathError(f"no pending write #{write_id}")
    db.set_pending_write_status(write_id, "rejected")
    db.audit("user", "reject_write", {"id": write_id, "path": pending["rel_path"]})
    return {"id": write_id, "status": "rejected"}
