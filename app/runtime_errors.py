from __future__ import annotations

from typing import Any

from app.i18n import normalize_locale, translate


def classify_llm_exception(exc: BaseException, *, phase: str, model: str) -> dict[str, Any]:
    raw_message = str(exc or "").strip() or exc.__class__.__name__
    lowered = raw_message.lower()
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
    return f"{title}：{request_failed}。{debug_hint}".strip()
