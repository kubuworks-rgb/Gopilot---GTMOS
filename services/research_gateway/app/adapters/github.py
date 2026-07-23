from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import UTC, datetime
from urllib.parse import urlsplit
from pydantic import HttpUrl

from services.research_gateway.app.config import settings
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import canonicalize_url, normalize_whitespace
from services.research_gateway.app.schemas import (
    AdapterHealth,
    GitHubRequest,
    SourceDocumentInput,
)
from services.research_gateway.app.security.url_policy import UnsafeUrlError, validate_exact_domain


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _repository_name(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith(("http://", "https://")):
        try:
            validate_exact_domain(candidate, {"github.com", "www.github.com"})
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc
        parts = [part for part in urlsplit(candidate).path.split("/") if part]
        if len(parts) < 2:
            raise GatewayAdapterError("GITHUB_UNAVAILABLE", "Invalid GitHub repository URL")
        candidate = f"{parts[0]}/{parts[1].removesuffix('.git')}"
    if not REPO_PATTERN.fullmatch(candidate):
        raise GatewayAdapterError("GITHUB_UNAVAILABLE", "Invalid GitHub repository name")
    return candidate


def _safe_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SystemRoot",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "GH_CONFIG_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    token = settings.github_token
    if token:
        environment["GH_TOKEN"] = token
    environment["NO_COLOR"] = "1"
    return environment


async def _run_gh(args: list[str], timeout: float = 20) -> str:
    executable = shutil.which("gh")
    if not executable:
        raise GatewayAdapterError("GITHUB_UNAVAILABLE", "GitHub CLI is not installed")
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_safe_environment(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GatewayAdapterError(
            "FETCH_TIMEOUT", "GitHub request timed out", retryable=True
        ) from exc
    if len(stdout) > 2_000_000 or len(stderr) > 64_000:
        raise GatewayAdapterError("GITHUB_UNAVAILABLE", "GitHub output exceeded limit")
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").lower()
        if "rate limit" in detail:
            raise GatewayAdapterError(
                "RATE_LIMITED", "GitHub rate limit reached", retryable=True
            )
        if "authentication" in detail or "auth login" in detail:
            raise GatewayAdapterError(
                "GITHUB_AUTH_REQUIRED", "GitHub authentication is required"
            )
        raise GatewayAdapterError("GITHUB_UNAVAILABLE", "GitHub request failed")
    return stdout.decode("utf-8", errors="replace")


class GitHubAdapter:
    name = "github"

    async def health(self) -> AdapterHealth:
        executable = shutil.which("gh")
        if not executable:
            return AdapterHealth(
                adapter=self.name,
                status="unavailable",
                backend="gh",
                detail="GitHub CLI is not installed",
            )
        try:
            version = (await _run_gh(["--version"], timeout=5)).splitlines()[0]
        except GatewayAdapterError as exc:
            return AdapterHealth(
                adapter=self.name,
                status="degraded",
                backend="gh",
                detail=exc.safe_message,
            )
        return AdapterHealth(
            adapter=self.name,
            status="available",
            backend="gh",
            version=version,
            detail="Read-only public repository adapter",
        )

    async def fetch(self, request: GitHubRequest) -> SourceDocumentInput:
        repository = _repository_name(request.repository)
        fields = (
            "nameWithOwner,description,url,homepageUrl,isPrivate,defaultBranchRef,"
            "languages,licenseInfo,latestRelease,updatedAt"
        )
        raw = await _run_gh(["repo", "view", repository, "--json", fields])
        try:
            metadata = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewayAdapterError(
                "GITHUB_UNAVAILABLE", "GitHub returned invalid JSON"
            ) from exc
        if metadata.get("isPrivate"):
            raise GatewayAdapterError(
                "URL_POLICY_BLOCKED", "Private repositories are not allowed"
            )
        readme = ""
        if request.include_readme:
            try:
                readme = await _run_gh(
                    [
                        "api",
                        f"repos/{repository}/readme",
                        "-H",
                        "Accept: application/vnd.github.raw+json",
                    ]
                )
            except GatewayAdapterError:
                readme = ""
        releases: list[object] = []
        if request.include_releases:
            try:
                releases_raw = await _run_gh(
                    [
                        "api",
                        f"repos/{repository}/releases",
                        "-f",
                        "per_page=5",
                        "--method",
                        "GET",
                    ]
                )
                parsed_releases = json.loads(releases_raw)
                if isinstance(parsed_releases, list):
                    releases = [
                        {
                            "name": item.get("name") or item.get("tag_name"),
                            "published_at": item.get("published_at"),
                            "url": item.get("html_url"),
                        }
                        for item in parsed_releases[:5]
                        if isinstance(item, dict)
                    ]
            except (GatewayAdapterError, json.JSONDecodeError):
                releases = []
        url = str(metadata.get("url") or f"https://github.com/{repository}")
        title = str(metadata.get("nameWithOwner") or repository)
        description = normalize_whitespace(str(metadata.get("description") or ""))
        text_parts = [
            f"Repository: {title}",
            f"Description: {description}" if description else "",
            f"Default branch: {(metadata.get('defaultBranchRef') or {}).get('name', '')}",
            f"Updated at: {metadata.get('updatedAt', '')}",
            readme,
        ]
        text = normalize_whitespace("\n".join(part for part in text_parts if part))
        metadata["releases"] = releases
        metadata["repository"] = repository
        return SourceDocumentInput(
            platform="github",
            source_type="repository",
            backend="gh",
            url=HttpUrl(url),
            canonical_url=HttpUrl(canonicalize_url(url)),
            title=title,
            published_at=None,
            retrieved_at=datetime.now(UTC),
            language="en",
            content_type="text/markdown",
            text=text,
            metadata=metadata,
        )
