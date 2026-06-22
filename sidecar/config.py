"""Runtime configuration for the sidecar.

Problem solved: one typed place to read environment-supplied settings. The Tauri shell passes
secrets (API keys, bearer token) and paths via environment variables at launch; nothing is
read from disk or persisted here. Missing keys simply disable the corresponding provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    db_path: str
    auth_token: str | None  # bearer token shared by shell; None disables auth (dev)
    gemini_api_key: str | None
    ollama_host: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=os.environ.get("PHORROM_DB_PATH", "phorrom.sqlite"),
            auth_token=os.environ.get("PHORROM_TOKEN") or None,
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        )
