from __future__ import annotations

import hashlib
import io
import stat
import time
from pathlib import Path

import pytest
from PIL import Image

from app.artifacts import (
    artifact_path_allowed,
    artifacts_root,
    manifest,
    resolve_artifact_path,
    safe_extract,
)
from app.db import emit_event


def test_artifact_path_traversal_is_blocked(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        resolve_artifact_path("project-id", "../../etc/passwd")


def test_manifest_only_exposes_known_existing_products(tmp_path):
    root = artifacts_root("manifest-test")
    (root / "odm_orthophoto").mkdir(parents=True)
    (root / "odm_orthophoto" / "odm_orthophoto.tif").write_bytes(b"TIFF")
    (root / "secret.txt").write_text("not allowlisted")
    items = manifest("manifest-test")
    assert [item["label"] for item in items] == ["Orthomosaic COG"]


def test_safe_zip_rejects_parent_paths(tmp_path):
    import zipfile

    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe path"):
        safe_extract(archive, tmp_path / "out")


def test_safe_zip_rejects_symlinks(tmp_path):
    import zipfile

    archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(link, "../../etc/passwd")
    with pytest.raises(ValueError, match="Symlinks"):
        safe_extract(archive, tmp_path / "out")


def test_viewer_allowlist_rejects_normalized_traversal(tmp_path):
    root = artifacts_root("viewer-test")
    (root / "3d_tiles").mkdir(parents=True)
    (root / "secret.txt").write_text("hidden")
    assert artifact_path_allowed(
        "viewer-test", "artifacts/3d_tiles/pointcloud/tileset.json"
    )
    assert not artifact_path_allowed(
        "viewer-test", "artifacts/3d_tiles/../secret.txt"
    )
    assert not artifact_path_allowed(
        "viewer-test", r"artifacts\3d_tiles\secret.txt"
    )


def test_manifest_discovers_current_odm_3d_tiles_layout(tmp_path):
    root = artifacts_root("tiles-test")
    pointcloud = root / "3d_tiles" / "pointcloud" / "tileset.json"
    model = root / "3d_tiles" / "model" / "tileset.json"
    pointcloud.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    pointcloud.write_text("{}")
    model.write_text("{}")
    items = manifest("tiles-test")
    assert {(item["category"], item["viewer"]) for item in items} == {
        ("point_cloud", "tiles3d"),
        ("mesh", "tiles3d"),
    }


def test_manifest_uses_terrain_mesh_when_full_3d_mesh_is_unavailable(tmp_path):
    root = artifacts_root("terrain-mesh-test")
    terrain = root / "odm_texturing_25d" / "odm_textured_model_geo.glb"
    terrain.parent.mkdir(parents=True)
    terrain.write_bytes(b"glTF")

    items = manifest("terrain-mesh-test")

    assert len(items) == 1
    assert items[0]["label"] == "Textured terrain mesh GLB"
    assert items[0]["path"] == "artifacts/odm_texturing_25d/odm_textured_model_geo.glb"
    assert artifact_path_allowed("terrain-mesh-test", items[0]["path"])


def test_disabled_outputs_are_hidden_from_manifest_and_viewer_routes(tmp_path):
    project_id = "filtered-manifest-test"
    root = artifacts_root(project_id)
    orthomosaic = root / "odm_orthophoto" / "odm_orthophoto.tif"
    mesh_tiles = root / "3d_tiles" / "model" / "tileset.json"
    raw_log = root / "log.json"
    orthomosaic.parent.mkdir(parents=True)
    mesh_tiles.parent.mkdir(parents=True)
    orthomosaic.write_bytes(b"TIFF")
    mesh_tiles.write_text("{}")
    raw_log.write_text("{}")
    (root.parent / "all.zip").write_bytes(b"ZIP")
    outputs = {
        "orthomosaic": True,
        "point_cloud": False,
        "mesh": False,
        "dsm": False,
        "dtm": False,
        "report": False,
        "raw": False,
        "splat": False,
    }

    items = manifest(project_id, outputs)

    assert [(item["category"], item["label"]) for item in items] == [
        ("orthomosaic", "Orthomosaic COG"),
        ("archive", "Selected ODM outputs"),
    ]
    assert artifact_path_allowed(
        project_id,
        "artifacts/odm_orthophoto/odm_orthophoto.tif",
        outputs,
    )
    assert not artifact_path_allowed(
        project_id,
        "artifacts/3d_tiles/model/tileset.json",
        outputs,
    )
    assert not artifact_path_allowed(project_id, "artifacts/log.json", outputs)
    assert artifact_path_allowed(project_id, "all.zip", outputs)


def test_sse_events_are_durable_and_ordered(authenticated):
    client, csrf = authenticated
    response = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Events", "preset": "standard", "outputs": {"splat": False}},
    )
    project_id = response.json()["id"]
    first = emit_event(project_id, "progress", {"progress": 10})
    second = emit_event(project_id, "progress", {"progress": 20})
    assert second > first
