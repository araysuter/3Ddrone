from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path = Path(os.getenv("MAPPER_DATA_ROOT", "/data"))
    nodeodm_url: str = os.getenv("NODEODM_URL", "http://nodeodm:3000").rstrip("/")
    nodeodm_token: str = os.getenv("NODEODM_TOKEN", "")
    splat_url: str = os.getenv("SPLAT_URL", "http://splat-worker:8090").rstrip("/")
    internal_token: str = os.getenv("MAPPER_INTERNAL_TOKEN", "")
    cookie_secure: bool = os.getenv("MAPPER_COOKIE_SECURE", "true").lower() == "true"
    demo_mode: bool = os.getenv("MAPPER_DEMO_MODE", "false").lower() == "true"
    session_hours: int = int(os.getenv("MAPPER_SESSION_HOURS", "24"))

    @property
    def database_path(self) -> Path:
        return self.data_root / "metadata" / "mapper.sqlite3"

    def ensure_directories(self) -> None:
        for name in ("source", "nodeodm", "splat", "metadata", "logs", "uploads"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)


settings = Settings()
if not settings.internal_token:
    # This remains process-local in development. Production compose requires an
    # explicit token so the API and worker agree across restarts.
    object.__setattr__(settings, "internal_token", secrets.token_urlsafe(32))
