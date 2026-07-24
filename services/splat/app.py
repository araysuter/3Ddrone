from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

INTERNAL_TOKEN = os.environ.get("MAPPER_INTERNAL_TOKEN", "")
STATE_ROOT = Path(os.environ.get("SPLAT_STATE_ROOT", "/data/splat"))
DRY_RUN = os.environ.get("SPLAT_DRY_RUN", "false").lower() == "true"
jobs: dict[str, dict[str, Any]] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
runner: asyncio.Task | None = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def authorize(x_internal_token: str | None) -> None:
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")


class JobRequest(BaseModel):
    project_id: str
    dataset: str
    source: str
    output: str
    downscale: int = Field(ge=1, le=4)
    steps: int = Field(ge=100, le=100000)
    quality_culling: bool = False


def state_path(job_id: str) -> Path:
    return STATE_ROOT / "jobs" / f"{job_id}.json"


def save(job: dict[str, Any]) -> None:
    STATE_ROOT.joinpath("jobs").mkdir(parents=True, exist_ok=True)
    temp = state_path(job["id"]).with_suffix(".tmp")
    temp.write_text(json.dumps(job, indent=2))
    temp.replace(state_path(job["id"]))


def load_jobs() -> None:
    STATE_ROOT.joinpath("jobs").mkdir(parents=True, exist_ok=True)
    for path in STATE_ROOT.joinpath("jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text())
            if job["status"] == "running":
                job["status"] = "queued"
                job["message"] = "Recovered after worker restart"
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


app = FastAPI(title="Mapper Splat Worker", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "all")}


@app.post("/jobs", status_code=202)
def create_job(
    payload: JobRequest, x_internal_token: str | None = Header(default=None)
) -> dict[str, Any]:
    authorize(x_internal_token)
    for existing in jobs.values():
        if existing["project_id"] == payload.project_id and existing["status"] in {"queued", "running"}:
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
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    jobs[job_id] = job
    save(job)
    queue.put_nowait(job_id)
    return job


@app.get("/jobs/{job_id}")
def get_job(job_id: str, x_internal_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_internal_token)
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


async def run_queue() -> None:
    while True:
        job_id = await queue.get()
        job = jobs[job_id]
        if job["status"] != "queued":
            queue.task_done()
            continue
        try:
            await execute(job)
        except asyncio.CancelledError:
            job["status"] = "queued"
            job["message"] = "Paused by worker shutdown"
            save(job)
            raise
        except Exception as exc:
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


async def execute(job: dict[str, Any]) -> None:
    job["status"] = "running"
    set_state(job, 2, "Preparing OpenSfM reconstruction")
    output = Path(job["output"]).resolve()
    dataset = Path(job["dataset"]).resolve()
    source = Path(job["source"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if DRY_RUN:
        for progress, message in (
            (18, "Exporting binary COLMAP cameras"),
            (35, "Initializing Splatfacto"),
            (72, "Training memory-safe Splatfacto"),
            (92, "Exporting PLY and SPZ"),
        ):
            set_state(job, progress, message)
            await asyncio.sleep(0.35)
        (output / "point_cloud.ply").write_text("ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")
        (output / "scene_transform.json").write_text(
            json.dumps({"version": 1, "coordinate_system": "ODM local", "transform": None}, indent=2)
        )
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
        images_link.symlink_to(source, target_is_directory=True)

    colmap_export = osfm_dataset / "colmap_export"
    colmap_files = ("cameras.bin", "images.bin", "points3D.bin")
    if not all((colmap_export / name).is_file() for name in colmap_files):
        set_state(job, 12, "Exporting OpenSfM cameras to binary COLMAP")
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
    missing_colmap = [name for name in colmap_files if not (colmap_export / name).is_file()]
    if missing_colmap:
        raise RuntimeError(
            "OpenSfM COLMAP export is incomplete; missing " + ", ".join(missing_colmap)
        )

    # OpenSfM's Brown camera exports as COLMAP FULL_OPENCV, which Nerfstudio
    # 1.1.5 cannot parse. Use Nerfstudio's supported ODM converter for training;
    # retain the native binary COLMAP export above as a durable interchange
    # product instead of weakening ODM's calibrated camera model.
    odm_dataset = work / "odm_dataset"
    odm_dataset.mkdir(parents=True, exist_ok=True)
    odm_inputs = {
        "cameras.json": dataset / "cameras.json",
        "odm_report": dataset / "odm_report",
        "opensfm": osfm_dataset,
        "images": source,
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
        "--vis",
        "tensorboard",
    ]
    if checkpoints:
        command.extend(["--load-dir", str(checkpoints[-1])])
    if job["quality_culling"]:
        command.extend(["--pipeline.model.cull-alpha-thresh", "0.01"])
    await run_command(job, command, progress_start=25, progress_end=88, training_steps=job["steps"])

    configs = sorted(training_root.rglob("config.yml"), key=lambda path: path.stat().st_mtime)
    if not configs:
        raise RuntimeError("Nerfstudio training completed without a config checkpoint")
    config_path = configs[-1]
    set_state(job, 90, "Exporting Gaussian PLY")
    await run_command(
        job,
        [
            "ns-export",
            "gaussian-splat",
            "--load-config",
            str(config_path),
            "--output-dir",
            str(output),
        ],
        progress_start=90,
        progress_end=96,
    )
    ply_candidates = list(output.glob("*.ply"))
    if not ply_candidates:
        raise RuntimeError("Nerfstudio did not export a Gaussian PLY")
    ply = ply_candidates[0]
    canonical_ply = output / "point_cloud.ply"
    if ply != canonical_ply:
        ply.replace(canonical_ply)

    set_state(job, 96, "Compressing web-ready SPZ")
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
        generated_spz.replace(output / "scene.spz")
    else:
        raise RuntimeError("Spark completed without emitting the required SPZ file")

    transform_candidates = list(training_root.rglob("dataparser_transforms.json"))
    transform = json.loads(transform_candidates[-1].read_text()) if transform_candidates else None
    (output / "scene_transform.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source_coordinate_system": "ODM/OpenSfM local reconstruction",
                "odm_georeferencing": "../odm_georeferencing",
                "nerfstudio_dataparser_transform": transform,
                "note": "Apply this normalization metadata when relating the splat to ODM projected coordinates.",
            },
            indent=2,
        )
    )
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
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdout
    async for raw in process.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        job["log"] = (job["log"] + [line])[-200:]
        if training_steps:
            match = re.search(r"(?:step|iteration)\D+(\d+)", line, re.IGNORECASE)
            if match:
                fraction = min(1.0, int(match.group(1)) / training_steps)
                job["progress"] = progress_start + (progress_end - progress_start) * fraction
        job["updated_at"] = utcnow()
        save(job)
    code = await process.wait()
    if code:
        raise RuntimeError(f"Command failed with exit code {code}: {' '.join(command[:3])}")
    set_state(job, progress_end, job["message"])
