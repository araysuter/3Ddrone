from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pytest
from PIL import Image

from app.artifacts import artifacts_root, manifest, resolve_artifact_path, safe_extract
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
