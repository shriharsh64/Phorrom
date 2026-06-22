"""SQLite storage layer.

Problem solved: durable, local, zero-config persistence for projects, the task/subtask graph,
model runs, the token ledger, provider quotas, an append-only audit log, and chat history.

Inputs : a database path (or ":memory:" for tests).
Outputs: a thin connection wrapper with schema bootstrap + typed helpers.

Design notes:
- One schema, created idempotently on connect; ``schema_version`` row tracks migrations.
- The token ledger is the single source of truth for budgeting (Phase 3); every model run
  appends to it so reservation/optimization run on real numbers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    root_path   TEXT,
    cloud_allowed INTEGER NOT NULL DEFAULT 0,  -- per-project privacy switch
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'todo',   -- todo|in_progress|blocked|done
    priority    REAL,                           -- 0..1, set by prioritizer
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS subtasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    external_id         TEXT,                   -- id from the decomposition DAG
    type                TEXT,                   -- coding|reasoning|summarization|...
    depends_on          TEXT,                   -- json array of external_ids
    size_hint           INTEGER,                -- expected token magnitude
    value               REAL,                   -- business value weight
    p_required          REAL,                   -- probability this is actually needed
    quality_sensitivity REAL,                   -- how much output quality matters
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subtask_id  INTEGER REFERENCES subtasks(id) ON DELETE SET NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    latency_ms  REAL NOT NULL,
    quality     REAL,                           -- observed/judged quality 0..1
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS token_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    model       TEXT,
    tokens      INTEGER NOT NULL,               -- consumed (+) on this entry
    kind        TEXT NOT NULL DEFAULT 'consume', -- consume|reserve|reset
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_quota (
    provider     TEXT PRIMARY KEY,
    rpd_limit    INTEGER,                        -- requests/day
    tpd_limit    INTEGER,                        -- tokens/day
    consumed_tpd INTEGER NOT NULL DEFAULT 0,
    reset_at     REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,                   -- 'user' | 'agent'
    action      TEXT NOT NULL,
    detail      TEXT,                            -- json
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    provider    TEXT,
    model       TEXT,
    created_at  REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._bootstrap()

    def _bootstrap(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- audit -----------------------------------------------------------------
    def audit(self, actor: str, action: str, detail: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit_log(actor, action, detail, created_at) VALUES(?,?,?,?)",
            (actor, action, json.dumps(detail or {}), time.time()),
        )
        self.conn.commit()

    # --- projects --------------------------------------------------------------
    def create_project(self, name: str, root_path: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO projects(name, root_path, created_at) VALUES(?,?,?)",
            (name, root_path, time.time()),
        )
        self.conn.commit()
        self.audit("user", "create_project", {"name": name})
        return int(cur.lastrowid)

    # --- chat ------------------------------------------------------------------
    def add_chat_message(
        self,
        role: str,
        content: str,
        project_id: int | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO chat_messages(project_id, role, content, provider, model, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (project_id, role, content, provider, model, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def chat_history(self, project_id: int | None = None, limit: int = 100) -> list[dict]:
        if project_id is None:
            rows = self.conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM chat_messages WHERE project_id=? ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --- runs + token ledger ---------------------------------------------------
    def record_run(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        subtask_id: int | None = None,
        quality: float | None = None,
    ) -> int:
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO runs(subtask_id, provider, model, tokens_in, tokens_out,"
            " latency_ms, quality, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (subtask_id, provider, model, tokens_in, tokens_out, latency_ms, quality, now),
        )
        self.conn.execute(
            "INSERT INTO token_ledger(provider, model, tokens, kind, created_at)"
            " VALUES(?,?,?,'consume',?)",
            (provider, model, tokens_in + tokens_out, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def tokens_consumed(self, provider: str | None = None) -> int:
        if provider is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(tokens),0) AS t FROM token_ledger WHERE kind='consume'"
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(tokens),0) AS t FROM token_ledger"
                " WHERE kind='consume' AND provider=?",
                (provider,),
            ).fetchone()
        return int(row["t"])
