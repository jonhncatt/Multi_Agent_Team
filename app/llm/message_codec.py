from __future__ import annotations

import json
from typing import Any

from app.tool_call_normalizer import canonicalize_tool_call

from .types import NativeLLMMessage, NativeLLMToolCall


_ROLE_MAP = {
    "system": "system",
    "human": "user",
    "user": "user",
    "ai": "assistant",
    "assistant": "assistant",
    "tool": "tool",
}


def runtime_message_to_native(message: Any) -> NativeLLMMessage:
    if isinstance(message, NativeLLMMessage):
        return message

    role = _ROLE_MAP.get(str(getattr(message, "type", "") or "").strip().lower(), "user")
    tool_calls: list[NativeLLMToolCall] = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or [], start=1):
        if not isinstance(call, dict):
            continue
        canonical = canonicalize_tool_call(call)

        tool_calls.append(
            NativeLLMToolCall(
                id=str(canonical.id or f"call_{index}"),
                name=str(canonical.name or canonical.raw_name),
                arguments=dict(canonical.args),
                raw_arguments=canonical.raw_args,
            )
        )

    return NativeLLMMessage(
        role=role,
        content=getattr(message, "content", None),
        name=getattr(message, "name", None),
        tool_call_id=getattr(message, "tool_call_id", None),
        tool_calls=tool_calls,
    )


def encode_messages(messages: list[Any]) -> list[dict[str, Any]]:
    return [encode_message(message) for message in messages]


def encode_message(message: Any) -> dict[str, Any]:
    native = runtime_message_to_native(message)
    payload: dict[str, Any] = {"role": native.role}

    if native.role == "assistant" and native.tool_calls:
        content = native.content
        payload["content"] = content if content not in ("", None) and content != [] else None
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _serialize_tool_arguments(call),
                },
            }
            for call in native.tool_calls
        ]
        return payload

    if native.role == "tool":
        payload["tool_call_id"] = str(native.tool_call_id or "")
        payload["content"] = _content_to_text(native.content)
        return payload

    payload["content"] = native.content
    return payload


def _serialize_tool_arguments(call: NativeLLMToolCall) -> str:
    raw = str(call.raw_arguments or "").strip()
    if raw:
        return raw
    return json.dumps(call.arguments or {}, ensure_ascii=False)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"text", "output_text", "input_text"}:
            parts.append(str(item.get("text") or ""))
            continue
        if "text" in item:
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part)
