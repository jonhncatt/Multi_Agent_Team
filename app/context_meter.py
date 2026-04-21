from __future__ import annotations

import json
import re
from typing import Any

import tiktoken

from app import session_context as session_context_impl


_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "moonshot-v1-8k": 8 * 1024,
    "moonshot-v1-32k": 32 * 1024,
    "moonshot-v1-128k": 128 * 1024,
    "mixtral-8x7b-32768": 32 * 1024,
}
_DEFAULT_FALLBACK_CONTEXT_WINDOW = 256_000
_AUTO_COMPACT_RATIO = 0.9
_STATIC_OVERHEAD_TOKENS = 1200
_K_WINDOW_PATTERN = re.compile(r"(?<!\d)(\d{1,4})k(?![a-z0-9])", re.IGNORECASE)
_RAW_WINDOW_PATTERN = re.compile(r"(?<!\d)(32768|65536|131072|262144|1048576)(?!\d)")


def _normalize_model_candidates(model: str | None) -> list[str]:
    raw = str(model or "").strip()
    if not raw:
        return []
    lowered = raw.lower()
    no_tier = lowered.split(":", 1)[0]
    bare = no_tier.split("/", 1)[-1]
    candidates = [lowered, no_tier, bare]
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def resolve_context_window(
    model: str | None,
    *,
    max_output_tokens: int | None = None,
) -> tuple[int, str]:
    candidates = _normalize_model_candidates(model)
    for item in candidates:
        if item in _MODEL_CONTEXT_WINDOWS:
            return _MODEL_CONTEXT_WINDOWS[item], "model_registry"
    for item in candidates:
        hit = _RAW_WINDOW_PATTERN.search(item)
        if hit:
            return int(hit.group(1)), "model_name_hint"
        hit = _K_WINDOW_PATTERN.search(item)
        if hit:
            return int(hit.group(1)) * 1024, "model_name_hint"
    fallback = max(
        _DEFAULT_FALLBACK_CONTEXT_WINDOW,
        int(max_output_tokens or 0) * 2,
    )
    return fallback, "fallback_budget"


def _encoding_for_model(model: str | None) -> Any:
    candidates = _normalize_model_candidates(model)
    for item in candidates:
        try:
            return tiktoken.encoding_for_model(item)
        except Exception:
            continue
    for encoding_name in ("o200k_base", "cl100k_base"):
        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception:
            continue
    raise RuntimeError("No tokenizer encoding available")


def count_tokens(text: str, model: str | None) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    try:
        encoding = _encoding_for_model(model)
        return len(encoding.encode(raw))
    except Exception:
        return max(1, len(raw) // 4)


def _serializable_turns(turns: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for item in list(turns or []):
        if not isinstance(item, dict):
            continue
        attachments = []
        for meta in list(item.get("attachments") or []):
            if not isinstance(meta, dict):
                continue
            attachments.append(
                {
                    "id": str(meta.get("id") or "").strip(),
                    "name": str(meta.get("name") or "").strip(),
                }
            )
        serialized.append(
            {
                "role": str(item.get("role") or "").strip(),
                "text": str(item.get("text") or ""),
                "attachments": attachments,
                "created_at": str(item.get("created_at") or ""),
            }
        )
    return serialized


def _build_serialized_context(
    *,
    session: dict[str, Any] | None,
    pending_message: str = "",
) -> str:
    payload = dict(session or {})
    thread_memory = session_context_impl.get_thread_memory(payload)
    current_task_focus = session_context_impl.get_current_task_focus(payload)
    artifact_memory_preview = session_context_impl.get_artifact_memory_preview(payload)
    route_state = payload.get("route_state") if isinstance(payload.get("route_state"), dict) else {}
    serialized = {
        "summary": str(payload.get("summary") or ""),
        "turns": _serializable_turns(payload.get("turns") or []),
        "thread_memory": thread_memory,
        "current_task_focus": current_task_focus,
        "artifact_memory_preview": artifact_memory_preview,
        "route_state": route_state,
        "pending_user_message": str(pending_message or ""),
    }
    return json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))


def build_context_meter(
    *,
    session: dict[str, Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
) -> dict[str, Any]:
    context_window, threshold_source = resolve_context_window(
        model,
        max_output_tokens=max_output_tokens,
    )
    auto_compact_token_limit = max(1, int(context_window * _AUTO_COMPACT_RATIO))
    serialized = _build_serialized_context(session=session, pending_message=pending_message)
    estimated_payload_tokens = count_tokens(serialized, model)
    estimated_tokens = estimated_payload_tokens + _STATIC_OVERHEAD_TOKENS
    used_ratio = 0.0
    if auto_compact_token_limit > 0:
        used_ratio = min(1.0, float(estimated_tokens) / float(auto_compact_token_limit))
    remaining_ratio = max(0.0, 1.0 - used_ratio)
    context_window_known = threshold_source != "fallback_budget"
    warning = ""
    if not context_window_known:
        warning = "当前模型未提供稳定 context window，以下为基于保守预算的估算。"
    return {
        "estimated_tokens": int(estimated_tokens),
        "estimated_payload_tokens": int(estimated_payload_tokens),
        "overhead_tokens": int(_STATIC_OVERHEAD_TOKENS),
        "context_window": int(context_window),
        "auto_compact_token_limit": int(auto_compact_token_limit),
        "used_ratio": round(used_ratio, 6),
        "remaining_ratio": round(remaining_ratio, 6),
        "used_percent": int(round(used_ratio * 100)),
        "remaining_percent": int(round(remaining_ratio * 100)),
        "threshold_source": threshold_source,
        "context_window_known": bool(context_window_known),
        "compaction_enabled": True,
        "last_compacted_at": str(last_compacted_at or ""),
        "warning": warning,
    }
