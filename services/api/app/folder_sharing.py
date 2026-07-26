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
from .db import all_rows, one, transaction, utcnow
from .security import require_csrf, require_session
from .sharing import (
    PUBLIC_HEADERS,
    _hardlink_tree,
    _load_project,
    _public_snapshot,
    _raster_metadata,
    _set_no_store,
    _share_id,
    _sharing_required,
)

router = APIRouter()


def _folder_share_root(share_id: str) -> Path:
    return settings.data_root / "metadata" / "folder-shares" / share_id


def _folder_share_item_root(share_id: str, item_id: str) -> Path:
    return _folder_share_root(share_id) / "items" / item_id


def _folder_share_snapshot_root(item: dict[str, Any]) -> Path:
    version = item.get("snapshot_version")
    if not isinstance(version, str) or len(version) != 32:
        raise HTTPException(status_code=404, detail="Share unavailable")
    try:
        int(version, 16)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Share unavailable") from exc
    item_root = _folder_share_item_root(item["share_id"], item["id"])
    versions = (item_root / "versions").resolve()
    root = (versions / version).resolve()
    if versions not in root.parents or not root.is_dir():
        raise HTTPException(status_code=404, detail="Share unavailable")
    return root


def _load_folder(folder_id: str) -> dict[str, Any]:
    folder = one(
        "SELECT id,name,created_at,updated_at FROM map_folders WHERE id=?",
        (folder_id,),
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Project not found")
    return folder


def _folder_share_url(share: dict[str, Any]) -> str:
    return f"{settings.public_base_url}/share/projects/{share['id']}"


def _ensure_folder_share_item(
    share: dict[str, Any], project_id: str
) -> dict[str, Any]:
    item = one(
        "SELECT * FROM folder_share_items WHERE share_id=? AND project_id=?",
        (share["id"], project_id),
    )
    if item:
        return item
    item_id = str(uuid.uuid4())
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            INSERT OR IGNORE INTO folder_share_items(
              id,share_id,project_id,snapshot_json,created_at,updated_at
            ) VALUES(?,?,?,'{}',?,?)
            """,
            (item_id, share["id"], project_id, now, now),
        )
    item = one(
        "SELECT * FROM folder_share_items WHERE share_id=? AND project_id=?",
        (share["id"], project_id),
    )
    if not item:
        raise RuntimeError("Project share item could not be created")
    return item


def _record_item_error(item: dict[str, Any], reason: Exception | str) -> None:
    message = str(reason).strip() or "Published map could not be updated"
    with transaction() as db:
        db.execute(
            "UPDATE folder_share_items SET publish_error=?,updated_at=? WHERE id=?",
            (message[:1000], utcnow(), item["id"]),
        )


def _publish_folder_share_item(
    share: dict[str, Any], project: dict[str, Any]
) -> bool:
    item = _ensure_folder_share_item(share, project["id"])
    version = uuid.uuid4().hex
    versions = _folder_share_item_root(share["id"], item["id"]) / "versions"
    destination = versions / version
    source = project_root(project["id"])
    try:
        versions.mkdir(parents=True, exist_ok=True)
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
                UPDATE folder_share_items
                SET snapshot_version=?,snapshot_json=?,last_published_at=?,
                    publish_error=NULL,updated_at=?
                WHERE id=? AND share_id=?
                """,
                (
                    version,
                    json.dumps(snapshot),
                    now,
                    now,
                    item["id"],
                    share["id"],
                ),
            )
        for previous in versions.iterdir():
            if previous.name != version and previous.is_dir():
                shutil.rmtree(previous)
        return True
    except Exception as exc:
        if destination.exists():
            shutil.rmtree(destination)
        _record_item_error(item, exc)
        return False


def _remove_item(item: dict[str, Any]) -> None:
    root = _folder_share_item_root(item["share_id"], item["id"])
    if root.is_dir():
        shutil.rmtree(root)
    with transaction() as db:
        db.execute("DELETE FROM folder_share_items WHERE id=?", (item["id"],))


def reconcile_folder_share(
    folder_id: str, *, retry_failed: bool = False
) -> dict[str, Any] | None:
    share = one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        return None
    projects = all_rows(
        "SELECT id FROM projects WHERE folder_id=? ORDER BY created_at DESC,id",
        (folder_id,),
    )
    project_ids = {project["id"] for project in projects}
    for item in all_rows(
        "SELECT * FROM folder_share_items WHERE share_id=?", (share["id"],)
    ):
        if item["project_id"] not in project_ids:
            _remove_item(item)
    for row in projects:
        project = _load_project(row["id"])
        if project["status"] not in {"completed", "partial"}:
            continue
        item = one(
            "SELECT * FROM folder_share_items WHERE share_id=? AND project_id=?",
            (share["id"], project["id"]),
        )
        should_publish = not item or not item.get("snapshot_version")
        if (
            project["status"] == "completed"
            and retry_failed
            and item
            and item.get("publish_error")
        ):
            should_publish = True
        if should_publish:
            _publish_folder_share_item(share, project)
    return one("SELECT * FROM folder_shares WHERE id=?", (share["id"],))


