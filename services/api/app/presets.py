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
    "texturing-data-term",
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
    return {key: values[key] for key in sorted(values)}


def resolve_outputs(values: dict[str, bool] | None) -> dict[str, bool]:
    outputs = OUTPUT_DEFAULTS | (values or {})
    if outputs["dtm"]:
        outputs["point_cloud"] = True
    if outputs["splat"]:
        outputs["raw"] = True
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
    if outputs["mesh"]:
        options["gltf"] = True
        options["3d-tiles"] = True
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
