from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
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
    # Operational windows intentionally follow Codex defaults. The API model
    # maximum is tracked separately and can be enabled explicitly by a
    # deployment with VP_CONTEXT_WINDOW_TOKENS.
    "gpt-5.6": 272_000,
    "gpt-5.6-sol": 272_000,
    "gpt-5.6-terra": 272_000,
    "gpt-5.6-luna": 272_000,
    "gpt-5.5": 272_000,
    "gpt-5.4": 272_000,
    "gpt-5.4-mini": 272_000,
    "moonshot-v1-8k": 8 * 1024,
    "moonshot-v1-32k": 32 * 1024,
    "moonshot-v1-128k": 128 * 1024,
    "mixtral-8x7b-32768": 32 * 1024,
}
_MODEL_MAX_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.6": 1_050_000,
    "gpt-5.6-sol": 1_050_000,
    "gpt-5.6-terra": 1_050_000,
    "gpt-5.6-luna": 1_050_000,
    "gpt-5.5": 272_000,
    "gpt-5.4": 272_000,
    "gpt-5.4-mini": 272_000,
}
_DEFAULT_FALLBACK_CONTEXT_WINDOW = 256_000
_DEFAULT_TOOL_OUTPUT_TOKEN_LIMIT = 10_000
_AUTO_COMPACT_RATIO = 0.9
_DANGER_COMPACT_RATIO = 0.95
_HISTORY_SOFT_LIMIT_TOKENS = 120_000
_STATIC_OVERHEAD_TOKENS = 1200
DEFAULT_RETAINED_CONTEXT_TOKENS = 20_000
_MAX_RETAINED_ITEM_IDS = 96
_COMPACTED_HISTORY_DIGEST_LIMIT = 12
_COMPACTED_HISTORY_CHAR_LIMIT = 6000
_K_WINDOW_PATTERN = re.compile(r"(?<!\d)(\d{1,4})k(?![a-z0-9])", re.IGNORECASE)
_RAW_WINDOW_PATTERN = re.compile(r"(?<!\d)(32768|65536|131072|262144|1048576)(?!\d)")


@dataclass(frozen=True, slots=True)
class ContextWindowStatus:
    model: str
    model_max_context_window: int
    operational_context_window: int
    effective_context_window: int
    auto_compact_token_limit: int
    current_tokens: int
    projected_tokens: int
    estimated_context_tokens: int
    remaining_tokens: int
    context_window_known: bool
    threshold_source: str
    auto_compact_limit_source: str
    estimate_source: str
    compact_recommendation: str
    compact_reason: str
    previous_model: str = ""
    previous_operational_context_window: int = 0
    model_changed: bool = False
    model_downgraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def profile_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_max_context_window": self.model_max_context_window,
            "operational_context_window": self.operational_context_window,
            "effective_context_window": self.effective_context_window,
            "auto_compact_token_limit": self.auto_compact_token_limit,
            "threshold_source": self.threshold_source,
            "auto_compact_limit_source": self.auto_compact_limit_source,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any] | None,
        *,
        model: str = "",
    ) -> "ContextWindowStatus":
        raw = dict(payload or {})
        nested = raw.get("context_window_status")
        if isinstance(nested, dict):
            raw = {**raw, **nested}
        operational = max(
            0,
            int(raw.get("operational_context_window") or raw.get("effective_context_window") or 0),
        )
        effective = max(0, int(raw.get("effective_context_window") or operational))
        current = max(0, int(raw.get("current_tokens") or raw.get("estimated_context_tokens") or 0))
        projected = max(0, int(raw.get("projected_tokens") or raw.get("observed_projected_tokens") or 0))
        estimated = max(current, projected)
        return cls(
            model=str(raw.get("model") or model or ""),
            model_max_context_window=max(operational, int(raw.get("model_max_context_window") or operational)),
            operational_context_window=operational,
            effective_context_window=effective,
            auto_compact_token_limit=max(0, int(raw.get("auto_compact_token_limit") or 0)),
            current_tokens=current,
            projected_tokens=projected,
            estimated_context_tokens=estimated,
            remaining_tokens=max(0, operational - estimated),
            context_window_known=bool(raw.get("context_window_known")),
            threshold_source=str(raw.get("threshold_source") or ""),
            auto_compact_limit_source=str(raw.get("auto_compact_limit_source") or ""),
            estimate_source=str(raw.get("estimate_source") or ""),
            compact_recommendation=str(raw.get("compact_recommendation") or "none"),
            compact_reason=str(raw.get("compact_reason") or ""),
            previous_model=str(raw.get("previous_model") or ""),
            previous_operational_context_window=max(0, int(raw.get("previous_operational_context_window") or 0)),
            model_changed=bool(raw.get("model_changed")),
            model_downgraded=bool(raw.get("model_downgraded")),
        )


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


