from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from apps.api.app.config import settings
from apps.api.app.jobs.queue import decode_job
from apps.api.app.services.live_research import execute_job


logger = logging.getLogger("gopilot.worker")


async def run() -> None:
    """Consume bounded research workflow IDs from Redis.

    The API enqueues IDs only. Domain execution remains inside typed workflow services;
    arbitrary code and commands are never accepted from queue payloads.
    """
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            try:
                item = await redis.blpop("gtm:research-jobs", timeout=5)
            except RedisError:
                logger.exception("Redis queue unavailable")
                await asyncio.sleep(2)
                continue
            if item is None:
                await asyncio.sleep(0)
                continue
            _, raw = item
            try:
                job = decode_job(raw)
                await execute_job(job.kind, job.target_id)
            except (ValueError, TypeError):
                logger.exception("Rejected invalid research job")
            except Exception:
                logger.exception("Research job failed")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
