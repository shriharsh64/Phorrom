"""Discovery of external CLI tools (Pandoc, LaTeX/TinyTeX, Tesseract, whisper.cpp).

Problem solved: the document and multimodal features shell out to native tools that live in
different places per machine. This centralizes locating them — env override first, then PATH,
then well-known install locations / project-relative folders — so the rest of the code just
asks ``tools.find_pandoc()`` etc. Everything degrades gracefully: if a tool is missing the
feature reports it instead of crashing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def project_root() -> Path:
    return Path(os.environ.get("PHORROM_ROOT") or os.getcwd())


def _first_existing(paths: list[str | Path | None]) -> str | None:
    for p in paths:
        if p and Path(p).exists():
            return str(p)
    return None


def find_pandoc() -> str | None:
    return (
        os.environ.get("PHORROM_PANDOC")
        or shutil.which("pandoc")
        or _first_existing([r"C:\Program Files\Pandoc\pandoc.exe",
                            r"C:\Program Files (x86)\Pandoc\pandoc.exe"])
    )


def latex_bin_dir() -> str | None:
    """Directory containing pdflatex/xelatex — added to PATH so Pandoc can find the engine."""
    env = os.environ.get("PHORROM_LATEX_BIN")
    if env and Path(env).exists():
        return env
    root = project_root()
    candidates = [
        root / "TinyTeX" / "bin" / "windows",
        Path.home() / "AppData" / "Roaming" / "TinyTeX" / "bin" / "windows",
        Path.home() / ".TinyTeX" / "bin" / "windows",
    ]
    for d in candidates:
        if (d / "pdflatex.exe").exists() or (d / "pdflatex").exists():
            return str(d)
    p = shutil.which("pdflatex")
    return str(Path(p).parent) if p else None


def find_tesseract() -> str | None:
    return (
        os.environ.get("PHORROM_TESSERACT")
        or shutil.which("tesseract")
        or _first_existing([r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"])
    )


def find_whisper() -> str | None:
    env = os.environ.get("PHORROM_WHISPER")
    if env and Path(env).exists():
        return env
    rel = project_root() / "sidecar" / "Release"
    for name in ("whisper-cli.exe", "main.exe", "whisper-cli", "main"):
        if (rel / name).exists():
            return str(rel / name)
    return shutil.which("whisper-cli") or shutil.which("whisper")


def find_whisper_model() -> str | None:
    env = os.environ.get("PHORROM_WHISPER_MODEL")
    if env and Path(env).exists():
        return env
    rel = project_root() / "sidecar" / "Release"
    if rel.is_dir():
        models = sorted(rel.glob("ggml-*.bin"))
        if models:
            return str(models[0])
    return None


def status() -> dict:
    """Snapshot of which tools are available (for the Docs/Settings UI)."""
    return {
        "pandoc": find_pandoc(),
        "latex_bin": latex_bin_dir(),
        "tesseract": find_tesseract(),
        "whisper": find_whisper(),
        "whisper_model": find_whisper_model(),
    }
