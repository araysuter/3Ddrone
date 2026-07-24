from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import jobs, main
from app.db import one, transaction, update_project, utcnow
from app.nodeodm import NodeODMClient, NodeODMError


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
