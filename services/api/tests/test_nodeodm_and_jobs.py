from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app import jobs, main
from app.db import one, transaction, update_project, utcnow
from app.nodeodm import (
    NodeODMClient,
    NodeODMError,
    nodeodm_output_paths,
    option_mismatches,
)


def test_nodeodm_image_reuses_an_existing_numeric_runtime_identity():
    dockerfile = (
        Path(__file__).resolve().parents[3] / "docker" / "nodeodm.Dockerfile"
    ).read_text()

    assert 'if ! getent group "${MAPPER_GID}"' in dockerfile
    assert 'if ! getent passwd "${MAPPER_UID}"' in dockerfile
    assert "USER ${MAPPER_UID}:${MAPPER_GID}" in dockerfile
    assert "\nUSER odm\n" not in dockerfile


def test_nodeodm_image_includes_stage_aware_concurrency_overlay():
    repository = Path(__file__).resolve().parents[3]
    dockerfile = (repository / "docker" / "nodeodm.Dockerfile").read_text()
    odm_config = (repository / "opendm" / "config.py").read_text()
    odm_osfm = (repository / "opendm" / "osfm.py").read_text()

    assert "COPY opendm/config.py /code/opendm/config.py" in dockerfile
    assert "COPY opendm/osfm.py /code/opendm/osfm.py" in dockerfile
    assert "parser.add_argument('--sfm-max-concurrency'" in odm_config
    assert "args.sfm_max_concurrency or args.max_concurrency" in odm_osfm


def test_nodeodm_option_helper_supports_python_312(tmp_path):
    odm_root = tmp_path / "odm"
    package = odm_root / "opendm"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "def config(parser=None):\n"
        "    parser.add_argument('--quality', default='high', type=str)\n"
    )
    destination = tmp_path / "options.json"
    helper = (
        Path(__file__).resolve().parents[3]
        / "vendor"
        / "nodeodm"
        / "helpers"
        / "odmOptionsToJson.py"
    )
    env = {**os.environ, "ODM_OPTIONS_TMP_FILE": str(destination)}

    result = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--project-path",
            str(odm_root),
            "bogusname",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert json.loads(destination.read_text())["--quality"]["default"] == "high"


@pytest.mark.asyncio
async def test_nodeodm_polling_recovers_from_transient_connection_errors(monkeypatch):
    client = NodeODMClient()
    calls = 0

    async def task_info(_task_uuid):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("temporary")
        return {"status": {"code": 40}, "progress": 100}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(client, "task_info", task_info)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    results = [item async for item in client.wait_for_terminal("task", poll_seconds=0.01)]

    assert calls == 3
    assert results[-1]["status"]["code"] == 40


@pytest.mark.asyncio
async def test_nodeodm_rejects_malformed_console_output(monkeypatch):
    client = NodeODMClient()

    async def malformed(*_args, **_kwargs):
        return {"unexpected": True}

    monkeypatch.setattr(client, "_json", malformed)
    with pytest.raises(NodeODMError, match="malformed"):
        await client.output("task", 0)


@pytest.mark.asyncio
async def test_nodeodm_commit_response_loss_keeps_reserved_task_for_recovery(monkeypatch):
    client = NodeODMClient()
    task_uuid = "00000000-0000-4000-8000-000000000020"
    calls: list[str] = []

    async def fake_json(_method, path, **_kwargs):
        calls.append(path)
        if path == "/task/new/init":
            return {"uuid": task_uuid}
        if path == f"/task/new/commit/{task_uuid}":
            raise httpx.ReadError("commit response was lost")
        if path == "/task/remove":
            raise AssertionError("A possibly committed durable task must not be removed")
        raise AssertionError(path)

    monkeypatch.setattr(client, "_json", fake_json)

    with pytest.raises(httpx.ReadError):
        await client.create_task("Recovery", [], [], task_uuid)

    assert calls == ["/task/new/init", f"/task/new/commit/{task_uuid}"]


@pytest.mark.asyncio
async def test_nodeodm_init_sends_multipart_fields_and_verifies_effective_options(monkeypatch):
    client = NodeODMClient()
    task_uuid = "00000000-0000-4000-8000-000000000023"
    options = [
        {"name": "feature-quality", "value": "ultra"},
        {"name": "rolling-shutter", "value": True},
        {"name": "orthophoto-resolution", "value": 2.5},
    ]
    init_kwargs = {}

    async def fake_json(_method, path, **kwargs):
        if path == "/task/new/init":
            init_kwargs.update(kwargs)
            return {"uuid": task_uuid}
        if path == f"/task/new/commit/{task_uuid}":
            return {"uuid": task_uuid}
        if path == f"/task/{task_uuid}/info":
            return {"status": {"code": 10}, "options": options}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_json", fake_json)

    output_paths = ["odm_orthophoto", "orthophoto_tiles"]
    assert (
        await client.create_task(
            "High FC330", [], options, task_uuid, output_paths
        )
        == task_uuid
    )
    assert "data" not in init_kwargs
    assert init_kwargs["files"]["name"] == (None, "High FC330")
    assert json.loads(init_kwargs["files"]["options"][1]) == options
    assert json.loads(init_kwargs["files"]["outputs"][1]) == output_paths
    assert init_kwargs["files"]["skipPostProcessing"] == (None, "true")
    assert init_kwargs["headers"] == {"Set-UUID": task_uuid}


