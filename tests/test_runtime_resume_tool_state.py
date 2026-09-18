from __future__ import annotations

from app.main import _logical_tool_state


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

