from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from app.artifacts import artifacts_root
from app.config import settings
from app.db import all_rows, init_db, one, update_project
from app.folder_sharing import publish_folder_share_for_project


OUTPUTS = {
    "orthomosaic": True,
    "point_cloud": False,
    "mesh": False,
    "splat": False,
    "dsm": False,
    "dtm": False,
    "report": False,
    "raw": True,
}


def _folder(client, csrf: str, name: str = "Arbordale Street") -> str:
    response = client.post(
        "/api/folders",
        json={"name": name},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _map(
    client,
    csrf: str,
    folder_id: str | None,
    *,
    name: str,
    status: str = "completed",
    artifact: bytes | None = b"orthomosaic",
) -> str:
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "preset": "high",
            "folder_id": folder_id,
            "outputs": OUTPUTS,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    project_id = response.json()["id"]
    if artifact is not None:
        preview = (
            artifacts_root(project_id)
            / "odm_orthophoto"
            / "odm_orthophoto.png"
        )
        preview.parent.mkdir(parents=True)
        preview.write_bytes(artifact)
        (artifacts_root(project_id) / "log.json").write_text('{"published":true}')
    update_project(
        project_id,
        status=status,
        stage="Completed" if status == "completed" else status.title(),
        progress=100 if status == "completed" else 96,
        inspection_json=json.dumps(
            {
                "images": 507,
                "camera_model": "FC330",
                "host_ram_gb": 48,
            }
        ),
    )
    return project_id


def _share_id(payload: dict) -> str:
    return urlsplit(payload["share"]["url"]).path.rsplit("/", 1)[-1]


def _sign_out(client) -> str:
    token = client.cookies.get("mapper_session")
    assert token
    client.cookies.delete("mapper_session")
    return token


def _sign_in(client, token: str) -> None:
    client.cookies.set("mapper_session", token)


def _public_collection(client, share_id: str) -> dict:
    response = client.get(f"/api/public/project-shares/{share_id}")
    assert response.status_code == 200
    return response.json()


def _public_artifact_url(share_id: str, item_id: str) -> str:
    return (
        f"/api/public/project-shares/{share_id}/maps/{item_id}/artifacts/"
        "artifacts/odm_orthophoto/odm_orthophoto.png"
    )


def test_project_share_schema_is_idempotent(authenticated):
    init_db()
    init_db()
    assert one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='folder_shares'"
    )
    assert one(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='folder_share_items'"
    )


def test_empty_project_share_is_public_without_a_cookie(authenticated):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200
    share_id = _share_id(created.json())
    assert created.json()["share"]["url"] == (
        f"https://dronemaps.ashersuter.com/share/projects/{share_id}"
    )
    assert created.json()["share"]["published_map_count"] == 0

    _sign_out(client)
    public = _public_collection(client, share_id)
    assert public == {"name": "Arbordale Street", "maps": []}
    assert client.get("/api/folders").status_code == 401


