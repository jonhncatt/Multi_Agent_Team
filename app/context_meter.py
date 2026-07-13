from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable

import tiktoken

from app.context_pack import (
    CompactionSummary,
    build_compaction_input,
    build_structured_compaction_summary,
    normalize_compaction_summary,
    parse_compaction_summary_text,
    render_compaction_summary,
)
from app.thread_transcript import normalize_thread_transcript, transcript_items_after_compaction


_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.5": 1_000_000,
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "moonshot-v1-8k": 8 * 1024,
    "moonshot-v1-32k": 32 * 1024,
    "moonshot-v1-128k": 128 * 1024,
    "mixtral-8x7b-32768": 32 * 1024,
}
_DEFAULT_FALLBACK_CONTEXT_WINDOW = 256_000
_AUTO_COMPACT_RATIO = 0.8
_DANGER_COMPACT_RATIO = 0.95
_HISTORY_SOFT_LIMIT_TOKENS = 120_000
_STATIC_OVERHEAD_TOKENS = 1200
_DEFAULT_RETAINED_RAW_TURNS = 12
_COMPACTED_HISTORY_DIGEST_LIMIT = 12
_COMPACTED_HISTORY_CHAR_LIMIT = 6000
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


@lru_cache(maxsize=64)
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


def quick_count_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    ascii_chars = 0
    non_ascii_chars = 0
    for char in raw:
        if ord(char) < 128:
            ascii_chars += 1
        else:
            non_ascii_chars += 1
    return max(1, int((ascii_chars / 4.0) + (non_ascii_chars / 1.5)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shorten(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return f"{raw[: max(0, limit - 1)].rstrip()}…"


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
                "id": str(item.get("id") or "").strip(),
                "role": str(item.get("role") or "").strip(),
                "text": str(item.get("text") or ""),
                "attachments": attachments,
                "created_at": str(item.get("created_at") or ""),
            }
        )
    return serialized


def _default_compaction_state() -> dict[str, Any]:
    return {
        "generation": 0,
        "compacted_history": "",
        "compacted_until_turn_id": "",
        "retained_turn_ids": [],
        "last_compacted_at": "",
        "last_compaction_reason": "",
        "last_compaction_phase": "",
        "phase": "",
        "reason": "",
        "before_tokens": 0,
        "after_tokens": 0,
        "estimated_context_tokens": 0,
        "effective_context_window": 0,
        "auto_compact_token_limit": 0,
        "danger_compact_token_limit": 0,
        "history_soft_limit_tokens": 0,
        "history_noise_tokens": 0,
        "threshold_source": "",
        "estimate_mode": "",
        "context_estimate_updated_at": "",
        "context_exact_updated_at": "",
        "calculation_ms": 0,
        "compact_recommendation": "none",
        "compact_reason": "",
        "retained_turn_count": 0,
        "mode": "token_budget",
        "compaction_source": "",
        "llm_compaction_used": False,
        "fallback_reason": "",
        "compaction_schema": [],
    }


def ensure_compaction_state(session: dict[str, Any] | None) -> dict[str, Any]:
    raw = session.get("compaction_state") if isinstance(session, dict) else {}
    payload = dict(raw) if isinstance(raw, dict) else {}
    legacy_status = session.get("compaction_status") if isinstance(session, dict) and isinstance(session.get("compaction_status"), dict) else {}
    legacy_meter = session.get("context_meter") if isinstance(session, dict) and isinstance(session.get("context_meter"), dict) else {}
    if legacy_status:
        payload = {**dict(legacy_status), **payload}
    if legacy_meter:
        payload = {
            "estimated_context_tokens": legacy_meter.get("estimated_tokens"),
            "effective_context_window": legacy_meter.get("context_window"),
            "auto_compact_token_limit": legacy_meter.get("auto_compact_token_limit"),
            "threshold_source": legacy_meter.get("threshold_source"),
            **payload,
        }
    normalized = {
        "generation": max(0, int(payload.get("generation") or 0)),
        "compacted_history": str(payload.get("compacted_history") or ""),
        "compacted_until_turn_id": str(payload.get("compacted_until_turn_id") or ""),
        "retained_turn_ids": [
            str(item).strip()
            for item in list(payload.get("retained_turn_ids") or [])
            if str(item).strip()
        ][: _DEFAULT_RETAINED_RAW_TURNS],
        "last_compacted_at": str(payload.get("last_compacted_at") or ""),
        "last_compaction_reason": str(payload.get("last_compaction_reason") or ""),
        "last_compaction_phase": str(payload.get("last_compaction_phase") or ""),
        "phase": str(payload.get("phase") or payload.get("last_compaction_phase") or ""),
        "reason": str(payload.get("reason") or ""),
        "before_tokens": max(0, int(payload.get("before_tokens") or 0)),
        "after_tokens": max(0, int(payload.get("after_tokens") or 0)),
        "estimated_context_tokens": max(0, int(payload.get("estimated_context_tokens") or 0)),
        "effective_context_window": max(0, int(payload.get("effective_context_window") or 0)),
        "auto_compact_token_limit": max(0, int(payload.get("auto_compact_token_limit") or 0)),
        "danger_compact_token_limit": max(0, int(payload.get("danger_compact_token_limit") or 0)),
        "history_soft_limit_tokens": max(0, int(payload.get("history_soft_limit_tokens") or 0)),
        "history_noise_tokens": max(0, int(payload.get("history_noise_tokens") or 0)),
        "threshold_source": str(payload.get("threshold_source") or ""),
        "estimate_mode": str(payload.get("estimate_mode") or ""),
        "context_estimate_updated_at": str(payload.get("context_estimate_updated_at") or ""),
        "context_exact_updated_at": str(payload.get("context_exact_updated_at") or ""),
        "calculation_ms": max(0, int(payload.get("calculation_ms") or 0)),
        "compact_recommendation": str(payload.get("compact_recommendation") or "none"),
        "compact_reason": str(payload.get("compact_reason") or ""),
        "retained_turn_count": max(0, int(payload.get("retained_turn_count") or 0)),
        "mode": str(payload.get("mode") or "token_budget"),
        "compaction_source": str(payload.get("compaction_source") or ""),
        "llm_compaction_used": bool(payload.get("llm_compaction_used")),
        "fallback_reason": str(payload.get("fallback_reason") or ""),
        "compaction_schema": [
            str(item).strip()
            for item in list(payload.get("compaction_schema") or [])
            if str(item).strip()
        ],
    }
    if isinstance(session, dict) and session.get("compaction_state") != normalized:
        session["compaction_state"] = dict(normalized)
    return normalized


def _find_turn_index(turns: list[dict[str, Any]], turn_id: str) -> int:
    wanted = str(turn_id or "").strip()
    if not wanted:
        return -1
    for index, item in enumerate(turns):
        if str(item.get("id") or "").strip() == wanted:
            return index
    return -1


def _build_runtime_context_view(
    *,
    session: dict[str, Any] | None,
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
) -> dict[str, Any]:
    payload = dict(session or {})
    compaction_state = ensure_compaction_state(payload)
    turns = _serializable_turns(payload.get("turns") or [])
    compacted_index = _find_turn_index(turns, str(compaction_state.get("compacted_until_turn_id") or ""))
    uncovered_turns = turns[compacted_index + 1 :] if compacted_index >= 0 else turns
    retained_turns = uncovered_turns[-max(1, retained_raw_turns) :]
    retained_turn_ids = [
        str(item.get("id") or "").strip()
        for item in retained_turns
        if str(item.get("id") or "").strip()
    ]
    effective_summary = str(compaction_state.get("compacted_history") or payload.get("summary") or "")
    phase = str(compaction_state.get("phase") or compaction_state.get("last_compaction_phase") or "")
    reason = str(compaction_state.get("reason") or "")
    if not reason and str(compaction_state.get("last_compaction_reason") or "").startswith("context_limit:"):
        reason = "context_limit"
    return {
        "summary": effective_summary,
        "history_turns": retained_turns,
        "uncovered_turns": uncovered_turns,
        "retained_turn_ids": retained_turn_ids,
        "all_turns": turns,
        "compaction_state": compaction_state,
    }


def _build_serialized_context(
    *,
    session: dict[str, Any] | None,
    pending_message: str = "",
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
) -> str:
    payload = dict(session or {})
    transcript = normalize_thread_transcript(
        payload.get("thread_transcript"),
        legacy_turns=payload.get("turns") or [],
    )
    compacted_summary, items = transcript_items_after_compaction(
        transcript,
        ensure_compaction_state(payload),
    )
    serialized = {
        "compacted_history": compacted_summary,
        "thread_transcript": items,
        "pending_user_message": str(pending_message or ""),
    }
    return json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))


