from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import math
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .artifacts import artifact_path_allowed, manifest, project_root, resolve_artifact_path, tile_path
from .config import settings
from .db import (
    all_rows,
    decode_project,
    emit_event,
    init_db,
    one,
    transaction,
    update_project,
    utcnow,
)
from .inspection import classify_file, inspect_files, validate_magic
from .jobs import notify_runner, runner_healthy, start_runner, stop_runner
from .nodeodm import NodeODMClient, NodeODMError
from .presets import OUTPUT_DEFAULTS, PRESETS, resolve_outputs, sanitize_advanced
from .security import (
    SESSION_COOKIE,
    check_login_throttle,
    create_admin,
    record_login,
    require_csrf,
    require_session,
    setup_complete,
    start_session,
    verify_admin,
)
from .system import metrics


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime()
    init_db()
    start_runner()
    yield
    await stop_runner()


app = FastAPI(
    title="Local Aerial Mapper",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Username must contain at least 3 non-space characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Username cannot contain control characters")
        return normalized


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    preset: str = "high"
    outputs: dict[str, bool] | None = None
    advanced: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Project name cannot be blank")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Project name cannot contain control characters")
        return normalized


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(ge=1, le=settings.max_upload_bytes)
    kind: str | None = None


class UploadComplete(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


_upload_locks_guard = threading.Lock()
_upload_locks: dict[str, threading.RLock] = {}
_upload_initialization_lock = threading.RLock()
_upload_completion_lock = threading.RLock()


def _upload_lock(upload_id: str) -> threading.RLock:
    with _upload_locks_guard:
        return _upload_locks.setdefault(upload_id, threading.RLock())


def _upload_part(upload_id: str) -> Path:
    return settings.data_root / "uploads" / f"{upload_id}.part"


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _reconcile_upload(upload: dict[str, Any]) -> dict[str, Any]:
    if upload["state"] != "uploading":
        return upload
    part = _upload_part(upload["id"])
    if not part.is_file():
        # Completion validates and renames the file before changing the
        # database row. Recover that narrow crash window instead of leaving a
        # fully written upload permanently stuck in the "uploading" state.
        destination = (
            settings.data_root
            / "source"
            / upload["project_id"]
            / upload["filename"]
        )
        if destination.is_file() and destination.stat().st_size == upload["size"]:
            digest = hashlib.sha256()
            with destination.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            actual = digest.hexdigest()
            with transaction() as db:
                db.execute(
                    """
                    UPDATE uploads
                    SET state='complete',sha256=?,offset=size,error=NULL
                    WHERE id=? AND state='uploading'
                    """,
                    (actual, upload["id"]),
                )
            return {
                **upload,
                "state": "complete",
                "sha256": actual,
                "offset": upload["size"],
                "error": None,
            }
        raise HTTPException(status_code=409, detail="Upload data is missing; initialize it again")
    actual_size = part.stat().st_size
    if actual_size > upload["size"]:
        with transaction() as db:
            db.execute(
                "UPDATE uploads SET state='rejected',error=? WHERE id=?",
                ("Stored upload exceeds its declared size", upload["id"]),
            )
        raise HTTPException(status_code=409, detail="Stored upload exceeds its declared size")
    if actual_size != upload["offset"]:
        with transaction() as db:
            db.execute("UPDATE uploads SET offset=? WHERE id=?", (actual_size, upload["id"]))
        upload = {**upload, "offset": actual_size}
    return upload


async def _read_upload_chunk(request: Request) -> bytes:
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > settings.max_chunk_bytes:
                raise HTTPException(status_code=413, detail="Upload chunk is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    chunk = bytearray()
    async for block in request.stream():
        chunk.extend(block)
        if len(chunk) > settings.max_chunk_bytes:
            raise HTTPException(status_code=413, detail="Upload chunk is too large")
    if not chunk:
        raise HTTPException(status_code=400, detail="Empty upload chunk")
    return bytes(chunk)


async def _remove_remote_project_state(project: dict[str, Any]) -> None:
    if settings.demo_mode:
        return
    task_uuid = project.get("nodeodm_uuid")
    if task_uuid:
        try:
            await NodeODMClient().remove(task_uuid)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise HTTPException(status_code=503, detail="NodeODM task cleanup failed") from exc
        except NodeODMError as exc:
            if "not found" not in str(exc).lower() and "does not exist" not in str(exc).lower():
                raise HTTPException(status_code=503, detail="NodeODM task cleanup failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="NodeODM is unavailable for task cleanup") from exc
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                f"{settings.splat_url}/projects/{project['id']}",
                headers={"X-Internal-Token": settings.internal_token},
            )
        if response.status_code != 404:
            response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Splat worker cleanup failed") from exc


def get_project(project_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project = decode_project(row)
    project["uploads"] = all_rows(
        "SELECT id,filename,size,offset,sha256,kind,state,error FROM uploads WHERE project_id=? ORDER BY created_at",
        (project_id,),
    )
    project["artifacts"] = manifest(project_id)
    return project


@app.get("/api/health")
def health() -> dict[str, Any]:
    if not settings.database_path.is_file():
        raise HTTPException(status_code=503, detail="Persistent data storage is unavailable")
    try:
        one("SELECT 1 AS ok")
        with tempfile.NamedTemporaryFile(dir=settings.data_root / "metadata"):
            pass
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Persistent data storage is unavailable") from exc
    if not runner_healthy():
        raise HTTPException(status_code=503, detail="Durable job runner is unavailable")
    return {"ok": True, "service": "mapper-api", "demo_mode": settings.demo_mode}


@app.get("/api/setup")
def setup_status() -> dict[str, bool]:
    return {"required": not setup_complete()}


@app.post("/api/setup")
def setup_admin(credentials: Credentials, response: Response) -> dict[str, str]:
    create_admin(credentials.username, credentials.password)
    csrf = start_session(response)
    return {"csrf_token": csrf}


@app.post("/api/login")
def login(credentials: Credentials, request: Request, response: Response) -> dict[str, str]:
    address = request.client.host if request.client else "unknown"
    check_login_throttle(address)
    valid = verify_admin(credentials.username, credentials.password)
    record_login(address, valid)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"csrf_token": start_session(response)}


@app.post("/api/logout")
def logout(
    response: Response,
    session: dict = Depends(require_csrf),
) -> dict[str, bool]:
    # Cookie deletion works even if parsing the raw Cookie header is skipped.
    response.delete_cookie(SESSION_COOKIE, path="/")
    with transaction() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (session["token_hash"],))
    return {"ok": True}


@app.get("/api/session")
def session(session: dict = Depends(require_session)) -> dict[str, Any]:
    return {"authenticated": True, "csrf_token": session["csrf_token"]}


@app.get("/api/presets")
def presets(_: dict = Depends(require_session)) -> dict[str, Any]:
    return {"presets": PRESETS, "outputs": OUTPUT_DEFAULTS}


@app.get("/api/system")
async def system_metrics(_: dict = Depends(require_session)) -> dict[str, Any]:
    result = metrics()
    if settings.demo_mode:
        return result
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            response = await client.get(
                f"{settings.splat_url}/metrics",
                headers={"X-Internal-Token": settings.internal_token},
            )
        response.raise_for_status()
        result["gpu"] = response.json()
    except Exception:
        pass
    return result


@app.get("/api/options")
async def allowed_options(_: dict = Depends(require_session)) -> dict[str, Any]:
    if settings.demo_mode:
        return {"options": []}
    try:
        metadata = await NodeODMClient().options()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="NodeODM option metadata is unavailable") from exc
    from .presets import ADVANCED_ALLOWLIST

    return {"options": [option for option in metadata if option.get("name") in ADVANCED_ALLOWLIST]}


