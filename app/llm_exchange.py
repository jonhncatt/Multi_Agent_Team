from __future__ import annotations

import json
import traceback
from typing import Any

from app.serialization import dump_model, safe_model_dump


MAX_EXCHANGES_PER_TURN = 12
MAX_MESSAGE_CONTENT_CHARS = 20000
MAX_TOOL_CALLS_PER_EXCHANGE = 20
MAX_TOOL_CALL_ARGS_CHARS = 10000
MAX_TRACEBACK_CHARS = 8000
MAX_METADATA_CHARS = 12000

_ROLE_ALIASES = {
    "ai": "assistant",
    "assistant": "assistant",
    "function": "function",
    "human": "user",
    "system": "system",
    "tool": "tool",
    "user": "user",
}


def truncate_text(text: str, limit: int) -> dict[str, Any]:
    raw = str(text or "")
    original_chars = len(raw)
    if limit <= 0:
        return {
            "content": "",
            "truncated": original_chars > 0,
            "original_chars": original_chars,
        }
    if original_chars <= limit:
        return {
            "content": raw,
            "truncated": False,
            "original_chars": original_chars,
        }
    if limit <= 3:
        content = raw[:limit]
    else:
        content = raw[: limit - 3] + "..."
    return {
        "content": content,
        "truncated": True,
        "original_chars": original_chars,
    }


def snapshot_messages(messages: list[Any], *, max_content_chars: int = MAX_MESSAGE_CONTENT_CHARS) -> list[dict[str, Any]]:
    return [
        snapshot_message(message, index=index, max_content_chars=max_content_chars)
        for index, message in enumerate(list(messages or []))
    ]


def snapshot_message(message: Any, *, index: int, max_content_chars: int = MAX_MESSAGE_CONTENT_CHARS) -> dict[str, Any]:
    content_info = truncate_text(_content_to_text(_message_attr(message, "content")), max_content_chars)
    return {
        "index": int(index),
        "class_name": message.__class__.__name__,
        "role": _message_role(message),
        "content": content_info["content"],
        "tool_call_id": str(_message_attr(message, "tool_call_id") or ""),
        "name": str(_message_attr(message, "name") or ""),
        "tool_calls": _snapshot_tool_calls(_message_attr(message, "tool_calls")),
        "additional_kwargs": _bounded_value(_message_attr(message, "additional_kwargs", {}), MAX_METADATA_CHARS),
        "response_metadata": _bounded_value(_message_attr(message, "response_metadata", {}), MAX_METADATA_CHARS),
        "truncated": bool(content_info["truncated"]),
        "original_chars": int(content_info["original_chars"]),
    }


def snapshot_ai_message(
    ai_msg: Any,
    *,
    max_content_chars: int = MAX_MESSAGE_CONTENT_CHARS,
    max_tool_calls: int = MAX_TOOL_CALLS_PER_EXCHANGE,
) -> dict[str, Any]:
    content_info = truncate_text(_content_to_text(_message_attr(ai_msg, "content")), max_content_chars)
    response_metadata = _message_attr(ai_msg, "response_metadata", {})
    return {
        "class_name": ai_msg.__class__.__name__,
        "role": "assistant",
        "content": content_info["content"],
        "tool_calls": _snapshot_tool_calls(
            _message_attr(ai_msg, "tool_calls"),
            max_tool_calls=max_tool_calls,
        ),
        "invalid_tool_calls": _snapshot_tool_calls(
            _message_attr(ai_msg, "invalid_tool_calls"),
            max_tool_calls=max_tool_calls,
        ),
        "additional_kwargs": _bounded_value(_message_attr(ai_msg, "additional_kwargs", {}), MAX_METADATA_CHARS),
        "response_metadata": _bounded_value(response_metadata, MAX_METADATA_CHARS),
        "usage_metadata": _bounded_value(_message_attr(ai_msg, "usage_metadata", {}), MAX_METADATA_CHARS),
        "finish_reason": _finish_reason(ai_msg, response_metadata),
        "truncated": bool(content_info["truncated"]),
        "original_chars": int(content_info["original_chars"]),
    }


def snapshot_error(
    exc: BaseException,
    *,
    classified: dict[str, Any] | None = None,
    max_traceback_chars: int = MAX_TRACEBACK_CHARS,
) -> dict[str, Any]:
    payload = dict(classified or {})
    raw_message = str(payload.get("raw_message") or exc or exc.__class__.__name__).strip() or exc.__class__.__name__
    traceback_text = str(payload.get("traceback_tail") or traceback.format_exc() or "").strip()
    traceback_info = truncate_text(traceback_text, max_traceback_chars)
    payload["exception_type"] = str(payload.get("exception_type") or exc.__class__.__name__)
    payload["raw_message"] = raw_message
    payload["message"] = str(payload.get("message") or raw_message)
    payload["traceback_tail"] = traceback_info["content"]
    if traceback_info["truncated"]:
        payload["traceback_tail_truncated"] = True
        payload["traceback_tail_original_chars"] = int(traceback_info["original_chars"])
    return payload


