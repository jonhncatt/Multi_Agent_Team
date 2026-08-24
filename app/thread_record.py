from __future__ import annotations

from typing import Any

from app.thread_transcript import (
    THREAD_TRANSCRIPT_SCHEMA_VERSION,
    normalize_turn_changes_summary,
    normalize_thread_transcript,
)


THREAD_RECORD_SCHEMA_VERSION = 6


def _text(value: Any) -> str:
    return str(value or "").strip()


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _legacy_summary(payload: dict[str, Any]) -> str:
    context_manager = _dict(payload.get("context_manager"))
    thread_memory = _dict(payload.get("thread_memory"))
    compaction_status = _dict(payload.get("compaction_status"))
    return _text(
        payload.get("summary")
        or context_manager.get("working_summary")
        or context_manager.get("clean_summary")
        or thread_memory.get("summary")
        or compaction_status.get("summary")
    )


def _legacy_active_attachment_ids(payload: dict[str, Any]) -> list[str]:
    values: list[Any] = list(payload.get("active_attachment_ids") or [])
    containers = [
        _dict(payload.get("work_cursor")),
        _dict(payload.get("current_task_focus")),
        _dict(payload.get("active_task_focus")),
        _dict(_dict(payload.get("route_state")).get("task_checkpoint")),
    ]
    agent_state = _dict(payload.get("agent_state"))
    containers.extend(
        [
            _dict(agent_state.get("current_task_focus")),
            _dict(agent_state.get("task_checkpoint")),
        ]
    )
    for container in containers:
        values.extend(list(container.get("active_attachments") or []))
    ids: list[str] = []
    for item in values:
        value = _text(item.get("id") if isinstance(item, dict) else item)
        if value and value not in ids:
            ids.append(value)
    return ids


def normalize_compaction(raw: Any, *, legacy_summary: str = "") -> dict[str, Any]:
    payload = _dict(raw)
    summary = _text(
        payload.get("summary")
        or payload.get("compacted_history")
        or legacy_summary
    )
    compacted_until_item_id = _text(
        payload.get("compacted_until_item_id")
        or payload.get("compacted_until_turn_id")
    )
    compacted_at = _text(
        payload.get("compacted_at")
        or payload.get("last_compacted_at")
    )
    try:
        generation = max(0, int(payload.get("generation") or 0))
    except Exception:
        generation = 0
    if not (summary or compacted_until_item_id or compacted_at or generation):
        return {}
    return {
        "generation": generation,
        "summary": summary,
        "compacted_until_item_id": compacted_until_item_id,
        "compacted_at": compacted_at,
    }


def compaction_state_compat(compaction: Any) -> dict[str, Any]:
    payload = normalize_compaction(compaction)
    return {
        "generation": int(payload.get("generation") or 0),
        "compacted_history": _text(payload.get("summary")),
        "compacted_until_turn_id": _text(payload.get("compacted_until_item_id")),
        "last_compacted_at": _text(payload.get("compacted_at")),
    }


def normalize_pending_interaction(raw: Any) -> dict[str, Any]:
    payload = _dict(raw)
    pending_turn = _dict(payload.get("turn") or payload.get("pending_turn"))
    user_input = _dict(payload.get("user_input") or payload.get("pending_user_input"))
    approval = _dict(payload.get("approval") or payload.get("pending_approval"))
    interaction_type = _text(payload.get("type") or pending_turn.get("type") or approval.get("type"))
    if not (pending_turn or user_input or approval):
        return {}
    return {
        "type": interaction_type,
        "turn": pending_turn,
        "user_input": user_input,
        "approval": approval,
    }


def pending_interaction_from_session(session: dict[str, Any]) -> dict[str, Any]:
    current = normalize_pending_interaction(session.get("pending_interaction"))
    if current:
        return current
    agent_state = _dict(session.get("agent_state"))
    return normalize_pending_interaction(
        {
            "pending_turn": agent_state.get("pending_turn"),
            "pending_user_input": agent_state.get("pending_user_input"),
            "pending_approval": agent_state.get("pending_approval"),
        }
    )


