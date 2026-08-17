from __future__ import annotations

import asyncio
import logging
import os

from redis.asyncio import Redis
from redis.exceptions import RedisError

from apps.api.app.config import settings
from apps.api.app.jobs.queue import (
    DEAD_LETTER_QUEUE,
    MAX_ATTEMPTS,
    PENDING_QUEUE,
    ResearchJob,
    awaited,
    decode_job,
    processing_queue,
)
from apps.api.app.services.live_research import execute_job, record_job_failure


logger = logging.getLogger("gopilot.worker")

WORKER_NAME = os.getenv("WORKER_NAME", "worker-1")


async def reclaim_orphaned_jobs(redis: Redis, processing: str) -> int:
    """Return this worker's in-flight jobs to the pending queue after a restart.

    A crash between claiming and completing a job used to lose it permanently: the
    account stayed in RESEARCH_CANDIDATE forever with nothing recorded anywhere.
    Only this worker's own list is touched, so a concurrent worker's in-flight job
    is never stolen.
    """

    reclaimed = 0
    while await awaited(redis.rpoplpush(processing, PENDING_QUEUE)):
        reclaimed += 1
    if reclaimed:
        logger.warning(
            "Reclaimed %s orphaned job(s) for %s", reclaimed, WORKER_NAME
        )
    return reclaimed


async def _retry_or_dead_letter(
    redis: Redis, job: ResearchJob, error: BaseException
) -> None:
    attempt = job.attempt + 1
    retried = job.model_copy(
        update={"attempt": attempt, "last_error": type(error).__name__}
    )
    if attempt < MAX_ATTEMPTS:
        logger.warning(
            "Job %s/%s failed (attempt %s/%s); requeueing",
            job.kind,
            job.target_id,
            attempt,
            MAX_ATTEMPTS,
        )
        await awaited(redis.rpush(PENDING_QUEUE, retried.model_dump_json()))
        return

    logger.error(
        "Job %s/%s exhausted %s attempts; moving to the dead-letter queue",
        job.kind,
        job.target_id,
        MAX_ATTEMPTS,
    )
    await awaited(redis.rpush(DEAD_LETTER_QUEUE, retried.model_dump_json()))
    # Surface the failure in the product, not only in the logs, so the UI can
    # distinguish "still running" from "gave up".
    try:
        await record_job_failure(job.kind, job.target_id, type(error).__name__)
    except Exception:  # noqa: BLE001 - reporting must never mask the original failure
        logger.exception("Could not record terminal failure for %s", job.target_id)


async def process_one(redis: Redis, processing: str, raw: str) -> None:
    try:
        job = decode_job(raw)
    except (ValueError, TypeError):
        # Undecodable payloads can never succeed; retrying would loop forever.
        logger.exception("Rejected malformed research job")
        await awaited(redis.lrem(processing, 1, raw))
        await awaited(redis.rpush(DEAD_LETTER_QUEUE, raw))
        return

    try:
        await execute_job(
            job.kind,
            job.target_id,
            workspace_id=job.workspace_id,
            actor_id=job.actor_id,
        )
    except Exception as exc:  # noqa: BLE001 - one bad job must not kill the worker
        logger.exception("Research job %s/%s failed", job.kind, job.target_id)
        await _retry_or_dead_letter(redis, job, exc)
    finally:
        # Release the claim exactly once, whether the job succeeded or failed.
        await awaited(redis.lrem(processing, 1, raw))


async def run() -> None:
    """Consume bounded research workflow IDs from Redis.

    The API enqueues IDs only. Domain execution stays inside typed workflow services;
    arbitrary code and commands are never accepted from queue payloads.

    Delivery is at-least-once: a job is atomically moved to a per-worker in-flight
    list when claimed and removed only after it settles, so a crash mid-job leaves a
    record that is reclaimed on restart.
    """

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    processing = processing_queue(WORKER_NAME)
    try:
        await reclaim_orphaned_jobs(redis, processing)
        while True:
            try:
                raw = await awaited(redis.blmove(
                    PENDING_QUEUE, processing, timeout=5, src="LEFT", dest="RIGHT"
                ))
            except RedisError:
                logger.exception("Redis queue unavailable")
                await asyncio.sleep(2)
                continue
            if raw is None:
                continue
            await process_one(redis, processing, raw)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())
