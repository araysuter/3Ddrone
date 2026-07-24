from __future__ import annotations

import mimetypes
import stat
import shutil
import zipfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .config import settings

KNOWN_ARTIFACTS = [
    ("orthomosaic", "Orthomosaic COG", "odm_orthophoto/odm_orthophoto.tif", "map"),
    ("orthomosaic", "Orthomosaic preview", "odm_orthophoto/odm_orthophoto.png", "image"),
    ("point_cloud", "Point cloud LAZ", "odm_georeferencing/odm_georeferenced_model.laz", "download"),
    ("point_cloud", "Point cloud COPC", "odm_georeferencing/odm_georeferenced_model.copc.laz", "download"),
    ("point_cloud", "EPT point cloud", "entwine_pointcloud/ept.json", "pointcloud"),
    ("point_cloud", "Potree point cloud", "potree_pointcloud/index.html", "pointcloud"),
    ("mesh", "Textured mesh OBJ", "odm_texturing/odm_textured_model_geo.obj", "mesh"),
    ("mesh", "Textured mesh GLB", "odm_texturing/odm_textured_model_geo.glb", "mesh"),
    ("point_cloud", "OGC 3D Tiles point cloud", "3d_tiles/pointcloud/tileset.json", "tiles3d"),
    ("mesh", "OGC 3D Tiles textured model", "3d_tiles/model/tileset.json", "tiles3d"),
    ("dsm", "Digital surface model", "odm_dem/dsm.tif", "map"),
    ("dtm", "Digital terrain model", "odm_dem/dtm.tif", "map"),
    ("report", "Quality report", "odm_report/report.pdf", "report"),
    ("raw", "ODM log", "log.json", "json"),
    ("raw", "Camera reconstruction", "opensfm/reconstruction.json", "json"),
    ("splat", "Gaussian splat PLY", "splat/point_cloud.ply", "splat"),
    ("splat", "Gaussian splat SPZ", "splat/scene.spz", "splat"),
    ("splat", "Scene transform", "splat/scene_transform.json", "json"),
]


def project_root(project_id: str) -> Path:
    return settings.data_root / "metadata" / "projects" / project_id


def artifacts_root(project_id: str) -> Path:
    return project_root(project_id) / "artifacts"


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > settings.max_archive_entries:
            raise ValueError(
                f"NodeODM archive has too many entries ({len(members):,} > "
                f"{settings.max_archive_entries:,})"
            )
        uncompressed_size = sum(member.file_size for member in members)
        if uncompressed_size > settings.max_archive_uncompressed_bytes:
            raise ValueError("NodeODM archive exceeds the configured uncompressed size limit")

        targets: set[Path] = set()
        for member in members:
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"Symlinks are not allowed in NodeODM archives: {member.filename}")
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"Unsafe path in NodeODM archive: {member.filename}")
            if target in targets and not member.is_dir():
                raise ValueError(f"Duplicate path in NodeODM archive: {member.filename}")
            targets.add(target)

        free_bytes = shutil.disk_usage(destination).free
        if uncompressed_size > max(0, free_bytes - settings.disk_reserve_bytes):
            raise ValueError("Not enough free disk space to extract NodeODM outputs safely")

        for member in members:
            target = (destination / member.filename).resolve()
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def install_nodeodm_archive(project_id: str, archive: Path) -> None:
    root = project_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    destination = artifacts_root(project_id)
    staging = root / f".artifacts-{uuid.uuid4().hex}.tmp"
    previous = root / f".artifacts-{uuid.uuid4().hex}.old"
    archive_staging = root / ".all.zip.tmp"
    try:
        safe_extract(archive, staging)
        shutil.copy2(archive, archive_staging)
        if destination.exists():
            destination.replace(previous)
        staging.replace(destination)
        archive_staging.replace(root / "all.zip")
    except Exception:
        if previous.exists():
            if destination.exists():
                shutil.rmtree(destination)
            previous.replace(destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if previous.exists():
            shutil.rmtree(previous)
        archive_staging.unlink(missing_ok=True)


def resolve_artifact_path(project_id: str, relative_path: str) -> Path:
    root = project_root(project_id).resolve()
    target = (root / relative_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Artifact path escapes project directory")
    if not target.is_file():
        raise FileNotFoundError(relative_path)
    return target


def artifact_path_allowed(project_id: str, relative_path: str) -> bool:
    normalized = relative_path.strip("/")
    logical_path = PurePosixPath(normalized)
    if (
        not normalized
        or logical_path.is_absolute()
        or any(part in {"", ".", ".."} for part in logical_path.parts)
        or "\\" in normalized
    ):
        return False
    exact = {item["path"] for item in manifest(project_id)}
    if normalized in exact:
        return True
    viewer_prefixes = (
        "artifacts/potree_pointcloud/",
        "artifacts/entwine_pointcloud/",
        "artifacts/3d_tiles/",
        "artifacts/odm_texturing/",
    )
    return normalized.startswith(viewer_prefixes)


def manifest(project_id: str) -> list[dict[str, Any]]:
    root = artifacts_root(project_id)
    results: list[dict[str, Any]] = []
    for category, label, relative, viewer in KNOWN_ARTIFACTS:
        path = root / relative
        if path.is_file():
            results.append(
                {
                    "id": relative.replace("/", ":"),
                    "category": category,
                    "label": label,
                    "path": f"artifacts/{relative}",
                    "viewer": viewer,
                    "size": path.stat().st_size,
                    "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                }
            )
    all_zip = project_root(project_id) / "all.zip"
    if all_zip.is_file():
        results.append(
            {
                "id": "all.zip",
                "category": "raw",
                "label": "All ODM outputs",
                "path": "all.zip",
                "viewer": "download",
                "size": all_zip.stat().st_size,
                "content_type": "application/zip",
            }
        )
    return results


def tile_path(project_id: str, layer: str, z: int, x: int, y: int) -> Path:
    candidates = {
        "orthomosaic": [f"orthophoto_tiles/{z}/{x}/{y}.png", f"odm_orthophoto/tiles/{z}/{x}/{y}.png"],
        "dsm": [f"dsm_tiles/{z}/{x}/{y}.png"],
        "dtm": [f"dtm_tiles/{z}/{x}/{y}.png"],
    }
    if layer not in candidates:
        raise ValueError("Unknown raster layer")
    for relative in candidates[layer]:
        candidate = artifacts_root(project_id) / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Tile is not available")


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
