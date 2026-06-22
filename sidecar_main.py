"""Frozen entry point for the Phorrom sidecar (packaged by PyInstaller).

Runs the FastAPI app under uvicorn. Port/DB come from the environment so the Tauri shell can
point it wherever it wants; defaults match the dev setup (127.0.0.1:8008).
"""

from __future__ import annotations

import os

import uvicorn

from sidecar.app import create_app


def main() -> None:
    host = os.environ.get("PHORROM_HOST", "127.0.0.1")
    port = int(os.environ.get("PHORROM_PORT", "8008"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
