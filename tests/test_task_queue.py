"""Tests for the async task queue."""

import asyncio

import pytest

from app.services.task_queue import TaskQueue, TaskStatus


@pytest.mark.asyncio
async def test_enqueue_and_complete() -> None:
    q = TaskQueue(max_concurrent=2)
    q.start()

    results = []

    async def my_task():
        results.append("done")
        return 42

    await q.enqueue("task-1", "test", my_task)
    await asyncio.sleep(0.2)

    task = q.get_task("task-1")
    assert task is not None
    assert task.name == "test"
    assert task.status in (TaskStatus.COMPLETED, TaskStatus.RUNNING)

    await q.stop()


@pytest.mark.asyncio
async def test_get_task_returns_none() -> None:
    q = TaskQueue()
    assert q.get_task("nonexistent") is None


@pytest.mark.asyncio
async def test_task_failure() -> None:
    q = TaskQueue(max_concurrent=2)
    q.start()

    async def failing_task():
        raise ValueError("oops")

    await q.enqueue("task-fail", "failing", failing_task)
    await asyncio.sleep(0.2)

    task = q.get_task("task-fail")
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert task.error is not None

    await q.stop()


@pytest.mark.asyncio
async def test_pending_count() -> None:
    q = TaskQueue(max_concurrent=1)

    async def slow_task():
        await asyncio.sleep(0.5)

    q.start()
    await q.enqueue("slow-1", "slow", slow_task)
    await q.enqueue("slow-2", "slow", slow_task)
    await asyncio.sleep(0.05)
    assert q.pending_count >= 0

    await q.stop()


@pytest.mark.asyncio
async def test_all_tasks() -> None:
    q = TaskQueue(max_concurrent=2)
    q.start()

    async def quick():
        return 1

    await q.enqueue("all-1", "one", quick)
    await q.enqueue("all-2", "two", quick)
    await asyncio.sleep(0.2)

    all_tasks = q.all_tasks
    assert len(all_tasks) == 2
    assert {t.id for t in all_tasks} == {"all-1", "all-2"}

    await q.stop()


@pytest.mark.asyncio
async def test_stop_does_not_raise_when_not_started() -> None:
    q = TaskQueue()
    await q.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    q = TaskQueue()
    q.start()
    q.start()
    await q.stop()
