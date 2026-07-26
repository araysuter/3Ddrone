from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="aerial-mapper-tests-"))
os.environ["MAPPER_DATA_ROOT"] = str(TEST_DATA_ROOT)
os.environ["MAPPER_COOKIE_SECURE"] = "false"
os.environ["MAPPER_DEMO_MODE"] = "true"
os.environ["MAPPER_INTERNAL_TOKEN"] = "test-internal-token"
os.environ["MAPPER_DISK_RESERVE_BYTES"] = str(1024**3)
os.environ["MAPPER_SHARING_ENABLED"] = "true"
os.environ["MAPPER_PUBLIC_BASE_URL"] = "https://dronemaps.ashersuter.com"

from app.config import settings
from app.db import init_db, transaction


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with transaction() as db:
        for table in (
            "project_events",
            "uploads",
            "folder_share_items",
            "folder_shares",
            "project_shares",
            "projects",
            "map_folders",
            "sessions",
            "login_attempts",
            "admins",
        ):
            db.execute(f"DELETE FROM {table}")
    for folder in (
        "source",
        "uploads",
        "metadata/projects",
        "metadata/shares",
        "metadata/folder-shares",
    ):
        path = settings.data_root / folder
        if path.exists():
            for child in path.iterdir():
                if child.is_dir():
                    import shutil

                    shutil.rmtree(child)
                else:
                    child.unlink()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authenticated(client):
    response = client.post(
        "/api/setup",
        json={"username": "mapper-admin", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return client, response.json()["csrf_token"]
