from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from .config import settings

NODEODM_OUTPUTS = [
    "odm_orthophoto",
    "odm_georeferencing",
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
    "task_output.txt",
    "log.json",
]


class NodeODMError(RuntimeError):
    pass


class NodeODMClient:
    def __init__(self) -> None:
        self.base_url = settings.nodeodm_url
        self.params = {"token": settings.nodeodm_token} if settings.nodeodm_token else {}

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        params = {**self.params, **kwargs.pop("params", {})}
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=600)) as client:
            response = await client.request(
                method, f"{self.base_url}{path}", params=params, **kwargs
            )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise NodeODMError(str(payload["error"]))
        return payload

    async def info(self) -> dict[str, Any]:
        return await self._json("GET", "/info")

    async def options(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/options", params=self.params)
        response.raise_for_status()
        return response.json()

    async def create_task(
        self,
        name: str,
        files: list[Path],
        options: list[dict[str, Any]],
    ) -> str:
        form = {
            "name": name,
            "options": json.dumps(options),
            "outputs": json.dumps(NODEODM_OUTPUTS),
        }
        result = await self._json("POST", "/task/new/init", data=form)
        task_uuid = result["uuid"]
        try:
            for path in files:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=1800)) as client:
                    with path.open("rb") as source:
                        response = await client.post(
                            f"{self.base_url}/task/new/upload/{task_uuid}",
                            params=self.params,
                            files={"images": (path.name, source, "application/octet-stream")},
                        )
                response.raise_for_status()
                payload = response.json()
                if payload.get("error"):
                    raise NodeODMError(str(payload["error"]))
            committed = await self._json("POST", f"/task/new/commit/{task_uuid}")
            return committed["uuid"]
        except Exception:
            await self.remove(task_uuid)
            raise

    async def task_info(self, task_uuid: str, with_output: int = 10) -> dict[str, Any]:
        return await self._json(
            "GET", f"/task/{task_uuid}/info", params={**self.params, "with_output": with_output}
        )

    async def output(self, task_uuid: str, line: int) -> dict[str, Any]:
        return await self._json("GET", f"/task/{task_uuid}/output", params={**self.params, "line": line})

    async def cancel(self, task_uuid: str) -> None:
        await self._json("POST", "/task/cancel", data={"uuid": task_uuid})

    async def restart(self, task_uuid: str, options: list[dict[str, Any]] | None = None) -> None:
        data: dict[str, Any] = {"uuid": task_uuid}
        if options is not None:
            data["options"] = json.dumps(options)
        await self._json("POST", "/task/restart", data=data)

    async def remove(self, task_uuid: str) -> None:
        try:
            await self._json("POST", "/task/remove", data={"uuid": task_uuid})
        except Exception:
            pass

    async def download_all(self, task_uuid: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=None)) as client:
            async with client.stream(
                "GET", f"{self.base_url}/task/{task_uuid}/download/all.zip", params=self.params
            ) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        output.write(chunk)

    async def wait_for_terminal(
        self, task_uuid: str, poll_seconds: float = 2
    ) -> AsyncIterator[dict[str, Any]]:
        while True:
            info = await self.task_info(task_uuid, with_output=50)
            yield info
            if int(info["status"]["code"]) in {30, 40, 50}:
                return
            await asyncio.sleep(poll_seconds)
