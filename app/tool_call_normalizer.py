from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.tool_trace_summary import safe_error_message


@dataclass(frozen=True)
class CanonicalToolCall:
    id: str
    name: str
    raw_name: str
    args: dict[str, Any]
    raw_args: str
    arguments_parse_status: str
    normalization_notes: list[str] = field(default_factory=list)
    error: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "raw_name": self.raw_name,
            "args": dict(self.args),
            "raw_args": self.raw_args,
            "arguments_parse_status": self.arguments_parse_status,
            "normalization_notes": list(self.normalization_notes),
            "error": self.error,
        }


def canonicalize_tool_call(raw_call: Any) -> CanonicalToolCall:
    payload = _as_payload(raw_call)
    function_payload = _as_payload(_get_value(raw_call, "function"))

    raw_name = str(payload.get("raw_name") or function_payload.get("name") or payload.get("name") or "").strip()
    name = str(payload.get("name") or raw_name or function_payload.get("name") or "").strip()
    if not raw_name:
        raw_name = name
    if not name:
        name = raw_name

    args_present, args_value = _field_state(raw_call, "args")
    arguments_present, arguments_value = _field_state(raw_call, "arguments")
    raw_args_present, raw_args_value = _field_state(raw_call, "raw_args")
    function_arguments_present, function_arguments_value = _field_state(_get_value(raw_call, "function"), "arguments")

    raw_args_text = _preserve_raw_args_text(
        raw_args_value=raw_args_value,
        arguments_value=arguments_value,
        function_arguments_value=function_arguments_value,
        args_value=args_value,
    )

    if isinstance(args_value, dict) and args_value:
        return CanonicalToolCall(
            id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
            name=name,
            raw_name=raw_name,
            args=dict(args_value),
            raw_args=raw_args_text or json.dumps(args_value, ensure_ascii=False, default=str),
            arguments_parse_status="valid_object",
            normalization_notes=["args_dict_preserved"],
        )

    string_result = _parse_first_non_empty_string_source(
        args_value=args_value,
        arguments_value=arguments_value,
        raw_args_value=raw_args_value,
        function_arguments_value=function_arguments_value,
        raw_args_text=raw_args_text,
    )
    if string_result is not None:
        return CanonicalToolCall(
            id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
            name=name,
            raw_name=raw_name,
            args=string_result["args"],
            raw_args=string_result["raw_args"],
            arguments_parse_status=string_result["status"],
            normalization_notes=string_result["notes"],
            error=string_result["error"],
        )

    dict_result = _parse_first_dict_source(
        args_value=args_value,
        arguments_value=arguments_value,
        raw_args_value=raw_args_value,
        function_arguments_value=function_arguments_value,
        raw_args_text=raw_args_text,
    )
    if dict_result is not None:
        return CanonicalToolCall(
            id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
            name=name,
            raw_name=raw_name,
            args=dict_result["args"],
            raw_args=dict_result["raw_args"],
            arguments_parse_status=dict_result["status"],
            normalization_notes=dict_result["notes"],
            error="",
        )

    non_object = _find_present_non_object_value(
        args_present=args_present,
        args_value=args_value,
        arguments_present=arguments_present,
        arguments_value=arguments_value,
        raw_args_present=raw_args_present,
        raw_args_value=raw_args_value,
        function_arguments_present=function_arguments_present,
        function_arguments_value=function_arguments_value,
        raw_args_text=raw_args_text,
    )
    if non_object is not None:
        return CanonicalToolCall(
            id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
            name=name,
            raw_name=raw_name,
            args={},
            raw_args=str(non_object["raw_args"] or ""),
            arguments_parse_status="not_object",
            normalization_notes=non_object["notes"],
            error=non_object["error"],
        )

    if _has_empty_argument_field(
        args_present=args_present,
        args_value=args_value,
        arguments_present=arguments_present,
        arguments_value=arguments_value,
        raw_args_present=raw_args_present,
        raw_args_value=raw_args_value,
        function_arguments_present=function_arguments_present,
        function_arguments_value=function_arguments_value,
    ):
        return CanonicalToolCall(
            id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
            name=name,
            raw_name=raw_name,
            args={},
            raw_args=raw_args_text,
            arguments_parse_status="empty_object",
            normalization_notes=["empty_argument_field"],
        )

    return CanonicalToolCall(
        id=str(payload.get("id") or _get_value(raw_call, "id") or "").strip(),
        name=name,
        raw_name=raw_name,
        args={},
        raw_args=raw_args_text,
        arguments_parse_status="missing",
    )