def test_nodeodm_archive_paths_include_only_selected_product_families():
    selected = nodeodm_output_paths(
        {
            "orthomosaic": True,
            "point_cloud": False,
            "mesh": False,
            "dsm": True,
            "dtm": False,
            "report": False,
            "raw": False,
            "splat": False,
        }
    )

    assert selected == [
        "odm_orthophoto",
        "orthophoto_tiles",
        "odm_dem",
        "dsm_tiles",
    ]
    assert "opensfm" not in selected
    assert "odm_texturing" not in selected
    assert "dtm_tiles" not in selected


@pytest.mark.asyncio
async def test_nodeodm_cancels_task_when_effective_options_do_not_match(monkeypatch):
    client = NodeODMClient()
    task_uuid = "00000000-0000-4000-8000-000000000024"
    calls: list[str] = []
    options = [{"name": "rolling-shutter", "value": True}]

    async def fake_json(_method, path, **_kwargs):
        calls.append(path)
        if path in {"/task/new/init", f"/task/new/commit/{task_uuid}"}:
            return {"uuid": task_uuid}
        if path == f"/task/{task_uuid}/info":
            return {"status": {"code": 10}, "options": []}
        if path == "/task/cancel":
            return {}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_json", fake_json)

    with pytest.raises(NodeODMError, match="rolling-shutter"):
        await client.create_task("Mismatch", [], options, task_uuid)

    assert calls[-1] == "/task/cancel"


@pytest.mark.asyncio
async def test_nodeodm_restart_verifies_recovery_options(monkeypatch):
    client = NodeODMClient()
    task_uuid = "00000000-0000-4000-8000-000000000025"
    options = [{"name": "skip-3dmodel", "value": True}]
    restart_data = {}

    async def fake_json(_method, path, **kwargs):
        if path == "/task/restart":
            restart_data.update(kwargs["data"])
            return {}
        if path == f"/task/{task_uuid}/info":
            return {"status": {"code": 10}, "options": options}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_json", fake_json)

    await client.restart(task_uuid, options)

    assert restart_data["uuid"] == task_uuid
    assert json.loads(restart_data["options"]) == options


def test_nodeodm_option_comparison_accepts_equivalent_numeric_values():
    assert option_mismatches(
        [{"name": "mesh-size", "value": 500000}],
        [{"name": "mesh-size", "value": 500000.0}],
    ) == []
    assert option_mismatches(
        [{"name": "rolling-shutter", "value": True}],
        [{"name": "rolling-shutter", "value": 1}],
    ) == ["rolling-shutter (expected True, got 1)"]


def test_full_mesh_failure_is_detected_and_fallback_disables_only_full_3d_mesh():
    lines = [
        'ReconstructMesh -i "/data/odm_meshing/odm_mesh_dirty.ply"',
        'File "/code/stages/odm_meshing.py", line 25, in process',
        "SubprocessException: Child returned 1",
    ]
    assert jobs.is_recoverable_full_mesh_failure(lines)
    fallback = jobs.terrain_mesh_fallback_options(
        [
            {"name": "gltf", "value": True},
            {"name": "3d-tiles", "value": True},
            {"name": "use-3dmesh", "value": True},
        ]
    )
    assert {"name": "skip-3dmodel", "value": True} in fallback
    assert {"name": "use-3dmesh", "value": True} not in fallback
    assert {"name": "gltf", "value": True} in fallback
    assert {"name": "3d-tiles", "value": True} in fallback


