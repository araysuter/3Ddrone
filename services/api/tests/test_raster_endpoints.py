from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.artifacts import artifacts_root


def create_project(client, csrf, outputs=None):
    response = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Raster test",
            "preset": "standard",
            "outputs": outputs or {"splat": False},
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_raster_metadata_and_elevation_sampling(authenticated):
    client, csrf = authenticated
    project_id = create_project(client, csrf)
    root = artifacts_root(project_id)
    dem = root / "odm_dem" / "dsm.tif"
    dem.parent.mkdir(parents=True)
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:32617",
        transform=from_origin(500000, 4700000, 1, 1),
        nodata=-9999,
    ) as output:
        output.write(np.array([[10, 20], [30, -9999]], dtype="float32"), 1)
    (root / "dsm_tiles" / "18").mkdir(parents=True)

    metadata = client.get(
        f"/api/projects/{project_id}/raster-metadata",
        params={"layer": "dsm"},
    )
    assert metadata.status_code == 200, metadata.text
    body = metadata.json()
    assert body["crs"] == "EPSG:32617"
    assert body["min_zoom"] == 18
    assert body["max_zoom"] == 18
    assert body["tile_scheme"] == "tms"

    sample = client.get(
        f"/api/projects/{project_id}/elevation",
        params={"layer": "dsm", "x": 500000.5, "y": 4699999.5},
    )
    assert sample.status_code == 200
    assert sample.json()["elevation"] == 10

    nodata = client.get(
        f"/api/projects/{project_id}/elevation",
        params={"layer": "dsm", "x": 500001.5, "y": 4699998.5},
    )
    assert nodata.status_code == 200
    assert nodata.json()["elevation"] is None

    outside = client.get(
        f"/api/projects/{project_id}/elevation",
        params={"layer": "dsm", "x": 0, "y": 0},
    )
    assert outside.status_code == 422


def test_disabled_raster_cannot_be_read_from_stale_files(authenticated):
    client, csrf = authenticated
    project_id = create_project(
        client,
        csrf,
        {"dsm": False, "dtm": False, "splat": False},
    )
    root = artifacts_root(project_id)
    dem = root / "odm_dem" / "dsm.tif"
    tile = root / "dsm_tiles" / "18" / "1" / "2.png"
    dem.parent.mkdir(parents=True)
    tile.parent.mkdir(parents=True)
    dem.write_bytes(b"stale")
    tile.write_bytes(b"stale")

    metadata = client.get(
        f"/api/projects/{project_id}/raster-metadata",
        params={"layer": "dsm"},
    )
    sample = client.get(
        f"/api/projects/{project_id}/elevation",
        params={"layer": "dsm", "x": 0, "y": 0},
    )
    tiled = client.get(
        f"/api/projects/{project_id}/tiles/dsm/18/1/2.png",
    )

    assert metadata.status_code == 404
    assert sample.status_code == 404
    assert tiled.status_code == 404
