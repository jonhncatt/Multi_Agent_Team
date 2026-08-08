from __future__ import annotations

import json
import re
from typing import Any

from app.tool_trace_summary import safe_preview


TURN_TRACE_SCHEMA_VERSION = 1


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


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _status(value: Any) -> str:
    raw = _text(value).lower()
    aliases = {
        "needs_user_input": "waiting_user",
        "blocked": "failed",
        "success": "completed",
        "done": "completed",
        "ok": "completed",
        "error": "failed",
    }
    normalized = aliases.get(raw, raw)
    if normalized in {"running", "waiting_user", "completed", "failed", "cancelled", "interrupted"}:
        return normalized
    return "completed" if not normalized else normalized


def _message_role(message: dict[str, Any]) -> str:
    role = _text(message.get("role")).lower()
    if role == "human":
        return "user"
    if role in {"ai", "model"}:
        return "assistant"
    return role


def _tool_call_ids(message: dict[str, Any]) -> list[str]:
    return [
        _text(item.get("id"))
        for item in _list_of_dicts(message.get("tool_calls"))
        if _text(item.get("id"))
    ]


def _message_matches_item(message: dict[str, Any], item: dict[str, Any]) -> bool:
    role = _message_role(message)
    if role != _text(item.get("role")).lower():
        return False
    if role == "tool":
        return bool(
            _text(message.get("tool_call_id"))
            and _text(message.get("tool_call_id")) == _text(item.get("tool_call_id"))
        )
    message_calls = _tool_call_ids(message)
    item_calls = _tool_call_ids(item)
    if message_calls or item_calls:
        return bool(message_calls and message_calls == item_calls)
    return str(message.get("content") or "").strip() == str(item.get("content") or "").strip()


