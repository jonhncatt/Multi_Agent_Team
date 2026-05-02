from __future__ import annotations

import json
import re
from typing import Any


_SENSITIVE_PATTERNS = [
    (re.compile(r"(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"((?:api[_-]?key|OPENAI_API_KEY|password|cookie)\s*[=:]\s*)[^\s,;]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"((?:access_token|refresh_token|token)\s*[=:]\s*)[^\s,;&]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"([?&](?:token|access_token|refresh_token|key|secret)=)[^&\s]+", re.IGNORECASE), r"\1***"),
]


def mask_sensitive_text(text: str) -> str:
    masked = str(text or "")
    for pattern, replacement in _SENSITIVE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    masked = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "***", masked)
    return masked


def safe_preview(value: Any, *, limit: int = 2000) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return mask_sensitive_text(str(value))[:limit]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 24:
                preview["..."] = "truncated"
                break
            preview[str(key)] = safe_preview(item, limit=max(64, limit // 2))
        return preview
    if isinstance(value, (list, tuple)):
        preview_list = [safe_preview(item, limit=max(64, limit // 2)) for item in list(value)[:12]]
        if len(value) > 12:
            preview_list.append("truncated")
        return preview_list
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    return mask_sensitive_text(text)[:limit]


def _result_count(result: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, int):
            return max(0, value)
    return 0


def summarize_tool_args(tool_name: str, args: dict[str, Any]) -> str:
    normalized = str(tool_name or "").strip()
    arguments = dict(args or {})
    if normalized == "read":
        return f"path={arguments.get('path') or '.'}"
    if normalized in {"search_file", "search_codebase"}:
        query = arguments.get("query") or arguments.get("pattern") or ""
        path = arguments.get("path") or ""
        return f"query={mask_sensitive_text(str(query))[:120]}{f' · path={path}' if path else ''}"
    if normalized == "search_file_multi":
        queries = list(arguments.get("queries") or [])
        return f"path={arguments.get('path') or '.'} · queries={len(queries)}"
    if normalized == "read_section":
        return f"path={arguments.get('path') or '.'} · heading={mask_sensitive_text(str(arguments.get('heading') or ''))[:120]}"
    if normalized == "web_search":
        return f"query={mask_sensitive_text(str(arguments.get('query') or arguments.get('q') or ''))[:120]}"
    if normalized in {"web_fetch", "web_download"}:
        return f"url={mask_sensitive_text(str(arguments.get('url') or ''))[:180]}"
    if normalized == "image_read":
        return f"path={arguments.get('path') or '.'}"
    if normalized == "apply_patch":
        patch_text = str(arguments.get("patch") or "")
        files = re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch_text, flags=re.MULTILINE)
        if files:
            return f"files={', '.join(files[:4])}"
        return "patch"
    if normalized == "exec_command":
        return mask_sensitive_text(str(arguments.get("cmd") or ""))[:160]
    if normalized == "update_plan":
        plan = arguments.get("plan") or arguments.get("steps") or arguments.get("items") or arguments.get("tasks") or arguments.get("plan_state") or []
        return f"items={len(plan) if isinstance(plan, list) else 0}"
    if normalized == "request_user_input":
        questions = list(arguments.get("questions") or [])
        return f"questions={len(questions)}"
    return mask_sensitive_text(json.dumps(arguments, ensure_ascii=False, default=str))[:240]


def preview_tool_arguments(tool_name: str, args: dict[str, Any]) -> tuple[str, str]:
    try:
        preview = summarize_tool_args(tool_name, args)
    except Exception as exc:
        return "", safe_error_message(exc)
    return str(preview or ""), ""


def safe_error_message(exc: BaseException | str) -> str:
    if isinstance(exc, BaseException):
        message = str(exc) or exc.__class__.__name__
    else:
        message = str(exc or "")
    return mask_sensitive_text(message)[:300]


def summarize_tool_result(tool_name: str, result: Any) -> str:
    normalized = str(tool_name or "").strip()
    payload = dict(result or {}) if isinstance(result, dict) else {}
    if not payload:
        return mask_sensitive_text(str(result or ""))[:200]
    if not bool(payload.get("ok")):
        error = payload.get("error")
        if isinstance(error, dict):
            return safe_error_message(error.get("message") or error.get("kind") or "tool failed")
        return safe_error_message(error or payload.get("summary") or "tool failed")
    if normalized == "read":
        return f"read {len(str(payload.get('content') or ''))} chars"
    if normalized == "search_codebase":
        return f"found {_result_count(payload, 'matches', 'results', 'count')} results"
    if normalized in {"search_file", "search_file_multi"}:
        return f"found {_result_count(payload, 'matches', 'results', 'count')} matches"
    if normalized == "read_section":
        return f"read section {len(str(payload.get('content') or ''))} chars"
    if normalized == "web_search":
        return f"found {_result_count(payload, 'results', 'count')} results"
    if normalized == "web_fetch":
        title = str(payload.get("title") or "").strip()
        status = payload.get("status")
        return f"status {status}{f' · {title[:120]}' if title else ''}"
    if normalized == "web_download":
        return f"downloaded {payload.get('filename') or payload.get('path') or 'file'}"
    if normalized == "image_read":
        visible_text = str(payload.get("visible_text") or "").strip().replace("\n", " / ")
        return visible_text[:120] if visible_text else str(payload.get("analysis") or payload.get("summary") or "image read")[:120]
    if normalized == "apply_patch":
        return str(payload.get("summary") or "patch applied")[:160]
    if normalized == "exec_command":
        output = str(payload.get("output") or "").strip().replace("\n", " / ")
        return f"exit {payload.get('returncode')} · {mask_sensitive_text(output)[:120]}".strip()
    if normalized == "update_plan":
        plan = payload.get("plan") or []
        return f"plan updated: {len(plan) if isinstance(plan, list) else 0} items"
    if normalized == "request_user_input":
        questions = payload.get("questions") or []
        return f"user input required: {len(questions) if isinstance(questions, list) else 0} questions"
    return mask_sensitive_text(str(payload.get("summary") or json.dumps(payload, ensure_ascii=False, default=str)))[:200]


def validate_tool_arguments(args: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    normalized_schema = dict(schema or {}) if isinstance(schema, dict) else {}
    if not normalized_schema:
        return {
            "status": "missing",
            "checked": False,
            "summary": "schema unavailable",
            "errors": [],
            "schema_type": "",
            "required": [],
        }

    errors: list[str] = []
    try:
        _validate_json_value(
            value=dict(args or {}),
            schema=normalized_schema,
            path="$",
            errors=errors,
        )
    except Exception as exc:
        message = safe_error_message(exc)
        return {
            "status": "error",
            "checked": False,
            "summary": message,
            "errors": [message],
            "schema_type": str(normalized_schema.get("type") or ""),
            "required": list(normalized_schema.get("required") or []),
        }

    return {
        "status": "valid" if not errors else "invalid",
        "checked": True,
        "summary": "schema matched" if not errors else errors[0],
        "errors": errors[:16],
        "error_count": len(errors),
        "schema_type": str(normalized_schema.get("type") or ""),
        "required": [
            str(item)
            for item in list(normalized_schema.get("required") or [])
            if str(item).strip()
        ],
        "allows_additional_properties": bool(normalized_schema.get("additionalProperties", True)),
    }


def normalize_tool_arguments(
    tool_name: str,
    args: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_name = str(tool_name or "").strip()
    original_args = dict(args or {})
    normalized_args = dict(original_args)
    normalized_schema = dict(schema or {}) if isinstance(schema, dict) else {}
    properties = normalized_schema.get("properties")
    property_map = dict(properties or {}) if isinstance(properties, dict) else {}
    if not normalized_schema or not property_map:
        return {
            "arguments": normalized_args,
            "changed": False,
            "notes": [],
            "status": "unchanged",
        }
    allowed_keys = {str(key) for key in property_map.keys() if str(key).strip()}
    alias_map: dict[str, tuple[str, ...]] = {
        "path": ("filepath", "filename", "file", "image_path"),
        "query": ("q", "query_text"),
        "url": ("uri", "link"),
        "patch": ("patch_text",),
    }
    if normalized_name == "image_read":
        alias_map["path"] = ("filepath", "filename", "file", "image_path", "image")

    notes: list[str] = []
    for target, aliases in alias_map.items():
        if target in normalized_args:
            continue
        if allowed_keys and target not in allowed_keys:
            continue
        present_aliases = [
            alias
            for alias in aliases
            if alias in normalized_args and normalized_args.get(alias) not in ("", None, [], {})
        ]
        if len(present_aliases) != 1:
            continue
        source_key = present_aliases[0]
        normalized_args[target] = normalized_args.pop(source_key)
        notes.append(f"{source_key}->{target}")

    return {
        "arguments": normalized_args,
        "changed": normalized_args != original_args,
        "notes": notes,
        "status": "normalized" if normalized_args != original_args else "unchanged",
    }


def build_tool_argument_audit(
    tool_name: str,
    args: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    preview, preview_error = preview_tool_arguments(tool_name, args)
    validation = validate_tool_arguments(args, schema)
    return {
        "raw_arguments": safe_preview(args, limit=4000),
        "arguments_preview": preview,
        "preview_error": preview_error,
        "schema_validation": validation,
    }


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_json_value(
    *,
    value: Any,
    schema: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    raw_type = schema.get("type")
    expected_types = [raw_type] if isinstance(raw_type, str) else [item for item in list(raw_type or []) if isinstance(item, str)]
    if expected_types and not any(_schema_type_matches(value, item) for item in expected_types):
        errors.append(f"{path} expected {'/'.join(expected_types)}, got {type(value).__name__}")
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        errors.append(f"{path} must be one of {', '.join(mask_sensitive_text(str(item)) for item in enum_values[:8])}")
        return

    if isinstance(value, dict):
        properties = schema.get("properties")
        property_map = dict(properties or {}) if isinstance(properties, dict) else {}
        required = [
            str(item)
            for item in list(schema.get("required") or [])
            if str(item).strip()
        ]
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in property_map:
                    errors.append(f"{path}.{key} is not allowed")
        for key, child_schema in property_map.items():
            if key not in value or not isinstance(child_schema, dict):
                continue
            _validate_json_value(
                value=value.get(key),
                schema=child_schema,
                path=f"{path}.{key}",
                errors=errors,
            )
        return

    if isinstance(value, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return
        for index, item in enumerate(value[:16]):
            _validate_json_value(
                value=item,
                schema=item_schema,
                path=f"{path}[{index}]",
                errors=errors,
            )
        return

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must have length >= {min_length}")
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path} must have length <= {max_length}")
        return

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path} must be >= {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path} must be <= {maximum}")
