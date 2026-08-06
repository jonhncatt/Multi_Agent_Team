import threading
import time

import pytest

from app.main import AgentRunQueue, AgentRunQueueCancelled


def test_agent_run_queue_allows_different_sessions_to_run_concurrently() -> None:
    queue = AgentRunQueue(max_concurrent_runs=2)

    with queue.run_slot("thread-a") as first:
        with queue.run_slot("thread-b") as second:
            assert first.waited is False
            assert second.waited is False


def test_agent_run_queue_serializes_same_session() -> None:
    queue = AgentRunQueue(max_concurrent_runs=2)
    first = queue.run_slot("thread-a")
    acquired = threading.Event()
    result: dict[str, object] = {}

    def worker() -> None:
        with queue.run_slot("thread-a") as second:
            result["waited"] = second.waited
            result["wait_ms"] = second.wait_ms
            acquired.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        time.sleep(0.05)
        assert acquired.is_set() is False
    finally:
        first.release()
        thread.join(timeout=1)

    assert acquired.is_set() is True
    assert result["waited"] is True
    assert int(result["wait_ms"]) > 0


def test_agent_run_queue_reports_queued_before_capacity_is_available() -> None:
    queue = AgentRunQueue(max_concurrent_runs=1)
    first = queue.run_slot("thread-a")
    queued = threading.Event()
    acquired = threading.Event()
    queue_states: list[dict[str, object]] = []

    def worker() -> None:
        with queue.run_slot(
            "thread-b",
            on_queued=lambda state: (queue_states.append(dict(state)), queued.set()),
        ) as second:
            assert second.waited is True
            acquired.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert queued.wait(timeout=1)
        assert acquired.is_set() is False
        assert len(queue_states) == 1
        assert queue_states[0]["reason"] == "capacity"
        assert queue_states[0]["active_count"] == 1
        assert queue_states[0]["waiting_count"] == 1
        assert queue_states[0]["max_concurrent_runs"] == 1
        assert float(queue_states[0]["queued_at"]) > 0
    finally:
        first.release()
        thread.join(timeout=1)

    assert acquired.is_set() is True


def test_agent_run_queue_cancels_while_waiting_without_taking_a_slot() -> None:
    queue = AgentRunQueue(max_concurrent_runs=1)
    first = queue.run_slot("thread-a")
    cancel_event = threading.Event()
    queued = threading.Event()
    finished = threading.Event()
    result: dict[str, object] = {}

    def worker() -> None:
        try:
            queue.run_slot(
                "thread-b",
                cancel_event=cancel_event,
                on_queued=lambda _state: queued.set(),
            )
        except AgentRunQueueCancelled as exc:
            result["wait_ms"] = exc.wait_ms
        finally:
            finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert queued.wait(timeout=1)
        cancel_event.set()
        assert finished.wait(timeout=1)
        assert int(result["wait_ms"]) >= 0
        with pytest.raises(AgentRunQueueCancelled):
            queue.run_slot("thread-c", cancel_event=cancel_event)
    finally:
        first.release()
        thread.join(timeout=1)

    with queue.run_slot("thread-c") as ticket:
        assert ticket.waited is False