def agent_state_compat(session: dict[str, Any]) -> dict[str, Any]:
    pending = pending_interaction_from_session(session)
    pending_turn = _dict(pending.get("turn"))
    return {
        "agent_id": "vintage_programmer",
        "phase": "waiting_user" if pending else "idle",
        "turn_status": "needs_user_input" if pending else "idle",
        "last_run_id": _text(session.get("latest_run_id")),
        "pending_turn": pending_turn,
        "pending_user_input": _dict(pending.get("user_input")),
        "pending_approval": _dict(pending.get("approval")),
        "plan": _list_of_dicts(pending_turn.get("plan"))[:12],
    }


def _run_summary_from_activity(activity: Any) -> dict[str, Any]:
    payload = _dict(activity)
    if not payload:
        return {}
    summary: dict[str, Any] = {}
    for key in ("run_id", "trace_ref", "status", "summary", "activity_summary"):
        value = payload.get(key)
        if _text(value):
            summary[key] = str(value)
    for source_key, target_key in (("run_duration_ms", "duration_ms"), ("tool_count", "tool_count")):
        if payload.get(source_key) in (None, ""):
            continue
        try:
            summary[target_key] = max(0, int(payload.get(source_key) or 0))
        except Exception:
            continue
    turn_changes = normalize_turn_changes_summary(payload.get("turn_changes"))
    if turn_changes:
        summary["turn_changes"] = turn_changes
    subagents = _list_of_dicts(payload.get("subagents"))
    if not subagents:
        subagents = [
            dict(item)
            for item in _list_of_dicts(payload.get("live_items"))
            if _text(item.get("type")) == "subagent"
        ]
    if subagents:
        summary["subagents"] = subagents[:16]
    return summary


