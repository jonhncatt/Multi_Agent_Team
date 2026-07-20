from __future__ import annotations

from typing import Any


RUN_RECORD_SCHEMA_VERSION = 2

_TOOL_ITEM_TYPES = {
    "toolCall",
    "commandExecution",
    "fileChange",
    "userInputRequest",
    "imageView",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _status(value: Any) -> str:
    raw = _text(value).lower()
    aliases = {
        "needs_user_input": "waiting_user",
        "blocked": "failed",
        "success": "completed",
        "done": "completed",
    }
    normalized = aliases.get(raw, raw)
    if normalized in {"running", "waiting_user", "completed", "failed", "cancelled", "interrupted"}:
        return normalized
    return "completed" if normalized else "completed"


def _slim_inspector(raw: Any) -> dict[str, Any]:
    inspector = _dict(raw)
    if not inspector:
        return {}
    run_state = _dict(inspector.get("run_state"))
    for key in (
        "task_state",
        "task_state_delta",
        "task_state_validation",
        "thread_memory",
        "recent_tasks",
        "artifact_memory_preview",
        "current_turn",
        "active_task_focus",
        "current_task_focus",
        "task_checkpoint",
        "recent_user_messages",
        "model_draft",
        "final_answer",
        "runtime_error",
        "llm_exchanges",
        "trace_events",
        "plan",
        "pending_user_input",
        "pending_approval",
        "pending_turn",
        "task_completion",
        "thread_context",
    ):
        run_state.pop(key, None)
    session = _dict(inspector.get("session"))
    for key in (
        "task_state",
        "task_state_delta",
        "task_state_validation",
        "task_completion",
        "thread_memory",
        "recent_tasks",
        "artifact_memory_preview",
        "current_turn",
        "active_task_focus",
        "current_task_focus",
        "task_checkpoint",
        "recent_user_messages",
    ):
        session.pop(key, None)
    result: dict[str, Any] = {}
    for key in (
        "agent",
        "evidence",
        "token_usage",
        "active_context_usage",
        "available_skills",
        "loaded_skills",
        "notes",
    ):
        value = inspector.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    if run_state:
        result["run_state"] = run_state
    if session:
        result["session"] = session
    return result


def encode_run_record(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw or {})
    activity = _dict(payload.get("activity"))
    debug_raw = _dict(payload.get("debug"))
    details_raw = _dict(payload.get("details"))

    events = _list_of_dicts(payload.get("events") or payload.get("trace_events") or activity.get("trace_events"))
    items = _list_of_dicts(payload.get("items") or payload.get("live_items") or activity.get("live_items"))
    if not items:
        items = _list_of_dicts(payload.get("tool_items") or activity.get("tool_items"))

    details: dict[str, Any] = {}
    for key in (
        "triggering_user_message",
        "triggering_user_turn_id",
        "tool_boundary_clean",
        "plan",
        "plan_explanation",
        "answer_stream",
        "intermediate_turns",
        "steered_user_messages",
        "phase_timings",
    ):
        value = details_raw.get(key) if key in details_raw else activity.get(key)
        if value not in (None, "", [], {}):
            details[key] = value

    debug = {
        "llm_exchanges": _list_of_dicts(
            debug_raw.get("llm_exchanges")
            or payload.get("llm_exchanges")
            or activity.get("llm_exchanges")
        ),
        "model_draft": str(
            debug_raw.get("model_draft")
            or payload.get("model_draft")
            or activity.get("model_draft")
            or ""
        ),
        "final_answer": str(
            debug_raw.get("final_answer")
            or payload.get("final_answer")
            or activity.get("final_answer")
            or ""
        ),
        "runtime_error": _dict(
            debug_raw.get("runtime_error")
            or payload.get("runtime_error")
            or activity.get("runtime_error")
        ),
        "inspector": _slim_inspector(
            debug_raw.get("inspector")
            or payload.get("inspector")
            or activity.get("inspector")
        ),
    }
    debug = {key: value for key, value in debug.items() if value not in (None, "", [], {})}

    status = _status(payload.get("status") or payload.get("turn_status") or activity.get("status"))
    started_at = payload.get("started_at") if payload.get("started_at") not in (None, "") else activity.get("started_at")
    finished_at = payload.get("finished_at") if payload.get("finished_at") not in (None, "") else activity.get("finished_at")
    duration_ms = _int(payload.get("duration_ms") or activity.get("run_duration_ms"))
    summary = _text(
        payload.get("summary")
        or activity.get("summary")
        or activity.get("activity_summary")
    )
    return {
        "run_record_schema_version": RUN_RECORD_SCHEMA_VERSION,
        "session_id": _text(payload.get("session_id") or payload.get("thread_id")),
        "thread_id": _text(payload.get("thread_id") or payload.get("session_id")),
        "run_id": _text(payload.get("run_id")),
        "turn_id": _text(payload.get("turn_id")),
        "turn_created_at": _text(payload.get("turn_created_at")),
        "created_at": _text(payload.get("created_at")),
        "updated_at": _text(payload.get("updated_at")),
        "status": status,
        "started_at": started_at or 0.0,
        "finished_at": finished_at or 0.0,
        "duration_ms": duration_ms,
        "summary": summary,
        "model": _text(payload.get("model") or payload.get("effective_model")),
        "permission_profile": _text(payload.get("permission_profile")),
        "token_usage": _dict(payload.get("token_usage")),
        "answer_bundle": _dict(payload.get("answer_bundle")),
        "tool_events": _list_of_dicts(payload.get("tool_events") or activity.get("tool_events")),
        "items": items,
        "events": events,
        "details": details,
        "debug": debug,
    }


def hydrate_run_record(raw: dict[str, Any]) -> dict[str, Any]:
    record = encode_run_record(raw)
    details = _dict(record.get("details"))
    debug = _dict(record.get("debug"))
    items = _list_of_dicts(record.get("items"))
    events = _list_of_dicts(record.get("events"))
    activity = {
        "run_id": _text(record.get("run_id")),
        "status": _text(record.get("status")),
        "summary": _text(record.get("summary")),
        "activity_summary": _text(record.get("summary")),
        "started_at": record.get("started_at") or 0.0,
        "finished_at": record.get("finished_at") or 0.0,
        "run_duration_ms": _int(record.get("duration_ms")),
        "trace_events": events,
        "live_items": items,
        "tool_items": [
            dict(item)
            for item in items
            if str(item.get("type") or "") in _TOOL_ITEM_TYPES
        ],
        **details,
        "llm_exchanges": _list_of_dicts(debug.get("llm_exchanges")),
        "model_draft": str(debug.get("model_draft") or ""),
        "final_answer": str(debug.get("final_answer") or ""),
        "runtime_error": _dict(debug.get("runtime_error")),
    }
    record["activity"] = activity
    record["inspector"] = _dict(debug.get("inspector"))
    record["model_draft"] = str(debug.get("model_draft") or "")
    record["final_answer"] = str(debug.get("final_answer") or "")
    record["runtime_error"] = _dict(debug.get("runtime_error"))
    record["llm_exchanges"] = _list_of_dicts(debug.get("llm_exchanges"))
    record["trace_events"] = events
    record["live_items"] = items
    record["tool_items"] = list(activity["tool_items"])
    return record
