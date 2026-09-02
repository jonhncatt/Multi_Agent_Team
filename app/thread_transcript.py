from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
from typing import Any, Iterable
import uuid


THREAD_TRANSCRIPT_SCHEMA_VERSION = 3
_ROLES = {"user", "assistant", "tool"}
_TURN_CHANGE_FILE_LIMIT = 64
_TURN_CHANGE_PATH_LIMIT = 1000
_TURN_CHANGE_SUMMARY_LIMIT = 300


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


def normalize_turn_changes_summary(raw: Any) -> dict[str, Any]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    files: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for entry in list(payload.get("files") or []):
        value = (
            {"path": entry}
            if isinstance(entry, str)
            else (dict(entry) if isinstance(entry, dict) else {})
        )
        path = str(value.get("path") or "").strip()[:_TURN_CHANGE_PATH_LIMIT]
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        files.append(
            {
                "path": path,
                "kind": str(value.get("kind") or "modified").strip()[:40] or "modified",
            }
        )
        if len(files) >= _TURN_CHANGE_FILE_LIMIT:
            break
    try:
        count = max(len(files), int(payload.get("count") or 0))
    except Exception:
        count = len(files)
    verification_payload = (
        dict(payload.get("verification") or {})
        if isinstance(payload.get("verification"), dict)
        else {}
    )
    verification = {
        key: value
        for key, value in {
            "status": str(verification_payload.get("status") or "").strip()[:40],
            "tool": str(verification_payload.get("tool") or "").strip()[:80],
            "summary": str(verification_payload.get("summary") or "").strip()[
                :_TURN_CHANGE_SUMMARY_LIMIT
            ],
        }.items()
        if value
    }
    retained = bool(payload.get("retained"))
    possible_untracked_changes = bool(payload.get("possible_untracked_changes"))
    if not count and not retained and not possible_untracked_changes and not verification:
        return {}
    return {
        "files": files,
        "count": count,
        "retained": retained,
        "possible_untracked_changes": possible_untracked_changes,
        "verification": verification,
    }


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
    turn_changes = normalize_turn_changes_summary(payload.get("turn_changes"))
    if turn_changes:
        summary["turn_changes"] = turn_changes
    subagents: list[dict[str, Any]] = []
    for raw_item in list(payload.get("subagents") or []):
        if not isinstance(raw_item, dict):
            continue
        subagent_id = str(raw_item.get("id") or raw_item.get("subagent_id") or "").strip()
        if not subagent_id:
            continue
        item = {
            "id": subagent_id,
            "type": "subagent",
            "status": str(raw_item.get("status") or "queued").strip() or "queued",
            "role": str(raw_item.get("role") or "explorer").strip() or "explorer",
            "label": str(raw_item.get("label") or "").strip()[:240],
            "task": str(raw_item.get("task") or "").strip()[:1000],
            "summary": str(raw_item.get("summary") or "").strip()[:2000],
        }
        for key in ("queued_at", "started_at", "completed_at", "tool_count"):
            if raw_item.get(key) not in (None, ""):
                item[key] = raw_item.get(key)
        subagents.append(item)
        if len(subagents) >= 16:
            break
    if subagents:
        summary["subagents"] = subagents
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
    task_context = raw.get("task_context")
    if role == "user" and isinstance(task_context, dict) and task_context:
        item["task_context"] = dict(task_context)
    if bool(raw.get("model_only")):
        item["model_only"] = True
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
        "deferred_items": [],
    }


def _pending_tool_calls_after(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the open tool-call batch at the end of a canonical transcript."""
    pending: dict[str, dict[str, Any]] = {}
    for item in list(items or []):
        role = str(item.get("role") or "")
        if pending:
            if role != "tool":
                break
            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if tool_call_id not in pending:
                break
            pending.pop(tool_call_id, None)
            continue
        if role != "assistant":
            continue
        for call in list(item.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            if call_id:
                pending[call_id] = dict(call)
    return pending


def _append_with_tool_barrier(
    canonical: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
    incoming: Iterable[dict[str, Any]],
) -> None:
    """Append transcript items without interleaving messages into a tool batch.

    An Assistant message containing tool calls opens a protocol transaction.
    Until every matching Tool message arrives, unrelated model-visible messages
    are retained in a FIFO mailbox.  Closing the batch flushes that mailbox at
    the first valid model boundary.
    """
    pending = _pending_tool_calls_after(canonical)
    completed_tool_call_ids = {
        str(item.get("tool_call_id") or "").strip()
        for item in canonical
        if str(item.get("role") or "") == "tool"
        and str(item.get("tool_call_id") or "").strip()
    }
    queue = deque(dict(item) for item in list(incoming or []))
    while queue:
        item = queue.popleft()
        role = str(item.get("role") or "")
        tool_call_id = str(item.get("tool_call_id") or "").strip()
        if role == "tool" and tool_call_id in completed_tool_call_ids:
            # Approval retries and post-execution persistence may submit the
            # same result twice. Tool call ids are unique within a Thread.
            continue
        if pending:
            if role == "tool" and tool_call_id in pending:
                canonical.append(item)
                completed_tool_call_ids.add(tool_call_id)
                pending.pop(tool_call_id, None)
                if not pending and deferred:
                    queued_before_current_input = list(deferred)
                    deferred.clear()
                    queue.extendleft(reversed(queued_before_current_input))
                continue
            deferred.append(item)
            continue

        canonical.append(item)
        if role == "assistant":
            pending = {
                str(call.get("id") or "").strip(): dict(call)
                for call in list(item.get("tool_calls") or [])
                if isinstance(call, dict) and str(call.get("id") or "").strip()
            }


def pending_tool_calls(transcript: dict[str, Any] | None) -> list[dict[str, Any]]:
    normalized = normalize_thread_transcript(transcript)
    return list(_pending_tool_calls_after(normalized.get("items") or []).values())


def normalize_thread_transcript(
    raw: Any,
    *,
    legacy_turns: Iterable[Any] | None = None,
) -> dict[str, Any]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items = [item for item in (normalize_transcript_item(value) for value in raw_items) if item is not None]
    raw_deferred = payload.get("deferred_items") if isinstance(payload.get("deferred_items"), list) else []
    deferred_items = [
        item
        for item in (normalize_transcript_item(value) for value in raw_deferred)
        if item is not None
    ]
    if not items and legacy_turns:
        items = transcript_from_legacy_turns(legacy_turns)
    canonical: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    _append_with_tool_barrier(canonical, deferred, items)
    _append_with_tool_barrier(canonical, deferred, deferred_items)
    return {
        "schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
        "items": canonical,
        "deferred_items": deferred,
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
    task_context: dict[str, Any] | None = None,
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
            "task_context": task_context or {},
            "tool_calls": tool_calls or [],
            "tool_call_id": tool_call_id,
            "name": name,
            "created_at": created_at or _now_iso(),
        }
    )
    if item is None:
        raise ValueError(f"Invalid transcript item role={role!r}")
    append_transcript_items(transcript, [item])
    return item


def append_transcript_items(transcript: dict[str, Any], items: Iterable[Any]) -> list[dict[str, Any]]:
    normalized_transcript = normalize_thread_transcript(transcript)
    transcript.clear()
    transcript.update(normalized_transcript)
    appended: list[dict[str, Any]] = []
    for raw in list(items or []):
        item = normalize_transcript_item(raw)
        if item is None:
            continue
        appended.append(item)
    canonical = transcript.setdefault("items", [])
    deferred = transcript.setdefault("deferred_items", [])
    _append_with_tool_barrier(canonical, deferred, appended)
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
