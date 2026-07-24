from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".dng", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".lrv", ".ts"}
PROVENANCE_EXTENSIONS = {".lchm"}
SUPPORT_NAMES = {"geo.txt", "gcp_list.txt", "image_groups.txt", "align.las", "align.laz", "align.tif"}


def classify_file(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in PROVENANCE_EXTENSIONS:
        return "provenance"
    if Path(filename).name.lower() in SUPPORT_NAMES or suffix == ".srt":
        return "support"
    raise ValueError(f"Unsupported file type: {suffix or 'none'}")


def validate_magic(path: Path, kind: str, filename: str | None = None) -> None:
    with path.open("rb") as source:
        header = source.read(512)
    suffix = Path(filename or path.name).suffix.lower()
    if kind == "image":
        is_jpeg = header[:3] == b"\xff\xd8\xff"
        is_tiff = header[:4] in {b"II*\x00", b"MM\x00*"}
        if not (is_jpeg or is_tiff):
            raise ValueError("Image signature is invalid")
        if suffix == ".dng":
            try:
                metadata = _exiftool(path)
                if metadata and str(_first(metadata, "FileType") or "").upper() not in {"DNG", "TIFF"}:
                    raise ValueError("DNG metadata is invalid")
            except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
                raise ValueError("DNG is corrupt or unreadable") from exc
            return
        try:
            with Image.open(path) as image:
                if image.width <= 0 or image.height <= 0 or image.width * image.height > 500_000_000:
                    raise ValueError("Image dimensions are invalid or unreasonably large")
                image.verify()
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Image is corrupt or unreadable") from exc
    elif kind == "video":
        iso_media = b"ftyp" in header[:64]
        transport_stream = (
            suffix == ".ts"
            and len(header) > 188
            and header[0] == 0x47
            and header[188] == 0x47
        )
        if not (iso_media or transport_stream):
            raise ValueError("Video signature is invalid")
    if kind == "video" and shutil.which("ffprobe"):
        try:
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", str(path)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.SubprocessError as exc:
            raise ValueError("Video is corrupt or unreadable") from exc
    elif kind == "support":
        name = Path(filename or path.name).name.lower()
        if name in {"align.las", "align.laz"} and header[:4] != b"LASF":
            raise ValueError("LAS/LAZ alignment signature is invalid")
        if name == "align.tif" and header[:4] not in {b"II*\x00", b"MM\x00*"}:
            raise ValueError("TIFF alignment signature is invalid")
        if suffix in {".txt", ".srt"} and b"\x00" in header:
            raise ValueError("Text support file contains binary data")


def _exiftool(path: Path) -> dict[str, Any]:
    executable = shutil.which("exiftool")
    if not executable:
        return {}
    result = subprocess.run(
        [executable, "-j", "-n", "-G", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("ExifTool returned invalid metadata")
    return payload[0]


def _first(meta: dict[str, Any], *keys: str) -> Any:
    for suffix in keys:
        for key, value in meta.items():
            # ExifTool's `-G` JSON output uses `GROUP:Tag` keys in current
            # releases, while older fixtures and some wrappers use
            # `[GROUP]Tag`. Accept both without using a loose suffix match
            # that could confuse similarly named tags.
            tag = key.rsplit(":", 1)[-1].rsplit("]", 1)[-1]
            if tag == suffix:
                return value
    return None


def inspect_files(files: list[Path]) -> dict[str, Any]:
    images = [path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]
    videos = [path for path in files if path.suffix.lower() in VIDEO_EXTENSIONS]
    provenance = [path for path in files if path.suffix.lower() in PROVENANCE_EXTENSIONS]
    geotagged = 0
    models: list[str] = []
    altitudes: list[float] = []
    pitches: list[float] = []
    megapixels: list[float] = []
    metadata_errors: list[str] = []
    for path in images:
        try:
            meta = _exiftool(path)
            lat = _first(meta, "GPSLatitude")
            lon = _first(meta, "GPSLongitude")
            if lat is not None and lon is not None:
                geotagged += 1
            model = _first(meta, "Model")
            if model:
                models.append(str(model))
            relative_altitude = _first(meta, "RelativeAltitude")
            if relative_altitude is not None:
                altitudes.append(float(relative_altitude))
            gimbal_pitch = _first(meta, "GimbalPitchDegree")
            if gimbal_pitch is not None:
                pitches.append(float(gimbal_pitch))
            width = _first(meta, "ImageWidth", "ExifImageWidth")
            height = _first(meta, "ImageHeight", "ExifImageHeight")
            if width and height:
                megapixels.append(float(width) * float(height) / 1_000_000)
        except Exception as exc:
            metadata_errors.append(f"{path.name}: {exc}")
    camera_model = Counter(models).most_common(1)[0][0] if models else ""
    nadir = sum(1 for pitch in pitches if pitch <= -85)
    oblique = len(pitches) - nadir
    accuracy = {
        "label": "Best effort — consumer GPS",
        "survey_grade": False,
        "detail": "Absolute accuracy is not certified. Add surveyed GCPs for defensible measurements.",
    }
    return {
        "images": len(images),
        "videos": len(videos),
        "provenance_files": len(provenance),
        "geotagged": geotagged,
        "camera_model": camera_model,
        "relative_altitude_median": round(median(altitudes), 2) if altitudes else None,
        "relative_altitude_range": [round(min(altitudes), 2), round(max(altitudes), 2)] if altitudes else None,
        "nadir": nadir,
        "oblique": oblique,
        "megapixels": round(median(megapixels), 2) if megapixels else None,
        "rolling_shutter_ms": 33 if camera_model.upper() == "FC330" else None,
        "accuracy": accuracy,
        "metadata_errors": metadata_errors,
    }
