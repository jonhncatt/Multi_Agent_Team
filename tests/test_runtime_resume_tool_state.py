from __future__ import annotations

from app.main import _build_run_snapshot, _logical_tool_state


def _event(call_id: str, status: str = "ok") -> dict:
    return {
        "name": "search_codebase",
        "raw_tool_call": {"id": call_id, "name": "search_codebase"},
        "status": status,
        "summary": f"{call_id}:{status}",
    }


def test_logical_tool_state_merges_resume_segments_by_tool_call_id() -> None:
    previous = {
        "logical_tool_count": 7,
        "logical_tool_event_ids": [f"call-{index}" for index in range(1, 8)],
        "logical_tool_events": [_event("call-7", "blocked")],
    }

    count, ids, recent = _logical_tool_state(
        previous,
        [_event("call-7", "ok"), _event("call-8", "ok")],
    )

    assert count == 8
    assert ids == [f"call-{index}" for index in range(1, 9)]
    assert [item["raw_tool_call"]["id"] for item in recent] == ["call-7", "call-8"]
    assert recent[0]["status"] == "ok"


def test_logical_tool_state_keeps_count_beyond_recent_timeline_limit() -> None:
    events = [_event(f"call-{index}") for index in range(30)]

    count, ids, recent = _logical_tool_state({}, events)

    assert count == 30
    assert len(ids) == 30
    assert len(recent) == 24
    assert recent[0]["raw_tool_call"]["id"] == "call-6"


def test_logical_tool_state_uses_call_id_for_typed_stream_items() -> None:
    previous = {
        "logical_tool_count": 1,
        "logical_tool_event_ids": ["call-1"],
        "logical_tool_events": [_event("call-1", "blocked")],
    }
    typed_item = {
        "id": "run-2:tool:1:1:call-1",
        "tool_call_id": "call-1",
        "type": "commandExecution",
        "tool": "exec_command",
        "status": "completed",
    }

    count, ids, _ = _logical_tool_state(previous, [typed_item])

    assert count == 1
    assert ids == ["call-1"]


def test_run_snapshot_optional_fields_have_patch_semantics() -> None:
    partial = _build_run_snapshot(
        goal="Continue",
        turn_status="running",
        cwd="/workspace",
    )

    assert partial == {
        "goal": "Continue",
        "turn_status": "running",
        "cwd": "/workspace",
    }

    cleared = _build_run_snapshot(
        goal="New turn",
        turn_status="running",
        cwd="/workspace",
        plan=[],
        pending_user_input={},
        pending_approval={},
        tool_count=0,
        evidence_status="not_needed",
        context_meter={},
        compaction_status={},
    )

    assert cleared["plan"] == []
    assert cleared["pending_user_input"] == {}
    assert cleared["pending_approval"] == {}
    assert cleared["tool_count"] == 0
    assert cleared["context_meter"] == {}
    assert cleared["compaction_status"] == {}