@lru_cache(maxsize=128)
def resolve_context_window(
    model: str | None,
    *,
    max_output_tokens: int | None = None,
    context_window_tokens: int | None = None,
) -> tuple[int, str]:
    explicit_window = max(0, int(context_window_tokens or 0))
    if explicit_window:
        return explicit_window, "config_override"
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


@lru_cache(maxsize=128)
def resolve_context_profile(
    model: str | None,
    *,
    max_output_tokens: int | None = None,
    context_window_tokens: int | None = None,
    max_context_window_tokens: int | None = None,
    tool_output_token_limit: int | None = None,
) -> dict[str, Any]:
    operational_window, source = resolve_context_window(
        model,
        max_output_tokens=max_output_tokens,
        context_window_tokens=context_window_tokens,
    )
    explicit_maximum = max(0, int(max_context_window_tokens or 0))
    candidates = _normalize_model_candidates(model)
    registry_maximum = next(
        (_MODEL_MAX_CONTEXT_WINDOWS[item] for item in candidates if item in _MODEL_MAX_CONTEXT_WINDOWS),
        operational_window,
    )
    maximum_window = max(operational_window, explicit_maximum or registry_maximum)
    return {
        "model_max_context_window": int(maximum_window),
        "operational_context_window": int(operational_window),
        "tool_output_token_limit": max(
            512,
            int(tool_output_token_limit or _DEFAULT_TOOL_OUTPUT_TOKEN_LIMIT),
        ),
        "source": source,
        "max_context_source": "config_override" if explicit_maximum else "model_registry",
    }