def publish_folder_share_for_project(project_id: str) -> bool:
    project = _load_project(project_id)
    folder_id = project.get("folder_id")
    if not folder_id:
        return False
    share = one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        return False
    item = one(
        "SELECT * FROM folder_share_items WHERE share_id=? AND project_id=?",
        (share["id"], project_id),
    )
    if project["status"] == "completed":
        return _publish_folder_share_item(share, project)
    if project["status"] == "partial":
        if item and item.get("snapshot_version"):
            _record_item_error(
                item,
                "The replacement ended with partial results; the prior publication remains active.",
            )
            return False
        return _publish_folder_share_item(share, project)
    if project["status"] == "failed" and item and item.get("snapshot_version"):
        detail = str(project.get("error") or "").strip()
        message = (
            "The replacement failed; the prior publication remains active."
            + (f" {detail}" if detail else "")
        )
        _record_item_error(item, message)
    return False


def sync_folder_share_membership(
    project_id: str, old_folder_id: str | None, new_folder_id: str | None
) -> None:
    if old_folder_id and old_folder_id != new_folder_id:
        old_share = one(
            "SELECT * FROM folder_shares WHERE folder_id=?", (old_folder_id,)
        )
        if old_share:
            item = one(
                "SELECT * FROM folder_share_items WHERE share_id=? AND project_id=?",
                (old_share["id"], project_id),
            )
            if item:
                _remove_item(item)
    if new_folder_id:
        publish_folder_share_for_project(project_id)


def refresh_folder_share_map_name(project_id: str) -> None:
    project = _load_project(project_id)
    for item in all_rows(
        "SELECT * FROM folder_share_items WHERE project_id=?", (project_id,)
    ):
        if not item.get("snapshot_version"):
            continue
        try:
            snapshot = json.loads(item["snapshot_json"] or "{}")
        except json.JSONDecodeError:
            continue
        snapshot["name"] = project["name"]
        with transaction() as db:
            db.execute(
                "UPDATE folder_share_items SET snapshot_json=?,updated_at=? WHERE id=?",
                (json.dumps(snapshot), utcnow(), item["id"]),
            )


def remove_folder_share_items_for_project(project_id: str) -> None:
    for item in all_rows(
        "SELECT * FROM folder_share_items WHERE project_id=?", (project_id,)
    ):
        _remove_item(item)


