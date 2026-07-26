from __future__ import annotations

import json
import sqlite3
import uuid

from app.config import settings
from app.db import init_db, one, transaction, utcnow


def create_folder(client, csrf: str, name: str = "Arbordale") -> dict:
    response = client.post(
        "/api/folders",
        headers={"X-CSRF-Token": csrf},
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_map(client, csrf: str, name: str = "Weekly map", folder_id: str | None = None) -> dict:
    response = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "preset": "standard",
            "outputs": {"splat": False},
            "folder_id": folder_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_legacy_database_migration_preserves_unassigned_maps():
    settings.database_path.unlink()
    legacy_id = str(uuid.uuid4())
    now = utcnow()
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            """
            CREATE TABLE projects (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              preset TEXT NOT NULL,
              status TEXT NOT NULL,
              stage TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0,
              outputs_json TEXT NOT NULL,
              advanced_json TEXT NOT NULL,
              inspection_json TEXT NOT NULL DEFAULT '{}',
              nodeodm_uuid TEXT,
              nodeodm_output_line INTEGER NOT NULL DEFAULT 0,
              splat_job_id TEXT,
              error TEXT,
              gcp_used INTEGER NOT NULL DEFAULT 0,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            INSERT INTO projects(
              id,name,preset,status,stage,progress,outputs_json,advanced_json,
              inspection_json,created_at,updated_at
            ) VALUES(?,?,'high','completed','Completed',100,?,?,?, ?,?)
            """,
            (legacy_id, "Existing map", json.dumps({}), json.dumps({}), "{}", now, now),
        )

    init_db()
    init_db()

    migrated = one("SELECT id,name,folder_id FROM projects WHERE id=?", (legacy_id,))
    assert migrated == {"id": legacy_id, "name": "Existing map", "folder_id": None}
    assert one("SELECT COUNT(*) AS count FROM map_folders")["count"] == 0


def test_folder_crud_is_authenticated_unique_and_validated(authenticated, client):
    client, csrf = authenticated
    assert client.get("/api/folders").status_code == 200

    forbidden = client.post("/api/folders", json={"name": "No CSRF"})
    assert forbidden.status_code == 403

    first = create_folder(client, csrf, "Arbordale")
    create_folder(client, csrf, "Barton Hills")
    duplicate = client.post(
        "/api/folders",
        headers={"X-CSRF-Token": csrf},
        json={"name": "arbordale"},
    )
    assert duplicate.status_code == 409

    renamed = client.patch(
        f"/api/folders/{first['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Arbordale Street"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Arbordale Street"

    bad_name = client.patch(
        f"/api/folders/{first['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "bad\nname"},
    )
    assert bad_name.status_code == 422
    assert [folder["name"] for folder in client.get("/api/folders").json()] == [
        "Arbordale Street",
        "Barton Hills",
    ]


def test_map_creation_assignment_and_active_reassignment(authenticated):
    client, csrf = authenticated
    folder = create_folder(client, csrf)
    mapping = create_map(client, csrf, folder_id=folder["id"])
    assert mapping["folder_id"] == folder["id"]
    assert mapping["status"] == "uploading"

    missing = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Missing folder",
            "preset": "standard",
            "outputs": {"splat": False},
            "folder_id": str(uuid.uuid4()),
        },
    )
    assert missing.status_code == 404

    unassigned = client.patch(
        f"/api/projects/{mapping['id']}/folder",
        headers={"X-CSRF-Token": csrf},
        json={"folder_id": None},
    )
    assert unassigned.status_code == 200
    assert unassigned.json()["folder_id"] is None
    assert unassigned.json()["status"] == "uploading"

    invalid_move = client.patch(
        f"/api/projects/{mapping['id']}/folder",
        headers={"X-CSRF-Token": csrf},
        json={"folder_id": str(uuid.uuid4())},
    )
    assert invalid_move.status_code == 404
    assert one("SELECT folder_id FROM projects WHERE id=?", (mapping["id"],))["folder_id"] is None

    malformed_move = client.patch(
        f"/api/projects/{mapping['id']}/folder",
        headers={"X-CSRF-Token": csrf},
        json={"folder_id": "not-a-folder-id"},
    )
    assert malformed_move.status_code == 422


def test_map_rename_is_metadata_only_and_csrf_protected(authenticated):
    client, csrf = authenticated
    folder = create_folder(client, csrf)
    mapping = create_map(client, csrf, name="Arbordale ST", folder_id=folder["id"])
    source = settings.data_root / "source" / mapping["id"] / "retained.txt"
    artifact = settings.data_root / "metadata" / "projects" / mapping["id"] / "artifact.txt"
    source.write_text("source")
    artifact.write_text("artifact")
    with transaction() as db:
        db.execute(
            "UPDATE projects SET status='processing',stage='Feature matching',progress=31 WHERE id=?",
            (mapping["id"],),
        )

    forbidden = client.patch(
        f"/api/projects/{mapping['id']}/name",
        json={"name": "Arbordale ST — July 26"},
    )
    assert forbidden.status_code == 403

    renamed = client.patch(
        f"/api/projects/{mapping['id']}/name",
        headers={"X-CSRF-Token": csrf},
        json={"name": " Arbordale ST — July 26 "},
    )
    assert renamed.status_code == 200
    renamed_map = renamed.json()
    assert renamed_map["name"] == "Arbordale ST — July 26"
    assert renamed_map["folder_id"] == folder["id"]
    assert renamed_map["status"] == "processing"
    assert renamed_map["stage"] == "Feature matching"
    assert renamed_map["progress"] == 31
    assert source.read_text() == "source"
    assert artifact.read_text() == "artifact"

    bad_name = client.patch(
        f"/api/projects/{mapping['id']}/name",
        headers={"X-CSRF-Token": csrf},
        json={"name": "bad\nname"},
    )
    assert bad_name.status_code == 422
    assert client.get(f"/api/projects/{mapping['id']}").json()["name"] == "Arbordale ST — July 26"

    missing = client.patch(
        f"/api/projects/{uuid.uuid4()}/name",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Missing map"},
    )
    assert missing.status_code == 404


def test_deleting_folder_unassigns_maps_without_deleting_data(authenticated):
    client, csrf = authenticated
    folder = create_folder(client, csrf)
    mapping = create_map(client, csrf, folder_id=folder["id"])
    source = settings.data_root / "source" / mapping["id"] / "retained.txt"
    artifact = settings.data_root / "metadata" / "projects" / mapping["id"] / "artifact.txt"
    source.write_text("source")
    artifact.write_text("artifact")
    with transaction() as db:
        db.execute(
            "UPDATE projects SET status='processing',stage='Feature matching' WHERE id=?",
            (mapping["id"],),
        )

    rejected = client.delete(
        f"/api/folders/{folder['id']}",
        headers={"X-CSRF-Token": csrf, "X-Confirm-Folder-Name": "wrong"},
    )
    assert rejected.status_code == 409

    deleted = client.delete(
        f"/api/folders/{folder['id']}",
        headers={"X-CSRF-Token": csrf, "X-Confirm-Folder-Name": folder["name"]},
    )
    assert deleted.status_code == 204
    retained = client.get(f"/api/projects/{mapping['id']}").json()
    assert retained["folder_id"] is None
    assert retained["status"] == "processing"
    assert retained["stage"] == "Feature matching"
    assert source.read_text() == "source"
    assert artifact.read_text() == "artifact"
    assert client.get("/api/folders").json() == []
