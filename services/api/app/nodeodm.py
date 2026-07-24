from __future__ import annotations

import asyncio
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from .config import settings

NODEODM_OUTPUTS = [
    "images",
    "odm_orthophoto",
    "odm_georeferencing",
    "odm_filterpoints",
    "odm_meshing",
    "odm_texturing",
    "odm_dem",
    "odm_report",
    "orthophoto_tiles",
    "dsm_tiles",
    "dtm_tiles",
    "entwine_pointcloud",
    "potree_pointcloud",
    "3d_tiles",
    "opensfm",
    "images.json",
    "cameras.json",
    "benchmark.txt",
    "img_list.txt",
    "task_output.txt",
    "log.json",
]


class NodeODMError(RuntimeError):
    pass


class NodeODMClient:
    def __init__(self) -> None:
        self.base_url = settings.nodeodm_url
        self.params = {"token": settings.nodeodm_token} if settings.nodeodm_token else {}

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        params = {**self.params, **kwargs.pop("params", {})}
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=600)) as client:
            response = await client.request(
                method, f"{self.base_url}{path}", params=params, **kwargs
            )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise NodeODMError(str(payload["error"]))
        return payload

    async def info(self) -> dict[str, Any]:
        return await self._json("GET", "/info")

    async def options(self) -> list[dict[str, Any]]:
        payload = await self._json("GET", "/options")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise NodeODMError("NodeODM returned malformed option metadata")
        return payload

    async def create_task(
        self,
        name: str,
        files: list[Path],
        options: list[dict[str, Any]],
        task_uuid: str,
    ) -> str:
        form = {
            "name": name,
            "options": json.dumps(options),
            "outputs": json.dumps(NODEODM_OUTPUTS),
        }
        result = await self._json(
            "POST",
            "/task/new/init",
            data=form,
            headers={"Set-UUID": task_uuid},
        )
        if not isinstance(result, dict) or result.get("uuid") != task_uuid:
            raise NodeODMError("NodeODM did not honor the durable task UUID")
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=1800)) as client:
            for path in files:
                with path.open("rb") as source:
                    response = await client.post(
                        f"{self.base_url}/task/new/upload/{task_uuid}",
                        params=self.params,
                        files={"images": (path.name, source, "application/octet-stream")},
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise NodeODMError("NodeODM returned malformed upload status")
                if payload.get("error"):
                    raise NodeODMError(str(payload["error"]))
        # Do not remove the UUID when commit raises: the response can be lost
        # after NodeODM has already queued the task. The orchestrator keeps this
        # reserved UUID and reconnects to it after restart; confirmed
        # uncommitted uploads return "not found" and are then retried with a new
        # UUID while NodeODM's upload-retention policy removes the old temp data.
        committed = await self._json("POST", f"/task/new/commit/{task_uuid}")
        if not isinstance(committed, dict) or committed.get("uuid") != task_uuid:
            raise NodeODMError("NodeODM committed an unexpected task UUID")
        return committed["uuid"]

    async def task_info(self, task_uuid: str) -> dict[str, Any]:
        payload = await self._json("GET", f"/task/{task_uuid}/info")
        try:
            int(payload["status"]["code"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NodeODMError("NodeODM returned malformed task status") from exc
        return payload

    async def output(self, task_uuid: str, line: int) -> list[str]:
        payload = await self._json(
            "GET", f"/task/{task_uuid}/output", params={"line": line}
        )
        if not isinstance(payload, list):
            raise NodeODMError("NodeODM returned malformed task output")
        return [str(item) for item in payload]

    async def cancel(self, task_uuid: str) -> None:
        await self._json("POST", "/task/cancel", data={"uuid": task_uuid})

    async def restart(self, task_uuid: str, options: list[dict[str, Any]] | None = None) -> None:
        data: dict[str, Any] = {"uuid": task_uuid}
        if options is not None:
            data["options"] = json.dumps(options)
        await self._json("POST", "/task/restart", data=data)

    async def remove(self, task_uuid: str) -> None:
        await self._json("POST", "/task/remove", data={"uuid": task_uuid})

    async def download_all(self, task_uuid: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.unlink(missing_ok=True)
        available = max(
            0, shutil.disk_usage(destination.parent).free - settings.disk_reserve_bytes
        )
        written = 0
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=None)) as client:
                async with client.stream(
                    "GET", f"{self.base_url}/task/{task_uuid}/download/all.zip", params=self.params
                ) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > available:
                        raise NodeODMError("Not enough free disk space for NodeODM output archive")
                    with partial.open("xb") as output:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            written += len(chunk)
                            if written > available:
                                raise NodeODMError(
                                    "NodeODM output archive exhausted the reserved free disk space"
                                )
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
            if not zipfile.is_zipfile(partial):
                raise NodeODMError("NodeODM returned an invalid output archive")
            partial.replace(destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    async def wait_for_terminal(
        self, task_uuid: str, poll_seconds: float = 2
    ) -> AsyncIterator[dict[str, Any]]:
        failures = 0
        while True:
            try:
                info = await self.task_info(task_uuid)
                failures = 0
            except (httpx.HTTPError, NodeODMError):
                failures += 1
                if failures >= 10:
                    raise
                await asyncio.sleep(min(30, poll_seconds * (2 ** (failures - 1))))
                continue
            yield info
            if int(info["status"]["code"]) in {30, 40, 50}:
                return
            await asyncio.sleep(poll_seconds)
