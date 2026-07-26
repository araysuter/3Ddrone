from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a whole number") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default).lower()).lower()
    if raw not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return raw == "true"


@dataclass(frozen=True)
class Settings:
    data_root: Path = Path(os.getenv("MAPPER_DATA_ROOT", "/data")).resolve()
    nodeodm_url: str = os.getenv("NODEODM_URL", "http://nodeodm:3000").rstrip("/")
    nodeodm_token: str = os.getenv("NODEODM_TOKEN", "")
    splat_url: str = os.getenv("SPLAT_URL", "http://splat-worker:8090").rstrip("/")
    internal_token: str = os.getenv("MAPPER_INTERNAL_TOKEN", "")
    sharing_enabled: bool = _env_bool("MAPPER_SHARING_ENABLED", False)
    public_base_url: str = os.getenv(
        "MAPPER_PUBLIC_BASE_URL", "https://dronemaps.ashersuter.com"
    ).rstrip("/")
    cookie_secure: bool = _env_bool("MAPPER_COOKIE_SECURE", True)
    demo_mode: bool = _env_bool("MAPPER_DEMO_MODE", False)
    session_hours: int = _env_int("MAPPER_SESSION_HOURS", 24)
    max_upload_bytes: int = _env_int("MAPPER_MAX_UPLOAD_BYTES", 100 * 1024**3)
    max_chunk_bytes: int = _env_int("MAPPER_MAX_CHUNK_BYTES", 8 * 1024**2)
    disk_reserve_bytes: int = _env_int("MAPPER_DISK_RESERVE_BYTES", 5 * 1024**3)
    max_archive_entries: int = _env_int("MAPPER_MAX_ARCHIVE_ENTRIES", 200_000)
    max_archive_uncompressed_bytes: int = _env_int(
        "MAPPER_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 2 * 1024**4
    )
    project_event_limit: int = _env_int("MAPPER_PROJECT_EVENT_LIMIT", 10_000)

    @property
    def database_path(self) -> Path:
        return self.data_root / "metadata" / "mapper.sqlite3"

    def ensure_directories(self) -> None:
        for name in ("source", "nodeodm", "splat", "metadata", "logs", "uploads"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)

    def validate_runtime(self) -> None:
        if not self.data_root.is_absolute() or self.data_root == Path("/"):
            raise RuntimeError("MAPPER_DATA_ROOT must be an absolute, dedicated directory")
        if not 1 <= self.session_hours <= 168:
            raise RuntimeError("MAPPER_SESSION_HOURS must be between 1 and 168")
        if not 1024 <= self.max_chunk_bytes <= 64 * 1024**2:
            raise RuntimeError("MAPPER_MAX_CHUNK_BYTES must be between 1 KiB and 64 MiB")
        if self.max_upload_bytes < self.max_chunk_bytes:
            raise RuntimeError("MAPPER_MAX_UPLOAD_BYTES must be at least one upload chunk")
        if self.disk_reserve_bytes < 1024**3:
            raise RuntimeError("MAPPER_DISK_RESERVE_BYTES must reserve at least 1 GiB")
        if not 100 <= self.max_archive_entries <= 1_000_000:
            raise RuntimeError("MAPPER_MAX_ARCHIVE_ENTRIES must be between 100 and 1000000")
        if self.max_archive_uncompressed_bytes < self.max_upload_bytes:
            raise RuntimeError(
                "MAPPER_MAX_ARCHIVE_UNCOMPRESSED_BYTES must be at least MAPPER_MAX_UPLOAD_BYTES"
            )
        if self.project_event_limit < 1_000:
            raise RuntimeError("MAPPER_PROJECT_EVENT_LIMIT must be at least 1000")
        if self.sharing_enabled:
            public_url = urlsplit(self.public_base_url)
            if (
                public_url.scheme != "https"
                or not public_url.hostname
                or public_url.username
                or public_url.password
                or public_url.query
                or public_url.fragment
                or public_url.path not in {"", "/"}
            ):
                raise RuntimeError(
                    "MAPPER_PUBLIC_BASE_URL must be an HTTPS origin without a path, query, or fragment"
                )
            if not self.demo_mode and not self.cookie_secure:
                raise RuntimeError(
                    "MAPPER_COOKIE_SECURE must remain true when public sharing is enabled"
                )
        if not self.demo_mode:
            for name, token in (
                ("NODEODM_TOKEN", self.nodeodm_token),
                ("MAPPER_INTERNAL_TOKEN", self.internal_token),
            ):
                if len(token) < 32 or token.startswith("replace-with-"):
                    raise RuntimeError(f"{name} must be replaced with a random 32+ character secret")
            if secrets.compare_digest(self.nodeodm_token, self.internal_token):
                raise RuntimeError("NODEODM_TOKEN and MAPPER_INTERNAL_TOKEN must be different")


settings = Settings()
if not settings.internal_token:
    # This remains process-local in development. Production compose requires an
    # explicit token so the API and worker agree across restarts.
    object.__setattr__(settings, "internal_token", secrets.token_urlsafe(32))