def _parse_first_non_empty_string_source(
    *,
    args_value: Any,
    arguments_value: Any,
    raw_args_value: Any,
    function_arguments_value: Any,
    raw_args_text: str,
) -> dict[str, Any] | None:
    candidates = (
        ("args", args_value),
        ("arguments", arguments_value),
        ("raw_args", raw_args_value),
        ("function.arguments", function_arguments_value),
    )
    for source, value in candidates:
        if not isinstance(value, str):
            continue
        if not value.strip():
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            return {
                "args": {},
                "raw_args": raw_args_text or value,
                "status": "invalid_json",
                "notes": [f"{source}_json_string_invalid"],
                "error": safe_error_message(exc),
            }
        if isinstance(parsed, dict):
            return {
                "args": dict(parsed),
                "raw_args": raw_args_text or value,
                "status": "empty_object" if not parsed else "valid_object",
                "notes": [f"{source}_json_string_parsed"],
                "error": "",
            }
        return {
            "args": {},
            "raw_args": raw_args_text or value,
            "status": "not_object",
            "notes": [f"{source}_json_string_not_object"],
            "error": f"tool arguments must be a JSON object, got {type(parsed).__name__}",
        }
    return None


def _parse_first_dict_source(
    *,
    args_value: Any,
    arguments_value: Any,
    raw_args_value: Any,
    function_arguments_value: Any,
    raw_args_text: str,
) -> dict[str, Any] | None:
    candidates = (
        ("args", args_value),
        ("arguments", arguments_value),
        ("raw_args", raw_args_value),
        ("function.arguments", function_arguments_value),
    )
    for source, value in candidates:
        if not isinstance(value, dict):
            continue
        raw = raw_args_text or json.dumps(value, ensure_ascii=False, default=str)
        return {
            "args": dict(value),
            "raw_args": raw,
            "status": "empty_object" if not value else "valid_object",
            "notes": [f"{source}_dict_preserved"],
        }
    return None


def _find_present_non_object_value(
    *,
    args_present: bool,
    args_value: Any,
    arguments_present: bool,
    arguments_value: Any,
    raw_args_present: bool,
    raw_args_value: Any,
    function_arguments_present: bool,
    function_arguments_value: Any,
    raw_args_text: str,
) -> dict[str, Any] | None:
    candidates = (
        ("args", args_present, args_value),
        ("arguments", arguments_present, arguments_value),
        ("raw_args", raw_args_present, raw_args_value),
        ("function.arguments", function_arguments_present, function_arguments_value),
    )
    for source, present, value in candidates:
        if not present:
            continue
        if value is None or isinstance(value, (dict, str)):
            continue
        return {
            "raw_args": raw_args_text or str(value),
            "notes": [f"{source}_non_object_value"],
            "error": f"tool arguments must be a JSON object, got {type(value).__name__}",
        }
    return None


def _has_empty_argument_field(
    *,
    args_present: bool,
    args_value: Any,
    arguments_present: bool,
    arguments_value: Any,
    raw_args_present: bool,
    raw_args_value: Any,
    function_arguments_present: bool,
    function_arguments_value: Any,
) -> bool:
    candidates = (
        (args_present, args_value),
        (arguments_present, arguments_value),
        (raw_args_present, raw_args_value),
        (function_arguments_present, function_arguments_value),
    )
    return any(present and isinstance(value, str) and not value.strip() for present, value in candidates)


def _preserve_raw_args_text(
    *,
    raw_args_value: Any,
    arguments_value: Any,
    function_arguments_value: Any,
    args_value: Any,
) -> str:
    for candidate in (raw_args_value, arguments_value, function_arguments_value, args_value):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _field_state(raw: Any, key: str) -> tuple[bool, Any]:
    if isinstance(raw, dict):
        return key in raw, raw.get(key)
    if raw is None:
        return False, None
    if hasattr(raw, key):
        try:
            return True, getattr(raw, key)
        except Exception:
            return True, None
    return False, None


def _get_value(raw: Any, key: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(key)
    if raw is None:
        return None
    return getattr(raw, key, None)


def _as_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw is None:
        return {}
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        try:
            data = model_dump()
            return dict(data or {}) if isinstance(data, dict) else {}
        except Exception:
            return {}
    raw_vars = getattr(raw, "__dict__", None)
    if isinstance(raw_vars, dict):
        return dict(raw_vars)
    return {}
