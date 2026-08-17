"""The worker must not lose a job when it dies mid-flight.

These run against a real Redis (set RUN_LIVE_REDIS_TESTS=1). The behaviour under
test is Redis semantics -- atomic BLMOVE, per-worker in-flight lists, LREM release --
so a faked client would prove nothing about the thing that actually broke.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from apps.api.app.jobs.queue import (
    DEAD_LETTER_QUEUE,
    PENDING_QUEUE,
    ResearchJob,
    awaited,
    decode_job,
    enqueue_job,
    processing_queue,
)
from services.worker.app.main import (
    _retry_or_dead_letter,
    process_one,
    reclaim_orphaned_jobs,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_REDIS_TESTS") != "1",
    reason="Set RUN_LIVE_REDIS_TESTS=1 with Redis running",
)

WORKER = "test-worker"
PROCESSING = processing_queue(WORKER)


def _job(target: str = "11111111-1111-1111-1111-111111111111") -> ResearchJob:
    return ResearchJob(
        kind="research_account",
        workspace_id="22222222-2222-2222-2222-222222222222",
        target_id=target,
        actor_id="tester",
    )


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True
    )
    for key in (PENDING_QUEUE, PROCESSING, DEAD_LETTER_QUEUE):
        await awaited(client.delete(key))
    try:
        yield client
    finally:
        for key in (PENDING_QUEUE, PROCESSING, DEAD_LETTER_QUEUE):
            await awaited(client.delete(key))
        await client.aclose()


@pytest.mark.asyncio
async def test_claiming_a_job_moves_it_to_the_in_flight_list(redis: Redis) -> None:
    await enqueue_job(_job(), redis=redis)

    raw = await awaited(
        redis.blmove(PENDING_QUEUE, PROCESSING, timeout=2, src="LEFT", dest="RIGHT")
    )

    assert raw is not None
    assert await awaited(redis.llen(PENDING_QUEUE)) == 0
    # The job is not lost in limbo: it is recorded as in flight.
    assert await awaited(redis.llen(PROCESSING)) == 1


@pytest.mark.asyncio
async def test_a_crash_mid_job_is_reclaimed_on_restart(redis: Redis) -> None:
    """The original defect: BLPOP removed the job, a crash lost it permanently."""
    await enqueue_job(_job(), redis=redis)
    raw = await awaited(
        redis.blmove(PENDING_QUEUE, PROCESSING, timeout=2, src="LEFT", dest="RIGHT")
    )
    assert raw is not None
    # ... worker dies here, before settling the job.

    reclaimed = await reclaim_orphaned_jobs(redis, PROCESSING)

    assert reclaimed == 1
    assert await awaited(redis.llen(PROCESSING)) == 0
    assert await awaited(redis.llen(PENDING_QUEUE)) == 1
    recovered = decode_job(await awaited(redis.lindex(PENDING_QUEUE, 0)))
    assert recovered.target_id == _job().target_id


@pytest.mark.asyncio
async def test_reclaim_only_touches_this_workers_list(redis: Redis) -> None:
    """A restart must never steal a job another worker is actively running."""
    other = processing_queue("other-worker")
    await awaited(redis.delete(other))
    await awaited(redis.rpush(other, _job("33333333-3333-3333-3333-333333333333").model_dump_json()))
    try:
        reclaimed = await reclaim_orphaned_jobs(redis, PROCESSING)

        assert reclaimed == 0
        assert await awaited(redis.llen(other)) == 1
    finally:
        await awaited(redis.delete(other))


@pytest.mark.asyncio
async def test_a_failing_job_is_retried_then_dead_lettered(redis: Redis) -> None:
    job = _job()

    await _retry_or_dead_letter(redis, job, RuntimeError("boom"))
    assert await awaited(redis.llen(PENDING_QUEUE)) == 1
    first = decode_job(await awaited(redis.lpop(PENDING_QUEUE)))
    assert first.attempt == 1
    assert first.last_error == "RuntimeError"

    await _retry_or_dead_letter(redis, first, RuntimeError("boom"))
    second = decode_job(await awaited(redis.lpop(PENDING_QUEUE)))
    assert second.attempt == 2

    # Third failure exhausts MAX_ATTEMPTS=3 and must not requeue forever.
    await _retry_or_dead_letter(redis, second, RuntimeError("boom"))
    assert await awaited(redis.llen(PENDING_QUEUE)) == 0
    assert await awaited(redis.llen(DEAD_LETTER_QUEUE)) == 1
    dead = decode_job(await awaited(redis.lindex(DEAD_LETTER_QUEUE, 0)))
    assert dead.attempt == 3


@pytest.mark.asyncio
async def test_a_malformed_payload_is_dead_lettered_not_retried(redis: Redis) -> None:
    """Undecodable payloads can never succeed; retrying would loop forever."""
    await awaited(redis.rpush(PROCESSING, "not json at all"))

    await process_one(redis, PROCESSING, "not json at all")

    assert await awaited(redis.llen(PROCESSING)) == 0
    assert await awaited(redis.llen(PENDING_QUEUE)) == 0
    assert await awaited(redis.llen(DEAD_LETTER_QUEUE)) == 1


@pytest.mark.asyncio
async def test_a_successful_job_releases_its_claim(redis: Redis, monkeypatch) -> None:
    job = _job()
    raw = job.model_dump_json()
    await awaited(redis.rpush(PROCESSING, raw))

    async def succeed(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("services.worker.app.main.execute_job", succeed)

    await process_one(redis, PROCESSING, raw)

    assert await awaited(redis.llen(PROCESSING)) == 0
    assert await awaited(redis.llen(PENDING_QUEUE)) == 0
    assert await awaited(redis.llen(DEAD_LETTER_QUEUE)) == 0
