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

SCHEMA_VERSION = 7

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

-- Shared skill model: the bridge between Ideation (#2) and the Resource Advisor (#3).
-- A concept starts as a 'gap' (often surfaced during ideation), becomes 'learning' once the
-- user starts the related material, and 'mastered' once done. Mastered concepts are fed back
-- to ideation so the engine can reason at a higher level next time.
CREATE TABLE IF NOT EXISTS concepts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'gap',     -- gap|learning|mastered
    origin      TEXT NOT NULL DEFAULT 'advisor', -- ideation|advisor|user
    notes       TEXT,
    created_at  REAL NOT NULL,
    UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS resource_suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage       TEXT,                            -- e.g. ideation|prototyping|deployment
    kind        TEXT NOT NULL,                   -- library|api|dataset|hardware|service|tool
    name        TEXT NOT NULL,
    description TEXT,
    url         TEXT,
    is_free     INTEGER NOT NULL DEFAULT 1,
    rationale   TEXT,
    status      TEXT NOT NULL DEFAULT 'suggested', -- suggested|accepted|done|dismissed
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    concept      TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    source       TEXT,                           -- youtube|arxiv|freecodecamp|mdn|docs|other
    rationale    TEXT,
    prereq_order INTEGER NOT NULL DEFAULT 0,      -- lower = earlier (prerequisite-first)
    is_gap       INTEGER NOT NULL DEFAULT 0,      -- 1 = targets a gap (weighted higher)
    priority     REAL NOT NULL DEFAULT 0,         -- higher = study sooner within its prereq tier
    status       TEXT NOT NULL DEFAULT 'todo',    -- todo|in_progress|done
    created_at   REAL NOT NULL
);

-- Breakthrough opportunities: high-leverage improvements where progress yields a concrete
-- project-goal benefit (business, speed, maintainability/ease-of-change, scalability, cost,
-- UX, or learning). Ranked by a score derived from impact, benefit breadth, and effort.
CREATE TABLE IF NOT EXISTS breakthroughs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    description      TEXT,
    benefit_types    TEXT,                        -- json array: business|speed|maintainability|...
    impact           TEXT,                        -- high|medium|low
    effort           TEXT,                        -- high|medium|low
    rationale        TEXT,
    related_concepts TEXT,                        -- json array of concept names
    score            REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'suggested', -- suggested|exploring|done|dismissed
    created_at       REAL NOT NULL
);
"""

# Problem records (capability #1) — the structured output of the Problem-Statement Architect.
SCHEMA += """
CREATE TABLE IF NOT EXISTS problem_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    statement        TEXT NOT NULL,
    scope            TEXT,
    gap              TEXT,
    stakeholders     TEXT,                          -- json array
    success_criteria TEXT,                          -- json array
    constraints      TEXT,                          -- json array
    assumptions      TEXT,                          -- json array
    validation       TEXT,                          -- notes on whether it's well-formed
    status           TEXT NOT NULL DEFAULT 'draft', -- draft|validated|archived
    created_at       REAL NOT NULL
);

-- Governed file writes await explicit user approval (capability #9). A proposed write is
-- staged here with a diff; committing it performs the actual write and audits it.
CREATE TABLE IF NOT EXISTS pending_writes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rel_path    TEXT NOT NULL,
    content     TEXT NOT NULL,
    diff        TEXT,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|committed|rejected
    created_at  REAL NOT NULL
);

-- Ideas (capability #2 — Ideation & Concept Engine). Ranked by feasibility x novelty x
-- relevance. Each idea's required_concepts that the user hasn't mastered are written back as
-- 'gap' concepts (origin='ideation'), which the Resource Advisor (#3) then targets.
CREATE TABLE IF NOT EXISTS ideas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    description       TEXT,
    feasibility       REAL,
    novelty           REAL,
    relevance         REAL,
    score             REAL NOT NULL DEFAULT 0,
    rationale         TEXT,
    required_concepts TEXT,                          -- json array
    status            TEXT NOT NULL DEFAULT 'suggested', -- suggested|selected|dismissed
    created_at        REAL NOT NULL
);

-- Contextual-bandit arms: one Beta(alpha,beta) posterior per (provider, model, task_type).
-- The router Thompson-samples these to learn each model's real strength from observed reward
-- (reward = quality − λ·cost, in 0..1). Persisted so learning survives restarts.
CREATE TABLE IF NOT EXISTS bandit_arms (
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    task_type  TEXT NOT NULL,
    alpha      REAL NOT NULL DEFAULT 1.0,
    beta       REAL NOT NULL DEFAULT 1.0,
    updates    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, model, task_type)
);

