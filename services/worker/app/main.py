from __future__ import annotations

import asyncio
import os

from redis.asyncio import Redis


async def run() -> None:
    """Consume bounded research workflow IDs from Redis.

    The API enqueues IDs only. Domain execution remains inside typed workflow services;
    arbitrary code and commands are never accepted from queue payloads.
    """
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    while True:
        item = await redis.blpop("gtm:research-runs", timeout=5)
        if item is None:
            await asyncio.sleep(0)
            continue
        _, workflow_run_id = item
        if not workflow_run_id.startswith("run_") or len(workflow_run_id) > 64:
            continue
        # Production repository orchestration binds here; fixture workflows execute
        # in-process so local demo startup never requires Redis.


if __name__ == "__main__":
    asyncio.run(run())