def build_context_window_status(
    *,
    model: str | None,
    current_tokens: int,
    projected_tokens: int = 0,
    max_output_tokens: int | None = None,
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    context_window_tokens: int | None = None,
    max_context_window_tokens: int | None = None,
    auto_compact_token_limit: int | None = None,
    estimate_source: str = "full_payload_estimate",
    previous_status: ContextWindowStatus | None = None,
    reuse_profile: bool = False,
) -> ContextWindowStatus:
    normalized_model = str(model or "").strip()
    immediate_previous_model = str(previous_status.model if previous_status else "").strip()
    continuing_model_change = bool(
        previous_status
        and previous_status.model_changed
        and immediate_previous_model == normalized_model
    )
    previous_model = (
        str(previous_status.previous_model or "").strip()
        if continuing_model_change and previous_status is not None
        else immediate_previous_model
    )
    model_changed = bool(
        continuing_model_change
        or (immediate_previous_model and normalized_model and immediate_previous_model != normalized_model)
    )
    if reuse_profile and previous_status is not None and not model_changed:
        operational_window = int(previous_status.operational_context_window)
        model_maximum = int(previous_status.model_max_context_window)
        threshold_source = str(previous_status.threshold_source or "model_registry")
        configured_auto_limit = int(previous_status.auto_compact_token_limit)
        auto_limit_source = str(previous_status.auto_compact_limit_source or "context_ratio")
    else:
        resolved_context_override = max(0, int(context_window_tokens or 0))
        resolved_maximum_override = max(0, int(max_context_window_tokens or 0))
        if model_changed and (resolved_context_override or resolved_maximum_override):
            registry_profile = resolve_context_profile(
                normalized_model,
                max_output_tokens=max_output_tokens,
                context_window_tokens=0,
                max_context_window_tokens=0,
            )
            if str(registry_profile.get("source") or "") != "fallback_budget":
                registry_operational = int(registry_profile["operational_context_window"])
                registry_maximum = int(registry_profile["model_max_context_window"])
                if resolved_context_override:
                    resolved_context_override = min(resolved_context_override, registry_operational)
                if resolved_maximum_override:
                    resolved_maximum_override = min(resolved_maximum_override, registry_maximum)
        profile = resolve_context_profile(
            normalized_model,
            max_output_tokens=max_output_tokens,
            context_window_tokens=resolved_context_override,
            max_context_window_tokens=resolved_maximum_override,
        )
        operational_window = int(profile["operational_context_window"])
        model_maximum = int(profile["model_max_context_window"])
        threshold_source = str(profile["source"])
        configured_auto_limit = max(0, int(auto_compact_token_limit or 0))
        auto_limit_source = "config_override" if configured_auto_limit else "context_ratio"
    normalized_auto_ratio = max(0.1, min(0.95, float(auto_compact_ratio or _AUTO_COMPACT_RATIO)))
    normalized_danger_ratio = max(
        normalized_auto_ratio,
        min(0.99, float(danger_compact_ratio or _DANGER_COMPACT_RATIO)),
    )
    resolved_auto_limit = configured_auto_limit or max(1, int(operational_window * normalized_auto_ratio))
    resolved_auto_limit = min(resolved_auto_limit, max(1, int(operational_window * 0.9)))
    effective_limit = max(resolved_auto_limit, int(operational_window * normalized_danger_ratio))
    normalized_current = max(0, int(current_tokens or 0))
    normalized_projected = max(0, int(projected_tokens or 0))
    estimated = max(normalized_current, normalized_projected)
    recommendation = "none"
    reason = ""
    if estimated >= effective_limit:
        recommendation = "required"
        reason = "context_danger_limit"
    elif estimated >= resolved_auto_limit:
        recommendation = "suggested"
        reason = "context_auto_limit"
    previous_window = (
        int(previous_status.previous_operational_context_window)
        if continuing_model_change and previous_status is not None
        else (int(previous_status.operational_context_window) if previous_status else 0)
    )
    return ContextWindowStatus(
        model=normalized_model,
        model_max_context_window=model_maximum,
        operational_context_window=operational_window,
        effective_context_window=effective_limit,
        auto_compact_token_limit=resolved_auto_limit,
        current_tokens=normalized_current,
        projected_tokens=normalized_projected,
        estimated_context_tokens=estimated,
        remaining_tokens=max(0, operational_window - estimated),
        context_window_known=threshold_source != "fallback_budget",
        threshold_source=threshold_source,
        auto_compact_limit_source=auto_limit_source,
        estimate_source=str(estimate_source or "full_payload_estimate"),
        compact_recommendation=recommendation,
        compact_reason=reason,
        previous_model=previous_model,
        previous_operational_context_window=previous_window,
        model_changed=model_changed,
        model_downgraded=bool(
            (previous_status.model_downgraded if continuing_model_change and previous_status is not None else False)
            or (model_changed and previous_window > 0 and operational_window < previous_window)
        ),
    )


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


def truncate_text_to_token_limit(
    text: str,
    *,
    model: str | None,
    max_tokens: int,
    from_end: bool = False,
) -> str:
    raw = str(text or "")
    limit = max(0, int(max_tokens or 0))
    if not raw or limit <= 0:
        return ""
    if count_tokens(raw, model) <= limit:
        return raw
    low = 0
    high = len(raw)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = raw[-middle:] if from_end else raw[:middle]
        if count_tokens(candidate, model) <= limit:
            low = middle
        else:
            high = middle - 1
    return raw[-low:] if from_end and low else raw[:low]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shorten(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return f"{raw[: max(0, limit - 1)].rstrip()}…"


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
        "context_window_status": {},
        "model_max_context_window": 0,
        "operational_context_window": 0,
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
        "observed_input_tokens": 0,
        "observed_output_tokens": 0,
        "observed_estimated_input_tokens": 0,
        "observed_generation": 0,
        "observed_model": "",
        "observed_at": "",
        "observed_source": "",
        "estimated_static_tokens": 0,
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
        ][: _MAX_RETAINED_ITEM_IDS],
        "last_compacted_at": str(payload.get("last_compacted_at") or ""),
        "last_compaction_reason": str(payload.get("last_compaction_reason") or ""),
        "last_compaction_phase": str(payload.get("last_compaction_phase") or ""),
        "phase": str(payload.get("phase") or payload.get("last_compaction_phase") or ""),
        "reason": str(payload.get("reason") or ""),
        "before_tokens": max(0, int(payload.get("before_tokens") or 0)),
        "after_tokens": max(0, int(payload.get("after_tokens") or 0)),
        "estimated_context_tokens": max(0, int(payload.get("estimated_context_tokens") or 0)),
        "context_window_status": (
            dict(payload.get("context_window_status") or {})
            if isinstance(payload.get("context_window_status"), dict)
            else {}
        ),
        "model_max_context_window": max(0, int(payload.get("model_max_context_window") or 0)),
        "operational_context_window": max(0, int(payload.get("operational_context_window") or 0)),
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
        "observed_input_tokens": max(0, int(payload.get("observed_input_tokens") or 0)),
        "observed_output_tokens": max(0, int(payload.get("observed_output_tokens") or 0)),
        "observed_estimated_input_tokens": max(0, int(payload.get("observed_estimated_input_tokens") or 0)),
        "observed_generation": max(0, int(payload.get("observed_generation") or 0)),
        "observed_model": str(payload.get("observed_model") or ""),
        "observed_at": str(payload.get("observed_at") or ""),
        "observed_source": str(payload.get("observed_source") or ""),
        "estimated_static_tokens": max(0, int(payload.get("estimated_static_tokens") or 0)),
    }
    if isinstance(session, dict) and session.get("compaction_state") != normalized:
        session["compaction_state"] = dict(normalized)
    return normalized


