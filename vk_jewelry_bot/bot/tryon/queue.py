"""In-process FIFO queue for try-on jobs.

The bot can receive VK messages concurrently, but native inference is intentionally
limited to one job at a time. This queue accepts photos immediately, keeps their
order, and lets one background consumer run the existing isolated worker process.
"""
import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from .errors import TryOnError
from .service import apply_tryon
from ..vk_media import upload_photo_for_message

logger = logging.getLogger("vk_jewelry_bot.tryon.queue")

DEFAULT_MAX_QUEUE_SIZE = 20


class TryOnQueueFull(Exception):
    """Raised when the pending queue reached its configured capacity."""


class DuplicateTryOnJob(Exception):
    """Raised when the same VK peer already has a queued/running job."""


@dataclass
class TryOnJob:
    message: Any
    bot: Any
    item: Any
    overlay_path: Path
    photo_bytes: bytes

    @property
    def peer_id(self) -> int:
        return self.message.peer_id


class TryOnQueue:
    def __init__(self, maxsize: int = DEFAULT_MAX_QUEUE_SIZE):
        self._queue: asyncio.Queue[TryOnJob] = asyncio.Queue(maxsize=maxsize)
        self._pending_peers: set[int] = set()
        self._worker_task: asyncio.Task | None = None
        self._processing_peer: int | None = None

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    @property
    def pending_count(self) -> int:
        return self._queue.qsize() + (1 if self._processing_peer is not None else 0)

    def has_peer(self, peer_id: int) -> bool:
        return peer_id in self._pending_peers

    async def enqueue(self, job: TryOnJob) -> int:
        """Add a job and return its 1-based position including the active job."""
        peer_id = job.peer_id
        if peer_id in self._pending_peers:
            raise DuplicateTryOnJob
        if self._queue.full():
            raise TryOnQueueFull

        self._pending_peers.add(peer_id)
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self._pending_peers.discard(peer_id)
            raise TryOnQueueFull from None

        position = self._queue.qsize() + (1 if self._processing_peer is not None else 0)
        self._ensure_worker()
        return position

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker(),
                name="vk-tryon-queue-worker",
            )

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            self._processing_peer = job.peer_id
            try:
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected queue worker failure for peer_id=%s", job.peer_id)
            finally:
                self._processing_peer = None
                self._pending_peers.discard(job.peer_id)
                self._queue.task_done()

    async def _process(self, job: TryOnJob) -> None:
        try:
            result_bytes = await asyncio.to_thread(
                apply_tryon,
                job.item,
                job.overlay_path,
                job.photo_bytes,
            )
        except TryOnError as exc:
            logger.info("Try-on failed for %s: %s", job.item.id, exc)
            await job.message.answer(str(exc))
            return
        except Exception:
            logger.exception("Unexpected try-on error for %s", job.item.id)
            await job.message.answer("Не получилось обработать это фото. Попробуйте другое.")
            return

        try:
            attachment = await upload_photo_for_message(
                job.bot.api,
                result_bytes,
                job.peer_id,
            )
            await job.message.answer(
                f"Вот как выглядит «{job.item.name}» 💍",
                attachment=attachment,
            )
        except Exception:
            logger.exception("Failed to upload try-on result for %s", job.item.id)
            await job.message.answer(
                "Примерка получилась, но не вышло отправить фото обратно 🙁 "
                "Попробуйте прислать это же фото ещё раз."
            )
            return

        await job.bot.state_dispenser.delete(job.peer_id)


tryon_queue = TryOnQueue()
