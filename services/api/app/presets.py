from __future__ import annotations

import os
from typing import Any

OUTPUT_DEFAULTS = {
    "orthomosaic": True,
    "point_cloud": True,
    "mesh": True,
    "dsm": True,
    "dtm": True,
    "report": True,
    "raw": True,
    "splat": True,
}

PRESETS: dict[str, dict[str, Any]] = {
    "standard": {
        "label": "Standard",
        "description": "Fast full reconstruction for coverage and routine mapping.",
        "odm": {
            "feature-quality": "high",
            "pc-quality": "medium",
            "orthophoto-resolution": 5,
            "dem-resolution": 5,
            "mesh-size": 200000,
        },
        "splat": {"downscale": 2, "steps": 15000, "quality_culling": False},
    },
    "high": {
        "label": "High",
        "description": "Recommended balance for the RTX 3060 Ti.",
        "odm": {
            "feature-quality": "ultra",
            "pc-quality": "high",
            "orthophoto-resolution": 2.5,
            "dem-resolution": 2.5,
            "mesh-size": 500000,
        },
        "splat": {"downscale": 1, "steps": 30000, "quality_culling": False},
    },
    "ultra": {
        "label": "Ultra",
        "description": "Maximum source-supported detail; substantially slower.",
        "odm": {
            "feature-quality": "ultra",
            "pc-quality": "ultra",
            "orthophoto-resolution": 1,
            "dem-resolution": 1,
            "mesh-size": 1000000,
        },
        "splat": {"downscale": 1, "steps": 45000, "quality_culling": True},
    },
}

ADVANCED_ALLOWLIST = {
    "auto-boundary",
    "auto-boundary-distance",
    "camera-lens",
    "crop",
    "dem-decimation",
    "dem-gapfill-steps",
    "matcher-neighbors",
    "matcher-order",
    "max-concurrency",
    "mesh-octree-depth",
    "min-num-features",
    "orthophoto-compression",
    "pc-filter",
    "sfm-algorithm",
    "sky-removal",
}

BLOCKED_OPTIONS = {
    "copy-to",
    "end-with",
    "force-gps",
    "ignore-gsd",
    "no-gpu",
    "project-path",
    "rerun",
    "rerun-all",
    "rerun-from",
    "sm-cluster",
    "split",
    "split-overlap",
}

ADVANCED_RULES: dict[str, tuple[str, Any]] = {
    "auto-boundary": ("bool", None),
    "auto-boundary-distance": ("number", (0, 10_000)),
    "camera-lens": (
        "choice",
        {"auto", "perspective", "brown", "fisheye", "fisheye_opencv", "spherical", "equirectangular", "dual"},
    ),
    "crop": ("number", (0, 1_000)),
    "dem-decimation": ("int", (1, 100)),
    "dem-gapfill-steps": ("int", (0, 50)),
    "matcher-neighbors": ("int", (0, 10_000)),
    "matcher-order": ("int", (0, 10_000)),
    "max-concurrency": ("int", (1, max(1, os.cpu_count() or 1))),
    "mesh-octree-depth": ("int", (1, 14)),
    "min-num-features": ("int", (1_000, 200_000)),
    "orthophoto-compression": (
        "choice",
        {"JPEG", "LZW", "PACKBITS", "DEFLATE", "LZMA", "NONE"},
    ),
    "pc-filter": ("number", (0, 50)),
    "sfm-algorithm": ("choice", {"incremental", "triangulation", "planar"}),
    "sky-removal": ("bool", None),
}


def calculate_concurrency(image_megapixels: float = 9, total_ram_gb: float = 48) -> int:
    usable_gb = max(2.0, total_ram_gb - 10.0)
    per_thread_gb = max(1.0, image_megapixels / 2.0)
    memory_limit = max(1, int(usable_gb / per_thread_gb))
    return max(1, min(os.cpu_count() or 1, memory_limit))


def sanitize_advanced(values: dict[str, Any] | None) -> dict[str, Any]:
    values = values or {}
    rejected = set(values) & (BLOCKED_OPTIONS | (set(values) - ADVANCED_ALLOWLIST))
    if rejected:
        raise ValueError(f"Unsupported advanced options: {', '.join(sorted(rejected))}")
    sanitized: dict[str, Any] = {}
    for key in sorted(values):
        value = values[key]
        kind, constraint = ADVANCED_RULES[key]
        if kind == "bool":
            if type(value) is not bool:
                raise ValueError(f"{key} must be true or false")
        elif kind == "int":
            if type(value) is not int:
                raise ValueError(f"{key} must be a whole number")
            minimum, maximum = constraint
            if not minimum <= value <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            minimum, maximum = constraint
            if not minimum <= float(value) <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
            value = float(value)
        elif kind == "choice" and value not in constraint:
            raise ValueError(f"{key} must be one of: {', '.join(sorted(constraint))}")
        sanitized[key] = value
    return sanitized


def resolve_outputs(values: dict[str, bool] | None) -> dict[str, bool]:
    unknown = set(values or {}) - set(OUTPUT_DEFAULTS)
    if unknown:
        raise ValueError(f"Unsupported outputs: {', '.join(sorted(unknown))}")
    if any(type(value) is not bool for value in (values or {}).values()):
        raise ValueError("Output selections must be true or false")
    outputs = OUTPUT_DEFAULTS | (values or {})
    if outputs["dtm"]:
        outputs["point_cloud"] = True
    if outputs["splat"]:
        outputs["raw"] = True
    if not any(outputs.values()):
        raise ValueError("Select at least one output")
    return outputs


def resolve_odm_options(
    preset_name: str,
    outputs: dict[str, bool],
    inspection: dict[str, Any],
    advanced: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if preset_name not in PRESETS:
        raise ValueError("Unknown preset")
    options = {
        **PRESETS[preset_name]["odm"],
        "feature-type": "sift",
        "cog": True,
        "tiles": True,
        "build-overviews": True,
        "max-concurrency": calculate_concurrency(
            float(inspection.get("megapixels") or 9),
            float(inspection.get("host_ram_gb") or 48),
        ),
    }
    options.update(sanitize_advanced(advanced))
    if inspection.get("camera_model", "").upper() == "FC330":
        options["rolling-shutter"] = True
        options["rolling-shutter-readout"] = 33
    if outputs["point_cloud"]:
        options["pc-ept"] = True
        options["pc-copc"] = True
    if outputs["point_cloud"] or outputs["mesh"]:
        options["3d-tiles"] = True
    if outputs["mesh"]:
        options["gltf"] = True
    if outputs["dsm"]:
        options["dsm"] = True
    if outputs["dtm"]:
        options["dtm"] = True
        options["pc-classify"] = True
    if not outputs["orthomosaic"]:
        options["skip-orthophoto"] = True
    if not outputs["mesh"]:
        options["skip-3dmodel"] = True
    if not outputs["report"]:
        options["skip-report"] = True
    # NodeODM expects flags as a name/value array. False flags are omitted.
    return [
        {"name": name, "value": value}
        for name, value in sorted(options.items())
        if value is not False and value is not None
    ]