def _message_attr(message: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(message, name)
    except Exception:
        value = default
    if value is not None:
        return value
    kwargs = getattr(message, "kwargs", None)
    if isinstance(kwargs, dict) and name in kwargs:
        return kwargs.get(name)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and name in additional_kwargs:
        return additional_kwargs.get(name)
    return default


def _message_role(message: Any) -> str:
    explicit_role = str(_message_attr(message, "role") or _message_attr(message, "type") or "").strip().lower()
    if explicit_role in _ROLE_ALIASES:
        return _ROLE_ALIASES[explicit_role]
    if str(_message_attr(message, "tool_call_id") or "").strip():
        return "tool"
    class_name = message.__class__.__name__
    normalized_class = class_name.lower()
    if "system" in normalized_class:
        return "system"
    if "human" in normalized_class:
        return "user"
    if normalized_class == "aimessage" or ("ai" in normalized_class and "message" in normalized_class):
        return "assistant"
    if "tool" in normalized_class:
        return "tool"
    if "function" in normalized_class:
        return "function"
    return class_name


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    dumped = safe_model_dump(content)
    if isinstance(dumped, str):
        return dumped
    try:
        return json.dumps(dumped, ensure_ascii=False)
    except Exception:
        return str(dumped)


def _bounded_value(value: Any, limit: int) -> Any:
    dumped = safe_model_dump(value)
    if dumped is None or isinstance(dumped, (int, float, bool)):
        return dumped
    if isinstance(dumped, str):
        text_info = truncate_text(dumped, limit)
        if not text_info["truncated"]:
            return text_info["content"]
        return text_info
    try:
        serialized = json.dumps(dumped, ensure_ascii=False)
    except Exception:
        serialized = str(dumped)
    if len(serialized) <= max(0, int(limit)):
        return dump_model(dumped)
    text_info = truncate_text(serialized, limit)
    text_info["value_type"] = type(dumped).__name__
    return text_info


def _snapshot_tool_calls(
    tool_calls: Any,
    *,
    max_tool_calls: int = MAX_TOOL_CALLS_PER_EXCHANGE,
    max_tool_call_args_chars: int = MAX_TOOL_CALL_ARGS_CHARS,
) -> list[Any]:
    if not isinstance(tool_calls, list) or not tool_calls:
        return []
    kept_calls = list(tool_calls)
    truncated_meta: dict[str, Any] | None = None
    if max_tool_calls > 0 and len(kept_calls) > max_tool_calls:
        if max_tool_calls == 1:
            kept_calls = []
        else:
            kept_calls = kept_calls[: max_tool_calls - 1]
        truncated_meta = {
            "truncated": True,
            "original_count": len(tool_calls),
            "kept_count": len(kept_calls),
        }
    snapshots = [
        _snapshot_tool_call(item, max_tool_call_args_chars=max_tool_call_args_chars)
        for item in kept_calls
    ]
    if truncated_meta is not None:
        snapshots.append(truncated_meta)
    return snapshots


def _snapshot_tool_call(tool_call: Any, *, max_tool_call_args_chars: int) -> Any:
    dumped = safe_model_dump(tool_call)
    if not isinstance(dumped, dict):
        return _bounded_value(dumped, max_tool_call_args_chars)
    snapshot: dict[str, Any] = {}
    for key, value in dumped.items():
        normalized_key = str(key)
        if normalized_key in {"args", "arguments", "input"}:
            snapshot[normalized_key] = _bounded_value(value, max_tool_call_args_chars)
        else:
            snapshot[normalized_key] = _bounded_value(value, MAX_METADATA_CHARS)
    return snapshot


def _finish_reason(ai_msg: Any, response_metadata: Any) -> str:
    direct = str(_message_attr(ai_msg, "finish_reason") or "").strip()
    if direct:
        return direct
    if isinstance(response_metadata, dict):
        for key in ("finish_reason", "stop_reason"):
            value = str(response_metadata.get(key) or "").strip()
            if value:
                return value
    additional_kwargs = _message_attr(ai_msg, "additional_kwargs", {})
    if isinstance(additional_kwargs, dict):
        for key in ("finish_reason", "stop_reason"):
            value = str(additional_kwargs.get(key) or "").strip()
            if value:
                return value
    return ""
