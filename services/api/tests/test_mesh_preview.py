from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path

from PIL import Image

from app.artifacts import artifacts_root, install_nodeodm_archive, manifest
from app.mesh_preview import (
    WEB_MESH_FILENAME,
    backfill_web_mesh_previews,
    build_web_mesh_preview,
    optimize_glb_textures,
)


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * ((-len(data)) % 4)


def _write_textured_glb(path: Path) -> None:
    image_output = io.BytesIO()
    Image.new("RGB", (128, 64), (20, 120, 220)).save(
        image_output,
        format="JPEG",
        quality=95,
    )
    geometry = b"\x01\x02\x03\x04"
    image = image_output.getvalue()
    binary = geometry + image
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(geometry)},
            {
                "buffer": 0,
                "byteOffset": len(geometry),
                "byteLength": len(image),
            },
        ],
        "images": [{"bufferView": 1, "mimeType": "image/jpeg"}],
    }
    json_blob = _pad(
        json.dumps(document, separators=(",", ":")).encode(),
        b" ",
    )
    binary_blob = _pad(binary, b"\0")
    total = 12 + 8 + len(json_blob) + 8 + len(binary_blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_blob), 0x4E4F534A)
        + json_blob
        + struct.pack("<II", len(binary_blob), 0x004E4942)
        + binary_blob
    )


def _read_glb(path: Path) -> tuple[dict, bytes]:
    blob = path.read_bytes()
    json_length = struct.unpack_from("<I", blob, 12)[0]
    document = json.loads(blob[20 : 20 + json_length])
    binary_header = 20 + json_length
    binary_length = struct.unpack_from("<I", blob, binary_header)[0]
    binary_start = binary_header + 8
    return document, blob[binary_start : binary_start + binary_length]


def test_optimizer_resizes_embedded_textures_and_preserves_geometry(tmp_path):
    source = tmp_path / "source.glb"
    destination = tmp_path / "preview.glb"
    _write_textured_glb(source)

    optimize_glb_textures(source, destination, max_texture_size=64)

    document, binary = _read_glb(destination)
    geometry_view, image_view = document["bufferViews"]
    geometry = binary[
        geometry_view["byteOffset"] :
        geometry_view["byteOffset"] + geometry_view["byteLength"]
    ]
    image_bytes = binary[
        image_view["byteOffset"] :
        image_view["byteOffset"] + image_view["byteLength"]
    ]
    assert geometry == b"\x01\x02\x03\x04"
    with Image.open(io.BytesIO(image_bytes)) as image:
        assert image.size == (64, 32)


def test_terrain_preview_is_generated_and_exposed_in_the_manifest(tmp_path):
    root = artifacts_root("mesh-preview-test")
    source = root / "odm_texturing_25d" / "odm_textured_model_geo.glb"
    _write_textured_glb(source)

    assert build_web_mesh_preview(root)
    assert not build_web_mesh_preview(root)

    preview = source.with_name(WEB_MESH_FILENAME)
    assert preview.is_file()
    item = next(
        artifact
        for artifact in manifest("mesh-preview-test")
        if "preview GLB" in artifact["label"]
    )
    assert item["label"] == "Textured terrain mesh preview GLB"
    assert item["path"] == (
        f"artifacts/odm_texturing_25d/{WEB_MESH_FILENAME}"
    )


def test_artifact_install_generates_a_preview_for_future_projects(tmp_path):
    source = tmp_path / "odm_textured_model_geo.glb"
    archive = tmp_path / "all.zip"
    _write_textured_glb(source)
    with zipfile.ZipFile(archive, "w") as output:
        output.write(
            source,
            "odm_texturing/odm_textured_model_geo.glb",
        )

    install_nodeodm_archive("mesh-install-test", archive)

    preview = (
        artifacts_root("mesh-install-test")
        / "odm_texturing"
        / WEB_MESH_FILENAME
    )
    assert preview.is_file()
    assert any(
        artifact["path"].endswith(WEB_MESH_FILENAME)
        for artifact in manifest("mesh-install-test")
    )


def test_backfill_isolates_a_malformed_legacy_model(tmp_path):
    projects = tmp_path / "projects"
    broken = (
        projects
        / "broken"
        / "artifacts"
        / "odm_texturing"
        / "odm_textured_model_geo.glb"
    )
    valid = (
        projects
        / "valid"
        / "artifacts"
        / "odm_texturing"
        / "odm_textured_model_geo.glb"
    )
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a GLB")
    _write_textured_glb(valid)

    assert backfill_web_mesh_previews(projects) == ["valid"]
    assert valid.with_name(WEB_MESH_FILENAME).is_file()
