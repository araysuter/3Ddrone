from __future__ import annotations

import asyncio
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .artifacts import artifacts_root, install_nodeodm_archive, project_root
from .config import settings
from .db import all_rows, decode_project, emit_event, one, transaction, update_project
from .nodeodm import NodeODMClient
from .presets import PRESETS, resolve_odm_options

_runner_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None

STAGES = [
    (0, "Queued"),
    (5, "Uploading to NodeODM"),
    (12, "Dataset validation"),
    (18, "Feature extraction"),
    (30, "Feature matching"),
    (40, "Camera reconstruction"),
    (50, "Dense point cloud"),
    (65, "Meshing and texturing"),
    (76, "Georeferencing"),
    (84, "DSM, DTM and orthomosaic"),
    (92, "Report and packaging"),
    (96, "Gaussian splat"),
    (100, "Completed"),
]


def stage_for_progress(progress: float) -> str:
    stage = STAGES[0][1]
    for threshold, label in STAGES:
        if progress >= threshold:
            stage = label
    return stage


def notify_runner() -> None:
    if _wake is not None:
        _wake.set()


def start_runner() -> None:
    global _runner_task, _wake
    if _runner_task is None or _runner_task.done():
        _wake = asyncio.Event()
        _runner_task = asyncio.create_task(worker_loop(), name="mapper-job-runner")


async def stop_runner() -> None:
    global _runner_task, _wake
    if _runner_task:
        _runner_task.cancel()
        try:
            await _runner_task
        except asyncio.CancelledError:
            pass
        _runner_task = None
        _wake = None


async def worker_loop() -> None:
    wake = _wake
    if wake is None:
        raise RuntimeError("Job runner wake event was not initialized")
    while True:
        project = one(
            """
            SELECT * FROM projects
            WHERE status IN ('queued','processing','splatting')
            ORDER BY created_at LIMIT 1
            """
        )
        if project:
            try:
                await process_project(decode_project(project))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                update_project(project["id"], status="failed", stage="Failed", error=str(exc))
                emit_event(project["id"], "state", {"status": "failed", "error": str(exc)})
            continue
        wake.clear()
        try:
            await asyncio.wait_for(wake.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


def _source_files(project_id: str) -> list[Path]:
    source = settings.data_root / "source" / project_id
    files = []
    for upload in all_rows(
        "SELECT filename,kind,state FROM uploads WHERE project_id=? ORDER BY created_at", (project_id,)
    ):
        if upload["state"] == "complete" and upload["kind"] in {"image", "video", "support"}:
            files.append(source / upload["filename"])
    return [path for path in files if path.is_file()]


async def process_project(project: dict[str, Any]) -> None:
    project_id = project["id"]
    if settings.demo_mode:
        await _demo_process(project)
        return
    client = NodeODMClient()
    if not project.get("nodeodm_uuid"):
        update_project(project_id, status="processing", stage="Uploading to NodeODM", progress=2)
        emit_event(project_id, "state", {"status": "processing", "stage": "Uploading to NodeODM"})
        options = resolve_odm_options(
            project["preset"], project["outputs"], project["inspection"], project["advanced"]
        )
        task_uuid = await client.create_task(project["name"], _source_files(project_id), options)
        update_project(project_id, nodeodm_uuid=task_uuid, progress=5)
        project["nodeodm_uuid"] = task_uuid

    task_uuid = project["nodeodm_uuid"]
    last_output = 0
    async for info in client.wait_for_terminal(task_uuid):
        current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
        if current and current["cancel_requested"]:
            await client.cancel(task_uuid)
        node_progress = float(info.get("progress") or 0)
        if node_progress <= 1:
            node_progress *= 100
        progress = min(92.0, max(5.0, 5.0 + node_progress * 0.87))
        stage = stage_for_progress(progress)
        update_project(project_id, status="processing", stage=stage, progress=progress)
        output = info.get("output") or []
        if output:
            emit_event(project_id, "log", {"lines": output[-50:]})
        emit_event(project_id, "progress", {"progress": progress, "stage": stage})
        code = int(info["status"]["code"])
        if code == 50:
            update_project(project_id, status="canceled", stage="Canceled")
            emit_event(project_id, "state", {"status": "canceled"})
            return
        if code == 30:
            message = info["status"].get("errorMessage") or "NodeODM processing failed"
            raise RuntimeError(message)
        if code == 40:
            break

    archive = project_root(project_id) / "nodeodm-all.zip"
    await client.download_all(task_uuid, archive)
    install_nodeodm_archive(project_id, archive)
    archive.unlink(missing_ok=True)
    emit_event(project_id, "artifacts", {"stage": "odm", "available": True})
    if project["outputs"].get("splat"):
        await run_splat(project)
    else:
        update_project(project_id, status="completed", stage="Completed", progress=100)
        emit_event(project_id, "state", {"status": "completed", "progress": 100})


async def run_splat(project: dict[str, Any]) -> None:
    project_id = project["id"]
    update_project(project_id, status="splatting", stage="Gaussian splat", progress=94)
    emit_event(project_id, "state", {"status": "splatting", "stage": "Gaussian splat"})
    payload = {
        "project_id": project_id,
        "dataset": str(artifacts_root(project_id)),
        "source": str(settings.data_root / "source" / project_id),
        "output": str(artifacts_root(project_id) / "splat"),
        **PRESETS[project["preset"]]["splat"],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=None)) as client:
            response = await client.post(
                f"{settings.splat_url}/jobs",
                json=payload,
                headers={"X-Internal-Token": settings.internal_token},
            )
            response.raise_for_status()
            job = response.json()
            update_project(project_id, splat_job_id=job["id"])
            while True:
                status = await client.get(
                    f"{settings.splat_url}/jobs/{job['id']}",
                    headers={"X-Internal-Token": settings.internal_token},
                )
                status.raise_for_status()
                details = status.json()
                emit_event(project_id, "splat", details)
                if details["status"] == "completed":
                    break
                if details["status"] == "failed":
                    raise RuntimeError(details.get("error") or "Gaussian splat failed")
                await asyncio.sleep(3)
        update_project(project_id, status="completed", stage="Completed", progress=100, error=None)
        emit_event(project_id, "state", {"status": "completed", "progress": 100})
    except Exception as exc:
        update_project(
            project_id,
            status="partial",
            stage="ODM complete — splat failed",
            progress=96,
            error=str(exc),
        )
        emit_event(project_id, "state", {"status": "partial", "error": str(exc)})


async def _demo_process(project: dict[str, Any]) -> None:
    project_id = project["id"]
    for progress in (4, 12, 21, 34, 48, 61, 74, 86, 93):
        if one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))["cancel_requested"]:
            update_project(project_id, status="canceled", stage="Canceled")
            return
        stage = stage_for_progress(progress)
        update_project(project_id, status="processing", stage=stage, progress=progress)
        emit_event(
            project_id,
            "log",
            {"lines": [f"[demo] {stage.lower()} completed at {progress:.0f}%"]},
        )
        emit_event(project_id, "progress", {"progress": progress, "stage": stage})
        await asyncio.sleep(0.35)
    if project["outputs"].get("splat"):
        update_project(project_id, status="splatting", stage="Gaussian splat", progress=96)
        await asyncio.sleep(0.7)
    update_project(project_id, status="completed", stage="Completed", progress=100)
    emit_event(project_id, "state", {"status": "completed", "progress": 100})
