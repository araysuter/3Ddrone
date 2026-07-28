from __future__ import annotations

import io
import json
import logging
import os
import struct
import uuid
from pathlib import Path

from PIL import Image

WEB_MESH_FILENAME = "odm_textured_model_geo.web-v2.glb"
WEB_MESH_MAX_TEXTURE_SIZE = 1024

_GLB_MAGIC = b"glTF"
_GLB_VERSION = 2
_JSON_CHUNK = 0x4E4F534A
_BINARY_CHUNK = 0x004E4942
LOGGER = logging.getLogger(__name__)


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * ((-len(data)) % 4)


def optimize_glb_textures(
    source: Path,
    destination: Path,
    *,
    max_texture_size: int = WEB_MESH_MAX_TEXTURE_SIZE,
) -> None:
    """Create an atomic, browser-sized GLB while preserving source geometry."""
    if max_texture_size < 64:
        raise ValueError("Web mesh textures must be at least 64 pixels")

    blob = source.read_bytes()
    if len(blob) < 28 or blob[:4] != _GLB_MAGIC:
        raise ValueError("Expected a GLB file")
    version, declared_length = struct.unpack_from("<II", blob, 4)
    if version != _GLB_VERSION or declared_length != len(blob):
        raise ValueError("Expected a complete GLB 2.0 file")

    json_length, json_kind = struct.unpack_from("<II", blob, 12)
    if json_kind != _JSON_CHUNK:
        raise ValueError("GLB JSON chunk is missing")
    json_start = 20
    json_end = json_start + json_length
    document = json.loads(blob[json_start:json_end])

    binary_header = json_end
    if binary_header + 8 > len(blob):
        raise ValueError("GLB binary chunk is missing")
    binary_length, binary_kind = struct.unpack_from("<II", blob, binary_header)
    if binary_kind != _BINARY_CHUNK:
        raise ValueError("GLB binary chunk is missing")
    binary_start = binary_header + 8
    binary = blob[binary_start : binary_start + binary_length]
    if len(binary) != binary_length:
        raise ValueError("GLB binary chunk is truncated")
    if len(document.get("buffers", [])) != 1:
        raise ValueError("Web mesh optimization requires one embedded GLB buffer")

    image_views = {
        image["bufferView"]: image["mimeType"]
        for image in document.get("images", [])
        if "bufferView" in image
    }
    views = document.get("bufferViews", [])
    output = bytearray()
    for index in sorted(
        range(len(views)),
        key=lambda item: views[item].get("byteOffset", 0),
    ):
        view = views[index]
        if view.get("buffer", 0) != 0:
            raise ValueError("Web mesh optimization requires embedded buffer views")
        start = int(view.get("byteOffset", 0))
        length = int(view["byteLength"])
        data = binary[start : start + length]
        if len(data) != length:
            raise ValueError("GLB buffer view is truncated")

        mime_type = image_views.get(index)
        if mime_type in {"image/jpeg", "image/png"}:
            with Image.open(io.BytesIO(data)) as image:
                if max(image.size) > max_texture_size:
                    image.thumbnail(
                        (max_texture_size, max_texture_size),
                        Image.Resampling.LANCZOS,
                    )
                    encoded = io.BytesIO()
                    if mime_type == "image/jpeg":
                        image.convert("RGB").save(
                            encoded,
                            format="JPEG",
                            quality=84,
                            optimize=True,
                        )
                    else:
                        image.save(encoded, format="PNG", optimize=True)
                    data = encoded.getvalue()

        while len(output) % 4:
            output.append(0)
        view["byteOffset"] = len(output)
        view["byteLength"] = len(data)
        output.extend(data)

    document["buffers"][0]["byteLength"] = len(output)
    json_blob = _pad(
        json.dumps(document, separators=(",", ":")).encode("utf-8"),
        b" ",
    )
    binary_blob = _pad(bytes(output), b"\0")
    total_length = 12 + 8 + len(json_blob) + 8 + len(binary_blob)
    optimized = (
        struct.pack("<4sII", _GLB_MAGIC, _GLB_VERSION, total_length)
        + struct.pack("<II", len(json_blob), _JSON_CHUNK)
        + json_blob
        + struct.pack("<II", len(binary_blob), _BINARY_CHUNK)
        + binary_blob
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_bytes(optimized)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_web_mesh_preview(artifacts: Path) -> bool:
    """Build or refresh the first available ODM web-mesh preview."""
    for directory in ("odm_texturing", "odm_texturing_25d"):
        source = artifacts / directory / "odm_textured_model_geo.glb"
        if not source.is_file():
            continue
        destination = source.with_name(WEB_MESH_FILENAME)
        if (
            destination.is_file()
            and destination.stat().st_size > 0
            and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns
        ):
            return False
        optimize_glb_textures(source, destination)
        return True
    return False


def backfill_web_mesh_previews(projects: Path) -> list[str]:
    """Create missing previews for existing project artifact directories."""
    updated: list[str] = []
    if not projects.is_dir():
        return updated
    for project in projects.iterdir():
        if not project.is_dir():
            continue
        try:
            if build_web_mesh_preview(project / "artifacts"):
                updated.append(project.name)
        except Exception:
            LOGGER.exception(
                "Could not build the browser-optimized mesh preview for %s",
                project.name,
            )
    return updated
