from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from services.research_gateway.app.config import settings
from services.research_gateway.app.schemas import AdapterHealth, CapabilityHealth


_cached: tuple[datetime, AdapterHealth, list[CapabilityHealth]] | None = None


def _safe_environment() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in (
            "PATH",
            "SystemRoot",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "AGENT_REACH_HOME",
        )
        if key in os.environ
    } | {"PYTHONUTF8": "1", "NO_COLOR": "1"}


def _command() -> list[str]:
    executable = shutil.which("agent-reach")
    if executable:
        return [executable]
    return [sys.executable, "-m", "agent_reach.cli"]


async def _run(command: list[str], *args: str, timeout: float = 10) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_safe_environment(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, stdout, stderr


async def agent_reach_report(
    ttl_seconds: int = 300,
) -> tuple[AdapterHealth, list[CapabilityHealth]]:
    global _cached
    now = datetime.now(UTC)
    if _cached and now - _cached[0] < timedelta(seconds=ttl_seconds):
        return _cached[1], _cached[2]
    if not settings.agent_reach_enabled:
        health = AdapterHealth(
            adapter="agent-reach",
            status="unavailable",
            detail="Disabled or not installed during controlled setup",
        )
        _cached = (now, health, [])
        return health, []
    try:
        command = _command()
        version_code, version_stdout, _ = await _run(command, "--version", timeout=5)
        returncode, stdout, stderr = await _run(
            command, "doctor", "--json", timeout=15
        )
    except (TimeoutError, OSError):
        health = AdapterHealth(
            adapter="agent-reach",
            status="unavailable",
            detail="Health check timed out",
        )
        _cached = (now, health, [])
        return health, []
    if (
        len(stdout) > 256_000
        or len(stderr) > 32_000
        or len(version_stdout) > 4_000
    ):
        health = AdapterHealth(
            adapter="agent-reach",
            status="unavailable",
            detail="Health output exceeded limit",
        )
        _cached = (now, health, [])
        return health, []
    try:
        payload: Any = json.loads(stdout.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object")
        capabilities = [
            CapabilityHealth(
                channel=str(channel),
                status=(
                    "available"
                    if item.get("status") == "ok"
                    else "degraded"
                    if item.get("status") == "warn"
                    else "unavailable"
                ),
                backend=", ".join(str(value) for value in item.get("backends", []))
                or None,
                detail=str(item.get("message") or "") or None,
            )
            for channel, item in payload.items()
            if isinstance(item, dict)
        ]
        version = (
            version_stdout.decode("utf-8", errors="replace").strip()
            if version_code == 0
            else None
        )
        health = AdapterHealth(
            adapter="agent-reach",
            status="available" if returncode == 0 else "degraded",
            backend="capability-router",
            version=version,
            detail=f"{len(capabilities)} capability checks",
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        health = AdapterHealth(
            adapter="agent-reach",
            status="unavailable",
            detail="Invalid health JSON",
        )
        capabilities = []
    _cached = (now, health, capabilities)
    return health, capabilities


async def agent_reach_health(ttl_seconds: int = 300) -> AdapterHealth:
    health, _ = await agent_reach_report(ttl_seconds)
    return health
