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
