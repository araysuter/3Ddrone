from __future__ import annotations

from pathlib import Path

from app import inspection


def test_fc330_capture_summary(monkeypatch, tmp_path):
    files = []
    metadata = {}
    for index in range(34):
        path = tmp_path / f"DJI_{index:04}.JPG"
        path.write_bytes(b"\xff\xd8\xff")
        files.append(path)
        metadata[path.name] = {
            # This is the exact grouped-key shape produced by
            # `exiftool -j -n -G` in the API image.
            "EXIF:Model": "FC330",
            "EXIF:GPSLatitude": 42.1 + index / 10000,
            "EXIF:GPSLongitude": -83.7,
            "XMP:RelativeAltitude": 79.8 + (index % 4) / 10,
            "XMP:GimbalPitchDegree": -90 if index < 8 else -65,
            "File:ImageWidth": 4000,
            "File:ImageHeight": 2250,
        }
    monkeypatch.setattr(inspection, "_exiftool", lambda path: metadata[path.name])
    summary = inspection.inspect_files(files)
    assert summary["images"] == 34
    assert summary["geotagged"] == 34
    assert summary["camera_model"] == "FC330"
    assert summary["nadir"] == 8
    assert summary["oblique"] == 26
    assert summary["relative_altitude_median"] == 79.9
    assert summary["rolling_shutter_ms"] == 33
    assert summary["accuracy"]["survey_grade"] is False


def test_litchi_mission_is_provenance_not_reconstruction_input(tmp_path):
    mission = tmp_path / "Test Data.lchm"
    mission.write_text("{}")
    summary = inspection.inspect_files([mission])
    assert summary["provenance_files"] == 1
    assert summary["images"] == 0
