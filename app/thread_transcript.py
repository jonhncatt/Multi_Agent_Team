from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Iterable
import uuid


THREAD_TRANSCRIPT_SCHEMA_VERSION = 2
_ROLES = {"user", "assistant", "tool"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in list(raw or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        call_id = str(item.get("id") or "").strip()
        args = item.get("args")
        if args is None:
            args = item.get("arguments")
        if isinstance(args, str):
            try:
                decoded = json.loads(args)
            except Exception:
                decoded = {"raw": args}
            args = decoded
        if not isinstance(args, dict):
            args = {"value": args} if args is not None else {}
        if not name:
            continue
        calls.append(
            {
                "id": call_id or f"call_{uuid.uuid4().hex}",
                "name": name,
                "args": args,
                "type": "tool_call",
            }
        )
    return calls


def _normalize_trace_summary(raw: Any) -> dict[str, Any]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    if not payload:
        return {}
    summary: dict[str, Any] = {}
    for key in ("trace_ref", "status"):
        value = str(payload.get(key) or "").strip()
        if value:
            summary[key] = value
    for key in ("duration_ms", "tool_count"):
        if payload.get(key) in (None, ""):
            continue
        try:
            summary[key] = max(0, int(payload.get(key) or 0))
        except Exception:
            continue
    return summary


def normalize_transcript_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip().lower()
    if role == "human":
        role = "user"
    elif role in {"ai", "model"}:
        role = "assistant"
    if role not in _ROLES:
        return None
    content = _text(raw.get("content") if "content" in raw else raw.get("text"))
    item: dict[str, Any] = {
        "id": str(raw.get("id") or uuid.uuid4()).strip(),
        "role": role,
        "content": content,
        "created_at": str(raw.get("created_at") or _now_iso()),
    }
    turn_id = str(raw.get("turn_id") or "").strip()
    if turn_id:
        item["turn_id"] = turn_id
    if role == "assistant":
        tool_calls = _normalize_tool_calls(raw.get("tool_calls"))
        if tool_calls:
            item["tool_calls"] = tool_calls
        trace = _normalize_trace_summary(raw.get("trace") or raw.get("run"))
        if trace:
            item["trace"] = trace
    elif role == "tool":
        tool_call_id = str(raw.get("tool_call_id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not tool_call_id:
            return None
        item["tool_call_id"] = tool_call_id
        if name:
            item["name"] = name
    attachments = [
        {
            "id": str(meta.get("id") or "").strip(),
            "name": str(meta.get("name") or "").strip(),
        }
        for meta in list(raw.get("attachments") or [])
        if isinstance(meta, dict) and (str(meta.get("id") or "").strip() or str(meta.get("name") or "").strip())
    ]
    if attachments and role == "user":
        item["attachments"] = attachments
    return item


def transcript_from_legacy_turns(turns: Iterable[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in list(turns or []):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        turn_id = str(raw.get("id") or uuid.uuid4()).strip()
        item = normalize_transcript_item(
            {
                "id": turn_id,
                "turn_id": turn_id,
                "role": role,
                "content": raw.get("text") if "text" in raw else raw.get("content"),
                "attachments": raw.get("attachments") or [],
                "created_at": raw.get("created_at") or "",
            }
        )
        if item is not None:
            items.append(item)
    return items


def default_thread_transcript() -> dict[str, Any]:
    return {
        "schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
        "items": [],
    }


def normalize_thread_transcript(
    raw: Any,
    *,
    legacy_turns: Iterable[Any] | None = None,
) -> dict[str, Any]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items = [item for item in (normalize_transcript_item(value) for value in raw_items) if item is not None]
    if not items and legacy_turns:
        items = transcript_from_legacy_turns(legacy_turns)
    return {
        "schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
        "items": items,
    }


def migrate_session_to_thread_transcript(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    payload = dict(session or {})
    legacy_turns: Iterable[Any] = payload.get("turns") if isinstance(payload.get("turns"), list) else []
    if not legacy_turns and isinstance(payload.get("history_turns"), list):
        legacy_turns = payload.get("history_turns") or []
    if not legacy_turns and isinstance(payload.get("messages"), list):
        legacy_turns = payload.get("messages") or []
    raw_manager = payload.get("context_manager") if isinstance(payload.get("context_manager"), dict) else {}
    using_manager_history = not bool(legacy_turns)
    if not legacy_turns and isinstance(raw_manager.get("recent_turns"), list):
        legacy_turns = raw_manager.get("recent_turns") or []
    if not legacy_turns and isinstance(raw_manager.get("clean_turns"), list):
        legacy_turns = raw_manager.get("clean_turns") or []
    normalized = normalize_thread_transcript(
        payload.get("thread_transcript"),
        legacy_turns=legacy_turns,
    )
    try:
        existing_schema_version = int(payload.get("thread_schema_version") or 0)
    except Exception:
        existing_schema_version = 0
    changed = (
        payload.get("thread_transcript") != normalized
        or existing_schema_version != THREAD_TRANSCRIPT_SCHEMA_VERSION
    )
    payload["thread_transcript"] = normalized
    payload["thread_schema_version"] = THREAD_TRANSCRIPT_SCHEMA_VERSION
    legacy_summary = str(raw_manager.get("working_summary") or raw_manager.get("clean_summary") or "").strip()
    if legacy_summary and using_manager_history:
        compaction_state = dict(payload.get("compaction_state") or {})
        if not str(compaction_state.get("compacted_history") or "").strip():
            compaction_state["compacted_history"] = legacy_summary
            compaction_state.setdefault("compaction_source", "legacy_context_manager")
            payload["compaction_state"] = compaction_state
            changed = True
    return payload, changed


def append_transcript_item(
    transcript: dict[str, Any],
    *,
    role: str,
    content: str,
    item_id: str | None = None,
    turn_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str = "",
    name: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    item = normalize_transcript_item(
        {
            "id": item_id or str(uuid.uuid4()),
            "turn_id": turn_id or "",
            "role": role,
            "content": content,
            "attachments": attachments or [],
            "tool_calls": tool_calls or [],
            "tool_call_id": tool_call_id,
            "name": name,
            "created_at": created_at or _now_iso(),
        }
    )
    if item is None:
        raise ValueError(f"Invalid transcript item role={role!r}")
    transcript.setdefault("schema_version", THREAD_TRANSCRIPT_SCHEMA_VERSION)
    transcript.setdefault("items", []).append(item)
    return item


def append_transcript_items(transcript: dict[str, Any], items: Iterable[Any]) -> list[dict[str, Any]]:
    appended: list[dict[str, Any]] = []
    for raw in list(items or []):
        item = normalize_transcript_item(raw)
        if item is None:
            continue
        transcript.setdefault("items", []).append(item)
        appended.append(item)
    transcript["schema_version"] = THREAD_TRANSCRIPT_SCHEMA_VERSION
    return appended


def transcript_items_after_compaction(
    transcript: dict[str, Any] | None,
    compaction_state: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    normalized = normalize_thread_transcript(transcript)
    items = list(normalized.get("items") or [])
    state = dict(compaction_state or {})
    summary = str(state.get("compacted_history") or "").strip()
    through_id = str(
        state.get("compacted_until_item_id")
        or state.get("compacted_until_turn_id")
        or ""
    ).strip()
    if not summary:
        return "", items
    if not through_id:
        return summary, items
    compacted_index = -1
    for index, item in enumerate(items):
        if through_id in {str(item.get("id") or ""), str(item.get("turn_id") or "")}:
            compacted_index = index
    if compacted_index < 0:
        return "", items
    return summary, items[compacted_index + 1 :]