-- Prior-art / patent research (capability #4). Each row is a real retrieved result (never
-- fabricated); summaries are grounded only in these rows and cite them by index.
CREATE TABLE IF NOT EXISTS research_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    source      TEXT NOT NULL,                   -- arxiv|semantic_scholar|google_patents
    title       TEXT NOT NULL,
    authors     TEXT,                            -- json array
    year        INTEGER,
    url         TEXT,
    abstract    TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS research_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    summary     TEXT,
    white_space TEXT,
    n_results   INTEGER NOT NULL DEFAULT 0,
    grounded    INTEGER NOT NULL DEFAULT 1,      -- 0 if heuristic/ungrounded fallback was used
    created_at  REAL NOT NULL
);
"""

# Columns added after the initial v2 release, applied to existing DBs via ALTER (see _migrate).
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("learning_items", "is_gap", "INTEGER NOT NULL DEFAULT 0"),
    ("learning_items", "priority", "REAL NOT NULL DEFAULT 0"),
    ("tasks", "urgency", "REAL"),
    ("tasks", "impact", "REAL"),
    ("tasks", "depends_on", "TEXT"),
]


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._bootstrap()

    def _bootstrap(self) -> None:
        self.conn.executescript(SCHEMA)  # creates any missing tables
        self._migrate()                  # adds any missing columns to pre-existing tables
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def _migrate(self) -> None:
        for table, column, decl in _ADDED_COLUMNS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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

    def list_projects(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_project(self, project_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def set_project_root(self, project_id: int, root_path: str) -> None:
        self.conn.execute(
            "UPDATE projects SET root_path=? WHERE id=?", (root_path, project_id)
        )
        self.conn.commit()

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

    # --- concepts (shared skill model / ideation bridge) -----------------------
    def upsert_concept(
        self,
        project_id: int,
        name: str,
        status: str = "gap",
        origin: str = "advisor",
        notes: str | None = None,
    ) -> int:
        """Insert a concept, or keep the existing one (never downgrade a mastered concept)."""

        name = name.strip()
        existing = self.conn.execute(
            "SELECT id, status FROM concepts WHERE project_id=? AND name=?",
            (project_id, name),
        ).fetchone()
        if existing is not None:
            # Only fill in notes if missing; preserve a higher status (gap < learning < mastered).
            if notes:
                self.conn.execute(
                    "UPDATE concepts SET notes=COALESCE(notes, ?) WHERE id=?",
                    (notes, existing["id"]),
                )
                self.conn.commit()
            return int(existing["id"])
        cur = self.conn.execute(
            "INSERT INTO concepts(project_id, name, status, origin, notes, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (project_id, name, status, origin, notes, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_concept_status(self, project_id: int, name: str, status: str) -> None:
        self.conn.execute(
            "UPDATE concepts SET status=? WHERE project_id=? AND name=?",
            (status, project_id, name.strip()),
        )
        self.conn.commit()

    def list_concepts(self, project_id: int, status: str | None = None) -> list[dict]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM concepts WHERE project_id=? ORDER BY name", (project_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM concepts WHERE project_id=? AND status=? ORDER BY name",
                (project_id, status),
            ).fetchall()
        return [dict(r) for r in rows]

    def mastered_concepts(self, project_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM concepts WHERE project_id=? AND status='mastered' ORDER BY name",
            (project_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # --- resource suggestions --------------------------------------------------
    def add_resource_suggestion(
        self,
        project_id: int,
        kind: str,
        name: str,
        stage: str | None = None,
        description: str | None = None,
        url: str | None = None,
        is_free: bool = True,
        rationale: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO resource_suggestions(project_id, stage, kind, name, description, url,"
            " is_free, rationale, status, created_at) VALUES(?,?,?,?,?,?,?,?, 'suggested', ?)",
            (project_id, stage, kind, name, description, url, int(is_free), rationale, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_resource_suggestions(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM resource_suggestions WHERE project_id=? ORDER BY kind, id",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_resource_status(self, item_id: int, status: str) -> bool:
        cur = self.conn.execute(
            "UPDATE resource_suggestions SET status=? WHERE id=?", (status, item_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # --- learning items --------------------------------------------------------
    def add_learning_item(
        self,
        project_id: int,
        concept: str,
        title: str,
        url: str | None = None,
        source: str | None = None,
        rationale: str | None = None,
        prereq_order: int = 0,
        is_gap: bool = False,
        priority: float = 0.0,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO learning_items(project_id, concept, title, url, source, rationale,"
            " prereq_order, is_gap, priority, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?, 'todo', ?)",
            (project_id, concept, title, url, source, rationale, prereq_order,
             int(is_gap), priority, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_learning_items(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM learning_items WHERE project_id=?"
            " ORDER BY prereq_order, priority DESC, id",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_learning_item(self, item_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM learning_items WHERE id=?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_learning_status(self, item_id: int, status: str) -> dict | None:
        """Set a learning item's status and reconcile the parent concept's mastery.

        Returns the updated item dict (or None if it doesn't exist). A concept becomes
        'mastered' once all its learning items are done, 'learning' once any is started.
        """

        item = self.get_learning_item(item_id)
        if item is None:
            return None
        self.conn.execute(
            "UPDATE learning_items SET status=? WHERE id=?", (status, item_id)
        )
        self.conn.commit()

        project_id, concept = item["project_id"], item["concept"]
        rows = self.conn.execute(
            "SELECT status FROM learning_items WHERE project_id=? AND concept=?",
            (project_id, concept),
        ).fetchall()
        statuses = [r["status"] for r in rows]
        if statuses and all(s == "done" for s in statuses):
            self.set_concept_status(project_id, concept, "mastered")
        elif any(s in ("in_progress", "done") for s in statuses):
            self.set_concept_status(project_id, concept, "learning")
        return self.get_learning_item(item_id)

    # --- breakthrough opportunities --------------------------------------------
    def add_breakthrough(
        self,
        project_id: int,
        title: str,
        description: str | None = None,
        benefit_types: list[str] | None = None,
        impact: str | None = None,
        effort: str | None = None,
        rationale: str | None = None,
        related_concepts: list[str] | None = None,
        score: float = 0.0,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO breakthroughs(project_id, title, description, benefit_types, impact,"
            " effort, rationale, related_concepts, score, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?, 'suggested', ?)",
            (project_id, title, description, json.dumps(benefit_types or []), impact, effort,
             rationale, json.dumps(related_concepts or []), score, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_breakthroughs(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM breakthroughs WHERE project_id=? ORDER BY score DESC, id",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["benefit_types"] = json.loads(d.get("benefit_types") or "[]")
            d["related_concepts"] = json.loads(d.get("related_concepts") or "[]")
            out.append(d)
        return out

    def set_breakthrough_status(self, item_id: int, status: str) -> bool:
        cur = self.conn.execute(
            "UPDATE breakthroughs SET status=? WHERE id=?", (status, item_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def clear_advisor_outputs(self, project_id: int) -> None:
        """Remove prior suggestions/learning items/breakthroughs before a fresh run.

        Concepts are preserved so mastery/progress survive re-runs.
        """

        self.conn.execute("DELETE FROM resource_suggestions WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM learning_items WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM breakthroughs WHERE project_id=?", (project_id,))
        self.conn.commit()

    # --- problem records (capability #1) ---------------------------------------
    def add_problem_record(
        self,
        project_id: int,
        statement: str,
        scope: str | None = None,
        gap: str | None = None,
        stakeholders: list[str] | None = None,
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        assumptions: list[str] | None = None,
        validation: str | None = None,
        status: str = "draft",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO problem_records(project_id, statement, scope, gap, stakeholders,"
            " success_criteria, constraints, assumptions, validation, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, statement, scope, gap, json.dumps(stakeholders or []),
             json.dumps(success_criteria or []), json.dumps(constraints or []),
             json.dumps(assumptions or []), validation, status, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _decode_problem(row: dict) -> dict:
        for f in ("stakeholders", "success_criteria", "constraints", "assumptions"):
            row[f] = json.loads(row.get(f) or "[]")
        return row

    def latest_problem_record(self, project_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM problem_records WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return self._decode_problem(dict(row)) if row else None

    def list_problem_records(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM problem_records WHERE project_id=? ORDER BY id DESC", (project_id,)
        ).fetchall()
        return [self._decode_problem(dict(r)) for r in rows]

    # --- tasks + prioritization (capabilities #8) ------------------------------
    def add_task(
        self,
        project_id: int,
        title: str,
        description: str | None = None,
        urgency: float | None = None,
        impact: float | None = None,
        depends_on: list[int] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks(project_id, title, description, urgency, impact, depends_on,"
            " status, created_at) VALUES(?,?,?,?,?,?, 'todo', ?)",
            (project_id, title, description, urgency, impact,
             json.dumps(depends_on or []), time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_tasks(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY COALESCE(priority,0) DESC, id",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["depends_on"] = json.loads(d.get("depends_on") or "[]")
            out.append(d)
        return out

    def set_task_priority(self, task_id: int, priority: float) -> None:
        self.conn.execute("UPDATE tasks SET priority=? WHERE id=?", (priority, task_id))
        self.conn.commit()

    def set_task_status(self, task_id: int, status: str) -> bool:
        cur = self.conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
        self.conn.commit()
        return cur.rowcount > 0

    # --- subtasks (orchestrator DAG) -------------------------------------------
    def add_subtask(
        self,
        task_id: int,
        external_id: str,
        type: str,
        depends_on: list[str],
        size_hint: int,
        value: float,
        p_required: float,
        quality_sensitivity: float,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO subtasks(task_id, external_id, type, depends_on, size_hint, value,"
            " p_required, quality_sensitivity, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?, 'pending', ?)",
            (task_id, external_id, type, json.dumps(depends_on), size_hint, value,
             p_required, quality_sensitivity, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_subtasks(self, task_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["depends_on"] = json.loads(d.get("depends_on") or "[]")
            out.append(d)
        return out

    # --- ideas (capability #2) -------------------------------------------------
    def add_idea(
        self,
        project_id: int,
        title: str,
        description: str | None,
        feasibility: float | None,
        novelty: float | None,
        relevance: float | None,
        score: float,
        rationale: str | None,
        required_concepts: list[str] | None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ideas(project_id, title, description, feasibility, novelty, relevance,"
            " score, rationale, required_concepts, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?, 'suggested', ?)",
            (project_id, title, description, feasibility, novelty, relevance, score, rationale,
             json.dumps(required_concepts or []), time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_ideas(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM ideas WHERE project_id=? ORDER BY score DESC, id", (project_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["required_concepts"] = json.loads(d.get("required_concepts") or "[]")
            out.append(d)
        return out

    def set_idea_status(self, idea_id: int, status: str) -> bool:
        cur = self.conn.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
        self.conn.commit()
        return cur.rowcount > 0

    def clear_ideas(self, project_id: int) -> None:
        self.conn.execute("DELETE FROM ideas WHERE project_id=?", (project_id,))
        self.conn.commit()

    # --- contextual-bandit arms (router learning) ------------------------------
    def get_bandit_arm(self, provider: str, model: str, task_type: str) -> tuple[float, float]:
        row = self.conn.execute(
            "SELECT alpha, beta FROM bandit_arms WHERE provider=? AND model=? AND task_type=?",
            (provider, model, task_type),
        ).fetchone()
        return (row["alpha"], row["beta"]) if row else (1.0, 1.0)

    def update_bandit_arm(self, provider: str, model: str, task_type: str, reward: float) -> None:
        reward = max(0.0, min(1.0, reward))
        alpha, beta = self.get_bandit_arm(provider, model, task_type)
        self.conn.execute(
            "INSERT INTO bandit_arms(provider, model, task_type, alpha, beta, updates)"
            " VALUES(?,?,?,?,?,1)"
            " ON CONFLICT(provider, model, task_type) DO UPDATE SET"
            " alpha=alpha+?, beta=beta+?, updates=updates+1",
            (provider, model, task_type, 1.0 + reward, 1.0 + (1.0 - reward),
             reward, 1.0 - reward),
        )
        self.conn.commit()

    def list_bandit_arms(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT *, alpha/(alpha+beta) AS mean FROM bandit_arms ORDER BY provider, model, task_type"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- prior-art research (capability #4) ------------------------------------
    def add_research_result(
        self, project_id: int, query: str, source: str, title: str,
        authors: list[str] | None, year: int | None, url: str | None, abstract: str | None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO research_results(project_id, query, source, title, authors, year, url,"
            " abstract, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, query, source, title, json.dumps(authors or []), year, url, abstract,
             time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_research_results(self, project_id: int, query: str | None = None) -> list[dict]:
        if query is None:
            rows = self.conn.execute(
                "SELECT * FROM research_results WHERE project_id=? ORDER BY id DESC", (project_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM research_results WHERE project_id=? AND query=? ORDER BY id DESC",
                (project_id, query),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["authors"] = json.loads(d.get("authors") or "[]")
            out.append(d)
        return out

    def add_research_summary(
        self, project_id: int, query: str, summary: str | None, white_space: str | None,
        n_results: int, grounded: bool,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO research_summaries(project_id, query, summary, white_space, n_results,"
            " grounded, created_at) VALUES(?,?,?,?,?,?,?)",
            (project_id, query, summary, white_space, n_results, int(grounded), time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_research_summary(self, project_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM research_summaries WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return dict(row) if row else None

    # --- governed file writes (capability #9) ----------------------------------
    def add_pending_write(
        self, project_id: int, rel_path: str, content: str, diff: str, reason: str | None
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO pending_writes(project_id, rel_path, content, diff, reason, status,"
            " created_at) VALUES(?,?,?,?,?, 'pending', ?)",
            (project_id, rel_path, content, diff, reason, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_pending_write(self, write_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM pending_writes WHERE id=?", (write_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_pending_write_status(self, write_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE pending_writes SET status=? WHERE id=?", (status, write_id)
        )
        self.conn.commit()
