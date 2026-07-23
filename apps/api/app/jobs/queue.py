from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis

from apps.api.app.config import settings


JobKind = Literal[
    "research",
    "discover_accounts",
    "research_account",
    "regenerate_brief",
]


class ResearchJob(BaseModel):
    kind: JobKind
    workspace_id: str
    target_id: str
    actor_id: str


async def enqueue_job(job: ResearchJob) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush("gtm:research-jobs", job.model_dump_json())
    finally:
        await redis.aclose()


def decode_job(raw: str) -> ResearchJob:
    payload = json.loads(raw)
    return ResearchJob.model_validate(payload)
