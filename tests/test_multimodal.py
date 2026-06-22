"""Multimodal OCR/transcription tests — mocked subprocess + a live tesseract smoke (gated)."""

from __future__ import annotations

import subprocess

import pytest

from sidecar import tools
from sidecar.multimodal import extract


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_ocr_reports_missing_tool(monkeypatch) -> None:
    monkeypatch.setattr(tools, "find_tesseract", lambda: None)
    r = extract.ocr_image("whatever.png")
    assert r["ok"] is False and "Tesseract" in r["error"]


def test_ocr_parses_stdout(monkeypatch, tmp_path) -> None:
    img = tmp_path / "a.png"; img.write_bytes(b"\x89PNG")
    monkeypatch.setattr(tools, "find_tesseract", lambda: "tesseract")
    monkeypatch.setattr(extract.subprocess, "run", lambda *a, **k: _Proc(0, "Hello OCR\n"))
    r = extract.ocr_image(str(img))
    assert r["ok"] is True and r["text"] == "Hello OCR" and r["engine"] == "tesseract"


def test_transcribe_reports_missing_model(monkeypatch, tmp_path) -> None:
    aud = tmp_path / "a.wav"; aud.write_bytes(b"RIFF")
    monkeypatch.setattr(tools, "find_whisper", lambda: "whisper-cli")
    monkeypatch.setattr(tools, "find_whisper_model", lambda: None)
    r = extract.transcribe_audio(str(aud))
    assert r["ok"] is False and "model" in r["error"]


def test_transcribe_parses_stdout(monkeypatch, tmp_path) -> None:
    aud = tmp_path / "a.wav"; aud.write_bytes(b"RIFF")
    monkeypatch.setattr(tools, "find_whisper", lambda: "whisper-cli")
    monkeypatch.setattr(tools, "find_whisper_model", lambda: "ggml-tiny.en.bin")
    monkeypatch.setattr(extract.subprocess, "run", lambda *a, **k: _Proc(0, " transcribed text "))
    r = extract.transcribe_audio(str(aud))
    assert r["ok"] is True and r["text"] == "transcribed text"


@pytest.mark.skipif(tools.find_tesseract() is None, reason="tesseract not installed")
def test_tesseract_executable_runs() -> None:
    out = subprocess.run([tools.find_tesseract(), "--version"], capture_output=True, text=True)
    assert out.returncode == 0 and "tesseract" in (out.stdout + out.stderr).lower()