def remove_folder_share(folder_id: str) -> None:
    share = one("SELECT id FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        return
    root = _folder_share_root(share["id"])
    if root.is_dir():
        shutil.rmtree(root)


def _folder_share_admin_payload(
    share: dict[str, Any] | None
) -> dict[str, Any]:
    if not settings.sharing_enabled:
        return {"configured": False, "share": None}
    if not share:
        return {"configured": True, "share": None}
    items = all_rows(
        """
        SELECT i.snapshot_version,i.last_published_at,i.publish_error,p.name
        FROM folder_share_items i
        JOIN projects p ON p.id=i.project_id
        WHERE i.share_id=?
        ORDER BY p.created_at DESC,p.id
        """,
        (share["id"],),
    )
    published = [item for item in items if item["snapshot_version"]]
    failed = [item for item in items if item["publish_error"]]
    last_published = max(
        (
            item["last_published_at"]
            for item in published
            if item["last_published_at"]
        ),
        default=None,
    )
    return {
        "configured": True,
        "share": {
            "enabled": bool(share["enabled"]),
            "url": _folder_share_url(share),
            "view_count": int(share["view_count"]),
            "last_viewed_at": share["last_viewed_at"],
            "last_published_at": last_published,
            "published_map_count": len(published),
            "failed_map_count": len(failed),
            "publication_issues": [
                {"map_name": item["name"], "message": item["publish_error"]}
                for item in failed
            ],
        },
    }


@router.get("/api/folders/{folder_id}/share")
def folder_share_status(
    folder_id: str,
    response: Response,
    _: dict = Depends(require_session),
) -> dict[str, Any]:
    _load_folder(folder_id)
    _set_no_store(response)
    return _folder_share_admin_payload(
        one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    )


@router.post("/api/folders/{folder_id}/share")
def enable_folder_share(
    folder_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_folder(folder_id)
    share = one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        share_id = str(uuid.uuid4())
        now = utcnow()
        with transaction() as db:
            db.execute(
                """
                INSERT INTO folder_shares(
                  id,folder_id,generation,enabled,view_count,created_at,updated_at
                ) VALUES(?,?,1,0,0,?,?)
                """,
                (share_id, folder_id, now, now),
            )
        share = one("SELECT * FROM folder_shares WHERE id=?", (share_id,))
    if not share:
        raise HTTPException(status_code=500, detail="Project share could not be created")
    reconcile_folder_share(folder_id, retry_failed=True)
    with transaction() as db:
        db.execute(
            "UPDATE folder_shares SET enabled=1,updated_at=? WHERE id=?",
            (utcnow(), share["id"]),
        )
    _set_no_store(response)
    return _folder_share_admin_payload(
        one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    )


@router.delete("/api/folders/{folder_id}/share")
def disable_folder_share(
    folder_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_folder(folder_id)
    share = one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        raise HTTPException(status_code=404, detail="Project share does not exist")
    with transaction() as db:
        db.execute(
            "UPDATE folder_shares SET enabled=0,updated_at=? WHERE id=?",
            (utcnow(), share["id"]),
        )
    _set_no_store(response)
    return _folder_share_admin_payload(
        one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    )


@router.post("/api/folders/{folder_id}/share/retry")
def retry_folder_share(
    folder_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_folder(folder_id)
    if not one("SELECT id FROM folder_shares WHERE folder_id=?", (folder_id,)):
        raise HTTPException(status_code=404, detail="Project share does not exist")
    reconcile_folder_share(folder_id, retry_failed=True)
    _set_no_store(response)
    return _folder_share_admin_payload(
        one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    )


@router.post("/api/folders/{folder_id}/share/regenerate")
def regenerate_folder_share(
    folder_id: str,
    response: Response,
    _: dict = Depends(require_csrf),
) -> dict[str, Any]:
    _sharing_required()
    _load_folder(folder_id)
    share = one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    if not share:
        raise HTTPException(status_code=404, detail="Project share does not exist")
    old_id = share["id"]
    old_root = _folder_share_root(old_id)
    while True:
        new_id = str(uuid.uuid4())
        new_root = _folder_share_root(new_id)
        if not new_root.exists() and not one(
            "SELECT id FROM folder_shares WHERE id=?", (new_id,)
        ):
            break
    moved = False
    try:
        with transaction() as db:
            db.execute(
                """
                UPDATE folder_shares
                SET id=?,generation=generation+1,view_count=0,
                    last_viewed_at=NULL,updated_at=?
                WHERE id=?
                """,
                (new_id, utcnow(), old_id),
            )
            if old_root.is_dir():
                old_root.rename(new_root)
                moved = True
    except Exception:
        if moved and new_root.is_dir() and not old_root.exists():
            new_root.rename(old_root)
        raise
    _set_no_store(response)
    return _folder_share_admin_payload(
        one("SELECT * FROM folder_shares WHERE folder_id=?", (folder_id,))
    )


def _public_folder_share(share_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _sharing_required()
    normalized = _share_id(share_id)
    share = one("SELECT * FROM folder_shares WHERE id=?", (normalized,))
    if not share or not share["enabled"]:
        raise HTTPException(status_code=404, detail="Share unavailable")
    folder = one("SELECT id,name FROM map_folders WHERE id=?", (share["folder_id"],))
    if not folder:
        raise HTTPException(status_code=404, detail="Share unavailable")
    return share, folder


def _public_folder_share_item(
    share_id: str, item_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    share, folder = _public_folder_share(share_id)
    normalized_item = _share_id(item_id)
    item = one(
        """
        SELECT * FROM folder_share_items
        WHERE id=? AND share_id=? AND snapshot_version IS NOT NULL
        """,
        (normalized_item, share["id"]),
    )
    if not item:
        raise HTTPException(status_code=404, detail="Share unavailable")
    _folder_share_snapshot_root(item)
    return share, folder, item


@router.get("/api/public/project-shares/{share_id}")
def public_folder_share(
    share_id: str,
    response: Response,
) -> dict[str, Any]:
    share, folder = _public_folder_share(share_id)
    maps: list[dict[str, Any]] = []
    items = all_rows(
        """
        SELECT i.*,p.created_at
        FROM folder_share_items i
        JOIN projects p ON p.id=i.project_id
        WHERE i.share_id=? AND i.snapshot_version IS NOT NULL
        ORDER BY p.created_at DESC,p.id
        """,
        (share["id"],),
    )
    for item in items:
        try:
            _folder_share_snapshot_root(item)
            snapshot = json.loads(item["snapshot_json"])
        except (HTTPException, json.JSONDecodeError):
            continue
        maps.append(
            {
                "id": item["id"],
                "name": snapshot["name"],
                "status": snapshot["status"],
            }
        )
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            UPDATE folder_shares
            SET view_count=view_count+1,last_viewed_at=?,updated_at=?
            WHERE id=? AND enabled=1 AND generation=?
            """,
            (now, now, share["id"], share["generation"]),
        )
    _set_no_store(response)
    return {"name": folder["name"], "maps": maps}


@router.get("/api/public/project-shares/{share_id}/maps/{item_id}")
def public_folder_share_map(
    share_id: str,
    item_id: str,
    response: Response,
) -> dict[str, Any]:
    _, folder, item = _public_folder_share_item(share_id, item_id)
    try:
        snapshot = json.loads(item["snapshot_json"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail="Share unavailable") from exc
    root = _folder_share_snapshot_root(item)
    snapshot["folder_name"] = folder["name"]
    snapshot["artifacts"] = manifest_for_root(root, snapshot["outputs"])
    _set_no_store(response)
    return snapshot


@router.get(
    "/api/public/project-shares/{share_id}/maps/{item_id}/artifacts/{relative_path:path}"
)
def public_folder_share_artifact(
    share_id: str,
    item_id: str,
    relative_path: str,
    download: bool = Query(default=False),
) -> FileResponse:
    _, _, item = _public_folder_share_item(share_id, item_id)
    snapshot = json.loads(item["snapshot_json"])
    root = _folder_share_snapshot_root(item)
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


@router.get(
    "/api/public/project-shares/{share_id}/maps/{item_id}/tiles/{layer}/{z}/{x}/{y}.png"
)
def public_folder_share_tile(
    share_id: str,
    item_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
) -> FileResponse:
    _, _, item = _public_folder_share_item(share_id, item_id)
    snapshot = json.loads(item["snapshot_json"])
    if snapshot["outputs"].get(layer, True) is False:
        raise HTTPException(status_code=404, detail="Output is unavailable")
    if not 0 <= z <= 30 or x < 0 or y < 0:
        raise HTTPException(status_code=404, detail="Invalid tile coordinate")
    try:
        path = tile_path_for_root(
            _folder_share_snapshot_root(item), layer, z, x, y
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Tile is unavailable") from exc
    return FileResponse(path, media_type="image/png", headers=PUBLIC_HEADERS)


@router.get(
    "/api/public/project-shares/{share_id}/maps/{item_id}/raster-metadata"
)
def public_folder_share_raster_metadata(
    share_id: str,
    item_id: str,
    layer: str,
    response: Response,
) -> dict[str, Any]:
    _, _, item = _public_folder_share_item(share_id, item_id)
    snapshot = json.loads(item["snapshot_json"])
    result = _raster_metadata(
        _folder_share_snapshot_root(item), layer, snapshot["outputs"]
    )
    _set_no_store(response)
    return result


@router.get("/api/public/project-shares/{share_id}/maps/{item_id}/elevation")
def public_folder_share_elevation(
    share_id: str,
    item_id: str,
    layer: str,
    x: float,
    y: float,
    response: Response,
) -> dict[str, Any]:
    _, _, item = _public_folder_share_item(share_id, item_id)
    snapshot = json.loads(item["snapshot_json"])
    if layer not in {"dsm", "dtm"}:
        raise HTTPException(status_code=422, detail="Layer must be dsm or dtm")
    if snapshot["outputs"].get(layer, True) is False:
        raise HTTPException(status_code=404, detail="Output is unavailable")
    path = (
        _folder_share_snapshot_root(item)
        / "artifacts"
        / "odm_dem"
        / f"{layer}.tif"
    )
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Elevation raster is unavailable")
    if not math.isfinite(x) or not math.isfinite(y):
        raise HTTPException(status_code=422, detail="Coordinates must be finite")
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            bounds = dataset.bounds
            if (
                not bounds.left <= x <= bounds.right
                or not bounds.bottom <= y <= bounds.top
            ):
                raise HTTPException(
                    status_code=422, detail="Coordinate is outside the raster"
                )
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
                elevation = None
            else:
                elevation = value
            result = {
                "layer": layer,
                "x": x,
                "y": y,
                "elevation": elevation,
                "crs": str(dataset.crs),
            }
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="Raster sampling support is unavailable"
        ) from exc
    _set_no_store(response)
    return result
