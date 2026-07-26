from __future__ import annotations

import json
import math
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse

from .artifacts import (
    artifact_path_allowed_for_root,
    manifest_for_root,
    project_root,
    resolve_artifact_path_for_root,
    tile_path_for_root,
)
from .config import settings
from .db import all_rows, decode_project, one, transaction, utcnow
from .security import require_csrf, require_session

router = APIRouter()

PUBLIC_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
}


def _sharing_required() -> None:
    if not settings.sharing_enabled:
        raise HTTPException(status_code=503, detail="Public sharing is not configured")


def _share_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Share unavailable") from exc


def _share_root(share_id: str) -> Path:
    return settings.data_root / "metadata" / "shares" / share_id


def _snapshot_root(share: dict[str, Any]) -> Path:
    version = share.get("snapshot_version")
    if not isinstance(version, str) or len(version) != 32:
        raise HTTPException(status_code=404, detail="Share unavailable")
    try:
        int(version, 16)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Share unavailable") from exc
    root = (_share_root(share["id"]) / "versions" / version).resolve()
    versions = (_share_root(share["id"]) / "versions").resolve()
    if versions not in root.parents or not root.is_dir():
        raise HTTPException(status_code=404, detail="Share unavailable")
    return root


def _share_url(share: dict[str, Any]) -> str:
    return f"{settings.public_base_url}/share/maps/{share['id']}"


def _set_no_store(response: Response) -> None:
    for name, value in PUBLIC_HEADERS.items():
        response.headers[name] = value


