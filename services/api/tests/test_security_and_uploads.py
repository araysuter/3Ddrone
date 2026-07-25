from __future__ import annotations

import hashlib
import io

from PIL import Image

from app.config import settings
from app.db import one, transaction


def jpeg_bytes(color=(24, 80, 120)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(buffer, "JPEG")
    return buffer.getvalue()


def create_project(client, csrf, name="School test"):
    response = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "preset": "high",
            "outputs": {"splat": False},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def initialize(client, csrf, project_id, filename, content):
    response = client.post(
        f"/api/projects/{project_id}/uploads",
        headers={"X-CSRF-Token": csrf},
        json={"filename": filename, "size": len(content)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_setup_is_one_time_and_csrf_is_required(client):
    first = client.post(
        "/api/setup",
        json={"username": "admin", "password": "a sufficiently long password"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/setup",
        json={"username": "other", "password": "another sufficiently long password"},
    )
    assert second.status_code == 409
    forbidden = client.post(
        "/api/projects",
        json={"name": "No CSRF", "preset": "high", "outputs": {}},
    )
    assert forbidden.status_code == 403


def test_resumable_upload_offset_checksum_and_duplicate_rejection(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = jpeg_bytes()
    upload = initialize(client, csrf, project["id"], "DJI_0001.JPG", content)
    midpoint = len(content) // 2
    first = client.patch(
        f"/api/uploads/{upload['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
        content=content[:midpoint],
    )
    assert first.status_code == 204
    offset = client.head(f"/api/uploads/{upload['id']}")
    assert offset.headers["Upload-Offset"] == str(midpoint)
    wrong_offset = client.patch(
        f"/api/uploads/{upload['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
        content=content[midpoint:],
    )
    assert wrong_offset.status_code == 409
    second = client.patch(
        f"/api/uploads/{upload['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": str(midpoint)},
        content=content[midpoint:],
    )
    assert second.headers["Upload-Offset"] == str(len(content))
    checksum = hashlib.sha256(content).hexdigest()
    completed = client.post(
        f"/api/uploads/{upload['id']}/complete",
        headers={"X-CSRF-Token": csrf},
        json={"sha256": checksum},
    )
    assert completed.status_code == 200

    duplicate = initialize(client, csrf, project["id"], "DJI_0002.JPG", content)
    client.patch(
        f"/api/uploads/{duplicate['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
        content=content,
    )
    rejected = client.post(
        f"/api/uploads/{duplicate['id']}/complete",
        headers={"X-CSRF-Token": csrf},
        json={"sha256": checksum},
    )
    assert rejected.status_code == 409
    assert "Duplicate" in rejected.json()["detail"]


def test_corrupt_image_is_rejected(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = b"this is not an image"
    upload = initialize(client, csrf, project["id"], "bad.JPG", content)
    client.patch(
        f"/api/uploads/{upload['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
        content=content,
    )
    response = client.post(
        f"/api/uploads/{upload['id']}/complete",
        headers={"X-CSRF-Token": csrf},
        json={"sha256": hashlib.sha256(content).hexdigest()},
    )
    assert response.status_code == 422


def test_upload_head_reconciles_durable_file_offset(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = jpeg_bytes()
    upload = initialize(client, csrf, project["id"], "DJI_0001.JPG", content)
    midpoint = len(content) // 2
    part = settings.data_root / "uploads" / f"{upload['id']}.part"
    part.write_bytes(content[:midpoint])

    response = client.head(f"/api/uploads/{upload['id']}")

    assert response.status_code == 204
    assert response.headers["Upload-Offset"] == str(midpoint)
    assert one("SELECT offset FROM uploads WHERE id=?", (upload["id"],))["offset"] == midpoint


def test_upload_head_recovers_a_completed_rename_after_database_crash(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = jpeg_bytes()
    upload = initialize(client, csrf, project["id"], "DJI_0001.JPG", content)
    part = settings.data_root / "uploads" / f"{upload['id']}.part"
    part.unlink()
    destination = settings.data_root / "source" / project["id"] / "DJI_0001.JPG"
    destination.write_bytes(content)

    response = client.head(f"/api/uploads/{upload['id']}")

    assert response.status_code == 204
    assert response.headers["Upload-State"] == "complete"
    recovered = one("SELECT state,sha256,offset FROM uploads WHERE id=?", (upload["id"],))
    assert recovered == {
        "state": "complete",
        "sha256": hashlib.sha256(content).hexdigest(),
        "offset": len(content),
    }


def test_rejected_filename_can_be_initialized_again(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = b"not an image"
    upload = initialize(client, csrf, project["id"], "retry.JPG", content)
    client.patch(
        f"/api/uploads/{upload['id']}",
        headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
        content=content,
    )
    client.post(
        f"/api/uploads/{upload['id']}/complete",
        headers={"X-CSRF-Token": csrf},
        json={"sha256": hashlib.sha256(content).hexdigest()},
    )

    replacement = initialize(
        client,
        csrf,
        project["id"],
        "retry.JPG",
        jpeg_bytes(),
    )

    assert replacement["id"] != upload["id"]
    assert one("SELECT state FROM uploads WHERE id=?", (replacement["id"],))["state"] == "uploading"


def test_cross_platform_and_control_character_filenames_are_rejected(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    for filename in ("..\\escape.JPG", "line\nbreak.JPG", f"{'é' * 120}.JPG"):
        response = client.post(
            f"/api/projects/{project['id']}/uploads",
            headers={"X-CSRF-Token": csrf},
            json={"filename": filename, "size": 10},
        )
        assert response.status_code == 422


def test_control_characters_are_rejected_in_admin_and_project_names(client):
    setup = client.post(
        "/api/setup",
        json={"username": "bad\nadmin", "password": "a sufficiently long password"},
    )
    assert setup.status_code == 422

    valid = client.post(
        "/api/setup",
        json={"username": "admin", "password": "a sufficiently long password"},
    )
    csrf = valid.json()["csrf_token"]
    project = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "bad\nproject", "preset": "standard", "outputs": {}},
    )
    assert project.status_code == 422


def test_start_rejects_unfinished_and_too_small_photo_sets(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf)
    content = jpeg_bytes()
    initialize(client, csrf, project["id"], "DJI_0001.JPG", content)
    unfinished = client.post(
        f"/api/projects/{project['id']}/start",
        headers={"X-CSRF-Token": csrf},
    )
    assert unfinished.status_code == 409
    assert "incomplete" in unfinished.json()["detail"]

    with transaction() as db:
        db.execute("DELETE FROM uploads WHERE project_id=?", (project["id"],))
    for index in range(2):
        image = jpeg_bytes((24 + index, 80, 120))
        upload = initialize(
            client,
            csrf,
            project["id"],
            f"DJI_{index:04}.JPG",
            image,
        )
        client.patch(
            f"/api/uploads/{upload['id']}",
            headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
            content=image,
        )
        client.post(
            f"/api/uploads/{upload['id']}/complete",
            headers={"X-CSRF-Token": csrf},
            json={"sha256": hashlib.sha256(image).hexdigest()},
        )
    too_small = client.post(
        f"/api/projects/{project['id']}/start",
        headers={"X-CSRF-Token": csrf},
    )
    assert too_small.status_code == 409
    assert "three overlapping images" in too_small.json()["detail"]


def test_reprocess_reuses_completed_uploads_and_applies_new_settings(authenticated):
    client, csrf = authenticated
    project = create_project(client, csrf, name="Original mapping")
    folder = client.post(
        "/api/folders",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Reprocessing project"},
    ).json()
    client.patch(
        f"/api/projects/{project['id']}/folder",
        headers={"X-CSRF-Token": csrf},
        json={"folder_id": folder["id"]},
    )
    source_paths = []
    for index in range(3):
        content = jpeg_bytes((24 + index, 80 + index, 120))
        filename = f"DJI_{index:04}.JPG"
        upload = initialize(client, csrf, project["id"], filename, content)
        client.patch(
            f"/api/uploads/{upload['id']}",
            headers={"X-CSRF-Token": csrf, "Upload-Offset": "0"},
            content=content,
        )
        completed = client.post(
            f"/api/uploads/{upload['id']}/complete",
            headers={"X-CSRF-Token": csrf},
            json={"sha256": hashlib.sha256(content).hexdigest()},
        )
        assert completed.status_code == 200
        source_paths.append(settings.data_root / "source" / project["id"] / filename)

    with transaction() as db:
        db.execute(
            "UPDATE projects SET status='completed',stage='Completed',progress=100 WHERE id=?",
            (project["id"],),
        )

    response = client.post(
        f"/api/projects/{project['id']}/reprocess",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Reprocessed mapping",
            "preset": "ultra",
            "outputs": {"splat": False, "dtm": False},
            "advanced": {"crop": 0, "pc-filter": 0},
        },
    )

    assert response.status_code == 200, response.text
    reprocessed = response.json()
    assert reprocessed["name"] == "Reprocessed mapping"
    assert reprocessed["preset"] == "ultra"
    assert reprocessed["status"] == "queued"
    assert reprocessed["progress"] == 0
    assert reprocessed["folder_id"] == folder["id"]
    assert reprocessed["advanced"] == {"crop": 0.0, "pc-filter": 0.0}
    assert len(reprocessed["uploads"]) == 3
    assert all(upload["state"] == "complete" for upload in reprocessed["uploads"])
    assert all(path.is_file() for path in source_paths)


def test_docs_are_disabled_and_sessions_expire(authenticated):
    client, _ = authenticated
    assert client.get("/docs").status_code == 404
    cookie = client.cookies.get("mapper_session")
    assert cookie
    from app.security import token_hash

    with transaction() as db:
        db.execute(
            "UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
            (token_hash(cookie),),
        )
    assert client.get("/api/session").status_code == 401
