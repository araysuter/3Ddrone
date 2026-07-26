from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from .artifacts import artifacts_root, install_nodeodm_archive, project_root
from .config import settings
from .db import all_rows, decode_project, emit_event, one, transaction, update_project
from .folder_sharing import publish_folder_share_for_project
from .nodeodm import NodeODMClient, NodeODMError, nodeodm_output_paths
from .presets import PRESETS, resolve_odm_options
from .sharing import publish_existing_share

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


def _option_enabled(options: Any, name: str) -> bool:
    if not isinstance(options, list):
        return False
    return any(
        isinstance(option, dict)
        and option.get("name") == name
        and option.get("value") is True
        for option in options
    )


def terrain_mesh_fallback_options(
    options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        option for option in options if option.get("name") not in {"skip-3dmodel", "use-3dmesh"}
    ] + [{"name": "skip-3dmodel", "value": True}]


def is_recoverable_full_mesh_failure(lines: list[str]) -> bool:
    text = "\n".join(lines).lower()
    mesh_context = any(
        marker in text
        for marker in (
            "screened_poisson_reconstruction",
            "odm_mesh.dirty",
            "odm_mesh_dirty",
            "stages/odm_meshing.py",
        )
    )
    return mesh_context and ("reconstructmesh" in text or "opendm/mesh.py" in text)


def notify_runner() -> None:
    if _wake is not None:
        _wake.set()


