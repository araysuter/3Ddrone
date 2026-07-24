from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest


SPLAT_APP = Path(__file__).resolve().parents[2] / "splat" / "app.py"
SPEC = importlib.util.spec_from_file_location("splat_worker_app", SPLAT_APP)
assert SPEC and SPEC.loader
splat_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(splat_app)


def test_splat_pipeline_uses_supported_odm_and_spark_paths(tmp_path, monkeypatch) -> None:
    project_id = "00000000-0000-4000-8000-000000000001"
    data_root = tmp_path / "data"
    dataset = data_root / "metadata" / "projects" / project_id / "artifacts"
    opensfm = dataset / "opensfm"
    report = dataset / "odm_report"
    source = data_root / "source" / project_id
    output = dataset / "splat"
    opensfm.mkdir(parents=True)
    report.mkdir()
    source.mkdir(parents=True)
    (opensfm / "reconstruction.json").write_text("[{}]")
    (dataset / "cameras.json").write_text("{}")
    (report / "shots.geojson").write_text("{}")
    (source / "DJI_0001.JPG").write_bytes(b"image")

    commands: list[list[str]] = []

    async def fake_run_command(job, command, **kwargs) -> None:
        commands.append(command)
        if "export_colmap" in command:
            export = tmp_path / "state" / "work" / project_id / "dataset" / "colmap_export"
            export.mkdir(parents=True)
            for name in ("cameras.bin", "images.bin", "points3D.bin"):
                (export / name).write_bytes(b"colmap")
        elif command[:2] == ["ns-process-data", "odm"]:
            converted = Path(command[command.index("--output-dir") + 1])
            converted.mkdir(parents=True)
            (converted / "transforms.json").write_text('{"frames": []}')
        elif command[:2] == ["ns-train", "splatfacto"]:
            training = Path(command[command.index("--output-dir") + 1])
            config = training / "odm-splat" / "run" / "config.yml"
            config.parent.mkdir(parents=True)
            config.write_text("pipeline: test")
        elif command[:2] == ["ns-export", "gaussian-splat"]:
            export = Path(command[command.index("--output-dir") + 1])
            export.mkdir(parents=True, exist_ok=True)
            (export / "splat.ply").write_text("ply")
        elif command[:2] == ["node", "/opt/spark/scripts/compress-to-spz.js"]:
            Path(command[-1]).with_suffix(".spz").write_bytes(b"spz")

    monkeypatch.setattr(splat_app, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(splat_app, "DATA_ROOT", data_root)
    monkeypatch.setattr(splat_app, "DRY_RUN", False)
    monkeypatch.setattr(splat_app, "run_command", fake_run_command)

    job = {
        "id": "00000000-0000-4000-8000-000000000002",
        "project_id": project_id,
        "dataset": str(dataset),
        "source": str(source),
        "output": str(output),
        "downscale": 2,
        "steps": 100,
        "quality_culling": False,
        "status": "queued",
        "progress": 0,
        "message": "",
        "error": None,
        "log": [],
    }

    asyncio.run(splat_app.execute(job))

    assert job["status"] == "completed"
    assert (output / "point_cloud.ply").is_file()
    assert (output / "scene.spz").read_bytes() == b"spz"
    assert json.loads((output / "scene_transform.json").read_text())["version"] == 1

    colmap_command = next(command for command in commands if "export_colmap" in command)
    assert "--binary" in colmap_command

    convert_command = next(command for command in commands if command[:2] == ["ns-process-data", "odm"])
    assert convert_command[convert_command.index("--num-downscales") + 1] == "0"
    assert convert_command[convert_command.index("--max-dataset-size") + 1] == "-1"

    train_command = next(command for command in commands if command[:2] == ["ns-train", "splatfacto"])
    assert Path(train_command[train_command.index("--data") + 1]).name == "nerfstudio_dataset"
    assert train_command[train_command.index("--pipeline.datamanager.camera-res-scale-factor") + 1] == "0.5"

    compress_command = next(command for command in commands if command[0] == "node")
    assert compress_command[:2] == ["node", "/opt/spark/scripts/compress-to-spz.js"]
    assert all(command[0] != "npm" for command in commands)


def test_interrupted_splat_job_is_requeued_from_durable_state(tmp_path, monkeypatch) -> None:
    project_id = "00000000-0000-4000-8000-000000000003"
    job_id = "00000000-0000-4000-8000-000000000004"
    data_root = tmp_path / "data"
    state_root = data_root / "splat"
    state_file = state_root / "jobs" / f"{job_id}.json"
    state_file.parent.mkdir(parents=True)
    payload = {
        "id": job_id,
        "project_id": project_id,
        "dataset": str(data_root / "metadata" / "projects" / project_id / "artifacts"),
        "source": str(data_root / "source" / project_id),
        "output": str(
            data_root / "metadata" / "projects" / project_id / "artifacts" / "splat"
        ),
        "downscale": 2,
        "steps": 100,
        "quality_culling": False,
        "status": "running",
        "progress": 50,
        "message": "Training",
        "error": None,
        "log": [],
        "log_count": 0,
        "cancel_requested": False,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    state_file.write_text(json.dumps(payload))
    monkeypatch.setattr(splat_app, "DATA_ROOT", data_root)
    monkeypatch.setattr(splat_app, "STATE_ROOT", state_root)
    splat_app.jobs.clear()

    splat_app.load_jobs()

    assert splat_app.jobs[job_id]["status"] == "queued"
    assert json.loads(state_file.read_text())["status"] == "queued"


def test_run_command_kills_a_stubborn_process_group_on_cancel(tmp_path, monkeypatch) -> None:
    job_id = "00000000-0000-4000-8000-000000000005"
    job = {
        "id": job_id,
        "cancel_requested": False,
        "progress": 0,
        "message": "Testing cancellation",
        "updated_at": "",
        "log": [],
        "log_count": 0,
    }
    monkeypatch.setattr(splat_app, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(splat_app, "PROCESS_TERMINATE_SECONDS", 0.2)

    async def scenario() -> None:
        task = asyncio.create_task(
            splat_app.run_command(
                job,
                [
                    sys.executable,
                    "-c",
                    (
                        "import signal,time;"
                        "signal.signal(signal.SIGTERM, lambda *_: None);"
                        "print('ready', flush=True);"
                        "time.sleep(30)"
                    ),
                ],
                progress_start=0,
                progress_end=100,
            )
        )
        await asyncio.sleep(0.2)
        job["cancel_requested"] = True
        with pytest.raises(splat_app.JobCanceled):
            await asyncio.wait_for(task, timeout=3)

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 3
    assert job_id not in splat_app.active_processes


def test_stale_queue_entry_does_not_crash_the_splat_runner(monkeypatch) -> None:
    async def scenario() -> None:
        test_queue: asyncio.Queue[str] = asyncio.Queue()
        await test_queue.put("00000000-0000-4000-8000-000000000006")
        monkeypatch.setattr(splat_app, "queue", test_queue)
        monkeypatch.setattr(splat_app, "jobs", {})
        runner = asyncio.create_task(splat_app.run_queue())
        await asyncio.sleep(0.05)
        assert not runner.done()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())