def record_context_usage_observation(
    session: dict[str, Any] | None,
    *,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_input_tokens: int = 0,
    estimated_static_tokens: int = 0,
) -> dict[str, Any]:
    """Persist the latest active request size, not cumulative per-turn usage."""
    if not isinstance(session, dict):
        return {}
    state = ensure_compaction_state(session)
    observed_input = max(0, int(input_tokens or 0))
    observed_estimate = max(0, int(estimated_input_tokens or 0))
    state.update(
        {
            "observed_input_tokens": observed_input,
            "observed_output_tokens": max(0, int(output_tokens or 0)),
            "observed_estimated_input_tokens": observed_estimate,
            "observed_generation": max(0, int(state.get("generation") or 0)),
            "observed_model": str(model or ""),
            "observed_at": _now_iso(),
            "observed_source": "provider_usage" if observed_input > 0 else "full_payload_estimate",
            "estimated_static_tokens": max(
                _STATIC_OVERHEAD_TOKENS,
                int(estimated_static_tokens or state.get("estimated_static_tokens") or 0),
            ),
        }
    )
    session["compaction_state"] = dict(state)
    return state


def _serializable_transcript_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": str(item.get("id") or "").strip(),
        "turn_id": str(item.get("turn_id") or "").strip(),
        "role": str(item.get("role") or "").strip(),
        "text": str(item.get("content") or ""),
        "created_at": str(item.get("created_at") or ""),
    }
    if item.get("attachments"):
        payload["attachments"] = list(item.get("attachments") or [])
    if item.get("tool_calls"):
        payload["tool_calls"] = list(item.get("tool_calls") or [])
    if str(item.get("tool_call_id") or "").strip():
        payload["tool_call_id"] = str(item.get("tool_call_id") or "")
    if str(item.get("name") or "").strip():
        payload["name"] = str(item.get("name") or "")
    return payload


def _transcript_transactions(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    transactions: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in list(items or []):
        if str(item.get("role") or "") == "user" and current:
            transactions.append(current)
            current = []
        current.append(item)
    if current:
        transactions.append(current)
    return transactions


def _retained_transcript_items(
    items: list[dict[str, Any]],
    *,
    retained_history_tokens: int = DEFAULT_RETAINED_CONTEXT_TOKENS,
) -> list[dict[str, Any]]:
    transactions = _transcript_transactions(items)
    if not transactions:
        return []
    token_budget = max(1, int(retained_history_tokens or DEFAULT_RETAINED_CONTEXT_TOKENS))
    retained_groups: list[list[dict[str, Any]]] = []
    retained_tokens = 0
    for group in reversed(transactions):
        group_tokens = quick_count_tokens(json.dumps(group, ensure_ascii=False, separators=(",", ":")))
        if retained_groups and retained_tokens + group_tokens > token_budget:
            break
        retained_groups.append(group)
        retained_tokens += group_tokens
    retained_groups.reverse()
    return [item for group in retained_groups for item in group]


def _build_runtime_context_view(
    *,
    session: dict[str, Any] | None,
    retained_history_tokens: int = DEFAULT_RETAINED_CONTEXT_TOKENS,
) -> dict[str, Any]:
    payload = dict(session or {})
    compaction_state = ensure_compaction_state(payload)
    transcript = normalize_thread_transcript(
        payload.get("thread_transcript"),
        legacy_turns=payload.get("turns") or [],
    )
    _summary, active_items = transcript_items_after_compaction(transcript, compaction_state)
    uncovered_turns = [_serializable_transcript_item(item) for item in active_items]
    retained_turns = _retained_transcript_items(
        uncovered_turns,
        retained_history_tokens=retained_history_tokens,
    )
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
        "all_turns": [_serializable_transcript_item(item) for item in list(transcript.get("items") or [])],
        "compaction_state": compaction_state,
    }