def runner_healthy() -> bool:
    return _runner_task is not None and not _runner_task.done()


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
                decoded = decode_project(project)
                if decoded["status"] == "splatting":
                    await run_splat(decoded)
                else:
                    await process_project(decoded)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                update_project(project["id"], status="failed", stage="Failed", error=str(exc))
                publish_folder_share_for_project(project["id"])
                emit_event(project["id"], "state", {"status": "failed", "error": str(exc)})
            continue
        wake.clear()
        try:
            await asyncio.wait_for(wake.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


def _source_files(project_id: str) -> list[Path]:
    source = settings.data_root / "source" / project_id
    files: list[Path] = []
    missing: list[str] = []
    for upload in all_rows(
        "SELECT filename,kind,state FROM uploads WHERE project_id=? ORDER BY created_at", (project_id,)
    ):
        if upload["state"] == "complete" and upload["kind"] in {"image", "video", "support"}:
            path = source / upload["filename"]
            if path.is_file():
                files.append(path)
            else:
                missing.append(upload["filename"])
    if missing:
        raise RuntimeError(
            "Validated source data disappeared before NodeODM upload: "
            + ", ".join(missing[:10])
            + ("…" if len(missing) > 10 else "")
        )
    return files


async def process_project(project: dict[str, Any]) -> None:
    project_id = project["id"]
    if settings.demo_mode:
        await _demo_process(project)
        return
    client = NodeODMClient()
    current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
    if current and current["cancel_requested"]:
        update_project(project_id, status="canceled", stage="Canceled")
        emit_event(project_id, "state", {"status": "canceled"})
        return
    if project.get("nodeodm_uuid"):
        for attempt in range(5):
            try:
                await client.task_info(project["nodeodm_uuid"])
                break
            except NodeODMError as exc:
                message = str(exc).lower()
                if "not found" not in message and "does not exist" not in message:
                    raise
                # The API may have stopped after reserving an upload UUID but before
                # NodeODM committed the task. Use a fresh UUID; NodeODM will age out
                # any incomplete temporary upload without duplicating GPU work.
                update_project(project_id, nodeodm_uuid=None, nodeodm_output_line=0)
                project["nodeodm_uuid"] = None
                project["nodeodm_output_line"] = 0
                break
            except httpx.HTTPError:
                if attempt == 4:
                    raise
                await asyncio.sleep(2**attempt)
    if not project.get("nodeodm_uuid"):
        update_project(project_id, status="processing", stage="Uploading to NodeODM", progress=2)
        emit_event(project_id, "state", {"status": "processing", "stage": "Uploading to NodeODM"})
        options = resolve_odm_options(
            project["preset"], project["outputs"], project["inspection"], project["advanced"]
        )
        task_uuid = str(uuid.uuid4())
        update_project(project_id, nodeodm_uuid=task_uuid, nodeodm_output_line=0)
        try:
            await client.create_task(
                project["name"],
                _source_files(project_id),
                options,
                task_uuid,
                nodeodm_output_paths(project["outputs"]),
            )
        except Exception:
            # Keep the reserved UUID durable. If the commit response was lost,
            # a restart can reconnect to that exact task instead of submitting
            # a second GPU job. A confirmed "not found" is reset above.
            raise
        accepted = {option["name"]: option["value"] for option in options}
        emit_event(
            project_id,
            "log",
            {
                "lines": [
                    "[mapper] NodeODM accepted requested settings: "
                    f"preset={project['preset']}, "
                    f"feature-quality={accepted.get('feature-quality')}, "
                    f"pc-quality={accepted.get('pc-quality')}, "
                    f"rolling-shutter={accepted.get('rolling-shutter', False)}, "
                    f"rolling-shutter-readout={accepted.get('rolling-shutter-readout', 0)}ms, "
                    "outputs="
                    + ",".join(
                        name
                        for name, enabled in project["outputs"].items()
                        if enabled
                    )
                    + "."
                ]
            },
        )
        update_project(project_id, nodeodm_uuid=task_uuid, nodeodm_output_line=0, progress=5)
        project["nodeodm_uuid"] = task_uuid
        project["nodeodm_output_line"] = 0

    task_uuid = project["nodeodm_uuid"]
    last_output = int(project.get("nodeodm_output_line") or 0)
    while True:
        cancel_sent = False
        cancel_failures = 0
        terminal_info: dict[str, Any] | None = None
        async for info in client.wait_for_terminal(task_uuid):
            terminal_info = info
            current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
            if current and current["cancel_requested"] and not cancel_sent:
                try:
                    await client.cancel(task_uuid)
                    cancel_sent = True
                    cancel_failures = 0
                except (httpx.HTTPError, NodeODMError):
                    cancel_failures += 1
                    if cancel_failures >= 10:
                        raise
            code = int(info["status"]["code"])
            if code not in {30, 50}:
                node_progress = float(info.get("progress") or 0)
                if node_progress <= 1:
                    node_progress *= 100
                progress = min(92.0, max(5.0, 5.0 + node_progress * 0.87))
                stage = stage_for_progress(progress)
                update_project(project_id, status="processing", stage=stage, progress=progress)
            try:
                output = await client.output(task_uuid, last_output)
            except Exception:
                output = []
            if output:
                last_output += len(output)
                update_project(project_id, nodeodm_output_line=last_output)
                safe_output = [line[:16_384] for line in output]
                for offset in range(0, len(safe_output), 100):
                    emit_event(project_id, "log", {"lines": safe_output[offset : offset + 100]})
            if code not in {30, 50}:
                emit_event(project_id, "progress", {"progress": progress, "stage": stage})
            if code == 50:
                update_project(project_id, status="canceled", stage="Canceled")
                emit_event(project_id, "state", {"status": "canceled"})
                return

        if terminal_info is None:
            raise RuntimeError("NodeODM stopped polling without a terminal status")
        code = int(terminal_info["status"]["code"])
        if code == 40:
            break
        if code != 30:
            raise RuntimeError(f"NodeODM returned unexpected terminal status {code}")

        try:
            failure_tail = await client.output(task_uuid, max(0, last_output - 300))
        except Exception:
            failure_tail = []
        can_recover_mesh = (
            project["outputs"].get("mesh", False)
            and is_recoverable_full_mesh_failure(failure_tail)
            and not _option_enabled(terminal_info.get("options"), "skip-3dmodel")
        )
        if can_recover_mesh:
            options = resolve_odm_options(
                project["preset"],
                project["outputs"],
                project["inspection"],
                project["advanced"],
            )
            fallback_options = terrain_mesh_fallback_options(options)
            recovery_message = (
                "[mapper] Full 3D mesh cleanup failed. Retrying the same durable ODM task "
                "with its 2.5D terrain mesh; completed reconstruction work will be reused."
            )
            emit_event(project_id, "log", {"lines": [recovery_message]})
            update_project(
                project_id,
                status="processing",
                stage="Recovering with 2.5D terrain mesh",
                progress=50,
                nodeodm_output_line=0,
                error=None,
            )
            emit_event(
                project_id,
                "state",
                {
                    "status": "processing",
                    "stage": "Recovering with 2.5D terrain mesh",
                    "progress": 50,
                },
            )
            await client.restart(task_uuid, fallback_options)
            last_output = 0
            continue

        message = terminal_info["status"].get("errorMessage") or "NodeODM processing failed"
        if is_recoverable_full_mesh_failure(failure_tail):
            message = (
                "ODM failed during mesh generation, including the automatic 2.5D terrain-mesh "
                f"recovery: {message}"
            )
            failed_stage = "ODM failed — Meshing and texturing"
            failed_progress = 64
        else:
            failed_stage = "ODM processing failed"
            failed_progress = min(91, float(one(
                "SELECT progress FROM projects WHERE id=?", (project_id,)
            )["progress"]))
        update_project(
            project_id,
            status="failed",
            stage=failed_stage,
            progress=failed_progress,
            error=message,
        )
        publish_folder_share_for_project(project_id)
        emit_event(
            project_id,
            "state",
            {
                "status": "failed",
                "stage": failed_stage,
                "progress": failed_progress,
                "error": message,
            },
        )
        return

    current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
    if current and current["cancel_requested"]:
        update_project(project_id, status="canceled", stage="Canceled")
        emit_event(project_id, "state", {"status": "canceled"})
        return

    archive = project_root(project_id) / "nodeodm-all.zip"
    await client.download_all(task_uuid, archive)
    install_nodeodm_archive(project_id, archive)
    archive.unlink(missing_ok=True)
    emit_event(project_id, "artifacts", {"stage": "odm", "available": True})
    if project["outputs"].get("splat"):
        await run_splat(project)
    else:
        update_project(project_id, status="completed", stage="Completed", progress=100)
        publish_existing_share(project_id)
        publish_folder_share_for_project(project_id)
        emit_event(project_id, "state", {"status": "completed", "progress": 100})


async def run_splat(project: dict[str, Any]) -> None:
    project_id = project["id"]
    current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
    if current and current["cancel_requested"]:
        update_project(project_id, status="canceled", stage="Canceled")
        emit_event(project_id, "state", {"status": "canceled"})
        return
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
            for attempt in range(10):
                try:
                    response = await client.post(
                        f"{settings.splat_url}/jobs",
                        json=payload,
                        headers={"X-Internal-Token": settings.internal_token},
                    )
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 9:
                        raise
                    await asyncio.sleep(min(30, 2**attempt))
            job = response.json()
            update_project(project_id, splat_job_id=job["id"])
            last_signature: tuple[Any, ...] | None = None
            cancel_sent = False
            poll_failures = 0
            while True:
                try:
                    current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
                    if current and current["cancel_requested"] and not cancel_sent:
                        cancel_response = await client.post(
                            f"{settings.splat_url}/jobs/{job['id']}/cancel",
                            headers={"X-Internal-Token": settings.internal_token},
                        )
                        cancel_response.raise_for_status()
                        cancel_sent = True
                    status = await client.get(
                        f"{settings.splat_url}/jobs/{job['id']}",
                        headers={"X-Internal-Token": settings.internal_token},
                    )
                    status.raise_for_status()
                    poll_failures = 0
                except httpx.HTTPError:
                    poll_failures += 1
                    if poll_failures >= 10:
                        raise
                    await asyncio.sleep(min(30, 2 ** (poll_failures - 1)))
                    continue
                details = status.json()
                signature = (
                    details.get("status"),
                    details.get("progress"),
                    details.get("message"),
                    details.get("error"),
                    tuple((details.get("log") or [])[-5:]),
                )
                if signature != last_signature:
                    emit_event(
                        project_id,
                        "splat",
                        {
                            "status": details.get("status"),
                            "progress": details.get("progress"),
                            "message": details.get("message"),
                            "error": details.get("error"),
                            "lines": (details.get("log") or [])[-5:],
                        },
                    )
                    last_signature = signature
                if details["status"] == "completed":
                    break
                if details["status"] == "canceled":
                    update_project(project_id, status="canceled", stage="Canceled", error=None)
                    emit_event(project_id, "state", {"status": "canceled"})
                    return
                if details["status"] == "failed":
                    raise RuntimeError(details.get("error") or "Gaussian splat failed")
                await asyncio.sleep(3)
        splat_output = artifacts_root(project_id) / "splat"
        missing_outputs = [
            name
            for name in ("point_cloud.ply", "scene.spz", "scene_transform.json")
            if not (splat_output / name).is_file()
        ]
        if missing_outputs:
            raise RuntimeError(
                "Gaussian splat worker reported completion without "
                + ", ".join(missing_outputs)
            )
        update_project(project_id, status="completed", stage="Completed", progress=100, error=None)
        publish_existing_share(project_id)
        publish_folder_share_for_project(project_id)
        emit_event(project_id, "state", {"status": "completed", "progress": 100})
    except Exception as exc:
        current = one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))
        if current and current["cancel_requested"]:
            update_project(project_id, status="canceled", stage="Canceled", error=None)
            emit_event(project_id, "state", {"status": "canceled"})
        else:
            update_project(
                project_id,
                status="partial",
                stage="ODM complete — splat failed",
                progress=96,
                error=str(exc),
            )
            publish_folder_share_for_project(project_id)
            emit_event(project_id, "state", {"status": "partial", "error": str(exc)})


async def _demo_process(project: dict[str, Any]) -> None:
    project_id = project["id"]
    for progress in (4, 12, 21, 34, 48, 61, 74, 86, 93):
        if one("SELECT cancel_requested FROM projects WHERE id=?", (project_id,))["cancel_requested"]:
            update_project(project_id, status="canceled", stage="Canceled")
            emit_event(project_id, "state", {"status": "canceled"})
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
    publish_existing_share(project_id)
    publish_folder_share_for_project(project_id)
    emit_event(project_id, "state", {"status": "completed", "progress": 100})
