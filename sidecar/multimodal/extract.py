"""OCR + speech-to-text via local CLIs.

Problem solved: bring images and audio into the agent as text. OCR shells out to Tesseract;
transcription shells out to whisper.cpp's CLI with a local GGML model. Both are local/offline
and free. Each returns a clear error dict if its tool/model isn't installed rather than raising.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import tools


def ocr_image(image_path: str, lang: str = "eng") -> dict:
    """Run Tesseract on an image, returning recognized text."""
    tess = tools.find_tesseract()
    if tess is None:
        return {"ok": False, "error": "Tesseract not found", "text": ""}
    if not Path(image_path).is_file():
        return {"ok": False, "error": f"file not found: {image_path}", "text": ""}
    try:
        # `tesseract <img> stdout` prints recognized text to stdout.
        proc = subprocess.run([tess, image_path, "stdout", "-l", lang],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"tesseract failed: {e}", "text": ""}
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip()[:400], "text": ""}
    return {"ok": True, "text": proc.stdout.strip(), "engine": "tesseract"}


def transcribe_audio(audio_path: str, model: str | None = None) -> dict:
    """Transcribe a WAV/MP3 with whisper.cpp. Audio should be 16kHz WAV for best results."""
    whisper = tools.find_whisper()
    if whisper is None:
        return {"ok": False, "error": "whisper.cpp CLI not found", "text": ""}
    model = model or tools.find_whisper_model()
    if model is None:
        return {"ok": False, "error": "no whisper GGML model found (place ggml-*.bin in sidecar/Release)", "text": ""}
    if not Path(audio_path).is_file():
        return {"ok": False, "error": f"file not found: {audio_path}", "text": ""}
    try:
        # -nt: no timestamps, -np: no progress prints → clean transcript on stdout.
        proc = subprocess.run([whisper, "-m", model, "-f", audio_path, "-nt", "-np"],
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"whisper failed: {e}", "text": ""}
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip()[:400], "text": ""}
    return {"ok": True, "text": proc.stdout.strip(), "engine": "whisper.cpp", "model": Path(model).name}
