from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from typing import Any

from services.research_gateway.app.schemas import AdapterHealth


_cached: tuple[datetime, AdapterHealth] | None = None


async def agent_reach_health(ttl_seconds: int = 300) -> AdapterHealth:
    global _cached
    now = datetime.now(UTC)
    if _cached and now - _cached[0] < timedelta(seconds=ttl_seconds):
        return _cached[1]
    executable = shutil.which("agent-reach")
    if not executable or os.getenv("AGENT_REACH_ENABLED", "false").lower() != "true":
        health = AdapterHealth(adapter="agent-reach", status="unavailable", detail="Disabled or not installed during controlled setup")
        _cached = (now, health)
        return health
    process = await asyncio.create_subprocess_exec(
        executable,
        "doctor",
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONUTF8": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.wait()
        health = AdapterHealth(adapter="agent-reach", status="unavailable", detail="Health check timed out")
        _cached = (now, health)
        return health
    if len(stdout) > 256_000 or len(stderr) > 32_000:
        health = AdapterHealth(adapter="agent-reach", status="unavailable", detail="Health output exceeded limit")
    else:
        try:
            payload: Any = json.loads(stdout.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            health = AdapterHealth(adapter="agent-reach", status="available" if process.returncode == 0 else "degraded", backend="v1.4.2", detail=f"{len(payload)} capability fields")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            health = AdapterHealth(adapter="agent-reach", status="unavailable", detail="Invalid health JSON")
    _cached = (now, health)
    return health