def build_compaction_status(
    *,
    session: dict[str, Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
    estimate_mode: str = "exact",
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    history_soft_limit_tokens: int = _HISTORY_SOFT_LIMIT_TOKENS,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = dict(session or {})
    runtime_view = _build_runtime_context_view(
        session=payload,
        retained_raw_turns=retained_raw_turns,
    )
    compaction_state = ensure_compaction_state(payload)
    context_window, threshold_source = resolve_context_window(
        model,
        max_output_tokens=max_output_tokens,
    )
    normalized_auto_ratio = max(0.1, min(0.95, float(auto_compact_ratio or _AUTO_COMPACT_RATIO)))
    normalized_danger_ratio = max(normalized_auto_ratio, min(0.99, float(danger_compact_ratio or _DANGER_COMPACT_RATIO)))
    normalized_history_soft_limit = max(1000, int(history_soft_limit_tokens or _HISTORY_SOFT_LIMIT_TOKENS))
    auto_compact_token_limit = max(1, int(context_window * normalized_auto_ratio))
    danger_compact_token_limit = max(auto_compact_token_limit, int(context_window * normalized_danger_ratio))
    serialized = _build_serialized_context(
        session=payload,
        pending_message=pending_message,
        retained_raw_turns=retained_raw_turns,
    )
    normalized_estimate_mode = str(estimate_mode or "exact").strip().lower()
    if normalized_estimate_mode not in {"cached", "quick", "exact"}:
        normalized_estimate_mode = "exact"
    if normalized_estimate_mode == "exact":
        estimated_payload_tokens = count_tokens(serialized, model)
    else:
        estimated_payload_tokens = quick_count_tokens(serialized)
    estimated_tokens = estimated_payload_tokens + _STATIC_OVERHEAD_TOKENS
    retained_ids = {
        str(item.get("id") or "").strip()
        for item in list(runtime_view.get("history_turns") or [])
        if str(item.get("id") or "").strip()
    }
    compactable_turns = [
        item
        for item in list(runtime_view.get("uncovered_turns") or [])
        if str(item.get("id") or "").strip()
        and str(item.get("id") or "").strip() not in retained_ids
    ]
    history_noise_tokens = quick_count_tokens(
        json.dumps(compactable_turns, ensure_ascii=False, separators=(",", ":"))
    )
    compact_recommendation = "none"
    compact_reason = ""
    if estimated_tokens >= danger_compact_token_limit:
        compact_recommendation = "required"
        compact_reason = "context_danger_limit"
    elif estimated_tokens >= auto_compact_token_limit:
        compact_recommendation = "suggested"
        compact_reason = "context_auto_limit"
    elif compactable_turns and history_noise_tokens >= normalized_history_soft_limit:
        compact_recommendation = "suggested"
        compact_reason = "history_soft_limit"
    context_window_known = threshold_source != "fallback_budget"
    warning = ""
    if not context_window_known:
        warning = "当前模型未提供稳定 context window，以下为基于保守预算的估算。"
    retained_turn_ids = list(runtime_view.get("retained_turn_ids") or [])
    phase = str(compaction_state.get("phase") or compaction_state.get("last_compaction_phase") or "")
    reason = str(compaction_state.get("reason") or "")
    if not reason and str(compaction_state.get("last_compaction_reason") or "").startswith("context_limit:"):
        reason = "context_limit"
    updated_at = _now_iso()
    calculation_ms = max(0, int((time.perf_counter() - started) * 1000))
    exact_updated_at = (
        updated_at
        if normalized_estimate_mode == "exact"
        else str(compaction_state.get("context_exact_updated_at") or "")
    )
    return {
        "enabled": True,
        "mode": "token_budget",
        "replacement_history_mode": True,
        "generation": max(0, int(compaction_state.get("generation") or 0)),
        "compacted_history_present": bool(str(compaction_state.get("compacted_history") or "").strip()),
        "compacted_history_chars": len(str(compaction_state.get("compacted_history") or "")),
        "compacted_until_turn_id": str(compaction_state.get("compacted_until_turn_id") or ""),
        "retained_turn_ids": retained_turn_ids,
        "retained_turn_count": len(retained_turn_ids),
        "estimated_context_tokens": int(estimated_tokens),
        "estimated_payload_tokens": int(estimated_payload_tokens),
        "effective_context_window": int(context_window),
        "auto_compact_token_limit": int(auto_compact_token_limit),
        "danger_compact_token_limit": int(danger_compact_token_limit),
        "history_soft_limit_tokens": int(normalized_history_soft_limit),
        "history_noise_tokens": int(history_noise_tokens),
        "threshold_source": threshold_source,
        "context_window_known": bool(context_window_known),
        "last_compacted_at": str(last_compacted_at or compaction_state.get("last_compacted_at") or ""),
        "last_compaction_reason": str(compaction_state.get("last_compaction_reason") or ""),
        "last_compaction_phase": str(compaction_state.get("last_compaction_phase") or ""),
        "estimate_mode": normalized_estimate_mode,
        "context_estimate_updated_at": updated_at,
        "context_exact_updated_at": exact_updated_at,
        "calculation_ms": int(calculation_ms),
        "compact_recommendation": compact_recommendation,
        "compact_reason": compact_reason,
        "phase": phase,
        "reason": reason,
        "before_tokens": int(compaction_state.get("before_tokens") or 0),
        "after_tokens": int(compaction_state.get("after_tokens") or 0),
        "compaction_source": str(compaction_state.get("compaction_source") or ""),
        "llm_compaction_used": bool(compaction_state.get("llm_compaction_used")),
        "fallback_reason": str(compaction_state.get("fallback_reason") or ""),
        "compaction_schema": list(compaction_state.get("compaction_schema") or []),
        "warning": warning,
    }


def _persist_compaction_estimates(
    session: dict[str, Any] | None,
    *,
    status: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(session or {})
    state = ensure_compaction_state(payload)
    state["estimated_context_tokens"] = int(status.get("estimated_context_tokens") or 0)
    state["effective_context_window"] = int(status.get("effective_context_window") or 0)
    state["auto_compact_token_limit"] = int(status.get("auto_compact_token_limit") or 0)
    state["danger_compact_token_limit"] = int(status.get("danger_compact_token_limit") or 0)
    state["history_soft_limit_tokens"] = int(status.get("history_soft_limit_tokens") or 0)
    state["history_noise_tokens"] = int(status.get("history_noise_tokens") or 0)
    state["threshold_source"] = str(status.get("threshold_source") or "")
    state["estimate_mode"] = str(status.get("estimate_mode") or "")
    state["context_estimate_updated_at"] = str(status.get("context_estimate_updated_at") or "")
    if str(status.get("context_exact_updated_at") or "").strip():
        state["context_exact_updated_at"] = str(status.get("context_exact_updated_at") or "")
    state["calculation_ms"] = int(status.get("calculation_ms") or 0)
    state["compact_recommendation"] = str(status.get("compact_recommendation") or "none")
    state["compact_reason"] = str(status.get("compact_reason") or "")
    state["retained_turn_count"] = int(status.get("retained_turn_count") or 0)
    if isinstance(session, dict):
        session["compaction_state"] = dict(state)
    return state


def build_context_meter(
    *,
    session: dict[str, Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
    estimate_mode: str = "exact",
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    history_soft_limit_tokens: int = _HISTORY_SOFT_LIMIT_TOKENS,
) -> dict[str, Any]:
    status = build_compaction_status(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at,
        estimate_mode=estimate_mode,
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        history_soft_limit_tokens=history_soft_limit_tokens,
    )
    return build_context_meter_from_status(status)


def build_context_meter_from_status(status: dict[str, Any] | None) -> dict[str, Any]:
    status_payload = dict(status or {})
    estimated_tokens = int(status_payload.get("estimated_context_tokens") or 0)
    estimated_payload_tokens = int(status_payload.get("estimated_payload_tokens") or 0)
    auto_compact_token_limit = int(status_payload.get("auto_compact_token_limit") or 0)
    context_window = int(status_payload.get("effective_context_window") or 0)
    used_ratio = 0.0
    if context_window > 0:
        used_ratio = min(1.0, float(estimated_tokens) / float(context_window))
    elif auto_compact_token_limit > 0:
        used_ratio = min(1.0, float(estimated_tokens) / float(auto_compact_token_limit))
    remaining_ratio = max(0.0, 1.0 - used_ratio)
    remaining_tokens = max(0, context_window - estimated_tokens) if context_window > 0 else 0
    estimate_mode = str(status_payload.get("estimate_mode") or "")
    stale = bool(status_payload.get("stale"))
    return {
        "estimated_tokens": estimated_tokens,
        "estimated_payload_tokens": estimated_payload_tokens,
        "overhead_tokens": int(_STATIC_OVERHEAD_TOKENS),
        "context_window": int(context_window),
        "auto_compact_token_limit": auto_compact_token_limit,
        "danger_compact_token_limit": int(status_payload.get("danger_compact_token_limit") or 0),
        "history_soft_limit_tokens": int(status_payload.get("history_soft_limit_tokens") or 0),
        "history_noise_tokens": int(status_payload.get("history_noise_tokens") or 0),
        "remaining_tokens": int(remaining_tokens),
        "used_ratio": round(used_ratio, 6),
        "remaining_ratio": round(remaining_ratio, 6),
        "used_percent": int(round(used_ratio * 100)),
        "remaining_percent": int(round(remaining_ratio * 100)),
        "threshold_source": str(status_payload.get("threshold_source") or ""),
        "context_window_known": bool(status_payload.get("context_window_known")),
        "compaction_enabled": bool(status_payload.get("enabled")),
        "last_compacted_at": str(status_payload.get("last_compacted_at") or ""),
        "estimate_mode": estimate_mode,
        "stale": stale,
        "calculation_ms": int(status_payload.get("calculation_ms") or 0),
        "updated_at": str(status_payload.get("context_estimate_updated_at") or ""),
        "exact_updated_at": str(status_payload.get("context_exact_updated_at") or ""),
        "compact_recommendation": str(status_payload.get("compact_recommendation") or "none"),
        "compact_reason": str(status_payload.get("compact_reason") or ""),
        "warning": str(status_payload.get("warning") or ""),
    }


def build_runtime_context_payload(
    *,
    session: dict[str, Any] | None = None,
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
) -> dict[str, Any]:
    runtime_view = _build_runtime_context_view(
        session=session,
        retained_raw_turns=retained_raw_turns,
    )
    return {
        "summary": str(runtime_view.get("summary") or ""),
        "history_turns": list(runtime_view.get("history_turns") or []),
        "retained_turn_ids": list(runtime_view.get("retained_turn_ids") or []),
    }


def _format_attachment_label(turn: dict[str, Any]) -> str:
    attachment_names = [
        str(item.get("name") or "").strip()
        for item in list(turn.get("attachments") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if not attachment_names:
        return ""
    return f" attachments={', '.join(attachment_names[:3])}"


def _turn_digest(turn: dict[str, Any]) -> str:
    role = str(turn.get("role") or "unknown").strip() or "unknown"
    text = _shorten(str(turn.get("text") or "").replace("\n", " "), 220)
    suffix = _format_attachment_label(turn)
    return f"- {role}: {text}{suffix}"


_COMPACTION_SCHEMA_KEYS = [
    "user_requirements",
    "confirmed_facts",
    "files_touched",
    "decisions",
    "failed_attempts",
    "current_state",
    "next_steps",
    "open_questions",
    "do_not_repeat",
]


def _compaction_summary_has_content(summary: CompactionSummary) -> bool:
    return bool(
        summary.user_requirements
        or summary.confirmed_facts
        or summary.files_touched
        or summary.decisions
        or summary.failed_attempts
        or str(summary.current_state or "").strip()
        or summary.next_steps
        or summary.open_questions
        or summary.do_not_repeat
    )


def _coerce_compactor_result(raw: Any) -> tuple[CompactionSummary | None, str]:
    if isinstance(raw, CompactionSummary):
        return normalize_compaction_summary(raw), ""
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    if payload and isinstance(payload.get("summary"), (dict, CompactionSummary)):
        summary = normalize_compaction_summary(payload.get("summary"))
        return summary, str(payload.get("source") or "llm")
    if payload and any(key in payload for key in _COMPACTION_SCHEMA_KEYS):
        return normalize_compaction_summary(payload), str(payload.get("source") or "llm")
    if isinstance(raw, str):
        parsed = parse_compaction_summary_text(raw)
        if parsed is not None:
            return parsed, "llm"
    return None, ""


def _build_compaction_summary_with_optional_llm(
    compaction_input: dict[str, Any],
    *,
    llm_compactor: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[CompactionSummary, dict[str, Any]]:
    fallback_summary = build_structured_compaction_summary(compaction_input)
    meta = {
        "source": "deterministic_fallback",
        "llm_used": False,
        "fallback_reason": "compactor_not_configured",
        "schema": list(_COMPACTION_SCHEMA_KEYS),
    }
    if llm_compactor is None:
        return fallback_summary, meta
    try:
        raw_result = llm_compactor(dict(compaction_input))
        summary, source = _coerce_compactor_result(raw_result)
    except Exception as exc:
        meta["fallback_reason"] = f"llm_exception:{exc.__class__.__name__}"
        return fallback_summary, meta
    if summary is None or not _compaction_summary_has_content(summary):
        meta["fallback_reason"] = "llm_output_invalid"
        return fallback_summary, meta
    meta["source"] = source or "llm"
    meta["llm_used"] = True
    meta["fallback_reason"] = ""
    return summary, meta


def maybe_auto_compact_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    phase: str = "pre_turn",
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
    llm_compactor: Callable[[dict[str, Any]], Any] | None = None,
    force: bool = False,
    trigger: str = "auto",
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    history_soft_limit_tokens: int = _HISTORY_SOFT_LIMIT_TOKENS,
) -> dict[str, Any]:
    payload = dict(session or {})
    status_before = build_compaction_status(
        session=payload,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        retained_raw_turns=retained_raw_turns,
        estimate_mode="exact" if force else "quick",
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        history_soft_limit_tokens=history_soft_limit_tokens,
    )
    _persist_compaction_estimates(session, status=status_before)
    if not force and str(status_before.get("compact_recommendation") or "none") == "none":
        return {
            "compacted": False,
            "status_before": status_before,
            "status_after": status_before,
            "compacted_turn_count": 0,
        }
    if not force and str(status_before.get("estimate_mode") or "") != "exact":
        exact_status = build_compaction_status(
            session=payload,
            model=model,
            max_output_tokens=max_output_tokens,
            pending_message=pending_message,
            retained_raw_turns=retained_raw_turns,
            estimate_mode="exact",
            auto_compact_ratio=auto_compact_ratio,
            danger_compact_ratio=danger_compact_ratio,
            history_soft_limit_tokens=history_soft_limit_tokens,
        )
        _persist_compaction_estimates(session, status=exact_status)
        status_before = exact_status
        if str(status_before.get("compact_recommendation") or "none") == "none":
            return {
                "compacted": False,
                "status_before": status_before,
                "status_after": status_before,
                "compacted_turn_count": 0,
            }

    runtime_view = _build_runtime_context_view(
        session=payload,
        retained_raw_turns=retained_raw_turns,
    )
    turns = list(runtime_view.get("uncovered_turns") or [])
    retained_turns = list(runtime_view.get("history_turns") or [])
    retained_ids = {
        str(item.get("id") or "").strip()
        for item in retained_turns
        if str(item.get("id") or "").strip()
    }
    compacted_turns = [
        item
        for item in turns
        if str(item.get("id") or "").strip() and str(item.get("id") or "").strip() not in retained_ids
    ]
    if not compacted_turns:
        return {
            "compacted": False,
            "status_before": status_before,
            "status_after": status_before,
            "compacted_turn_count": 0,
        }

    state = ensure_compaction_state(session)
    next_generation = max(0, int(state.get("generation") or 0)) + 1
    raw_task_state = (
        dict((session or {}).get("task_state") or {})
        if isinstance((session or {}).get("task_state"), dict)
        else {}
    )
    raw_work_cursor = (
        dict((session or {}).get("work_cursor") or {})
        if isinstance((session or {}).get("work_cursor"), dict)
        else {}
    )
    transcript = normalize_thread_transcript(
        (session or {}).get("thread_transcript"),
        legacy_turns=(session or {}).get("turns") or [],
    )
    _previous_summary, active_transcript_items = transcript_items_after_compaction(transcript, state)
    last_turn_id = str(compacted_turns[-1].get("id") or "").strip()
    transcript_items_to_compact: list[dict[str, Any]] = []
    for item in active_transcript_items:
        transcript_items_to_compact.append(item)
        if last_turn_id in {str(item.get("id") or ""), str(item.get("turn_id") or "")}:
            break
    compacted_messages = [
        {
            "role": str(item.get("role") or ""),
            "text": str(item.get("content") or ""),
            "tool": str(item.get("name") or ""),
            "tool_call_id": str(item.get("tool_call_id") or ""),
        }
        for item in transcript_items_to_compact
    ]
    compacted_tool_evidence: list[dict[str, Any]] = []
    for item in transcript_items_to_compact:
        if str(item.get("role") or "") != "tool":
            continue
        content = str(item.get("content") or "")
        try:
            decoded = json.loads(content)
        except Exception:
            decoded = {}
        decoded = decoded if isinstance(decoded, dict) else {}
        status = str(decoded.get("status") or "").strip().lower()
        if not status:
            status = "ok" if bool(decoded.get("ok")) else "unknown"
        summary = str(decoded.get("summary") or decoded.get("message") or decoded.get("error") or content)
        compacted_tool_evidence.append(
            {
                "name": str(item.get("name") or "tool"),
                "status": status,
                "summary": _shorten(summary, 500),
            }
        )
    compaction_input = build_compaction_input(
        old_messages=compacted_messages or compacted_turns,
        tool_evidence=compacted_tool_evidence,
        task_state=raw_task_state,
        work_cursor=raw_work_cursor,
        modified_files=list(raw_work_cursor.get("active_files") or []),
        failed_attempts=raw_task_state.get("failed_attempts") or [],
        current_status=str(raw_task_state.get("status") or ""),
    )
    compaction_summary, compaction_meta = _build_compaction_summary_with_optional_llm(
        compaction_input,
        llm_compactor=llm_compactor,
    )
    compacted_history = _shorten(
        render_compaction_summary(compaction_summary, generation=next_generation),
        _COMPACTED_HISTORY_CHAR_LIMIT,
    )
    compact_reason = str(status_before.get("compact_reason") or "context_limit")
    compact_limit = int(status_before.get("auto_compact_token_limit") or 0)
    if compact_reason == "context_danger_limit":
        compact_limit = int(status_before.get("danger_compact_token_limit") or compact_limit)
    elif compact_reason == "history_soft_limit":
        compact_limit = int(status_before.get("history_soft_limit_tokens") or compact_limit)
    last_compaction_reason = (
        "manual"
        if force or str(trigger or "") == "manual"
        else (
            f"{compact_reason}:"
            f"{int(status_before.get('estimated_context_tokens') or 0)}/"
            f"{compact_limit}"
        )
    )
    state.update(
        {
            "generation": next_generation,
            "compacted_history": compacted_history,
            "compacted_until_turn_id": last_turn_id,
            "retained_turn_ids": [str(item.get("id") or "").strip() for item in retained_turns if str(item.get("id") or "").strip()],
            "last_compacted_at": _now_iso(),
            "last_compaction_reason": last_compaction_reason,
            "last_compaction_phase": str(phase or "pre_turn"),
            "phase": str(phase or "pre_turn"),
            "reason": "manual" if force or str(trigger or "") == "manual" else compact_reason,
            "before_tokens": int(status_before.get("estimated_context_tokens") or 0),
            "mode": "token_budget",
            "compaction_source": str(compaction_meta.get("source") or ""),
            "llm_compaction_used": bool(compaction_meta.get("llm_used")),
            "fallback_reason": str(compaction_meta.get("fallback_reason") or ""),
            "compaction_schema": list(compaction_meta.get("schema") or _COMPACTION_SCHEMA_KEYS),
        }
    )
    if isinstance(session, dict):
        session["compaction_state"] = dict(state)
        session["summary"] = compacted_history
    status_after = build_compaction_status(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        retained_raw_turns=retained_raw_turns,
        estimate_mode="exact",
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        history_soft_limit_tokens=history_soft_limit_tokens,
    )
    _persist_compaction_estimates(session, status=status_after)
    state["after_tokens"] = int(status_after.get("estimated_context_tokens") or 0)
    if isinstance(session, dict):
        session["compaction_state"] = dict(state)
    return {
        "compacted": True,
        "status_before": status_before,
        "status_after": status_after,
        "compacted_turn_count": len(compacted_turns),
        "compaction_source": str(compaction_meta.get("source") or ""),
        "llm_compaction_used": bool(compaction_meta.get("llm_used")),
        "fallback_reason": str(compaction_meta.get("fallback_reason") or ""),
    }