def attach_legacy_turn_metadata(
    transcript: dict[str, Any],
    legacy_turns: Any,
) -> dict[str, Any]:
    turns_by_id = {
        _text(item.get("id")): item
        for item in _list_of_dicts(legacy_turns)
        if _text(item.get("id"))
    }
    items: list[dict[str, Any]] = []
    for raw_item in list((transcript or {}).get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        if str(item.get("role") or "") == "assistant" and not isinstance(item.get("trace"), dict):
            legacy = turns_by_id.get(_text(item.get("id")))
            if legacy:
                run = _run_summary_from_activity(legacy.get("activity"))
                if run:
                    item["trace"] = run
        items.append(item)
    return {
        "schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
        "items": items,
    }


def project_turns_from_thread(session: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = normalize_thread_transcript(session.get("thread_transcript"))
    turns: list[dict[str, Any]] = []
    for item in list(transcript.get("items") or []):
        if bool(item.get("model_only")):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "assistant" and not content.strip():
            continue
        if role not in {"user", "assistant"}:
            continue
        run = _dict(item.get("trace") or item.get("run")) if role == "assistant" else {}
        turn_changes = normalize_turn_changes_summary(run.get("turn_changes"))
        activity = {
            **({"run_id": _text(run.get("run_id"))} if _text(run.get("run_id")) else {}),
            **({"trace_ref": _text(run.get("trace_ref"))} if _text(run.get("trace_ref")) else {}),
            "status": _text(run.get("status")) or ("completed" if role == "assistant" else "idle"),
            **({"summary": _text(run.get("summary"))} if _text(run.get("summary")) else {}),
            **(
                {"activity_summary": _text(run.get("activity_summary"))}
                if _text(run.get("activity_summary"))
                else {}
            ),
            **({"tool_count": max(0, int(run.get("tool_count") or 0))} if run else {}),
            **({"run_duration_ms": max(0, int(run.get("duration_ms") or 0))} if run else {}),
            **({"turn_changes": turn_changes} if turn_changes else {}),
            **(
                {"live_items": _list_of_dicts(run.get("subagents"))}
                if _list_of_dicts(run.get("subagents"))
                else {}
            ),
        }
        turns.append(
            {
                "id": _text(item.get("id")),
                "role": role,
                "text": content,
                "attachments": _list_of_dicts(item.get("attachments")),
                "answer_bundle": {},
                "activity": activity,
                "created_at": _text(item.get("created_at")),
            }
        )

    pending = pending_interaction_from_session(session)
    if pending:
        pending_turn = _dict(pending.get("turn"))
        pending_input = _dict(pending.get("user_input"))
        pending_approval = _dict(pending.get("approval"))
        summary = _text(
            pending_input.get("summary")
            or pending_approval.get("summary")
            or "Waiting for user input."
        )
        turns.append(
            {
                "id": f"pending-{_text(pending_turn.get('turn_id')) or _text(pending_turn.get('tool_call_id')) or 'interaction'}",
                "role": "runtime",
                "text": summary,
                "attachments": [],
                "answer_bundle": {},
                "activity": {
                    "status": "needs_user_input",
                    "run_id": _text(pending_turn.get("turn_id")),
                },
                "created_at": _text(pending_turn.get("created_at")),
            }
        )
    return turns


def hydrate_thread_record(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw or {})
    compaction = normalize_compaction(
        payload.get("compaction_state") or payload.get("compaction") or payload.get("compaction_status"),
        legacy_summary=_legacy_summary(payload),
    )
    payload["thread_record_schema_version"] = THREAD_RECORD_SCHEMA_VERSION
    payload["compaction"] = compaction
    payload["compaction_state"] = compaction_state_compat(compaction)
    payload["summary"] = _text(compaction.get("summary"))
    payload["auto_title"] = _text(payload.get("auto_title"))
    payload["title_generation"] = _dict(payload.get("title_generation"))
    payload["pinned"] = bool(payload.get("pinned"))
    payload["pin_updated_at"] = _text(payload.get("pin_updated_at"))
    payload["active_attachment_ids"] = _legacy_active_attachment_ids(payload)
    payload["pending_interaction"] = pending_interaction_from_session(payload)
    payload.pop("agent_state", None)
    return payload


def encode_thread_record(session: dict[str, Any]) -> dict[str, Any]:
    payload = hydrate_thread_record(session)
    transcript = normalize_thread_transcript(
        payload.get("thread_transcript"),
        legacy_turns=payload.get("turns") or [],
    )
    compaction = normalize_compaction(
        payload.get("compaction_state") or payload.get("compaction"),
        legacy_summary=_legacy_summary(payload),
    )
    pending = pending_interaction_from_session(payload)
    record = {
        "thread_record_schema_version": THREAD_RECORD_SCHEMA_VERSION,
        "id": _text(payload.get("id")),
        "created_at": _text(payload.get("created_at")),
        "updated_at": _text(payload.get("updated_at")),
        "activity_at": _text(payload.get("activity_at")),
        "activity_revision": max(0, int(payload.get("activity_revision") or 0)),
        "activity_kind": _text(payload.get("activity_kind")),
        "title": str(payload.get("title") or ""),
        "auto_title": _text(payload.get("auto_title")),
        "title_generation": _dict(payload.get("title_generation")),
        "pinned": bool(payload.get("pinned")),
        "pin_updated_at": _text(payload.get("pin_updated_at")),
        "project_id": _text(payload.get("project_id")),
        "project_title": str(payload.get("project_title") or ""),
        "project_root": str(payload.get("project_root") or ""),
        "git_branch": str(payload.get("git_branch") or ""),
        "cwd": str(payload.get("cwd") or payload.get("project_root") or ""),
        "thread_transcript": transcript,
        "thread_schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
        "active_attachment_ids": _legacy_active_attachment_ids(payload),
        "attachment_context_cleared": bool(payload.get("attachment_context_cleared")),
        "compaction": compaction,
        "pending_interaction": pending,
    }
    return record
