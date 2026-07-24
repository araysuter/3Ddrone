from __future__ import annotations

import pytest

from app.presets import (
    calculate_concurrency,
    resolve_odm_options,
    resolve_outputs,
    sanitize_advanced,
)


def as_dict(options):
    return {option["name"]: option["value"] for option in options}


def test_high_fc330_preset_enables_gpu_products_and_known_readout():
    outputs = resolve_outputs(None)
    options = as_dict(
        resolve_odm_options(
            "high",
            outputs,
            {"camera_model": "FC330", "megapixels": 9, "host_ram_gb": 48},
        )
    )
    assert options["feature-type"] == "sift"
    assert options["feature-quality"] == "ultra"
    assert options["pc-quality"] == "high"
    assert options["rolling-shutter"] is True
    assert options["rolling-shutter-readout"] == 33
    assert options["pc-ept"] is True
    assert options["pc-copc"] is True
    assert options["gltf"] is True
    assert options["3d-tiles"] is True
    assert options["cog"] is True
    assert "ignore-gsd" not in options
    assert "no-gpu" not in options


def test_output_dependencies_are_resolved():
    outputs = resolve_outputs(
        {
            "point_cloud": False,
            "dtm": True,
            "raw": False,
            "splat": True,
        }
    )
    assert outputs["point_cloud"] is True
    assert outputs["raw"] is True


def test_disabled_products_do_not_request_their_odm_exports():
    outputs = resolve_outputs(
        {
            "orthomosaic": False,
            "point_cloud": False,
            "mesh": False,
            "dsm": False,
            "dtm": False,
            "report": False,
            "raw": True,
            "splat": False,
        }
    )
    options = as_dict(
        resolve_odm_options(
            "standard",
            outputs,
            {"camera_model": "FC330", "megapixels": 9, "host_ram_gb": 48},
        )
    )

    assert options["skip-orthophoto"] is True
    assert options["skip-3dmodel"] is True
    assert options["skip-report"] is True
    assert "pc-ept" not in options
    assert "pc-copc" not in options
    assert "3d-tiles" not in options
    assert "gltf" not in options
    assert "dsm" not in options
    assert "dtm" not in options
    assert "cog" not in options
    assert "tiles" not in options
    assert "build-overviews" not in options


@pytest.mark.parametrize("name", ["project-path", "copy-to", "rerun-from", "ignore-gsd", "sm-cluster"])
def test_dangerous_advanced_options_are_rejected(name):
    with pytest.raises(ValueError, match="Unsupported"):
        sanitize_advanced({name: True})


def test_concurrency_reserves_ten_gb_for_services():
    # 9 MP images are estimated at 4.5 GB/thread, leaving 38 GB for ODM.
    assert calculate_concurrency(9, 48) <= 8
    assert calculate_concurrency(40, 12) == 1