@app.get("/api/projects")
def list_projects(_: dict = Depends(require_session)) -> list[dict[str, Any]]:
    return [
        decode_project(row)
        for row in all_rows("SELECT * FROM projects ORDER BY created_at DESC")
    ]


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    if payload.preset not in PRESETS:
        raise HTTPException(status_code=422, detail="Unknown preset")
    try:
        outputs = resolve_outputs(payload.outputs)
        advanced = sanitize_advanced(payload.advanced)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project_id = str(uuid.uuid4())
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            INSERT INTO projects(
              id,name,preset,status,stage,progress,outputs_json,advanced_json,
              inspection_json,created_at,updated_at
            ) VALUES(?,?,?,'uploading','Waiting for files',0,?,?,?, ?,?)
            """,
            (
                project_id,
                payload.name.strip(),
                payload.preset,
                json.dumps(outputs),
                json.dumps(advanced),
                "{}",
                now,
                now,
            ),
        )
    (settings.data_root / "source" / project_id).mkdir(parents=True, exist_ok=True)
    project_root(project_id).mkdir(parents=True, exist_ok=True)
    emit_event(project_id, "state", {"status": "uploading", "stage": "Waiting for files"})
    return get_project(project_id)


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str, _: dict = Depends(require_session)) -> dict[str, Any]:
    return get_project(project_id)


@app.post("/api/projects/{project_id}/uploads", status_code=201, response_model=None)
def initialize_upload(
    project_id: str, payload: UploadCreate, _: dict = Depends(require_csrf)
) -> Any:
    project = get_project(project_id)
    if project["status"] not in {"uploading", "failed", "canceled"}:
        raise HTTPException(
            status_code=409,
            detail="Files can only be added before processing or after a failed/canceled run",
        )
    filename = Path(payload.filename).name
    if (
        filename != payload.filename
        or filename in {".", ".."}
        or "\\" in filename
        or "\x00" in filename
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        or len(filename.encode("utf-8")) > 240
        or not filename.strip()
    ):
        raise HTTPException(status_code=422, detail="Invalid filename")
    try:
        kind = classify_file(filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    if payload.kind and payload.kind != kind:
        raise HTTPException(status_code=422, detail="File kind does not match extension")
    with _upload_initialization_lock:
        existing = one(
            "SELECT * FROM uploads WHERE project_id=? AND filename=?",
            (project_id, filename),
        )
        if existing and existing["state"] == "uploading":
            with _upload_lock(existing["id"]):
                existing = _reconcile_upload(existing)
            if existing["size"] != payload.size or existing["kind"] != kind:
                raise HTTPException(
                    status_code=409,
                    detail="An unfinished upload with this name has a different size or type",
                )
            return JSONResponse(
                status_code=200,
                content={
                    "id": existing["id"],
                    "offset": existing["offset"],
                    "size": existing["size"],
                    "kind": existing["kind"],
                },
            )
        if existing and existing["state"] == "complete":
            raise HTTPException(status_code=409, detail="A completed file with this name already exists")
        if existing:
            _upload_part(existing["id"]).unlink(missing_ok=True)
            with transaction() as db:
                db.execute("DELETE FROM uploads WHERE id=?", (existing["id"],))

        reserved = one(
            "SELECT COALESCE(SUM(size-offset),0) AS bytes FROM uploads WHERE state='uploading'"
        )
        free_bytes = shutil.disk_usage(settings.data_root).free
        available = max(
            0,
            free_bytes
            - settings.disk_reserve_bytes
            - int(reserved["bytes"] if reserved else 0),
        )
        if payload.size > available:
            raise HTTPException(
                status_code=507,
                detail="Not enough unreserved disk space for this upload",
            )

        upload_id = str(uuid.uuid4())
        part = _upload_part(upload_id)
        try:
            part.touch(exist_ok=False)
        except OSError as exc:
            if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
                raise HTTPException(status_code=507, detail="Upload storage is full") from exc
            raise HTTPException(status_code=500, detail="Upload storage could not be initialized") from exc
        try:
            with transaction() as db:
                db.execute(
                    """
                    INSERT INTO uploads(id,project_id,filename,size,kind,state,created_at)
                    VALUES(?,?,?,?,?,'uploading',?)
                    """,
                    (upload_id, project_id, filename, payload.size, kind, utcnow()),
                )
        except sqlite3.IntegrityError as exc:
            part.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="A file with this name already exists") from exc
        except Exception:
            part.unlink(missing_ok=True)
            raise
    return {"id": upload_id, "offset": 0, "size": payload.size, "kind": kind}


@app.head("/api/uploads/{upload_id}")
def upload_offset(upload_id: str, _: dict = Depends(require_session)) -> Response:
    upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    with _upload_lock(upload_id):
        upload = _reconcile_upload(upload)
    return Response(
        status_code=204,
        headers={
            "Upload-Offset": str(upload["offset"]),
            "Upload-Length": str(upload["size"]),
            "Upload-State": upload["state"],
        },
    )


@app.patch("/api/uploads/{upload_id}")
async def append_upload(
    upload_id: str,
    request: Request,
    upload_offset: int = Header(alias="Upload-Offset"),
    _: dict = Depends(require_csrf),
) -> Response:
    chunk = await _read_upload_chunk(request)
    with _upload_lock(upload_id):
        upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        if upload["state"] != "uploading":
            raise HTTPException(status_code=409, detail="Upload is not writable")
        upload = _reconcile_upload(upload)
        if upload_offset != upload["offset"]:
            raise HTTPException(
                status_code=409,
                detail="Upload offset mismatch",
                headers={"Upload-Offset": str(upload["offset"])},
            )
        new_offset = upload_offset + len(chunk)
        if new_offset > upload["size"]:
            raise HTTPException(status_code=413, detail="Chunk exceeds declared file size")
        if len(chunk) > max(
            0, shutil.disk_usage(settings.data_root).free - settings.disk_reserve_bytes
        ):
            raise HTTPException(status_code=507, detail="Upload would consume reserved disk space")
        part = _upload_part(upload_id)
        with part.open("r+b") as destination:
            destination.seek(upload_offset)
            destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        with transaction() as db:
            db.execute("UPDATE uploads SET offset=? WHERE id=?", (new_offset, upload_id))
    return Response(status_code=204, headers={"Upload-Offset": str(new_offset)})


@app.post("/api/uploads/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    payload: UploadComplete,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    with _upload_completion_lock, _upload_lock(upload_id):
        upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        if upload["state"] != "uploading":
            raise HTTPException(status_code=409, detail="Upload cannot be completed from its state")
        upload = _reconcile_upload(upload)
        if upload["offset"] != upload["size"]:
            raise HTTPException(status_code=409, detail="Upload is incomplete")
        part = _upload_part(upload_id)
        digest = hashlib.sha256()
        with part.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if not secrets.compare_digest(actual.lower(), payload.sha256.lower()):
            raise HTTPException(status_code=422, detail="Checksum mismatch")
        duplicate = one(
            "SELECT filename FROM uploads WHERE project_id=? AND sha256=? AND id<>? AND state='complete'",
            (upload["project_id"], actual, upload_id),
        )
        if duplicate:
            with transaction() as db:
                db.execute(
                    "UPDATE uploads SET state='rejected',error=?,offset=0 WHERE id=?",
                    (f"Duplicate of {duplicate['filename']}", upload_id),
                )
            part.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=f"Duplicate of {duplicate['filename']}")
        try:
            validate_magic(part, upload["kind"], upload["filename"])
        except ValueError as exc:
            with transaction() as db:
                db.execute(
                    "UPDATE uploads SET state='rejected',error=?,offset=0 WHERE id=?",
                    (str(exc), upload_id),
                )
            part.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        destination = settings.data_root / "source" / upload["project_id"] / upload["filename"]
        if destination.exists():
            raise HTTPException(status_code=409, detail="Source destination already exists")
        part.replace(destination)
        _fsync_directory(destination.parent)
        try:
            with transaction() as db:
                db.execute(
                    "UPDATE uploads SET state='complete',sha256=?,offset=size,error=NULL WHERE id=?",
                    (actual, upload_id),
                )
        except Exception:
            destination.replace(part)
            _fsync_directory(part.parent)
            raise
    emit_event(upload["project_id"], "upload", {"filename": upload["filename"], "state": "complete"})
    return {"id": upload_id, "sha256": actual, "state": "complete"}


@app.post("/api/projects/{project_id}/inspect")
def inspect_project(project_id: str, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    project = get_project(project_id)
    paths = [
        settings.data_root / "source" / project_id / upload["filename"]
        for upload in project["uploads"]
        if upload["state"] == "complete"
    ]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Validated source data is missing from disk: "
                + ", ".join(missing[:10])
                + ("…" if len(missing) > 10 else "")
            ),
        )
    inspection = inspect_files(paths)
    host = metrics()
    inspection["host_ram_gb"] = host["ram_total_gb"]
    inspection["logical_cores"] = host["logical_cores"]
    gcp_used = any(path.name.lower() == "gcp_list.txt" for path in paths)
    if gcp_used:
        inspection["accuracy"] = {
            "label": "GCP-assisted",
            "survey_grade": False,
            "detail": "GCPs were supplied. Accuracy still depends on control quality and residuals.",
        }
    update_project(project_id, inspection_json=json.dumps(inspection), gcp_used=int(gcp_used))
    emit_event(project_id, "inspection", inspection)
    return inspection


@app.post("/api/projects/{project_id}/start")
async def start_project(project_id: str, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    project = get_project(project_id)
    unfinished = [upload for upload in project["uploads"] if upload["state"] == "uploading"]
    if unfinished:
        raise HTTPException(
            status_code=409,
            detail=f"{len(unfinished)} upload(s) are still incomplete",
        )
    complete_inputs = [
        upload for upload in project["uploads"] if upload["state"] == "complete" and upload["kind"] in {"image", "video"}
    ]
    if not complete_inputs:
        raise HTTPException(status_code=409, detail="Upload at least one image or video")
    image_count = sum(1 for upload in complete_inputs if upload["kind"] == "image")
    video_count = sum(1 for upload in complete_inputs if upload["kind"] == "video")
    if not video_count and image_count < 3:
        raise HTTPException(
            status_code=409,
            detail="Upload at least three overlapping images (or one supported video)",
        )
    if project["status"] not in {"uploading", "failed", "canceled"}:
        raise HTTPException(status_code=409, detail="Project cannot be started from its current state")
    # Refresh immediately before every run so files added after a failed or
    # canceled attempt cannot leave stale camera/GCP/resource metadata behind.
    inspect_project(project_id, {})
    if project["status"] in {"failed", "canceled"}:
        await _remove_remote_project_state(project)
    update_project(
        project_id,
        status="queued",
        stage="Queued",
        progress=0,
        cancel_requested=0,
        error=None,
        nodeodm_uuid=None if project["status"] in {"failed", "canceled"} else project["nodeodm_uuid"],
        nodeodm_output_line=0,
        splat_job_id=None if project["status"] in {"failed", "canceled"} else project["splat_job_id"],
    )
    emit_event(project_id, "state", {"status": "queued", "stage": "Queued"})
    notify_runner()
    return get_project(project_id)


@app.post("/api/projects/{project_id}/cancel")
def cancel_project(project_id: str, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    project = get_project(project_id)
    if project["status"] not in {"queued", "processing", "splatting"}:
        raise HTTPException(status_code=409, detail="Project is not active")
    update_project(project_id, cancel_requested=1, stage="Canceling")
    emit_event(project_id, "state", {"status": project["status"], "stage": "Canceling"})
    return get_project(project_id)


@app.post("/api/projects/{project_id}/retry-splat")
def retry_splat(project_id: str, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    project = get_project(project_id)
    if project["status"] != "partial":
        raise HTTPException(status_code=409, detail="Only a partial project can retry the splat stage")
    update_project(
        project_id,
        status="splatting",
        stage="Gaussian splat retry",
        error=None,
        cancel_requested=0,
        splat_job_id=None,
    )
    notify_runner()
    return get_project(project_id)


@app.post("/api/projects/{project_id}/reprocess")
async def reprocess_project(
    project_id: str, payload: ProjectCreate, _: dict = Depends(require_csrf)
) -> dict[str, Any]:
    project = get_project(project_id)
    if project["status"] in {"queued", "processing", "splatting"}:
        raise HTTPException(status_code=409, detail="Cancel the active project first")
    if payload.preset not in PRESETS:
        raise HTTPException(status_code=422, detail="Unknown preset")
    complete_inputs = [
        upload
        for upload in project["uploads"]
        if upload["state"] == "complete" and upload["kind"] in {"image", "video"}
    ]
    if not complete_inputs:
        raise HTTPException(status_code=409, detail="No complete reconstruction inputs remain")
    try:
        outputs = resolve_outputs(payload.outputs)
        advanced = sanitize_advanced(payload.advanced)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    inspect_project(project_id, {})
    await _remove_remote_project_state(project)
    update_project(
        project_id,
        name=payload.name.strip(),
        preset=payload.preset,
        outputs_json=json.dumps(outputs),
        advanced_json=json.dumps(advanced),
        nodeodm_uuid=None,
        nodeodm_output_line=0,
        splat_job_id=None,
        status="queued",
        stage="Queued",
        progress=0,
        error=None,
        cancel_requested=0,
    )
    notify_runner()
    return get_project(project_id)


@app.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    confirm: str = Header(alias="X-Confirm-Project-Name"),
    _: dict = Depends(require_csrf),
) -> Response:
    project = get_project(project_id)
    if confirm != project["name"]:
        raise HTTPException(status_code=409, detail="Project name confirmation does not match")
    if project["status"] in {"queued", "processing", "splatting"}:
        raise HTTPException(status_code=409, detail="Cancel the active project before deleting it")
    await _remove_remote_project_state(project)
    upload_ids = [
        row["id"]
        for row in all_rows("SELECT id FROM uploads WHERE project_id=?", (project_id,))
    ]
    with transaction() as db:
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    for upload_id in upload_ids:
        _upload_part(upload_id).unlink(missing_ok=True)
    for path in (
        settings.data_root / "source" / project_id,
        project_root(project_id),
    ):
        if path.is_dir():
            shutil.rmtree(path)
    return Response(status_code=204)


@app.get("/api/projects/{project_id}/events")
async def project_events(
    project_id: str,
    request: Request,
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None),
    _: dict = Depends(require_session),
) -> StreamingResponse:
    get_project(project_id)
    cursor = max(last_event_id or 0, after or 0)

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            rows = all_rows(
                "SELECT * FROM project_events WHERE project_id=? AND id>? ORDER BY id LIMIT 100",
                (project_id, cursor),
            )
            if rows:
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {row['payload_json']}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{project_id}/artifacts")
def artifact_manifest(project_id: str, _: dict = Depends(require_session)) -> dict[str, Any]:
    get_project(project_id)
    return {"artifacts": manifest(project_id)}


@app.get("/api/projects/{project_id}/artifacts/{relative_path:path}")
def download_artifact(
    project_id: str,
    relative_path: str,
    download: bool = Query(default=False),
    _: dict = Depends(require_session),
) -> FileResponse:
    get_project(project_id)
    if not artifact_path_allowed(project_id, relative_path):
        raise HTTPException(status_code=404, detail="Artifact is not allowlisted")
    try:
        path = resolve_artifact_path(project_id, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, filename=path.name if download else None)


@app.get("/api/projects/{project_id}/tiles/{layer}/{z}/{x}/{y}.png")
def raster_tile(
    project_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    _: dict = Depends(require_session),
) -> FileResponse:
    get_project(project_id)
    if not 0 <= z <= 30 or x < 0 or y < 0:
        raise HTTPException(status_code=404, detail="Invalid tile coordinate")
    try:
        path = tile_path(project_id, layer, z, x, y)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png")


@app.get("/api/projects/{project_id}/raster-metadata")
def raster_metadata(
    project_id: str,
    layer: str,
    _: dict = Depends(require_session),
) -> dict[str, Any]:
    get_project(project_id)
    raster_paths = {
        "orthomosaic": project_root(project_id)
        / "artifacts"
        / "odm_orthophoto"
        / "odm_orthophoto.tif",
        "dsm": project_root(project_id) / "artifacts" / "odm_dem" / "dsm.tif",
        "dtm": project_root(project_id) / "artifacts" / "odm_dem" / "dtm.tif",
    }
    if layer not in raster_paths:
        raise HTTPException(status_code=422, detail="Unknown raster layer")
    raster_path = raster_paths[layer]
    if not raster_path.is_file():
        raise HTTPException(status_code=404, detail="Raster is not available")
    tile_roots = {
        "orthomosaic": [
            project_root(project_id) / "artifacts" / "orthophoto_tiles",
            project_root(project_id) / "artifacts" / "odm_orthophoto" / "tiles",
        ],
        "dsm": [project_root(project_id) / "artifacts" / "dsm_tiles"],
        "dtm": [project_root(project_id) / "artifacts" / "dtm_tiles"],
    }
    zooms = sorted(
        {
            int(path.name)
            for root in tile_roots[layer]
            if root.is_dir()
            for path in root.iterdir()
            if path.is_dir() and path.name.isdigit()
        }
    )
    try:
        import rasterio
        from rasterio.warp import transform_bounds

        with rasterio.open(raster_path) as dataset:
            if dataset.crs is None:
                raise HTTPException(status_code=422, detail="Raster has no coordinate system")
            bounds = dataset.bounds
            web_bounds = transform_bounds(
                dataset.crs,
                "EPSG:3857",
                bounds.left,
                bounds.bottom,
                bounds.right,
                bounds.top,
                densify_pts=21,
            )
            return {
                "layer": layer,
                "crs": dataset.crs.to_string(),
                "crs_proj4": dataset.crs.to_proj4(),
                "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
                "bounds_3857": list(web_bounds),
                "min_zoom": zooms[0] if zooms else 0,
                "max_zoom": zooms[-1] if zooms else 24,
                "tile_scheme": "tms",
                "units": str(dataset.crs.linear_units or "unknown"),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Raster metadata could not be read") from exc


@app.get("/api/projects/{project_id}/elevation")
def elevation_sample(
    project_id: str,
    layer: str,
    x: float,
    y: float,
    _: dict = Depends(require_session),
) -> dict[str, Any]:
    get_project(project_id)
    if layer not in {"dsm", "dtm"}:
        raise HTTPException(status_code=422, detail="Layer must be dsm or dtm")
    path = project_root(project_id) / "artifacts" / "odm_dem" / f"{layer}.tif"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Elevation raster not found")
    if not math.isfinite(x) or not math.isfinite(y):
        raise HTTPException(status_code=422, detail="Coordinates must be finite")
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            bounds = dataset.bounds
            if not bounds.left <= x <= bounds.right or not bounds.bottom <= y <= bounds.top:
                raise HTTPException(status_code=422, detail="Coordinate is outside the raster")
            sample = next(dataset.sample([(x, y)], indexes=1, masked=True))
            if getattr(sample, "mask", False) is True or bool(getattr(sample, "mask", [False])[0]):
                value = None
            else:
                value = float(sample[0])
            nodata = dataset.nodata
            if value is None or not math.isfinite(value) or (nodata is not None and value == nodata):
                return {"layer": layer, "x": x, "y": y, "elevation": None, "crs": str(dataset.crs)}
            return {"layer": layer, "x": x, "y": y, "elevation": value, "crs": str(dataset.crs)}
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Raster sampling support is unavailable") from exc


@app.get("/api/about")
def about(_: dict = Depends(require_session)) -> dict[str, Any]:
    return {
        "name": "Local Aerial Mapper",
        "license": "AGPL-3.0-only",
        "source": "https://github.com/araysuter/3Ddrone",
        "engines": {"ODM": "3.6.0", "NodeODM": "2.2.3"},
        "warranty": "This software is provided without warranty. Outputs are not survey certification.",
    }