@pytest.mark.asyncio
async def test_failed_full_mesh_restarts_same_task_once_with_terrain_fallback(
    monkeypatch,
):
    project_id = "00000000-0000-4000-8000-000000000026"
    now = utcnow()
    outputs = {
        "orthomosaic": True,
        "point_cloud": True,
        "mesh": True,
        "dsm": True,
        "dtm": True,
        "report": True,
        "raw": True,
        "splat": False,
    }
    with transaction() as db:
        db.execute(
            """
            INSERT INTO projects(
              id,name,preset,status,stage,progress,outputs_json,advanced_json,
              inspection_json,nodeodm_uuid,created_at,updated_at
            ) VALUES(?,?,?,'processing','Meshing and texturing',60,?,?,?, ?,?,?)
            """,
            (
                project_id,
                "Terrain recovery",
                "standard",
                json.dumps(outputs),
                "{}",
                json.dumps(
                    {
                        "camera_model": "FC330",
                        "megapixels": 12,
                        "host_ram_gb": 48,
                    }
                ),
                "durable-task",
                now,
                now,
            ),
        )

    failure_lines = [
        'ReconstructMesh -i "/data/odm_meshing/odm_mesh_dirty.ply"',
        'File "/code/stages/odm_meshing.py", line 25, in process',
        "SubprocessException: Child returned 1",
    ]

    class FakeNodeODM:
        def __init__(self):
            self.recovery_options = None
            self.recovered = False

        async def task_info(self, _task_uuid):
            return {"status": {"code": 20}, "options": []}

        async def wait_for_terminal(self, _task_uuid):
            if not self.recovered:
                yield {
                    "status": {"code": 30, "errorMessage": "Cannot process dataset"},
                    "progress": 100,
                    "options": [],
                }
            else:
                yield {
                    "status": {"code": 40},
                    "progress": 100,
                    "options": self.recovery_options,
                }

        async def output(self, _task_uuid, _line):
            return ["Terrain recovery completed"] if self.recovered else failure_lines

        async def restart(self, _task_uuid, options):
            self.recovery_options = options
            self.recovered = True

        async def download_all(self, _task_uuid, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"placeholder")

    fake = FakeNodeODM()
    monkeypatch.setattr(jobs, "settings", replace(jobs.settings, demo_mode=False))
    monkeypatch.setattr(jobs, "NodeODMClient", lambda: fake)
    monkeypatch.setattr(jobs, "install_nodeodm_archive", lambda *_args: None)
    async def unexpected_splat(_project):
        raise AssertionError("Disabled splat stage must not be invoked")

    monkeypatch.setattr(jobs, "run_splat", unexpected_splat)

    await jobs.process_project(jobs.decode_project(one("SELECT * FROM projects WHERE id=?", (project_id,))))

    project = one("SELECT * FROM projects WHERE id=?", (project_id,))
    assert project["status"] == "completed"
    assert project["nodeodm_uuid"] == "durable-task"
    assert {"name": "skip-3dmodel", "value": True} in fake.recovery_options


def test_source_file_list_fails_closed_when_validated_data_disappears():
    project_id = "00000000-0000-4000-8000-000000000021"
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            INSERT INTO projects(
              id,name,preset,status,stage,progress,outputs_json,advanced_json,
              inspection_json,created_at,updated_at
            ) VALUES(?,?,?,'queued','Queued',0,?,?,?, ?,?)
            """,
            (
                project_id,
                "Missing source",
                "standard",
                json.dumps({"splat": False}),
                "{}",
                "{}",
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO uploads(
              id,project_id,filename,size,offset,sha256,kind,state,created_at
            ) VALUES(?,?,?,?,?,?,?,'complete',?)
            """,
            (
                "00000000-0000-4000-8000-000000000022",
                project_id,
                "missing.JPG",
                10,
                10,
                "0" * 64,
                "image",
                now,
            ),
        )

    with pytest.raises(RuntimeError, match="disappeared"):
        jobs._source_files(project_id)


def insert_project(project_id: str, status: str) -> None:
    now = utcnow()
    with transaction() as db:
        db.execute(
            """
            INSERT INTO projects(
              id,name,preset,status,stage,progress,outputs_json,advanced_json,
              inspection_json,nodeodm_uuid,splat_job_id,cancel_requested,created_at,updated_at
            ) VALUES(?,?,?,?,?,96,?,?,?,'odm-task','old-splat',1,?,?)
            """,
            (
                project_id,
                "Retry test",
                "standard",
                status,
                "ODM complete — splat failed",
                json.dumps({"splat": True}),
                "{}",
                "{}",
                now,
                now,
            ),
        )


def test_retry_splat_resets_cancellation_without_rerunning_odm(monkeypatch):
    project_id = "00000000-0000-4000-8000-000000000010"
    insert_project(project_id, "partial")
    monkeypatch.setattr(main, "notify_runner", lambda: None)

    project = main.retry_splat(project_id, {})

    assert project["status"] == "splatting"
    assert project["cancel_requested"] is False
    assert project["splat_job_id"] is None
    assert project["nodeodm_uuid"] == "odm-task"


@pytest.mark.asyncio
async def test_worker_routes_splat_recovery_directly_to_splat_stage(monkeypatch):
    project_id = "00000000-0000-4000-8000-000000000011"
    insert_project(project_id, "splatting")
    called = asyncio.Event()

    async def fake_splat(project):
        assert project["nodeodm_uuid"] == "odm-task"
        update_project(project["id"], status="completed")
        called.set()

    async def unexpected_odm(_project):
        raise AssertionError("ODM must not rerun for a splat retry")

    monkeypatch.setattr(jobs, "run_splat", fake_splat)
    monkeypatch.setattr(jobs, "process_project", unexpected_odm)
    jobs._wake = asyncio.Event()
    worker = asyncio.create_task(jobs.worker_loop())
    try:
        await asyncio.wait_for(called.wait(), timeout=2)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        jobs._wake = None

    assert one("SELECT status FROM projects WHERE id=?", (project_id,))["status"] == "completed"