def _match_sent_items(
    sent_messages: list[dict[str, Any]],
    thread_items: list[dict[str, Any]],
    *,
    before_index: int | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    candidates = thread_items if before_index is None else thread_items[: max(0, before_index)]
    matched_ids_reversed: list[str] = []
    unmatched_reversed: list[dict[str, Any]] = []
    cursor = len(candidates) - 1
    for message in reversed(sent_messages):
        if _message_role(message) == "system":
            continue
        found = -1
        for index in range(cursor, -1, -1):
            if _message_matches_item(message, candidates[index]):
                found = index
                break
        if found < 0:
            unmatched_reversed.append(message)
            continue
        item_id = _text(candidates[found].get("id"))
        if item_id:
            matched_ids_reversed.append(item_id)
        cursor = found - 1
    return list(reversed(matched_ids_reversed)), list(reversed(unmatched_reversed))


def _system_components(system_message: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"^\[([^\]\n]+)\]\s*$", str(system_message or ""), re.MULTILINE):
        name = match.group(1).strip()
        if name and name not in values:
            values.append(name)
    return values


def _context_for_exchange(
    exchange: dict[str, Any],
    *,
    thread_items: list[dict[str, Any]],
    before_index: int | None,
) -> tuple[dict[str, Any], list[str]]:
    sent = _list_of_dicts(exchange.get("sent_messages_exact"))
    system_parts = [str(item.get("content") or "") for item in sent if _message_role(item) == "system"]
    system_message = "\n\n".join(part for part in system_parts if part).strip()
    input_item_ids, unmatched = _match_sent_items(sent, thread_items, before_index=before_index)
    supporting_messages = [
        {
            "role": _message_role(item),
            "content": str(item.get("content") or ""),
            **({"name": _text(item.get("name"))} if _text(item.get("name")) else {}),
            **(
                {"tool_call_id": _text(item.get("tool_call_id"))}
                if _text(item.get("tool_call_id"))
                else {}
            ),
        }
        for item in unmatched
        if _message_role(item) in {"user", "assistant", "tool"}
    ]
    composition = _dict(exchange.get("request_composition"))
    context = {
        "system_message": system_message,
        "components": _system_components(system_message),
        "supporting_messages": supporting_messages,
        "tool_names": [_text(item) for item in list(composition.get("bound_tool_names") or []) if _text(item)],
    }
    return context, input_item_ids


def _response_matches_item(response: dict[str, Any], item: dict[str, Any]) -> bool:
    if not response or _text(item.get("role")) != "assistant":
        return False
    response_calls = _tool_call_ids(response)
    item_calls = _tool_call_ids(item)
    if response_calls or item_calls:
        return bool(response_calls and response_calls == item_calls)
    return str(response.get("content") or "").strip() == str(item.get("content") or "").strip()


def _usage_from_exchange(exchange: dict[str, Any]) -> dict[str, Any]:
    response = _dict(exchange.get("model_returned_exact"))
    usage = _dict(response.get("usage_metadata"))
    if not usage:
        usage = _dict(_dict(response.get("response_metadata")).get("token_usage"))
    return {
        key: _int(value)
        for key, value in {
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }.items()
        if value not in (None, "")
    }


def _finish_reason(exchange: dict[str, Any]) -> str:
    response = _dict(exchange.get("model_returned_exact"))
    return _text(response.get("finish_reason") or _dict(response.get("response_metadata")).get("finish_reason"))


def _invalid_tool_call_facts(exchange: dict[str, Any]) -> list[dict[str, str]]:
    response = _dict(exchange.get("model_returned_exact"))
    facts: list[dict[str, str]] = []
    for item in _list_of_dicts(response.get("invalid_tool_calls")):
        fact = {
            "name": _text(item.get("name")),
            "error": _text(item.get("error")),
        }
        if fact["name"] or fact["error"]:
            facts.append({key: value for key, value in fact.items() if value})
    return facts


def _tool_call_id_from_event(event: dict[str, Any]) -> str:
    raw_call = _dict(event.get("raw_tool_call"))
    validation = _dict(event.get("validation_result"))
    return _text(
        event.get("tool_call_id")
        or event.get("call_id")
        or validation.get("call_id")
        or validation.get("tool_call_id")
        or raw_call.get("id")
        or _dict(event.get("diagnostics")).get("tool_call_id")
    )


def _error_kind_from_tool_event(event: dict[str, Any]) -> str:
    candidates = [
        event.get("error_kind"),
        _dict(event.get("diagnostics")).get("error_kind"),
        _dict(event.get("result_preview")).get("error_kind"),
        _dict(_dict(event.get("result_preview")).get("error")).get("kind"),
    ]
    validation = _dict(event.get("validation_result"))
    if validation.get("allowed") is False:
        candidates.append(validation.get("code"))
    return next((_text(value) for value in candidates if _text(value)), "")


def _trace_event_call_id(event: dict[str, Any]) -> str:
    payload = _dict(event.get("payload"))
    raw_call = _dict(payload.get("raw_tool_call"))
    validation = _dict(payload.get("validation_result"))
    return _text(
        payload.get("tool_call_id")
        or payload.get("call_id")
        or validation.get("call_id")
        or validation.get("tool_call_id")
        or raw_call.get("id")
        or payload.get("id")
    )


def _tool_timing(
    call_id: str,
    trace_events: list[dict[str, Any]],
    *,
    occurrence: int = 1,
) -> dict[str, Any]:
    related = [event for event in trace_events if _trace_event_call_id(event) == call_id]
    start_types = {"tool.started", "command.started"}
    finish_types = {"tool.finished", "tool.failed", "command.finished", "command.failed"}
    transactions: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
    active_start: dict[str, Any] | None = None
    for event in related:
        event_type = _text(event.get("type"))
        if event_type in start_types:
            if active_start is not None:
                transactions.append((active_start, None))
            active_start = event
        elif event_type in finish_types:
            transactions.append((active_start, event))
            active_start = None
    if active_start is not None:
        transactions.append((active_start, None))
    occurrence_index = max(0, int(occurrence or 1) - 1)
    start, finish = transactions[occurrence_index] if occurrence_index < len(transactions) else (None, None)
    started_at = _float(start.get("timestamp")) if start else 0.0
    finished_at = _float(finish.get("timestamp")) if finish else 0.0
    duration_ms = _int(finish.get("duration_ms")) if finish else 0
    if not duration_ms and started_at and finished_at:
        duration_ms = max(0, int((finished_at - started_at) * 1000))
    return {
        **({"started_at": started_at} if started_at else {}),
        **({"finished_at": finished_at} if finished_at else {}),
        **({"duration_ms": duration_ms} if duration_ms else {}),
    }


def _validation_summary(event: dict[str, Any]) -> dict[str, Any]:
    validation = _dict(event.get("validation_result"))
    if not validation:
        return {}
    result: dict[str, Any] = {}
    if "allowed" in validation:
        result["allowed"] = bool(validation.get("allowed"))
    for key in ("code", "message"):
        value = _text(validation.get(key))
        if value:
            result[key] = value
    return result


def _tool_audit_summary(event: dict[str, Any]) -> dict[str, Any]:
    """Keep the bounded audit fields that explain one tool transaction.

    ToolEvent already limits these previews before persistence. Grouping them
    under ``audit`` keeps the Trace timeline small and readable while still
    letting the UI inspect arguments, validation, and the result when a tool
    looks wrong.
    """

    result: dict[str, Any] = {}
    for key in (
        "raw_arguments",
        "normalized_arguments",
        "schema_validation",
        "result_preview",
    ):
        value = event.get(key)
        if value not in (None, "", [], {}):
            result[key] = safe_preview(value, limit=4000)
    for key in ("arguments_preview", "preview_error", "summary"):
        value = _text(safe_preview(event.get(key), limit=500))
        if value:
            result[key] = value
    return result


def _tool_result_from_transcript_item(item: dict[str, Any]) -> Any:
    """Recover a bounded tool result when the ephemeral ToolEvent is absent.

    The typed transcript is durable and still contains the provider-facing tool
    result. Some adapters do not populate every optional ToolEvent audit field,
    so the persisted Trace must not become an empty ``tool_completed`` shell.
    """

    content = item.get("content")
    if isinstance(content, (dict, list, tuple, bool, int, float)):
        return content
    raw = str(content or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def build_turn_trace(
    raw: dict[str, Any],
    *,
    thread_items: list[dict[str, Any]],
    turn_id: str = "",
) -> dict[str, Any]:
    payload = dict(raw or {})
    activity = _dict(payload.get("activity"))
    debug = _dict(payload.get("debug"))
    exchanges = _list_of_dicts(
        payload.get("llm_exchanges")
        or debug.get("llm_exchanges")
        or activity.get("llm_exchanges")
    )
    tool_events = _list_of_dicts(payload.get("tool_events") or activity.get("tool_events"))
    trace_events = _list_of_dicts(payload.get("trace_events") or activity.get("trace_events") or payload.get("events"))
    live_items = _list_of_dicts(payload.get("live_items") or activity.get("live_items"))
    all_items = _list_of_dicts(thread_items)
    logical_turn_id = _text(
        turn_id
        or payload.get("logical_turn_id")
        or payload.get("trace_turn_id")
        or payload.get("turn_id")
    )
    current_items = [item for item in all_items if _text(item.get("turn_id")) == logical_turn_id]
    if not current_items and payload.get("turn_id"):
        current_items = [item for item in all_items if _text(item.get("id")) == _text(payload.get("turn_id"))]

    item_indexes = {_text(item.get("id")): index for index, item in enumerate(all_items) if _text(item.get("id"))}
    assistant_items = [item for item in current_items if _text(item.get("role")) == "assistant"]
    unmatched_assistants = list(assistant_items)
    exchange_by_item: dict[str, dict[str, Any]] = {}
    unmatched_exchanges: list[dict[str, Any]] = []
    for exchange in exchanges:
        response = _dict(exchange.get("model_returned_exact"))
        matched = next((item for item in unmatched_assistants if _response_matches_item(response, item)), None)
        if matched is None and response and unmatched_assistants:
            matched = unmatched_assistants[0]
        if matched is None:
            unmatched_exchanges.append(exchange)
            continue
        item_id = _text(matched.get("id"))
        exchange_by_item[item_id] = exchange
        unmatched_assistants.remove(matched)

    contexts: list[dict[str, Any]] = []
    context_keys: list[tuple[Any, ...]] = []

    def register_context(exchange: dict[str, Any], item_id: str = "") -> tuple[str, list[str]]:
        before_index = item_indexes.get(item_id) if item_id else None
        context, input_item_ids = _context_for_exchange(
            exchange,
            thread_items=all_items,
            before_index=before_index,
        )
        key = (
            context.get("system_message"),
            tuple((item.get("role"), item.get("content"), item.get("tool_call_id"), item.get("name")) for item in context.get("supporting_messages") or []),
            tuple(context.get("tool_names") or []),
        )
        if key in context_keys:
            context_id = str(contexts[context_keys.index(key)].get("context_id"))
        else:
            context_id = f"context-{len(contexts) + 1}"
            contexts.append({"context_id": context_id, **context})
            context_keys.append(key)
        return context_id, input_item_ids

    tool_events_by_call: dict[str, list[dict[str, Any]]] = {}
    for event in tool_events:
        call_id = _tool_call_id_from_event(event)
        if call_id:
            tool_events_by_call.setdefault(call_id, []).append(event)

    pending_calls: dict[str, list[dict[str, Any]]] = {}
    tool_call_id_counts: dict[str, int] = {}
    for item in current_items:
        if _text(item.get("role")) != "assistant":
            continue
        for call in _list_of_dicts(item.get("tool_calls")):
            call_id = _text(call.get("id"))
            if call_id:
                pending_calls.setdefault(call_id, []).append(
                    {
                        "requested_by_item_id": _text(item.get("id")),
                        "tool_name": _text(call.get("name")),
                        "raw_arguments": (
                            dict(call.get("args") or {})
                            if isinstance(call.get("args"), dict)
                            else call.get("args")
                        ),
                    }
                )
                tool_call_id_counts[call_id] = tool_call_id_counts.get(call_id, 0) + 1

    call_occurrences: dict[str, int] = {}

    steps: list[dict[str, Any]] = []
    for item in current_items:
        item_id = _text(item.get("id"))
        role = _text(item.get("role"))
        if role == "user":
            steps.append({"type": "user_received", "item_id": item_id})
            continue
        if role == "assistant":
            exchange = exchange_by_item.get(item_id)
            step: dict[str, Any] = {"type": "assistant_generated", "item_id": item_id}
            if exchange:
                context_id, input_item_ids = register_context(exchange, item_id)
                step.update(
                    {
                        "context_id": context_id,
                        "input_item_ids": input_item_ids,
                        **({"input_through_item_id": input_item_ids[-1]} if input_item_ids else {}),
                        "model": _text(exchange.get("model")),
                        "status": _status(exchange.get("status")),
                        "duration_ms": _int(exchange.get("duration_ms")),
                        "finish_reason": _finish_reason(exchange),
                        "token_usage": _usage_from_exchange(exchange),
                        "invalid_tool_calls": _invalid_tool_call_facts(exchange),
                    }
                )
            steps.append({key: value for key, value in step.items() if value not in (None, "", [], {})})
            continue
        if role == "tool":
            call_id = _text(item.get("tool_call_id"))
            call_occurrences[call_id] = call_occurrences.get(call_id, 0) + 1
            occurrence = call_occurrences[call_id]
            event_queue = tool_events_by_call.get(call_id, [])
            event = event_queue.pop(0) if event_queue else {}
            owner_queue = pending_calls.get(call_id, [])
            owner = owner_queue.pop(0) if owner_queue else {}
            event_status = _text(event.get("status"))
            result_status = "completed" if event_status in {"", "ok", "success", "completed"} else _status(event_status)
            step_type = {
                "completed": "tool_completed",
                "skipped": "tool_skipped",
                "cancelled": "tool_cancelled",
                "canceled": "tool_cancelled",
                "rejected": "tool_rejected",
            }.get(result_status, "tool_failed")
            audit = _tool_audit_summary(event)
            owner_arguments = owner.get("raw_arguments")
            if "raw_arguments" not in audit and owner_arguments not in (None, "", [], {}):
                audit["raw_arguments"] = safe_preview(owner_arguments, limit=4000)
            transcript_result = _tool_result_from_transcript_item(item)
            if "result_preview" not in audit and transcript_result is not None:
                audit["result_preview"] = safe_preview(transcript_result, limit=4000)
            if "summary" not in audit and isinstance(transcript_result, dict):
                transcript_summary = _text(transcript_result.get("summary"))
                if transcript_summary:
                    audit["summary"] = _text(safe_preview(transcript_summary, limit=500))
            step = {
                "type": step_type,
                "item_id": item_id,
                "requested_by_item_id": _text(owner.get("requested_by_item_id")),
                "tool_call_id": call_id,
                "tool_name": _text(item.get("name")) or _text(owner.get("tool_name")) or _text(event.get("name")),
                "status": result_status,
                "error_kind": _error_kind_from_tool_event(event),
                "validation": _validation_summary(event),
                "audit": audit,
                **_tool_timing(call_id, trace_events, occurrence=occurrence),
            }
            collision_count = tool_call_id_counts.get(call_id, 0)
            if call_id and collision_count > 1:
                step["tool_call_id_collision"] = True
                step["tool_call_id_occurrence"] = occurrence
                step["tool_call_id_collision_count"] = collision_count
            diagnostics = _dict(event.get("diagnostics"))
            retry_count = _int(diagnostics.get("repeat_count") or diagnostics.get("retry_count"))
            recovery_result = _text(diagnostics.get("recovery_result") or diagnostics.get("recovery_status"))
            if retry_count:
                step["retry_count"] = retry_count
            if recovery_result:
                step["recovery_result"] = recovery_result
            steps.append({key: value for key, value in step.items() if value not in (None, "", [], {})})

    for exchange in unmatched_exchanges:
        context_id, input_item_ids = register_context(exchange)
        error = _dict(exchange.get("error"))
        steps.append(
            {
                "type": "model_failed" if error or _status(exchange.get("status")) == "failed" else "model_attempt",
                "context_id": context_id,
                "input_item_ids": input_item_ids,
                **({"input_through_item_id": input_item_ids[-1]} if input_item_ids else {}),
                "model": _text(exchange.get("model")),
                "status": _status(exchange.get("status")),
                "duration_ms": _int(exchange.get("duration_ms")),
                "error_kind": _text(error.get("kind")),
                "error_message": _text(error.get("message")),
                "invalid_tool_calls": _invalid_tool_call_facts(exchange),
            }
        )

    for item in live_items:
        if _text(item.get("type")) != "subagent":
            continue
        subagent_id = _text(item.get("id") or item.get("subagent_id"))
        if not subagent_id:
            continue
        steps.append(
            {
                "type": "subagent",
                "item_id": subagent_id,
                "subagent_id": subagent_id,
                "role": _text(item.get("role")) or "explorer",
                "label": _text(item.get("label")),
                "task": str(item.get("task") or "").strip(),
                "status": _text(item.get("status")) or "queued",
                "summary": str(item.get("summary") or "").strip(),
                "queued_at": _float(item.get("queued_at")),
                "started_at": _float(item.get("started_at")),
                "completed_at": _float(item.get("completed_at")),
                "tool_count": _int(item.get("tool_count")),
            }
        )

    for sequence, step in enumerate(steps, start=1):
        step["sequence"] = sequence

    runtime_error = _dict(payload.get("runtime_error") or activity.get("runtime_error") or debug.get("runtime_error"))
    started_at = _float(payload.get("started_at") or activity.get("started_at"))
    finished_at = _float(payload.get("finished_at") or activity.get("finished_at"))
    duration_ms = _int(payload.get("duration_ms") or activity.get("run_duration_ms"))
    return {
        "turn_trace_schema_version": TURN_TRACE_SCHEMA_VERSION,
        "thread_id": _text(payload.get("thread_id") or payload.get("session_id")),
        "turn_id": logical_turn_id,
        "created_at": _text(payload.get("created_at")),
        "updated_at": _text(payload.get("updated_at")),
        "status": _status(payload.get("status") or payload.get("turn_status") or activity.get("status")),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "contexts": contexts,
        "steps": steps,
        "terminal": {
            "status": _status(payload.get("status") or payload.get("turn_status") or activity.get("status")),
            **({"error_kind": _text(runtime_error.get("kind"))} if _text(runtime_error.get("kind")) else {}),
            **({"error_message": _text(runtime_error.get("message"))} if _text(runtime_error.get("message")) else {}),
        },
        "token_usage": _dict(payload.get("token_usage")),
    }


def normalize_turn_trace(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw or {})
    if int(payload.get("turn_trace_schema_version") or 0) != TURN_TRACE_SCHEMA_VERSION:
        return build_turn_trace(payload, thread_items=[], turn_id=_text(payload.get("turn_id")))
    return {
        "turn_trace_schema_version": TURN_TRACE_SCHEMA_VERSION,
        "thread_id": _text(payload.get("thread_id") or payload.get("session_id")),
        "turn_id": _text(payload.get("turn_id")),
        "created_at": _text(payload.get("created_at")),
        "updated_at": _text(payload.get("updated_at")),
        "status": _status(payload.get("status")),
        "started_at": _float(payload.get("started_at")),
        "finished_at": _float(payload.get("finished_at")),
        "duration_ms": _int(payload.get("duration_ms")),
        "contexts": _list_of_dicts(payload.get("contexts")),
        "steps": _list_of_dicts(payload.get("steps")),
        "terminal": _dict(payload.get("terminal")),
        "token_usage": _dict(payload.get("token_usage")),
    }
