from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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
from .jobs import notify_runner, start_runner, stop_runner
from .nodeodm import NodeODMClient
from .presets import OUTPUT_DEFAULTS, PRESETS, resolve_outputs, sanitize_advanced
from .security import (
    SESSION_COOKIE,
    check_login_throttle,
    create_admin,
    end_session,
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
    init_db()
    start_runner()
    yield
    await stop_runner()


app = FastAPI(title="Local Aerial Mapper", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


class Credentials(BaseModel):
    username: str
    password: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    preset: str = "high"
    outputs: dict[str, bool] | None = None
    advanced: dict[str, Any] | None = None


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(ge=1)
    kind: str | None = None


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
    mapper_session: str | None = Header(default=None, alias="Cookie"),
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
def system_metrics(_: dict = Depends(require_session)) -> dict[str, Any]:
    return metrics()


@app.get("/api/options")
async def allowed_options(_: dict = Depends(require_session)) -> dict[str, Any]:
    try:
        metadata = await NodeODMClient().options()
    except Exception:
        metadata = []
    allowed = set(sanitize_advanced({}).keys())
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


@app.post("/api/projects/{project_id}/uploads", status_code=201)
def initialize_upload(
    project_id: str, payload: UploadCreate, _: dict = Depends(require_csrf)
) -> dict[str, Any]:
    get_project(project_id)
    filename = Path(payload.filename).name
    if filename != payload.filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="Invalid filename")
    try:
        kind = classify_file(filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    if payload.kind and payload.kind != kind:
        raise HTTPException(status_code=422, detail="File kind does not match extension")
    upload_id = str(uuid.uuid4())
    with transaction() as db:
        try:
            db.execute(
                """
                INSERT INTO uploads(id,project_id,filename,size,kind,state,created_at)
                VALUES(?,?,?,?,?,'uploading',?)
                """,
                (upload_id, project_id, filename, payload.size, kind, utcnow()),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="A file with this name already exists") from exc
    part = settings.data_root / "uploads" / f"{upload_id}.part"
    part.touch(exist_ok=False)
    return {"id": upload_id, "offset": 0, "size": payload.size, "kind": kind}


@app.head("/api/uploads/{upload_id}")
def upload_offset(upload_id: str, _: dict = Depends(require_session)) -> Response:
    upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
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
    upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    if upload["state"] != "uploading":
        raise HTTPException(status_code=409, detail="Upload is not writable")
    if upload_offset != upload["offset"]:
        raise HTTPException(
            status_code=409,
            detail="Upload offset mismatch",
            headers={"Upload-Offset": str(upload["offset"])},
        )
    chunk = await request.body()
    if not chunk:
        raise HTTPException(status_code=400, detail="Empty upload chunk")
    new_offset = upload_offset + len(chunk)
    if new_offset > upload["size"]:
        raise HTTPException(status_code=413, detail="Chunk exceeds declared file size")
    part = settings.data_root / "uploads" / f"{upload_id}.part"
    with part.open("ab") as destination:
        destination.write(chunk)
        destination.flush()
    with transaction() as db:
        db.execute("UPDATE uploads SET offset=? WHERE id=?", (new_offset, upload_id))
    return Response(status_code=204, headers={"Upload-Offset": str(new_offset)})


@app.post("/api/uploads/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    sha256: str = Body(embed=True, min_length=64, max_length=64),
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    upload = one("SELECT * FROM uploads WHERE id=?", (upload_id,))
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    if upload["offset"] != upload["size"]:
        raise HTTPException(status_code=409, detail="Upload is incomplete")
    part = settings.data_root / "uploads" / f"{upload_id}.part"
    digest = hashlib.sha256()
    with part.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual.lower() != sha256.lower():
        raise HTTPException(status_code=422, detail="Checksum mismatch")
    duplicate = one(
        "SELECT filename FROM uploads WHERE project_id=? AND sha256=? AND id<>? AND state='complete'",
        (upload["project_id"], actual, upload_id),
    )
    if duplicate:
        part.unlink(missing_ok=True)
        with transaction() as db:
            db.execute(
                "UPDATE uploads SET state='rejected',error=? WHERE id=?",
                (f"Duplicate of {duplicate['filename']}", upload_id),
            )
        raise HTTPException(status_code=409, detail=f"Duplicate of {duplicate['filename']}")
    try:
        validate_magic(part, upload["kind"], upload["filename"])
    except ValueError as exc:
        with transaction() as db:
            db.execute("UPDATE uploads SET state='rejected',error=? WHERE id=?", (str(exc), upload_id))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    destination = settings.data_root / "source" / upload["project_id"] / upload["filename"]
    part.replace(destination)
    with transaction() as db:
        db.execute(
            "UPDATE uploads SET state='complete',sha256=?,offset=size WHERE id=?",
            (actual, upload_id),
        )
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
    inspection = inspect_files(paths)
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
def start_project(project_id: str, _: dict = Depends(require_csrf)) -> dict[str, Any]:
    project = get_project(project_id)
    complete_inputs = [
        upload for upload in project["uploads"] if upload["state"] == "complete" and upload["kind"] in {"image", "video"}
    ]
    if not complete_inputs:
        raise HTTPException(status_code=409, detail="Upload at least one image or video")
    if project["status"] not in {"uploading", "failed", "canceled", "partial"}:
        raise HTTPException(status_code=409, detail="Project cannot be started from its current state")
    if not project["inspection"]:
        inspect_project(project_id, {})
    update_project(
        project_id,
        status="queued",
        stage="Queued",
        progress=0,
        cancel_requested=0,
        error=None,
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
    update_project(project_id, status="splatting", stage="Gaussian splat retry", error=None)
    notify_runner()
    return get_project(project_id)


@app.post("/api/projects/{project_id}/reprocess")
def reprocess_project(
    project_id: str, payload: ProjectCreate, _: dict = Depends(require_csrf)
) -> dict[str, Any]:
    project = get_project(project_id)
    if project["status"] in {"queued", "processing", "splatting"}:
        raise HTTPException(status_code=409, detail="Cancel the active project first")
    try:
        outputs = resolve_outputs(payload.outputs)
        advanced = sanitize_advanced(payload.advanced)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    update_project(
        project_id,
        name=payload.name.strip(),
        preset=payload.preset,
        outputs_json=json.dumps(outputs),
        advanced_json=json.dumps(advanced),
        nodeodm_uuid=None,
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
def delete_project(
    project_id: str,
    confirm: str = Header(alias="X-Confirm-Project-Name"),
    _: dict = Depends(require_csrf),
) -> Response:
    project = get_project(project_id)
    if confirm != project["name"]:
        raise HTTPException(status_code=409, detail="Project name confirmation does not match")
    if project["status"] in {"queued", "processing", "splatting"}:
        raise HTTPException(status_code=409, detail="Cancel the active project before deleting it")
    with transaction() as db:
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))
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
    try:
        path = tile_path(project_id, layer, z, x, y)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png")


@app.get("/api/projects/{project_id}/elevation")
def elevation_sample(
    project_id: str,
    layer: str,
    x: float,
    y: float,
    _: dict = Depends(require_session),
) -> dict[str, Any]:
    if layer not in {"dsm", "dtm"}:
        raise HTTPException(status_code=422, detail="Layer must be dsm or dtm")
    path = project_root(project_id) / "artifacts" / "odm_dem" / f"{layer}.tif"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Elevation raster not found")
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            row, col = dataset.index(x, y)
            value = float(dataset.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
            nodata = dataset.nodata
            if nodata is not None and value == nodata:
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
