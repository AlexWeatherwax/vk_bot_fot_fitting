import asyncio
from types import SimpleNamespace

import pytest

from bot.tryon.queue import (
    DuplicateTryOnJob,
    TryOnJob,
    TryOnQueue,
    TryOnQueueFull,
)


def make_job(peer_id: int):
    return TryOnJob(
        message=SimpleNamespace(peer_id=peer_id),
        bot=SimpleNamespace(),
        item=SimpleNamespace(id=str(peer_id)),
        overlay_path=None,
        photo_bytes=b"photo",
    )


def test_queue_processes_jobs_fifo():
    async def scenario():
        queue = TryOnQueue(maxsize=10)
        started = asyncio.Event()
        release = asyncio.Event()
        order = []

        async def process(job):
            order.append(job.peer_id)
            if job.peer_id == 1:
                started.set()
                await release.wait()

        queue._process = process

        assert await queue.enqueue(make_job(1)) == 1
        await started.wait()
        assert await queue.enqueue(make_job(2)) == 2
        assert await queue.enqueue(make_job(3)) == 3

        release.set()
        await asyncio.wait_for(queue._queue.join(), timeout=2)
        assert order == [1, 2, 3]

        queue._worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queue._worker_task

    asyncio.run(scenario())


def test_same_peer_cannot_enqueue_twice():
    async def scenario():
        queue = TryOnQueue(maxsize=10)
        started = asyncio.Event()
        release = asyncio.Event()

        async def process(job):
            started.set()
            await release.wait()

        queue._process = process

        await queue.enqueue(make_job(7))
        await started.wait()
        with pytest.raises(DuplicateTryOnJob):
            await queue.enqueue(make_job(7))

        release.set()
        await asyncio.wait_for(queue._queue.join(), timeout=2)
        queue._worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queue._worker_task

    asyncio.run(scenario())


def test_queue_has_bounded_pending_capacity():
    async def scenario():
        queue = TryOnQueue(maxsize=1)
        started = asyncio.Event()
        release = asyncio.Event()

        async def process(job):
            started.set()
            await release.wait()

        queue._process = process

        await queue.enqueue(make_job(1))
        await started.wait()
        assert await queue.enqueue(make_job(2)) == 2

        with pytest.raises(TryOnQueueFull):
            await queue.enqueue(make_job(3))

        release.set()
        await asyncio.wait_for(queue._queue.join(), timeout=2)
        queue._worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queue._worker_task

    asyncio.run(scenario())
