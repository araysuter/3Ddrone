from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

INTERNAL_TOKEN = os.environ.get("MAPPER_INTERNAL_TOKEN", "")
DATA_ROOT = Path(os.environ.get("MAPPER_DATA_ROOT", "/data")).resolve()
STATE_ROOT = Path(os.environ.get("SPLAT_STATE_ROOT", str(DATA_ROOT / "splat"))).resolve()
if STATE_ROOT == DATA_ROOT or not STATE_ROOT.is_relative_to(DATA_ROOT):
    raise RuntimeError("SPLAT_STATE_ROOT must be a child of MAPPER_DATA_ROOT")
DRY_RUN = os.environ.get("SPLAT_DRY_RUN", "false").lower() == "true"
PROCESS_TERMINATE_SECONDS = float(os.environ.get("SPLAT_PROCESS_TERMINATE_SECONDS", "10"))
if not 0.1 <= PROCESS_TERMINATE_SECONDS <= 120:
    raise RuntimeError("SPLAT_PROCESS_TERMINATE_SECONDS must be between 0.1 and 120")
jobs: dict[str, dict[str, Any]] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
runner: asyncio.Task | None = None
active_processes: dict[str, asyncio.subprocess.Process] = {}
state_lock = threading.RLock()


class JobCanceled(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def authorize(x_internal_token: str | None) -> None:
    if (
        not INTERNAL_TOKEN
        or not x_internal_token
        or not secrets.compare_digest(x_internal_token, INTERNAL_TOKEN)
    ):
        raise HTTPException(status_code=403, detail="Invalid internal token")


class JobRequest(BaseModel):
    project_id: str
    dataset: str
    source: str
    output: str
    downscale: int = Field(ge=1, le=4)
    steps: int = Field(ge=100, le=100000)
    quality_culling: bool = False


def validate_project_id(project_id: str) -> str:
    try:
        parsed = uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid project id") from exc
    if str(parsed) != project_id:
        raise HTTPException(status_code=422, detail="Project id must use canonical UUID form")
    return project_id


def validate_job_paths(payload: JobRequest | dict[str, Any]) -> tuple[Path, Path, Path]:
    project_id = validate_project_id(
        payload.project_id if isinstance(payload, JobRequest) else str(payload["project_id"])
    )
    dataset_value = payload.dataset if isinstance(payload, JobRequest) else str(payload["dataset"])
    source_value = payload.source if isinstance(payload, JobRequest) else str(payload["source"])
    output_value = payload.output if isinstance(payload, JobRequest) else str(payload["output"])
    expected_dataset = (
        DATA_ROOT / "metadata" / "projects" / project_id / "artifacts"
    ).resolve()
    expected_source = (DATA_ROOT / "source" / project_id).resolve()
    expected_output = (expected_dataset / "splat").resolve()
    actual = (
        Path(dataset_value).resolve(),
        Path(source_value).resolve(),
        Path(output_value).resolve(),
    )
    expected = (expected_dataset, expected_source, expected_output)
    if any(path == DATA_ROOT or not path.is_relative_to(DATA_ROOT) for path in expected):
        raise HTTPException(status_code=422, detail="Project data resolves outside the data root")
    if actual != expected:
        raise HTTPException(status_code=422, detail="Job paths do not match the project data layout")
    return actual


def state_path(job_id: str) -> Path:
    return STATE_ROOT / "jobs" / f"{job_id}.json"


def save(job: dict[str, Any]) -> None:
    validate_project_id(str(job["id"]))
    jobs_root = STATE_ROOT / "jobs"
    with state_lock:
        jobs_root.mkdir(parents=True, exist_ok=True)
        destination = state_path(job["id"])
        temp = destination.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as output:
            json.dump(job, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(destination)
        directory_fd = os.open(jobs_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def load_jobs() -> None:
    STATE_ROOT.joinpath("jobs").mkdir(parents=True, exist_ok=True)
    for path in STATE_ROOT.joinpath("jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text())
            validate_project_id(path.stem)
            validate_project_id(str(job["id"]))
            if job["id"] != path.stem:
                continue
            validate_job_paths(job)
            if job["status"] == "running":
                if job.get("cancel_requested"):
                    job["status"] = "canceled"
                    job["message"] = "Canceled during worker restart"
                else:
                    job["status"] = "queued"
                    job["message"] = "Recovered after worker restart"
                job["updated_at"] = utcnow()
                save(job)
            jobs[job["id"]] = job
        except Exception:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runner
    load_jobs()
    runner = asyncio.create_task(run_queue())
    for job in jobs.values():
        if job["status"] == "queued":
            queue.put_nowait(job["id"])
    yield
    runner.cancel()
    try:
        await runner
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Mapper Splat Worker",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health")
def health() -> dict[str, Any]:
    if (
        not INTERNAL_TOKEN
        or len(INTERNAL_TOKEN) < 32
        or INTERNAL_TOKEN.startswith("replace-with-")
    ):
        raise HTTPException(status_code=503, detail="Internal worker token is not configured")
    if runner is None or runner.done():
        raise HTTPException(status_code=503, detail="Splat job runner is unavailable")
    try:
        jobs_root = STATE_ROOT / "jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=jobs_root):
            pass
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Splat state storage is not writable") from exc
    if DRY_RUN:
        return {"ok": True, "dry_run": True, "cuda_visible_devices": "none"}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader", "--id=0"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="GPU 0 is not available") from exc
    return {
        "ok": True,
        "dry_run": False,
        "gpu": result.stdout.strip(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "all"),
    }


@app.get("/metrics")
def gpu_metrics(x_internal_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_internal_token)
    if DRY_RUN:
        return {
            "available": False,
            "name": None,
            "utilization_percent": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
        }
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
                "--id=0",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        name, utilization, used, total = [
            value.strip() for value in result.stdout.splitlines()[0].split(",")
        ]
        return {
            "available": True,
            "name": name,
            "utilization_percent": float(utilization),
            "memory_used_mb": float(used),
            "memory_total_mb": float(total),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail="GPU metrics are unavailable") from exc


@app.post("/jobs", status_code=202)
async def create_job(
    payload: JobRequest, x_internal_token: str | None = Header(default=None)
) -> dict[str, Any]:
    authorize(x_internal_token)
    validate_job_paths(payload)
    for existing in jobs.values():
        if existing["project_id"] == payload.project_id and existing["status"] in {
            "queued",
            "running",
            "completed",
        }:
            return existing
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        **payload.model_dump(),
        "status": "queued",
        "progress": 0,
        "message": "Waiting for GPU",
        "error": None,
        "log": [],
        "log_count": 0,
        "cancel_requested": False,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    jobs[job_id] = job
    save(job)
    queue.put_nowait(job_id)
    return job


@app.get("/jobs/{job_id}")
async def get_job(
    job_id: str, x_internal_token: str | None = Header(default=None)
) -> dict[str, Any]:
    authorize(x_internal_token)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str, x_internal_token: str | None = Header(default=None)
) -> dict[str, Any]:
    authorize(x_internal_token)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] in {"completed", "failed", "canceled"}:
        return job
    job["cancel_requested"] = True
    if job["status"] == "queued":
        job["status"] = "canceled"
        job["message"] = "Gaussian splat canceled"
    else:
        job["message"] = "Canceling Gaussian splat"
        process = active_processes.get(job_id)
        if process and process.returncode is None:
            asyncio.create_task(stop_process(process))
    job["updated_at"] = utcnow()
    save(job)
    return job


@app.delete("/projects/{project_id}", status_code=204, response_class=Response)
async def delete_project_jobs(
    project_id: str, x_internal_token: str | None = Header(default=None)
) -> Response:
    authorize(x_internal_token)
    validate_project_id(project_id)
    matching = [job for job in jobs.values() if job["project_id"] == project_id]
    if any(job["status"] in {"queued", "running"} for job in matching):
        raise HTTPException(status_code=409, detail="Project still has an active splat job")
    for job in matching:
        jobs.pop(job["id"], None)
        state_path(job["id"]).unlink(missing_ok=True)
    work = STATE_ROOT / "work" / project_id
    if work.is_dir():
        shutil.rmtree(work)
    return Response(status_code=204)


async def run_queue() -> None:
    while True:
        job_id = await queue.get()
        job = jobs.get(job_id)
        if job is None:
            queue.task_done()
            continue
        if job["status"] != "queued":
            queue.task_done()
            continue
        try:
            await execute(job)
        except JobCanceled:
            job["status"] = "canceled"
            job["error"] = None
            job["message"] = "Gaussian splat canceled"
            job["updated_at"] = utcnow()
            save(job)
        except asyncio.CancelledError:
            job["status"] = "queued"
            job["message"] = "Paused by worker shutdown"
            save(job)
            raise
        except Exception as exc:
            if job.get("cancel_requested"):
                job["status"] = "canceled"
                job["error"] = None
                job["message"] = "Gaussian splat canceled"
            else:
                job["status"] = "failed"
                job["error"] = str(exc)
                job["message"] = "Gaussian splat failed"
            job["updated_at"] = utcnow()
            save(job)
        finally:
            queue.task_done()


def set_state(job: dict[str, Any], progress: float, message: str) -> None:
    job["progress"] = progress
    job["message"] = message
    job["updated_at"] = utcnow()
    save(job)


def raise_if_canceled(job: dict[str, Any]) -> None:
    if job.get("cancel_requested"):
        raise JobCanceled("Gaussian splat canceled")


def fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(payload, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fsync_directory(path.parent)


def publish_splat_output(staging: Path, destination: Path, job_id: str) -> None:
    required = ("point_cloud.ply", "scene.spz", "scene_transform.json")
    missing = [name for name in required if not (staging / name).is_file()]
    if missing:
        raise RuntimeError("Splat export is incomplete; missing " + ", ".join(missing))
    for name in required:
        with (staging / name).open("rb") as artifact:
            os.fsync(artifact.fileno())
    fsync_directory(staging)
    previous = destination.parent / f".splat-{job_id}.old"
    if previous.exists():
        shutil.rmtree(previous)
    if destination.exists():
        destination.replace(previous)
    try:
        staging.replace(destination)
        fsync_directory(destination.parent)
    except Exception:
        if previous.exists() and not destination.exists():
            previous.replace(destination)
        raise
    finally:
        if previous.exists():
            shutil.rmtree(previous)


async def execute(job: dict[str, Any]) -> None:
    validate_job_paths(job)
    raise_if_canceled(job)
    job["status"] = "running"
    set_state(job, 2, "Preparing OpenSfM reconstruction")
    output = Path(job["output"]).resolve()
    dataset = Path(job["dataset"]).resolve()
    source = Path(job["source"]).resolve()
    processed_images = dataset / "images"
    if not processed_images.is_dir():
        processed_images = source
    output.parent.mkdir(parents=True, exist_ok=True)
    interrupted_previous = sorted(
        output.parent.glob(".splat-*.old"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not output.exists() and interrupted_previous:
        interrupted_previous[0].replace(output)
        fsync_directory(output.parent)
        interrupted_previous = interrupted_previous[1:]
    for stale in interrupted_previous:
        if stale.is_symlink() or stale.is_file():
            stale.unlink()
        elif stale.is_dir():
            shutil.rmtree(stale)
    for stale in output.parent.glob(".splat-*.tmp"):
        if stale.is_symlink() or stale.is_file():
            stale.unlink()
        elif stale.is_dir():
            shutil.rmtree(stale)
    staging_output = output.parent / f".splat-{job['id']}.tmp"
    staging_output.mkdir()
    if DRY_RUN:
        for progress, message in (
            (18, "Exporting binary COLMAP cameras"),
            (35, "Initializing Splatfacto"),
            (72, "Training memory-safe Splatfacto"),
            (92, "Exporting PLY and SPZ"),
        ):
            raise_if_canceled(job)
            set_state(job, progress, message)
            await asyncio.sleep(0.35)
        (staging_output / "point_cloud.ply").write_text(
            "ply\nformat ascii 1.0\nelement vertex 0\nend_header\n"
        )
        (staging_output / "scene.spz").write_bytes(b"SPZ dry-run placeholder")
        write_json_atomic(
            staging_output / "scene_transform.json",
            {"version": 1, "coordinate_system": "ODM local", "transform": None},
        )
        publish_splat_output(staging_output, output, job["id"])
        job["status"] = "completed"
        set_state(job, 100, "Gaussian splat completed")
        return

    opensfm = dataset / "opensfm"
    if not (opensfm / "reconstruction.json").is_file():
        raise RuntimeError("OpenSfM reconstruction.json was not included in the ODM outputs")
    work = STATE_ROOT / "work" / job["project_id"]
    work.mkdir(parents=True, exist_ok=True)
    osfm_dataset = work / "dataset"
    osfm_dataset.mkdir(parents=True, exist_ok=True)
    for item in opensfm.iterdir():
        target = osfm_dataset / item.name
        if target.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)
    images_link = osfm_dataset / "images"
    if not images_link.exists():
        images_link.symlink_to(processed_images, target_is_directory=True)
    image_list = osfm_dataset / "image_list.txt"
    if image_list.is_file():
        image_names = [
            Path(line.strip()).name
            for line in image_list.read_text().splitlines()
            if line.strip()
        ]
        missing_images = [name for name in image_names if not (processed_images / name).is_file()]
        if missing_images:
            raise RuntimeError(
                "Packaged ODM images are incomplete; missing "
                + ", ".join(missing_images[:10])
            )
        image_list.write_text(
            "".join(f"{processed_images / name}\n" for name in image_names)
        )

    colmap_export = osfm_dataset / "colmap_export"
    colmap_files = ("cameras.bin", "images.bin", "points3D.bin")
    colmap_export_available = all(
        (colmap_export / name).is_file() for name in colmap_files
    )
    if not colmap_export_available:
        raise_if_canceled(job)
        set_state(job, 12, "Exporting OpenSfM cameras to binary COLMAP")
        colmap_warning: str | None = None
        try:
            await run_command(
                job,
                [
                    "/code/SuperBuild/install/bin/opensfm/bin/opensfm",
                    "export_colmap",
                    str(osfm_dataset),
                    "--binary",
                ],
                progress_start=12,
                progress_end=18,
            )
            colmap_export_available = all(
                (colmap_export / name).is_file() for name in colmap_files
            )
            if not colmap_export_available:
                missing = [
                    name for name in colmap_files if not (colmap_export / name).is_file()
                ]
                colmap_warning = (
                    "OpenSfM completed without all binary interchange files; missing "
                    + ", ".join(missing)
                )
        except JobCanceled:
            raise
        except Exception as exc:
            # Nerfstudio does not consume this export. Its ODM data parser reads
            # the calibrated OpenSfM reconstruction below, so an exporter bug
            # must not discard an otherwise valid ODM reconstruction.
            colmap_warning = str(exc)
        if not colmap_export_available:
            if colmap_export.exists():
                shutil.rmtree(colmap_export)
            warning = (
                "Optional binary COLMAP interchange export failed; continuing "
                f"with Nerfstudio's ODM converter. {colmap_warning or 'Unknown exporter error'}"
            )
            job["log"] = (job["log"] + [warning])[-200:]
            job["log_count"] = int(job.get("log_count") or 0) + 1
            set_state(job, 18, "COLMAP interchange unavailable; continuing with ODM cameras")

    # OpenSfM's Brown camera exports as COLMAP FULL_OPENCV, which Nerfstudio
    # 1.1.5 cannot parse. Use Nerfstudio's supported ODM converter for training.
    # When OpenSfM can also produce the native binary COLMAP files they remain
    # in the durable work directory as an optional interchange product.
    odm_dataset = work / "odm_dataset"
    odm_dataset.mkdir(parents=True, exist_ok=True)
    odm_inputs = {
        "cameras.json": dataset / "cameras.json",
        "odm_report": dataset / "odm_report",
        "opensfm": osfm_dataset,
        "images": processed_images,
    }
    missing_odm = [name for name, path in odm_inputs.items() if not path.exists()]
    if missing_odm:
        raise RuntimeError(
            "ODM-to-Nerfstudio conversion inputs are incomplete; missing " + ", ".join(missing_odm)
        )
    for name, source_path in odm_inputs.items():
        link = odm_dataset / name
        if not link.exists():
            link.symlink_to(source_path, target_is_directory=source_path.is_dir())

    training_dataset = work / "nerfstudio_dataset"
    transforms = training_dataset / "transforms.json"
    if not transforms.is_file():
        raise_if_canceled(job)
        set_state(job, 19, "Converting ODM cameras for Nerfstudio")
        await run_command(
            job,
            [
                "ns-process-data",
                "odm",
                "--data",
                str(odm_dataset),
                "--output-dir",
                str(training_dataset),
                "--num-downscales",
                "0",
                "--max-dataset-size",
                "-1",
            ],
            progress_start=19,
            progress_end=24,
        )
    if not transforms.is_file():
        raise RuntimeError("Nerfstudio's ODM converter did not produce transforms.json")

    training_root = work / "nerfstudio"
    checkpoints = sorted(
        [path for path in training_root.rglob("nerfstudio_models") if list(path.glob("*.ckpt"))],
        key=lambda path: path.stat().st_mtime,
    )
    set_state(
        job,
        30 if checkpoints else 22,
        "Resuming Splatfacto from the latest checkpoint"
        if checkpoints
        else "Initializing memory-safe Splatfacto",
    )
    scale = 1 / int(job["downscale"])
    command = [
        "ns-train",
        "splatfacto",
        "--data",
        str(training_dataset),
        "--output-dir",
        str(training_root),
        "--experiment-name",
        "odm-splat",
        "--max-num-iterations",
        str(job["steps"]),
        "--pipeline.datamanager.camera-res-scale-factor",
        str(scale),
        "--pipeline.datamanager.cache-images",
        "cpu",
        # TensorBoard is retained for durable training logs, but the mapper
        # never consumes validation renders. Disable those evaluation-only
        # passes so every scheduled GPU render advances the trained model.
        "--steps-per-eval-batch",
        "0",
        "--steps-per-eval-image",
        "0",
        "--steps-per-eval-all-images",
        "0",
        "--vis",
        "tensorboard",
    ]
    if checkpoints:
        command.extend(["--load-dir", str(checkpoints[-1])])
    if job["quality_culling"]:
        command.extend(["--pipeline.model.cull-alpha-thresh", "0.01"])
    raise_if_canceled(job)
    await run_command(job, command, progress_start=25, progress_end=88, training_steps=job["steps"])

    configs = sorted(training_root.rglob("config.yml"), key=lambda path: path.stat().st_mtime)
    if not configs:
        raise RuntimeError("Nerfstudio training completed without a config checkpoint")
    config_path = configs[-1]
    raise_if_canceled(job)
    set_state(job, 90, "Exporting Gaussian PLY")
    await run_command(
        job,
        [
            "ns-export",
            "gaussian-splat",
            "--load-config",
            str(config_path),
            "--output-dir",
            str(staging_output),
        ],
        progress_start=90,
        progress_end=96,
    )
    ply_candidates = sorted(staging_output.glob("*.ply"), key=lambda path: path.stat().st_mtime)
    if not ply_candidates:
        raise RuntimeError("Nerfstudio did not export a Gaussian PLY")
    ply = ply_candidates[0]
    canonical_ply = staging_output / "point_cloud.ply"
    if ply != canonical_ply:
        ply.replace(canonical_ply)

    set_state(job, 96, "Compressing web-ready SPZ")
    raise_if_canceled(job)
    compress_command = ["node", "/opt/spark/scripts/compress-to-spz.js"]
    if job["quality_culling"]:
        compress_command.extend(["--filter-opacity", "0.01"])
    compress_command.append(str(canonical_ply))
    await run_command(
        job,
        compress_command,
        progress_start=96,
        progress_end=99,
    )
    generated_spz = canonical_ply.with_suffix(".spz")
    if generated_spz.is_file():
        generated_spz.replace(staging_output / "scene.spz")
    else:
        raise RuntimeError("Spark completed without emitting the required SPZ file")

    transform_candidates = sorted(
        training_root.rglob("dataparser_transforms.json"),
        key=lambda path: path.stat().st_mtime,
    )
    transform = json.loads(transform_candidates[-1].read_text()) if transform_candidates else None
    write_json_atomic(
        staging_output / "scene_transform.json",
        {
            "version": 1,
            "source_coordinate_system": "ODM/OpenSfM local reconstruction",
            "odm_georeferencing": "../odm_georeferencing",
            "nerfstudio_dataparser_transform": transform,
            "native_colmap_export": {
                "available": colmap_export_available,
                "path": str(colmap_export) if colmap_export_available else None,
            },
            "note": "Apply this normalization metadata when relating the splat to ODM projected coordinates.",
        },
    )
    publish_splat_output(staging_output, output, job["id"])
    job["status"] = "completed"
    set_state(job, 100, "Gaussian splat completed")


async def run_command(
    job: dict[str, Any],
    command: list[str],
    *,
    cwd: Path | None = None,
    progress_start: float,
    progress_end: float,
    training_steps: int | None = None,
) -> None:
    raise_if_canceled(job)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        start_new_session=True,
    )
    active_processes[job["id"]] = process
    assert process.stdout
    command_output_tail: list[str] = []

    async def read_output() -> None:
        async for raw in process.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            command_output_tail.append(line)
            del command_output_tail[:-12]
            job["log"] = (job["log"] + [line])[-200:]
            job["log_count"] = int(job.get("log_count") or 0) + 1
            if training_steps:
                match = re.search(r"(?:step|iteration)\D+(\d+)", line, re.IGNORECASE)
                if match:
                    fraction = min(1.0, int(match.group(1)) / training_steps)
                    job["progress"] = progress_start + (progress_end - progress_start) * fraction
            job["updated_at"] = utcnow()
            save(job)

    reader_task = asyncio.create_task(read_output())
    wait_task = asyncio.create_task(process.wait())
    try:
        while not wait_task.done():
            if job.get("cancel_requested"):
                await stop_process(process)
                break
            await asyncio.wait({wait_task}, timeout=0.5)
            if reader_task.done() and not reader_task.cancelled():
                error = reader_task.exception()
                if error is not None:
                    await stop_process(process)
                    raise error
        code = await wait_task
        try:
            await asyncio.wait_for(reader_task, timeout=3)
        except asyncio.TimeoutError:
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
    except asyncio.CancelledError:
        await stop_process(process)
        reader_task.cancel()
        wait_task.cancel()
        await asyncio.gather(reader_task, wait_task, return_exceptions=True)
        raise
    finally:
        active_processes.pop(job["id"], None)
    raise_if_canceled(job)
    if code:
        detail = " | ".join(line[:500] for line in command_output_tail)
        suffix = f". Last output: {detail}" if detail else ""
        raise RuntimeError(
            f"Command failed with exit code {code}: {' '.join(command[:3])}{suffix}"
        )
    set_state(job, progress_end, job["message"])


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=PROCESS_TERMINATE_SECONDS)
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()