def _load_project(project_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Map not found")
    return decode_project(row)


def _folder_name(project: dict[str, Any]) -> str | None:
    folder_id = project.get("folder_id")
    if not folder_id:
        return None
    folder = one("SELECT name FROM map_folders WHERE id=?", (folder_id,))
    return folder["name"] if folder else None


def _public_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    inspection = project.get("inspection") or {}
    accuracy = inspection.get("accuracy")
    public_inspection: dict[str, Any] = {
        key: inspection[key]
        for key in ("images", "camera_model", "relative_altitude_median")
        if key in inspection
    }
    if isinstance(accuracy, dict):
        public_inspection["accuracy"] = {
            key: accuracy[key]
            for key in ("label", "survey_grade", "detail")
            if key in accuracy
        }
    return {
        "folder_name": _folder_name(project),
        "name": project["name"],
        "preset": project["preset"],
        "status": "partial" if project["status"] == "partial" else "completed",
        "outputs": project["outputs"],
        "inspection": public_inspection,
        "gcp_used": bool(project.get("gcp_used")),
    }


def _hardlink_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise RuntimeError("Published artifact directory is unavailable")
    destination.mkdir(parents=True, exist_ok=False)
    for item in source.rglob("*"):
        if item.is_symlink():
            raise RuntimeError("Published artifacts cannot contain symbolic links")
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(item, target)


def _publish_snapshot(share: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    share_id = share["id"]
    version = uuid.uuid4().hex
    versions = _share_root(share_id) / "versions"
    destination = versions / version
    source = project_root(project["id"])
    versions.mkdir(parents=True, exist_ok=True)
    try:
        destination.mkdir()
        _hardlink_tree(source / "artifacts", destination / "artifacts")
        archive = source / "all.zip"
        if archive.is_file():
            os.link(archive, destination / "all.zip")
        snapshot = _public_snapshot(project)
        now = utcnow()
        with transaction() as db:
            db.execute(
                """
                UPDATE project_shares
                SET snapshot_version=?,snapshot_json=?,last_published_at=?,
                    publish_error=NULL,updated_at=?
                WHERE id=?
                """,
                (version, json.dumps(snapshot), now, now, share_id),
            )
        for previous in versions.iterdir():
            if previous.name != version and previous.is_dir():
                shutil.rmtree(previous)
        published = one("SELECT * FROM project_shares WHERE id=?", (share_id,))
        if not published:
            raise RuntimeError("Published share record disappeared")
        return published
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise


def publish_existing_share(project_id: str) -> bool:
    share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    if not share:
        return False
    project = _load_project(project_id)
    if project["status"] != "completed":
        return False
    try:
        _publish_snapshot(share, project)
        return True
    except Exception as exc:
        with transaction() as db:
            db.execute(
                "UPDATE project_shares SET publish_error=?,updated_at=? WHERE id=?",
                (str(exc), utcnow(), share["id"]),
            )
        return False


def refresh_share_folder_labels(project_ids: list[str]) -> None:
    for project_id in project_ids:
        share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
        if not share or not share.get("snapshot_version"):
            continue
        try:
            snapshot = json.loads(share["snapshot_json"] or "{}")
            snapshot["folder_name"] = _folder_name(_load_project(project_id))
            with transaction() as db:
                db.execute(
                    "UPDATE project_shares SET snapshot_json=?,updated_at=? WHERE id=?",
                    (json.dumps(snapshot), utcnow(), share["id"]),
                )
        except (json.JSONDecodeError, HTTPException):
            continue


def refresh_share_map_names(project_ids: list[str]) -> None:
    for project_id in project_ids:
        share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
        if not share or not share.get("snapshot_version"):
            continue
        try:
            snapshot = json.loads(share["snapshot_json"] or "{}")
            snapshot["name"] = _load_project(project_id)["name"]
            with transaction() as db:
                db.execute(
                    "UPDATE project_shares SET snapshot_json=?,updated_at=? WHERE id=?",
                    (json.dumps(snapshot), utcnow(), share["id"]),
                )
        except (json.JSONDecodeError, HTTPException):
            continue


def remove_project_share(project_id: str) -> None:
    share = one("SELECT id FROM project_shares WHERE project_id=?", (project_id,))
    if share:
        root = _share_root(share["id"])
        if root.is_dir():
            shutil.rmtree(root)


def _admin_payload(share: dict[str, Any] | None) -> dict[str, Any]:
    if not settings.sharing_enabled:
        return {"configured": False, "share": None}
    if not share:
        return {"configured": True, "share": None}
    return {
        "configured": True,
        "share": {
            "enabled": bool(share["enabled"]),
            "url": _share_url(share),
            "view_count": int(share["view_count"]),
            "last_viewed_at": share["last_viewed_at"],
            "last_published_at": share["last_published_at"],
            "publish_error": share["publish_error"],
        },
    }


@router.get("/api/projects/{project_id}/share")
def share_status(
    project_id: str,
    response: Response,
    _: dict = Depends(require_session),
) -> dict[str, Any]:
    _load_project(project_id)
    _set_no_store(response)
    return _admin_payload(
        one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    )


@router.post("/api/projects/{project_id}/share")
def enable_share(
    project_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    project = _load_project(project_id)
    share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    created = False
    if not share:
        if project["status"] not in {"completed", "partial"}:
            raise HTTPException(
                status_code=409, detail="Only a completed or partial map can be shared"
            )
        share_id = str(uuid.uuid4())
        now = utcnow()
        with transaction() as db:
            db.execute(
                """
                INSERT INTO project_shares(
                  id,project_id,generation,enabled,snapshot_json,
                  view_count,created_at,updated_at
                ) VALUES(?,?,1,0,'{}',0,?,?)
                """,
                (share_id, project_id, now, now),
            )
        share = one("SELECT * FROM project_shares WHERE id=?", (share_id,))
        created = True
    if not share:
        raise HTTPException(status_code=500, detail="Share could not be created")
    try:
        if not share.get("snapshot_version"):
            if project["status"] not in {"completed", "partial"}:
                raise HTTPException(
                    status_code=409, detail="No completed result is available to publish"
                )
            share = _publish_snapshot(share, project)
        with transaction() as db:
            db.execute(
                "UPDATE project_shares SET enabled=1,publish_error=NULL,updated_at=? WHERE id=?",
                (utcnow(), share["id"]),
            )
    except Exception:
        if created:
            with transaction() as db:
                db.execute("DELETE FROM project_shares WHERE id=?", (share["id"],))
            root = _share_root(share["id"])
            if root.is_dir():
                shutil.rmtree(root)
        raise
    _set_no_store(response)
    return _admin_payload(
        one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    )


@router.delete("/api/projects/{project_id}/share")
def disable_share(
    project_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_project(project_id)
    share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    if not share:
        raise HTTPException(status_code=404, detail="Share link does not exist")
    with transaction() as db:
        db.execute(
            "UPDATE project_shares SET enabled=0,updated_at=? WHERE id=?",
            (utcnow(), share["id"]),
        )
    _set_no_store(response)
    return _admin_payload(
        one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    )


@router.post("/api/projects/{project_id}/share/regenerate")
def regenerate_share(
    project_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_project(project_id)
    share = one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    if not share or not share.get("snapshot_version"):
        raise HTTPException(status_code=404, detail="Share link does not exist")
    old_id = share["id"]
    old_root = _share_root(old_id)
    if not old_root.is_dir():
        raise HTTPException(status_code=409, detail="Published share files are unavailable")
    while True:
        new_id = str(uuid.uuid4())
        new_root = _share_root(new_id)
        if not new_root.exists() and not one(
            "SELECT id FROM project_shares WHERE id=?", (new_id,)
        ):
            break
    moved = False
    try:
        with transaction() as db:
            db.execute(
                """
                UPDATE project_shares
                SET id=?,generation=generation+1,view_count=0,last_viewed_at=NULL,updated_at=?
                WHERE id=?
                """,
                (new_id, utcnow(), old_id),
            )
            old_root.rename(new_root)
            moved = True
    except Exception:
        if moved and new_root.is_dir() and not old_root.exists():
            new_root.rename(old_root)
        raise
    _set_no_store(response)
    return _admin_payload(
        one("SELECT * FROM project_shares WHERE project_id=?", (project_id,))
    )


def _public_share(share_id: str) -> dict[str, Any]:
    _sharing_required()
    normalized = _share_id(share_id)
    share = one("SELECT * FROM project_shares WHERE id=?", (normalized,))
    if not share or not share["enabled"] or not share.get("snapshot_version"):
        raise HTTPException(status_code=404, detail="Share unavailable")
    return share


@router.get("/api/public/map-shares/{share_id}")
def public_share_detail(
    share_id: str,
    response: Response,
) -> dict[str, Any]:
    share = _public_share(share_id)
    try:
        snapshot = json.loads(share["snapshot_json"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail="Share unavailable") from exc
    root = _snapshot_root(share)
    snapshot["artifacts"] = manifest_for_root(root, snapshot["outputs"])
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            UPDATE project_shares
            SET view_count=view_count+1,last_viewed_at=?,updated_at=?
            WHERE id=? AND enabled=1 AND generation=?
            """,
            (now, now, share["id"], share["generation"]),
        )
    _set_no_store(response)
    return snapshot


@router.get("/api/public/map-shares/{share_id}/artifacts/{relative_path:path}")
def public_artifact(
    share_id: str,
    relative_path: str,
    download: bool = Query(default=False),
) -> FileResponse:
    share = _public_share(share_id)
    snapshot = json.loads(share["snapshot_json"])
    root = _snapshot_root(share)
    if not artifact_path_allowed_for_root(root, relative_path, snapshot["outputs"]):
        raise HTTPException(status_code=404, detail="Artifact is not available")
    try:
        path = resolve_artifact_path_for_root(root, relative_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Artifact is not available") from exc
    return FileResponse(
        path,
        filename=path.name if download else None,
        headers=PUBLIC_HEADERS,
    )


@router.get("/api/public/map-shares/{share_id}/tiles/{layer}/{z}/{x}/{y}.png")
def public_raster_tile(
    share_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
) -> FileResponse:
    share = _public_share(share_id)
    snapshot = json.loads(share["snapshot_json"])
    if snapshot["outputs"].get(layer, True) is False:
        raise HTTPException(status_code=404, detail="Output is unavailable")
    if not 0 <= z <= 30 or x < 0 or y < 0:
        raise HTTPException(status_code=404, detail="Invalid tile coordinate")
    try:
        path = tile_path_for_root(_snapshot_root(share), layer, z, x, y)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Tile is unavailable") from exc
    return FileResponse(path, media_type="image/png", headers=PUBLIC_HEADERS)


def _raster_metadata(root: Path, layer: str, outputs: dict[str, bool]) -> dict[str, Any]:
    raster_paths = {
        "orthomosaic": root
        / "artifacts"
        / "odm_orthophoto"
        / "odm_orthophoto.tif",
        "dsm": root / "artifacts" / "odm_dem" / "dsm.tif",
        "dtm": root / "artifacts" / "odm_dem" / "dtm.tif",
    }
    if layer not in raster_paths:
        raise HTTPException(status_code=422, detail="Unknown raster layer")
    if outputs.get(layer, True) is False:
        raise HTTPException(status_code=404, detail="Output is unavailable")
    raster_path = raster_paths[layer]
    if not raster_path.is_file():
        raise HTTPException(status_code=404, detail="Raster is unavailable")
    tile_roots = {
        "orthomosaic": [
            root / "artifacts" / "orthophoto_tiles",
            root / "artifacts" / "odm_orthophoto" / "tiles",
        ],
        "dsm": [root / "artifacts" / "dsm_tiles"],
        "dtm": [root / "artifacts" / "dtm_tiles"],
    }
    zooms = sorted(
        {
            int(path.name)
            for tile_root in tile_roots[layer]
            if tile_root.is_dir()
            for path in tile_root.iterdir()
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


@router.get("/api/public/map-shares/{share_id}/raster-metadata")
def public_raster_metadata(
    share_id: str,
    layer: str,
    response: Response,
) -> dict[str, Any]:
    share = _public_share(share_id)
    snapshot = json.loads(share["snapshot_json"])
    result = _raster_metadata(_snapshot_root(share), layer, snapshot["outputs"])
    _set_no_store(response)
    return result


@router.get("/api/public/map-shares/{share_id}/elevation")
def public_elevation(
    share_id: str,
    layer: str,
    x: float,
    y: float,
    response: Response,
) -> dict[str, Any]:
    share = _public_share(share_id)
    snapshot = json.loads(share["snapshot_json"])
    if layer not in {"dsm", "dtm"}:
        raise HTTPException(status_code=422, detail="Layer must be dsm or dtm")
    if snapshot["outputs"].get(layer, True) is False:
        raise HTTPException(status_code=404, detail="Output is unavailable")
    path = _snapshot_root(share) / "artifacts" / "odm_dem" / f"{layer}.tif"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Elevation raster is unavailable")
    if not math.isfinite(x) or not math.isfinite(y):
        raise HTTPException(status_code=422, detail="Coordinates must be finite")
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            bounds = dataset.bounds
            if not bounds.left <= x <= bounds.right or not bounds.bottom <= y <= bounds.top:
                raise HTTPException(status_code=422, detail="Coordinate is outside the raster")
            sample = next(dataset.sample([(x, y)], indexes=1, masked=True))
            if getattr(sample, "mask", False) is True or bool(
                getattr(sample, "mask", [False])[0]
            ):
                value = None
            else:
                value = float(sample[0])
            nodata = dataset.nodata
            if (
                value is None
                or not math.isfinite(value)
                or (nodata is not None and value == nodata)
            ):
                result = {
                    "layer": layer,
                    "x": x,
                    "y": y,
                    "elevation": None,
                    "crs": str(dataset.crs),
                }
            else:
                result = {
                    "layer": layer,
                    "x": x,
                    "y": y,
                    "elevation": value,
                    "crs": str(dataset.crs),
                }
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="Raster sampling support is unavailable"
        ) from exc
    _set_no_store(response)
    return result


@router.get("/api/public/about")
def public_about(response: Response) -> dict[str, Any]:
    _set_no_store(response)
    return {
        "name": "Local Aerial Mapper",
        "license": "AGPL-3.0-only",
        "source": "https://github.com/araysuter/3Ddrone",
        "engines": {"ODM": "3.6.0", "NodeODM": "2.2.3"},
        "warranty": "This software is provided without warranty. Outputs are not survey certification.",
    }
