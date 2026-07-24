from __future__ import annotations

import hashlib
import io

from PIL import Image


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