def _build_serialized_context(
    *,
    session: dict[str, Any] | None,
    pending_message: str = "",
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
    retained_history_tokens: int = DEFAULT_RETAINED_CONTEXT_TOKENS,
    estimate_mode: str = "exact",
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    history_soft_limit_tokens: int = _HISTORY_SOFT_LIMIT_TOKENS,
    context_window_tokens: int | None = None,
    max_context_window_tokens: int | None = None,
    auto_compact_token_limit: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = dict(session or {})
    runtime_view = _build_runtime_context_view(
        session=payload,
        retained_history_tokens=retained_history_tokens,
    )
    compaction_state = ensure_compaction_state(payload)
    normalized_history_soft_limit = max(1000, int(history_soft_limit_tokens or _HISTORY_SOFT_LIMIT_TOKENS))
    serialized = _build_serialized_context(
        session=payload,
        pending_message=pending_message,
    )
    normalized_estimate_mode = str(estimate_mode or "exact").strip().lower()
    if normalized_estimate_mode not in {"cached", "quick", "exact"}:
        normalized_estimate_mode = "exact"
    if normalized_estimate_mode == "exact":
        estimated_payload_tokens = count_tokens(serialized, model)
    else:
        estimated_payload_tokens = quick_count_tokens(serialized)
    estimated_static_tokens = max(
        _STATIC_OVERHEAD_TOKENS,
        int(compaction_state.get("estimated_static_tokens") or 0),
    )
    local_estimated_tokens = estimated_payload_tokens + estimated_static_tokens
    observed_generation = int(compaction_state.get("observed_generation") or 0)
    current_generation = int(compaction_state.get("generation") or 0)
    observed_input_tokens = int(compaction_state.get("observed_input_tokens") or 0)
    observed_estimated_tokens = int(compaction_state.get("observed_estimated_input_tokens") or 0)
    observed_base_tokens = observed_input_tokens or observed_estimated_tokens
    observed_projected_tokens = 0
    if observed_base_tokens > 0 and observed_generation == current_generation:
        pending_tokens = count_tokens(str(pending_message or ""), model) if normalized_estimate_mode == "exact" else quick_count_tokens(str(pending_message or ""))
        observed_projected_tokens = (
            observed_base_tokens
            + int(compaction_state.get("observed_output_tokens") or 0)
            + pending_tokens
        )
    estimate_source = "provider_usage" if observed_projected_tokens >= local_estimated_tokens and observed_input_tokens > 0 else "full_payload_estimate"
    window_status = build_context_window_status(
        model=model,
        current_tokens=local_estimated_tokens,
        projected_tokens=observed_projected_tokens,
        max_output_tokens=max_output_tokens,
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        context_window_tokens=context_window_tokens,
        max_context_window_tokens=max_context_window_tokens,
        auto_compact_token_limit=auto_compact_token_limit,
        estimate_source=estimate_source,
    )
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
    warning = ""
    if not window_status.context_window_known:
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
        "estimated_context_tokens": int(window_status.estimated_context_tokens),
        "estimated_payload_tokens": int(estimated_payload_tokens),
        **window_status.to_dict(),
        "context_window_status": window_status.to_dict(),
        "danger_compact_token_limit": int(window_status.effective_context_window),
        "history_soft_limit_tokens": int(normalized_history_soft_limit),
        "history_noise_tokens": int(history_noise_tokens),
        "observed_input_tokens": observed_input_tokens,
        "observed_projected_tokens": int(observed_projected_tokens),
        "estimated_static_tokens": int(estimated_static_tokens),
        "last_compacted_at": str(last_compacted_at or compaction_state.get("last_compacted_at") or ""),
        "last_compaction_reason": str(compaction_state.get("last_compaction_reason") or ""),
        "last_compaction_phase": str(compaction_state.get("last_compaction_phase") or ""),
        "estimate_mode": normalized_estimate_mode,
        "context_estimate_updated_at": updated_at,
        "context_exact_updated_at": exact_updated_at,
        "calculation_ms": int(calculation_ms),
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
    state["context_window_status"] = dict(status.get("context_window_status") or {})
    state["model_max_context_window"] = int(status.get("model_max_context_window") or 0)
    state["operational_context_window"] = int(status.get("operational_context_window") or 0)
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
    context_window_tokens: int | None = None,
    max_context_window_tokens: int | None = None,
    auto_compact_token_limit: int | None = None,
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
        context_window_tokens=context_window_tokens,
        max_context_window_tokens=max_context_window_tokens,
        auto_compact_token_limit=auto_compact_token_limit,
    )
    return build_context_meter_from_status(status)


