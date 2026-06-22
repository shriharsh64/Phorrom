"""Storage-layer tests — in-memory SQLite, no external services."""

from __future__ import annotations

from sidecar.storage.db import SCHEMA_VERSION, Database


def test_schema_bootstraps_with_version() -> None:
    db = Database(":memory:")
    row = db.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert int(row["value"]) == SCHEMA_VERSION
    db.close()


def test_chat_history_roundtrip_and_ordering() -> None:
    db = Database(":memory:")
    pid = db.create_project("demo")
    db.add_chat_message("user", "hi", project_id=pid)
    db.add_chat_message("assistant", "hello", project_id=pid, provider="mock", model="mock-small")
    history = db.chat_history(project_id=pid)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["content"] == "hello"
    db.close()


def test_record_run_updates_token_ledger() -> None:
    db = Database(":memory:")
    db.record_run("mock", "mock-small", tokens_in=10, tokens_out=5, latency_ms=1.0)
    db.record_run("mock", "mock-large", tokens_in=20, tokens_out=20, latency_ms=2.0)
    assert db.tokens_consumed("mock") == 55
    assert db.tokens_consumed() == 55
    assert db.tokens_consumed("gemini") == 0
    db.close()


def test_audit_log_appends() -> None:
    db = Database(":memory:")
    db.audit("user", "test_action", {"foo": "bar"})
    row = db.conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()
    assert row["c"] == 1
    db.close()
