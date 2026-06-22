"""Document generation tests — grounded Markdown assembly + real DOCX via Pandoc (gated)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sidecar import tools
from sidecar.docs import generator
from sidecar.storage.db import Database


def _seed(db: Database) -> int:
    pid = db.create_project("Irrigation")
    db.add_problem_record(pid, "Reduce water waste in small farms", gap="existing kit is costly",
                          scope="smallholder farms", success_criteria=["30% less water"])
    db.add_idea(pid, "Soil-moisture sensor mesh", "low-cost ESP32 mesh", 0.8, 0.6, 0.9, 0.83,
                "directly buildable", ["IoT"])
    db.add_research_result(pid, "irrigation", "arxiv", "Soil moisture sensing with IoT",
                           ["A. Researcher"], 2024, "http://arxiv.org/abs/x", "abstract text")
    db.add_research_summary(pid, "irrigation", "Existing work covers X.", "Edge ML is white space.",
                            1, True)
    db.add_task(pid, "Build sensor node", impact=0.9)
    db.add_progress_assessment(pid, 0.5, 0.42, [], [{"type": "blocked", "severity": "medium",
                               "detail": "node firmware blocked"}], ["Unblock firmware"], "narr")
    return pid


def test_generate_markdown_is_grounded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    db = Database(":memory:")
    pid = _seed(db)
    res = generator.generate(db, pid, fmt="md", style="ieee")
    assert res["format"] == "md"
    assert Path(res["path"]).exists()
    md = res["markdown"]
    # real project data is present; references come from the retrieved result
    assert "Reduce water waste in small farms" in md
    assert "Soil-moisture sensor mesh" in md
    assert "Soil moisture sensing with IoT" in md   # cited prior art
    assert "Edge ML is white space." in md
    assert "Build sensor node" in md
    assert "References" in md
    db.close()


def test_generate_markdown_handles_empty_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    db = Database(":memory:")
    pid = db.create_project("Empty")
    md = generator.generate(db, pid, fmt="md")["markdown"]
    assert "No prior-art search" in md  # no fabrication when there's no data
    db.close()


def test_invalid_format_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    db = Database(":memory:")
    pid = db.create_project("P")
    with pytest.raises(ValueError):
        generator.generate(db, pid, fmt="xml")
    db.close()


@pytest.mark.skipif(tools.find_pandoc() is None, reason="pandoc not installed")
def test_generate_docx_via_pandoc(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    db = Database(":memory:")
    pid = _seed(db)
    res = generator.generate(db, pid, fmt="docx", style="apa")
    assert res["format"] == "docx", res.get("warning")
    out = Path(res["path"])
    assert out.suffix == ".docx" and out.exists() and out.stat().st_size > 0
    db.close()
