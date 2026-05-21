from __future__ import annotations

from typing import Any


def new_answer_stream_state(*, run_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": str(thread_id or ""),
        "turn_id": str(run_id or ""),
        "item_id": f"{str(run_id or 'turn')}:agent_message",
        "item_started": False,
        "item_completed": False,
        "trace_started_id": "",
        "trace_done_id": "",
        "text": "",
        "delta_count": 0,
        "delta_chars": 0,
        "text_delta_trace_count": 0,
        "calls": [],
        "started_at": 0.0,
        "finished_at": 0.0,
    }


def start_answer_stream_call(
    state: dict[str, Any],
    *,
    model: str,
    phase: str,
    tool_round: int,
) -> dict[str, Any]:
    call_state = {
        "index": len(list(state.get("calls") or [])) + 1,
        "model": str(model or ""),
        "phase": str(phase or ""),
        "tool_round": max(0, int(tool_round)),
        "event_count": 0,
        "text_delta_count": 0,
        "text_chars": 0,
        "first_event_at": 0.0,
        "first_text_delta_at": 0.0,
        "last_text_delta_at": 0.0,
        "completed_at": 0.0,
    }
    state.setdefault("calls", []).append(call_state)
    return call_state


def consume_stream_delta_for_display(state: dict[str, Any], delta: str) -> str:
    return str(delta or "")


def answer_stream_diagnostics(state: dict[str, Any]) -> dict[str, Any]:
    calls = [dict(item) for item in list(state.get("calls") or []) if isinstance(item, dict)]
    total_delta_count = int(state.get("delta_count") or 0)
    total_chars = int(state.get("delta_chars") or 0)
    upstream_progressive = total_delta_count > 1
    summary = "received streamed answer deltas" if total_delta_count else "no streamed answer deltas observed"
    return {
        "streamed": bool(total_delta_count),
        "upstream_progressive": upstream_progressive,
        "delta_count": total_delta_count,
        "text_chars": total_chars,
        "call_count": len(calls),
        "summary": summary,
        "calls": calls,
    }