def build_context_meter_from_status(status: dict[str, Any] | None) -> dict[str, Any]:
    status_payload = dict(status or {})
    estimated_tokens = int(status_payload.get("estimated_context_tokens") or 0)
    estimated_payload_tokens = int(status_payload.get("estimated_payload_tokens") or 0)
    auto_compact_token_limit = int(status_payload.get("auto_compact_token_limit") or 0)
    context_window = int(
        status_payload.get("operational_context_window")
        or status_payload.get("effective_context_window")
        or 0
    )
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
        "overhead_tokens": max(0, estimated_tokens - estimated_payload_tokens),
        "context_window": int(context_window),
        "model_max_context_window": int(status_payload.get("model_max_context_window") or context_window),
        "effective_context_window": int(status_payload.get("effective_context_window") or context_window),
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
        "estimate_source": str(status_payload.get("estimate_source") or ""),
        "observed_input_tokens": int(status_payload.get("observed_input_tokens") or 0),
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
    retained_history_tokens: int = DEFAULT_RETAINED_CONTEXT_TOKENS,
) -> dict[str, Any]:
    runtime_view = _build_runtime_context_view(
        session=session,
        retained_history_tokens=retained_history_tokens,
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
    retained_history_tokens: int = DEFAULT_RETAINED_CONTEXT_TOKENS,
    llm_compactor: Callable[[dict[str, Any]], Any] | None = None,
    force: bool = False,
    trigger: str = "auto",
    auto_compact_ratio: float = _AUTO_COMPACT_RATIO,
    danger_compact_ratio: float = _DANGER_COMPACT_RATIO,
    history_soft_limit_tokens: int = _HISTORY_SOFT_LIMIT_TOKENS,
    context_window_tokens: int | None = None,
    max_context_window_tokens: int | None = None,
    auto_compact_token_limit: int | None = None,
) -> dict[str, Any]:
    payload = dict(session or {})
    status_before = build_compaction_status(
        session=payload,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        retained_history_tokens=retained_history_tokens,
        estimate_mode="exact" if force else "quick",
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        history_soft_limit_tokens=history_soft_limit_tokens,
        context_window_tokens=context_window_tokens,
        max_context_window_tokens=max_context_window_tokens,
        auto_compact_token_limit=auto_compact_token_limit,
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
            retained_history_tokens=retained_history_tokens,
            estimate_mode="exact",
            auto_compact_ratio=auto_compact_ratio,
            danger_compact_ratio=danger_compact_ratio,
            history_soft_limit_tokens=history_soft_limit_tokens,
            context_window_tokens=context_window_tokens,
            max_context_window_tokens=max_context_window_tokens,
            auto_compact_token_limit=auto_compact_token_limit,
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
        retained_history_tokens=retained_history_tokens,
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
        retained_history_tokens=retained_history_tokens,
        estimate_mode="exact",
        auto_compact_ratio=auto_compact_ratio,
        danger_compact_ratio=danger_compact_ratio,
        history_soft_limit_tokens=history_soft_limit_tokens,
        context_window_tokens=context_window_tokens,
        max_context_window_tokens=max_context_window_tokens,
        auto_compact_token_limit=auto_compact_token_limit,
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
