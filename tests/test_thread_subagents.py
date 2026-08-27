from __future__ import annotations

from pathlib import Path
import threading

from app.thread_subagents import ThreadSubagentManager


def _queued_item(subagent_id: str) -> dict[str, object]:
    return {
        "id": subagent_id,
        "type": "subagent",
        "status": "queued",
        "role": "explorer",
        "label": "Inspect lifecycle",
        "task": "Inspect the lifecycle.",
        "summary": "",
        "queued_at": 1.0,
    }


def _create(manager: ThreadSubagentManager, *, thread_id: str, subagent_id: str) -> None:
    manager.create(
        thread_id=thread_id,
        subagent_id=subagent_id,
        parent_run_id="run-1",
        role="explorer",
        item=_queued_item(subagent_id),
        cancel_event=threading.Event(),
    )


def test_thread_subagent_result_is_idempotent_and_terminal_state_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    manager = ThreadSubagentManager(tmp_path / "subagents", runtime_id="runtime-a")
    subagent_id = "run-1:subagent:one"
    _create(manager, thread_id="thread-a", subagent_id=subagent_id)
    completed_item = {
        **_queued_item(subagent_id),
        "status": "completed",
        "summary": "Completed finding.",
        "completed_at": 2.0,
    }
    completed_result = {
        "ok": True,
        "subagent_id": subagent_id,
        "role": "explorer",
        "status": "completed",
        "summary": "Completed finding.",
        "token_usage": {"total_tokens": 17},
    }

    assert manager.finish(
        thread_id="thread-a",
        subagent_id=subagent_id,
        status="completed",
        item=completed_item,
        result=completed_result,
    ) is True
    assert manager.finish(
        thread_id="thread-a",
        subagent_id=subagent_id,
        status="cancelled",
        item={**completed_item, "status": "cancelled"},
        result={**completed_result, "ok": False, "status": "cancelled"},
        detached=True,
    ) is False

    first_result, first_usage = manager.collect(thread_id="thread-a", subagent_id=subagent_id)
    reloaded_manager = ThreadSubagentManager(
        tmp_path / "subagents",
        runtime_id="runtime-after-reload",
    )
    second_result, second_usage = reloaded_manager.collect(
        thread_id="thread-a",
        subagent_id=subagent_id,
    )

    assert first_result == second_result == completed_result
    assert first_usage == {"total_tokens": 17}
    assert second_usage == {}
    records, unknown_ids = manager.records(
        thread_id="thread-a",
        subagent_ids=[subagent_id],
    )
    assert unknown_ids == []
    assert records[0]["status"] == "completed"


def test_thread_subagent_ids_are_isolated_by_thread(tmp_path: Path) -> None:
    manager = ThreadSubagentManager(tmp_path / "subagents", runtime_id="runtime-a")
    subagent_id = "run-1:subagent:isolated"
    _create(manager, thread_id="thread-a", subagent_id=subagent_id)

    records, unknown_ids = manager.records(
        thread_id="thread-b",
        subagent_ids=[subagent_id],
    )

    assert records == []
    assert unknown_ids == [subagent_id]


def test_active_subagent_is_marked_interrupted_after_runtime_restart(tmp_path: Path) -> None:
    state_root = tmp_path / "subagents"
    first_runtime = ThreadSubagentManager(state_root, runtime_id="runtime-before-restart")
    subagent_id = "run-1:subagent:restart"
    _create(first_runtime, thread_id="thread-a", subagent_id=subagent_id)
    assert first_runtime.mark_running(
        thread_id="thread-a",
        subagent_id=subagent_id,
        item={**_queued_item(subagent_id), "status": "inProgress", "started_at": 2.0},
    ) is True

    restarted_runtime = ThreadSubagentManager(state_root, runtime_id="runtime-after-restart")
    records, unknown_ids = restarted_runtime.records(
        thread_id="thread-a",
        subagent_ids=[subagent_id],
    )

    assert unknown_ids == []
    assert records[0]["status"] == "interrupted_by_restart"
    assert records[0]["result"]["error_kind"] == "subagent_interrupted_by_restart"
    result, usage = restarted_runtime.collect(thread_id="thread-a", subagent_id=subagent_id)
    assert result is not None
    assert result["status"] == "interrupted_by_restart"
    assert usage == {}

    another_runtime = ThreadSubagentManager(state_root, runtime_id="runtime-after-second-restart")
    persisted, unknown_ids = another_runtime.records(
        thread_id="thread-a",
        subagent_ids=[subagent_id],
    )
    assert unknown_ids == []
    assert persisted[0]["status"] == "interrupted_by_restart"


def test_cancelled_subagent_remains_queryable_after_a_later_agent_run(tmp_path: Path) -> None:
    state_root = tmp_path / "subagents"
    manager = ThreadSubagentManager(state_root, runtime_id="runtime-a")
    subagent_id = "run-1:subagent:cancelled"
    _create(manager, thread_id="thread-a", subagent_id=subagent_id)
    message = "Subagent was cancelled because its parent run ended."
    cancelled_result = {
        "ok": False,
        "subagent_id": subagent_id,
        "role": "explorer",
        "status": "cancelled",
        "error_kind": "subagent_cancelled",
        "error": message,
        "summary": message,
        "token_usage": {},
    }
    assert manager.finish(
        thread_id="thread-a",
        subagent_id=subagent_id,
        status="cancelled",
        item={**_queued_item(subagent_id), "status": "cancelled", "summary": message},
        result=cancelled_result,
        detached=True,
    ) is True

    later_run_manager = ThreadSubagentManager(state_root, runtime_id="runtime-b")
    records, unknown_ids = later_run_manager.records(
        thread_id="thread-a",
        subagent_ids=[subagent_id],
    )
    assert unknown_ids == []
    assert records[0]["status"] == "cancelled"
    result, _ = later_run_manager.collect(thread_id="thread-a", subagent_id=subagent_id)
    assert result == cancelled_result
