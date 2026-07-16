"""In-process async task queue for background processing."""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: Any = None


class TaskQueue:
    """Simple in-memory async task queue with at-most-once delivery."""

    def __init__(self, max_concurrent: int = 4) -> None:
        self._queue: asyncio.Queue[tuple[str, Callable[[], Coroutine[Any, Any, Any]]]] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._worker_task: asyncio.Task | None = None

    async def enqueue(self, task_id: str, name: str, coro_fn: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        task = Task(id=task_id, name=name)
        self._tasks[task_id] = task
        await self._queue.put((task_id, coro_fn))
        logger.debug("Task enqueued: id=%s, name=%s", task_id, name)

    async def _worker(self) -> None:
        while True:
            task_id, coro_fn = await self._queue.get()
            async with self._semaphore:
                task = self._tasks.get(task_id)
                if task:
                    task.status = TaskStatus.RUNNING
                    task.started_at = time.time()
                try:
                    result = await coro_fn()
                    if task:
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = time.time()
                        task.result = result
                    logger.info("Task completed: id=%s", task_id)
                except Exception as e:
                    if task:
                        task.status = TaskStatus.FAILED
                        task.completed_at = time.time()
                        task.error = str(e)
                    logger.error("Task failed: id=%s, error=%s", task_id, e)
            self._queue.task_done()

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("Task queue worker started (max_concurrent=%s)", self._max_concurrent)

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("Task queue worker stopped")

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def all_tasks(self) -> list[Task]:
        return list(self._tasks.values())


_task_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    return _task_queue
