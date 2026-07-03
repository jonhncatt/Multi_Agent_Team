import threading
import time

from app.main import AgentRunQueue


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
