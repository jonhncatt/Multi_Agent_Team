from __future__ import annotations

from typing import Any

from app.i18n import normalize_locale, translate


def _exception_status_code(exc: BaseException) -> int:
    queue: list[Any] = [exc]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for field in ("status_code", "status", "http_status"):
            try:
                value = int(getattr(current, field, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value:
                return value
        response = getattr(current, "response", None)
        if response is not None:
            queue.append(response)
        queue.extend(
            item
            for item in (getattr(current, "__cause__", None), getattr(current, "__context__", None))
            if item is not None
        )
    return 0


def is_request_too_large_exception(exc: BaseException) -> bool:
    if _exception_status_code(exc) == 413:
        return True
    message = str(exc or "").strip().lower()
    return any(
        marker in message
        for marker in (
            "413 request entity too large",
            "413 payload too large",
            "request entity too large",
            "payload too large",
            "content too large",
        )
    )


def classify_llm_exception(exc: BaseException, *, phase: str, model: str) -> dict[str, Any]:
    raw_message = str(exc or "").strip() or exc.__class__.__name__
    lowered = raw_message.lower()
    if is_request_too_large_exception(exc):
        return {
            "kind": "request_too_large",
            "layer": "gateway",
            "phase": str(phase or ""),
            "model": str(model or ""),
            "message": "LLM request exceeded the upstream gateway payload limit.",
            "exception_type": exc.__class__.__name__,
            "status_code": 413,
            "retryable_after_compaction": True,
            "raw_message": raw_message,
        }
    if "nonetype" in lowered and "model_dump" in lowered:
        return {
            "kind": "llm_empty_response",
            "layer": "langchain",
            "phase": str(phase or ""),
            "model": str(model or ""),
            "message": "LLM provider returned empty response before ChatResult creation.",
            "exception_type": exc.__class__.__name__,
            "raw_message": raw_message,
        }
    return {
        "kind": "llm_request_error",
        "layer": "llm",
        "phase": str(phase or ""),
        "model": str(model or ""),
        "message": raw_message or "LLM request failed.",
        "exception_type": exc.__class__.__name__,
        "raw_message": raw_message,
    }


def runtime_error_user_text(runtime_error: dict[str, Any] | None, *, locale: str) -> str:
    payload = dict(runtime_error or {})
    normalized_locale = normalize_locale(locale)
    title = translate(normalized_locale, "runtime.error.title")
    request_failed = translate(normalized_locale, "runtime.error.llm_request_failed")
    debug_hint = translate(normalized_locale, "runtime.error.debug_hint")
    kind = str(payload.get("kind") or "").strip()
    if kind == "llm_empty_response":
        reason = translate(normalized_locale, "runtime.error.llm_empty_response")
        return f"{title}：{request_failed}。{reason} {debug_hint}".strip()
    if kind == "request_too_large":
        reason = translate(normalized_locale, "runtime.error.request_too_large")
        return f"{title}：{reason} {debug_hint}".strip()
    return f"{title}：{request_failed}。{debug_hint}".strip()
