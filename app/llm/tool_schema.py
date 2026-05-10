from __future__ import annotations

import json
import logging
import re
from typing import Any


logger = logging.getLogger(__name__)
_VALID_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def build_openai_tools(tools: list[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for tool in tools:
        payload = structured_tool_to_openai_tool(tool)
        if payload is not None:
            payloads.append(payload)
    return payloads


def structured_tool_to_openai_tool(tool: Any) -> dict[str, Any] | None:
    original_name = str(getattr(tool, "name", "") or "").strip()
    if not original_name:
        logger.warning("llm.tool_schema.invalid missing tool name")
        return None

    normalized_name = _normalize_tool_name(original_name)
    if normalized_name != original_name:
        logger.warning(
            "llm.tool_schema.invalid normalized tool name",
            extra={"tool_name": original_name, "normalized_tool_name": normalized_name},
        )

    payload = {
        "type": "function",
        "function": {
            "name": normalized_name,
            "description": str(getattr(tool, "description", "") or "").strip(),
            "parameters": _tool_parameters_schema(tool, normalized_name),
        },
    }
    json.dumps(payload, ensure_ascii=False)
    return payload


def _tool_parameters_schema(tool: Any, tool_name: str) -> dict[str, Any]:
    schema = _extract_schema(tool)
    if not isinstance(schema, dict) or not schema:
        return _empty_object_schema()

    normalized = dict(schema)
    normalized.setdefault("type", "object")
    normalized.setdefault("properties", {})
    normalized.setdefault("required", [])
    normalized["additionalProperties"] = False

    try:
        json.dumps(normalized, ensure_ascii=False)
    except Exception as exc:
        logger.warning(
            "llm.tool_schema.invalid non-serializable schema",
            extra={"tool_name": tool_name, "error": str(exc)},
        )
        return _empty_object_schema()
    return normalized


def _extract_schema(tool: Any) -> dict[str, Any] | None:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        try:
            return args_schema.model_json_schema()
        except Exception as exc:
            logger.warning(
                "llm.tool_schema.invalid failed to build args_schema",
                extra={"tool_name": str(getattr(tool, "name", "") or ""), "error": str(exc)},
            )

    parameters = getattr(tool, "parameters", None)
    if isinstance(parameters, dict):
        return dict(parameters)
    return None


def _empty_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def _normalize_tool_name(name: str) -> str:
    normalized = _VALID_TOOL_NAME_RE.sub("_", str(name or "").strip())
    normalized = normalized[:64].strip("_")
    return normalized or "tool"
