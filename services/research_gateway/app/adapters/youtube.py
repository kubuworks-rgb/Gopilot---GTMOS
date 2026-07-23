from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from pydantic import HttpUrl

from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import canonicalize_url, normalize_whitespace
from services.research_gateway.app.schemas import (
    AdapterHealth,
    SourceDocumentInput,
    YouTubeRequest,
)
from services.research_gateway.app.security.url_policy import UnsafeUrlError, validate_exact_domain


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


class YouTubeAdapter:
    name = "youtube"

    @staticmethod
    def _command() -> list[str]:
        executable = shutil.which("yt-dlp")
        return [executable] if executable else [sys.executable, "-m", "yt_dlp"]

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "APPDATA": os.environ.get("APPDATA", ""),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            "PYTHONUTF8": "1",
            "NO_COLOR": "1",
        }

    async def health(self) -> AdapterHealth:
        process = await asyncio.create_subprocess_exec(
            *self._command(),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._environment(),
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        return AdapterHealth(
            adapter=self.name,
            status="available" if process.returncode == 0 else "degraded",
            backend="yt-dlp",
            version=stdout.decode("utf-8", errors="replace").strip() or None,
            detail="Public metadata and legitimate subtitle inspection",
        )

    async def fetch(self, request: YouTubeRequest) -> SourceDocumentInput:
        url = str(request.url)
        try:
            validate_exact_domain(url, YOUTUBE_HOSTS)
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc
        args = [
            *self._command(),
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            url,
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._environment(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GatewayAdapterError(
                "FETCH_TIMEOUT", "YouTube metadata request timed out", retryable=True
            ) from exc
        if len(stdout) > 3_000_000 or len(stderr) > 64_000:
            raise GatewayAdapterError("SOURCE_UNAVAILABLE", "YouTube output exceeded limit")
        if process.returncode != 0:
            raise GatewayAdapterError(
                "SOURCE_UNAVAILABLE", "YouTube metadata was unavailable"
            )
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise GatewayAdapterError(
                "SOURCE_UNAVAILABLE", "YouTube returned invalid metadata"
            ) from exc
        duration = int(data.get("duration") or 0)
        if duration > request.max_duration_seconds:
            raise GatewayAdapterError(
                "SOURCE_UNAVAILABLE", "Video exceeds the configured duration limit"
            )
        transcript = ""
        if request.include_transcript:
            transcript = await self._download_transcript(url)
        description = normalize_whitespace(str(data.get("description") or ""))
        text = normalize_whitespace(
            f"Video: {data.get('title', '')}. Channel: {data.get('channel', '')}. "
            f"Published: {data.get('upload_date', '')}. Duration: {duration} seconds. "
            f"{description} {transcript}"
        )
        if request.include_transcript and not transcript:
            data["transcript_status"] = "YOUTUBE_TRANSCRIPT_UNAVAILABLE"
        return SourceDocumentInput(
            platform="youtube",
            source_type="video",
            backend="yt-dlp",
            url=HttpUrl(str(data.get("webpage_url") or url)),
            canonical_url=HttpUrl(
                canonicalize_url(str(data.get("webpage_url") or url))
            ),
            title=str(data.get("title") or "YouTube video"),
            author=data.get("channel"),
            retrieved_at=datetime.now(UTC),
            language=data.get("language"),
            content_type="application/json",
            text=text,
            metadata={
                "id": data.get("id"),
                "duration": duration,
                "view_count": data.get("view_count"),
                "upload_date": data.get("upload_date"),
                "transcript_status": data.get("transcript_status", "available"),
            },
        )

    async def _download_transcript(self, url: str) -> str:
        with tempfile.TemporaryDirectory(prefix="gopilot-youtube-") as temp_dir:
            output = str(Path(temp_dir) / "subtitle")
            process = await asyncio.create_subprocess_exec(
                *self._command(),
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "en.*",
                "--sub-format",
                "json3",
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                "--output",
                output,
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._environment(),
            )
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except TimeoutError:
                process.kill()
                await process.wait()
                return ""
            if process.returncode != 0 or len(stderr) > 64_000:
                return ""
            candidates = sorted(Path(temp_dir).glob("subtitle*.json3"))
            if not candidates:
                return ""
            if candidates[0].stat().st_size > 5_000_000:
                return ""
            try:
                payload = json.loads(candidates[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return ""
            transcript = " ".join(
                str(segment.get("utf8") or "")
                for event in payload.get("events", [])
                if isinstance(event, dict)
                for segment in event.get("segs", [])
                if isinstance(segment, dict)
            )
            return normalize_whitespace(transcript)
