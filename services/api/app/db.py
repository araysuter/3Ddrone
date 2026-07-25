from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

_write_lock = threading.RLock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(settings.database_path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with _write_lock:
        db = connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def init_db() -> None:
    settings.ensure_directories()
    with transaction() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              csrf_token TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
              address TEXT PRIMARY KEY,
              failures INTEGER NOT NULL DEFAULT 0,
              blocked_until TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS map_folders (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL COLLATE NOCASE UNIQUE,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY,
              folder_id TEXT REFERENCES map_folders(id) ON DELETE SET NULL,
              name TEXT NOT NULL,
              preset TEXT NOT NULL,
              status TEXT NOT NULL,
              stage TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0,
              outputs_json TEXT NOT NULL,
              advanced_json TEXT NOT NULL,
              inspection_json TEXT NOT NULL DEFAULT '{}',
              nodeodm_uuid TEXT,
              nodeodm_output_line INTEGER NOT NULL DEFAULT 0,
              splat_job_id TEXT,
              error TEXT,
              gcp_used INTEGER NOT NULL DEFAULT 0,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS uploads (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              filename TEXT NOT NULL,
              size INTEGER NOT NULL,
              offset INTEGER NOT NULL DEFAULT 0,
              sha256 TEXT,
              kind TEXT NOT NULL,
              state TEXT NOT NULL,
              error TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(project_id, filename)
            );
            CREATE TABLE IF NOT EXISTS project_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_project
              ON project_events(project_id, id);
            CREATE TABLE IF NOT EXISTS project_shares (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
              generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
              enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
              snapshot_version TEXT,
              snapshot_json TEXT NOT NULL DEFAULT '{}',
              view_count INTEGER NOT NULL DEFAULT 0 CHECK (view_count >= 0),
              last_viewed_at TEXT,
              last_published_at TEXT,
              publish_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_shares_project
              ON project_shares(project_id);
            """
        )
        project_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "nodeodm_output_line" not in project_columns:
            db.execute(
                "ALTER TABLE projects ADD COLUMN nodeodm_output_line INTEGER NOT NULL DEFAULT 0"
            )
        if "folder_id" not in project_columns:
            db.execute(
                """
                ALTER TABLE projects
                ADD COLUMN folder_id TEXT REFERENCES map_folders(id) ON DELETE SET NULL
                """
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_folder_id ON projects(folder_id)"
        )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (utcnow(),))


def one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def all_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def emit_event(project_id: str, event_type: str, payload: dict[str, Any]) -> int:
    with transaction() as db:
        cursor = db.execute(
            "INSERT INTO project_events(project_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
            (project_id, event_type, json.dumps(payload), utcnow()),
        )
        event_id = int(cursor.lastrowid)
        if event_id % 250 == 0:
            db.execute(
                """
                DELETE FROM project_events
                WHERE project_id=? AND id NOT IN (
                  SELECT id FROM project_events
                  WHERE project_id=?
                  ORDER BY id DESC LIMIT ?
                )
                """,
                (project_id, project_id, settings.project_event_limit),
            )
        return event_id


def update_project(project_id: str, **values: Any) -> None:
    if not values:
        return
    values["updated_at"] = utcnow()
    columns = ", ".join(f"{key}=?" for key in values)
    with transaction() as db:
        db.execute(
            f"UPDATE projects SET {columns} WHERE id=?",
            (*values.values(), project_id),
        )


def decode_project(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for db_key, public_key in (
        ("outputs_json", "outputs"),
        ("advanced_json", "advanced"),
        ("inspection_json", "inspection"),
    ):
        result[public_key] = json.loads(result.pop(db_key) or "{}")
    result["gcp_used"] = bool(result["gcp_used"])
    result["cancel_requested"] = bool(result["cancel_requested"])
    return result