def test_public_project_lists_only_published_maps_and_sanitizes_payloads(
    authenticated,
):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    _map(
        client,
        csrf,
        folder_id,
        name="Arbordale (7/24/26)",
        artifact=b"older",
    )
    newest_id = _map(
        client,
        csrf,
        folder_id,
        name="Arbordale (7/25/26)",
        artifact=b"newest",
    )
    _map(
        client,
        csrf,
        folder_id,
        name="Still processing",
        status="processing",
        artifact=None,
    )
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id = _share_id(created.json())
    other_folder_id = _folder(client, csrf, "Dartmoor")
    _map(client, csrf, other_folder_id, name="Dartmoor", artifact=b"other")
    other_share = client.post(
        f"/api/folders/{other_folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    other_share_id = _share_id(other_share.json())

    _sign_out(client)
    public = _public_collection(client, share_id)
    assert set(public) == {"name", "maps"}
    assert [item["name"] for item in public["maps"]] == [
        "Arbordale (7/25/26)",
        "Arbordale (7/24/26)",
    ]
    assert all(set(item) == {"id", "name", "status"} for item in public["maps"])
    item_id = public["maps"][0]["id"]
    detail = client.get(
        f"/api/public/project-shares/{share_id}/maps/{item_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["name"] == "Arbordale (7/25/26)"
    assert payload["folder_name"] == "Arbordale Street"
    assert payload["inspection"]["images"] == 507
    assert "host_ram_gb" not in payload["inspection"]
    for private_field in (
        "id",
        "folder_id",
        "project_id",
        "advanced",
        "uploads",
        "error",
        "nodeodm_uuid",
    ):
        assert private_field not in payload
    artifact = client.get(_public_artifact_url(share_id, item_id))
    assert artifact.status_code == 200
    assert artifact.content == b"newest"
    assert "no-store" in artifact.headers["cache-control"]

    other_item_id = _public_collection(client, other_share_id)["maps"][0]["id"]
    assert (
        client.get(_public_artifact_url(share_id, other_item_id)).status_code
        == 404
    )
    assert client.get(f"/api/public/shares/{share_id}").status_code == 404
    assert one(
        "SELECT project_id FROM folder_share_items WHERE id=?", (item_id,)
    )["project_id"] == newest_id


def test_live_membership_and_renames_update_without_republishing(authenticated):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    other_folder_id = _folder(client, csrf, "Dartmoor")
    first_id = _map(
        client,
        csrf,
        folder_id,
        name="Arbordale (7/24/26)",
        artifact=b"first",
    )
    moved_id = _map(
        client,
        csrf,
        other_folder_id,
        name="Arbordale (7/25/26)",
        artifact=b"moved",
    )
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id = _share_id(created.json())
    first_item = one(
        "SELECT id,snapshot_version FROM folder_share_items WHERE project_id=?",
        (first_id,),
    )

    renamed_folder = client.patch(
        f"/api/folders/{folder_id}",
        json={"name": "Arbordale Survey"},
        headers={"X-CSRF-Token": csrf},
    )
    assert renamed_folder.status_code == 200
    renamed_map = client.patch(
        f"/api/projects/{first_id}/name",
        json={"name": "Arbordale — final"},
        headers={"X-CSRF-Token": csrf},
    )
    assert renamed_map.status_code == 200
    assert (
        one(
            "SELECT snapshot_version FROM folder_share_items WHERE project_id=?",
            (first_id,),
        )["snapshot_version"]
        == first_item["snapshot_version"]
    )
    moved = client.patch(
        f"/api/projects/{moved_id}/folder",
        json={"folder_id": folder_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert moved.status_code == 200
    removed = client.patch(
        f"/api/projects/{first_id}/folder",
        json={"folder_id": other_folder_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert removed.status_code == 200

    _sign_out(client)
    public = _public_collection(client, share_id)
    assert public["name"] == "Arbordale Survey"
    assert [item["name"] for item in public["maps"]] == [
        "Arbordale (7/25/26)"
    ]
    assert one(
        "SELECT id FROM folder_share_items WHERE project_id=?", (first_id,)
    ) is None


def test_reprocessing_retains_old_snapshot_and_partial_new_map_is_published(
    authenticated,
):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    project_id = _map(
        client,
        csrf,
        folder_id,
        name="Existing map",
        artifact=b"old",
    )
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id = _share_id(created.json())
    item_id = _public_collection(client, share_id)["maps"][0]["id"]

    preview = (
        artifacts_root(project_id)
        / "odm_orthophoto"
        / "odm_orthophoto.png"
    )
    update_project(project_id, status="processing", stage="Reprocessing")
    preview.unlink()
    preview.write_bytes(b"partial replacement")
    update_project(project_id, status="partial", stage="Partial", error="splat failed")
    assert publish_folder_share_for_project(project_id) is False
    assert client.get(_public_artifact_url(share_id, item_id)).content == b"old"

    status = client.get(f"/api/folders/{folder_id}/share").json()["share"]
    assert status["published_map_count"] == 1
    assert status["failed_map_count"] == 1

    update_project(project_id, status="completed", stage="Completed", error=None)
    assert publish_folder_share_for_project(project_id) is True
    assert (
        client.get(_public_artifact_url(share_id, item_id)).content
        == b"partial replacement"
    )

    preview.unlink()
    preview.write_bytes(b"failed replacement")
    update_project(
        project_id,
        status="failed",
        stage="Failed",
        error="NodeODM processing failed",
    )
    assert publish_folder_share_for_project(project_id) is False
    assert (
        client.get(_public_artifact_url(share_id, item_id)).content
        == b"partial replacement"
    )
    failed_status = client.get(f"/api/folders/{folder_id}/share").json()[
        "share"
    ]
    assert failed_status["failed_map_count"] == 1
    assert "prior publication remains active" in (
        failed_status["publication_issues"][0]["message"]
    )

    partial_id = _map(
        client,
        csrf,
        folder_id,
        name="Usable partial",
        status="partial",
        artifact=b"partial first result",
    )
    assert publish_folder_share_for_project(partial_id) is True
    public = _public_collection(client, share_id)
    assert {item["name"] for item in public["maps"]} == {
        "Existing map",
        "Usable partial",
    }


def test_publication_failures_are_isolated_and_retryable(authenticated):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    good_id = _map(
        client,
        csrf,
        folder_id,
        name="Published map",
        artifact=b"good",
    )
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    share_id = _share_id(created.json())
    broken_id = _map(
        client,
        csrf,
        folder_id,
        name="Broken publication",
        artifact=None,
    )
    assert publish_folder_share_for_project(broken_id) is False
    public = _public_collection(client, share_id)
    assert [item["name"] for item in public["maps"]] == ["Published map"]

    status = client.get(f"/api/folders/{folder_id}/share").json()["share"]
    assert status["published_map_count"] == 1
    assert status["failed_map_count"] == 1
    assert status["publication_issues"][0]["map_name"] == "Broken publication"

    preview = (
        artifacts_root(broken_id)
        / "odm_orthophoto"
        / "odm_orthophoto.png"
    )
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"recovered")
    retry = client.post(
        f"/api/folders/{folder_id}/share/retry",
        headers={"X-CSRF-Token": csrf},
    )
    assert retry.status_code == 200
    assert retry.json()["share"]["published_map_count"] == 2
    assert retry.json()["share"]["failed_map_count"] == 0
    assert {item["name"] for item in _public_collection(client, share_id)["maps"]} == {
        "Published map",
        "Broken publication",
    }
    assert one(
        "SELECT snapshot_version FROM folder_share_items WHERE project_id=?",
        (good_id,),
    )


def test_disable_rotation_metrics_deletion_and_map_share_independence(
    authenticated,
):
    client, csrf = authenticated
    folder_id = _folder(client, csrf)
    project_id = _map(
        client,
        csrf,
        folder_id,
        name="Arbordale",
        artifact=b"published",
    )
    project_share = client.post(
        f"/api/projects/{project_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    map_share_id = _share_id(project_share.json())
    created = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    old_share_id = _share_id(created.json())
    item_id = _public_collection(client, old_share_id)["maps"][0]["id"]
    assert (
        client.get(
            f"/api/public/project-shares/{old_share_id}/maps/{item_id}"
        ).status_code
        == 200
    )
    status = client.get(f"/api/folders/{folder_id}/share").json()["share"]
    assert status["view_count"] == 1
    assert status["last_viewed_at"]

    disabled = client.delete(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert disabled.json()["share"]["enabled"] is False
    assert (
        client.get(f"/api/public/project-shares/{old_share_id}").status_code
        == 404
    )
    assert (
        client.get(
            f"/api/public/project-shares/{old_share_id}/maps/{item_id}"
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/public/map-shares/{map_share_id}").status_code == 200
    )

    enabled = client.post(
        f"/api/folders/{folder_id}/share",
        headers={"X-CSRF-Token": csrf},
    )
    assert _share_id(enabled.json()) == old_share_id
    rotated = client.post(
        f"/api/folders/{folder_id}/share/regenerate",
        headers={"X-CSRF-Token": csrf},
    )
    new_share_id = _share_id(rotated.json())
    assert new_share_id != old_share_id
    assert rotated.json()["share"]["view_count"] == 0
    assert rotated.json()["share"]["last_viewed_at"] is None
    assert (
        client.get(f"/api/public/project-shares/{old_share_id}").status_code
        == 404
    )
    assert (
        client.get(f"/api/public/project-shares/{new_share_id}").status_code
        == 200
    )
    assert (
        client.get(
            f"/api/public/project-shares/{new_share_id}/maps/{item_id}"
        ).status_code
        == 200
    )

    share_root = settings.data_root / "metadata" / "folder-shares" / new_share_id
    assert share_root.is_dir()
    deleted = client.delete(
        f"/api/folders/{folder_id}",
        headers={
            "X-CSRF-Token": csrf,
            "X-Confirm-Folder-Name": "Arbordale Street",
        },
    )
    assert deleted.status_code == 204
    assert not share_root.exists()
    assert (
        client.get(f"/api/public/project-shares/{new_share_id}").status_code
        == 404
    )
    assert client.get(f"/api/public/map-shares/{map_share_id}").status_code == 200
    assert all_rows("SELECT * FROM folder_share_items") == []
