from __future__ import annotations

import json
import os
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Literal, TypeVar, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from apps.api.app.config import settings


T = TypeVar("T")


def awaited(value: Awaitable[T] | T) -> Awaitable[T]:
    """Narrow a redis-py command result to its async form.

    redis-py annotates sync and async commands with the same union, so awaiting one
    directly fails type checking even though the async client always returns a
    coroutine.
    """

    return cast(Awaitable[T], value)


JobKind = Literal[
    "research",
    "discover_accounts",
    "research_account",
    "regenerate_brief",
]

PENDING_QUEUE = "gtm:research-jobs"
DEAD_LETTER_QUEUE = "gtm:research-jobs:dead"

MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))


def processing_queue(worker_name: str) -> str:
    """In-flight jobs for one worker.

    Per-worker so a restart reclaims only its own orphans and never steals a job
    another worker is actively running. Scaling out requires a distinct WORKER_NAME
    per instance.
    """

    return f"gtm:research-jobs:processing:{worker_name}"


class ResearchJob(BaseModel):
    kind: JobKind
    workspace_id: str
    target_id: str
    actor_id: str
    attempt: int = 0
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None


async def enqueue_job(job: ResearchJob, redis: Redis | None = None) -> None:
    client = redis or Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await awaited(client.rpush(PENDING_QUEUE, job.model_dump_json()))
    finally:
        if redis is None:
            await client.aclose()


def decode_job(raw: str) -> ResearchJob:
    payload = json.loads(raw)
    return ResearchJob.model_validate(payload)
