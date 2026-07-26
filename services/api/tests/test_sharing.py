from __future__ import annotations

import json
from urllib.parse import urlsplit

from app.artifacts import artifacts_root
from app.db import transaction, update_project
from app.sharing import publish_existing_share


def _completed_map(client, csrf, *, name="Shared map"):
    folder = client.post(
        "/api/folders",
        json={"name": "Client project"},
        headers={"X-CSRF-Token": csrf},
    )
    assert folder.status_code == 201
    created = client.post(
        "/api/projects",
        json={
            "name": name,
            "preset": "high",
            "folder_id": folder.json()["id"],
            "outputs": {
                "orthomosaic": True,
                "point_cloud": False,
                "mesh": False,
                "splat": False,
                "dsm": False,
                "dtm": False,
                "report": False,
                "raw": True,
            },
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    root = artifacts_root(project_id)
    preview = root / "odm_orthophoto" / "odm_orthophoto.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"old-orthomosaic")
    (root / "log.json").write_text('{"safe":"published"}')
    (root.parent / "all.zip").write_bytes(b"published-archive")
    update_project(
        project_id,
        status="completed",
        stage="Completed",
        progress=100,
        inspection_json=json.dumps(
            {
                "images": 42,
                "camera_model": "FC330",
                "relative_altitude_median": 55,
                "host_ram_gb": 48,
                "accuracy": {
                    "label": "Best effort — consumer GPS",
                    "survey_grade": False,
                    "detail": "Review the report before relying on measurements.",
                },
            }
        ),
    )
    return project_id, folder.json()["id"], preview


def _share_parts(payload):
    share = payload["share"]
    parsed = urlsplit(share["url"])
    return parsed.path.rsplit("/", 1)[-1], share


def _without_admin(client):
    token = client.cookies.get("mapper_session")
    assert token
    client.cookies.delete("mapper_session")
    return token


def _restore_admin(client, token):
    client.cookies.set("mapper_session", token)


def test_share_link_is_public_revocable_and_rotates_id(authenticated):
    client, csrf = authenticated
    project_id, _, _ = _completed_map(client, csrf)

    created = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200
    share_id, share = _share_parts(created.json())
    assert created.json()["configured"] is True
    assert share["enabled"] is True
    assert share["url"] == f"https://dronemaps.ashersuter.com/share/{share_id}"

    admin_token = _without_admin(client)
    assert client.get("/api/projects").status_code == 401

    detail = client.get(f"/api/public/shares/{share_id}")
    assert detail.status_code == 200
    assert "no-store" in detail.headers["cache-control"]
    assert detail.headers["x-robots-tag"] == "noindex, nofollow, noarchive, nosnippet"
    public = detail.json()
    assert public["folder_name"] == "Client project"
    assert public["name"] == "Shared map"
    assert public["inspection"]["images"] == 42
    assert "host_ram_gb" not in public["inspection"]
    for private_field in (
        "id",
        "folder_id",
        "advanced",
        "uploads",
        "nodeodm_uuid",
        "splat_job_id",
        "error",
    ):
        assert private_field not in public
    assert {artifact["category"] for artifact in public["artifacts"]} == {
        "orthomosaic",
        "raw",
        "archive",
    }
    artifact = client.get(
        f"/api/public/shares/{share_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )
    assert artifact.status_code == 200
    assert artifact.content == b"old-orthomosaic"
    assert "no-store" in artifact.headers["cache-control"]

    _restore_admin(client, admin_token)
    status = client.get(f"/api/projects/{project_id}/share")
    assert status.json()["share"]["view_count"] == 1
    assert status.json()["share"]["last_viewed_at"]
    disabled = client.delete(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert disabled.status_code == 200
    assert disabled.json()["share"]["enabled"] is False

    client.cookies.delete("mapper_session")
    assert client.get(f"/api/public/shares/{share_id}").status_code == 404
    _restore_admin(client, admin_token)
    enabled = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert enabled.json()["share"]["url"] == share["url"]

    regenerated = client.post(
        f"/api/projects/{project_id}/share/regenerate",
        headers={"X-CSRF-Token": csrf},
    )
    new_share_id, new_share = _share_parts(regenerated.json())
    assert new_share_id != share_id
    assert new_share["url"] != share["url"]
    assert new_share["view_count"] == 0
    assert new_share["last_viewed_at"] is None

    client.cookies.delete("mapper_session")
    assert client.get(f"/api/public/shares/{share_id}").status_code == 404
    assert client.get(f"/api/public/shares/{new_share_id}").status_code == 200
    artifact = client.get(
        f"/api/public/shares/{new_share_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )
    assert artifact.status_code == 200
    assert artifact.content == b"old-orthomosaic"


def test_share_keeps_last_publication_until_completed_result_is_published(authenticated):
    client, csrf = authenticated
    project_id, _, preview = _completed_map(client, csrf)
    created = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id, _ = _share_parts(created.json())
    admin_token = _without_admin(client)

    update_project(project_id, status="processing", stage="Reprocessing", progress=40)
    preview.unlink()
    preview.write_bytes(b"new-orthomosaic")
    before_publish = client.get(
        f"/api/public/shares/{share_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )
    assert before_publish.content == b"old-orthomosaic"

    update_project(project_id, status="completed", stage="Completed", progress=100)
    assert publish_existing_share(project_id) is True
    after_publish = client.get(
        f"/api/public/shares/{share_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )
    assert after_publish.content == b"new-orthomosaic"

    _restore_admin(client, admin_token)
    with transaction() as db:
        assert (
            db.execute(
                "SELECT publish_error FROM project_shares WHERE project_id=?",
                (project_id,),
            ).fetchone()["publish_error"]
            is None
        )


def test_project_folder_rename_updates_published_header(authenticated):
    client, csrf = authenticated
    project_id, folder_id, _ = _completed_map(client, csrf)
    created = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id, _ = _share_parts(created.json())

    renamed = client.patch(
        f"/api/folders/{folder_id}",
        json={"name": "Renamed client project"},
        headers={"X-CSRF-Token": csrf},
    )
    assert renamed.status_code == 200
    _without_admin(client)
    assert (
        client.get(f"/api/public/shares/{share_id}").json()["folder_name"]
        == "Renamed client project"
    )


def test_map_rename_updates_published_header_without_republishing_files(authenticated):
    client, csrf = authenticated
    project_id, _, preview = _completed_map(client, csrf)
    created = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id, _ = _share_parts(created.json())

    renamed = client.patch(
        f"/api/projects/{project_id}/name",
        json={"name": "Shared map — July 26"},
        headers={"X-CSRF-Token": csrf},
    )
    assert renamed.status_code == 200
    assert renamed.json()["status"] == "completed"
    assert preview.read_bytes() == b"old-orthomosaic"

    _without_admin(client)
    public = client.get(f"/api/public/shares/{share_id}")
    assert public.status_code == 200
    assert public.json()["name"] == "Shared map — July 26"
    artifact = client.get(
        f"/api/public/shares/{share_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )
    assert artifact.content == b"old-orthomosaic"
