from __future__ import annotations

import shutil
import subprocess
from typing import Any

import psutil

from .config import settings


def metrics() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(settings.data_root)
    gpu: dict[str, Any] = {
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
            timeout=4,
        )
        name, utilization, used, total = [value.strip() for value in result.stdout.splitlines()[0].split(",")]
        gpu = {
            "available": True,
            "name": name,
            "utilization_percent": float(utilization),
            "memory_used_mb": float(used),
            "memory_total_mb": float(total),
        }
    except Exception:
        pass
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "logical_cores": psutil.cpu_count(),
        "ram_used_gb": round(memory.used / 1024**3, 2),
        "ram_total_gb": round(memory.total / 1024**3, 2),
        "disk_used_gb": round((disk.total - disk.free) / 1024**3, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "gpu": gpu,
    }
