from __future__ import annotations

import json
import re
from datetime import datetime, timezone
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
        "estimated_context_tokens": 0,
        "effective_context_window": 0,
        "auto_compact_token_limit": 0,
        "threshold_source": "",
        "retained_turn_count": 0,
        "mode": "token_budget",
    }


def ensure_compaction_state(session: dict[str, Any] | None) -> dict[str, Any]:
    raw = session.get("compaction_state") if isinstance(session, dict) else {}
    payload = dict(raw) if isinstance(raw, dict) else {}
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
        "estimated_context_tokens": max(0, int(payload.get("estimated_context_tokens") or 0)),
        "effective_context_window": max(0, int(payload.get("effective_context_window") or 0)),
        "auto_compact_token_limit": max(0, int(payload.get("auto_compact_token_limit") or 0)),
        "threshold_source": str(payload.get("threshold_source") or ""),
        "retained_turn_count": max(0, int(payload.get("retained_turn_count") or 0)),
        "mode": str(payload.get("mode") or "token_budget"),
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
    runtime_view = _build_runtime_context_view(
        session=payload,
        retained_raw_turns=retained_raw_turns,
    )
    thread_memory = session_context_impl.get_thread_memory(payload)
    current_task_focus = session_context_impl.get_current_task_focus(payload)
    artifact_memory_preview = session_context_impl.get_artifact_memory_preview(payload)
    route_state = payload.get("route_state") if isinstance(payload.get("route_state"), dict) else {}
    serialized = {
        "compacted_history": str(runtime_view.get("summary") or ""),
        "history_turns": runtime_view.get("history_turns") or [],
        "thread_memory": thread_memory,
        "current_task_focus": current_task_focus,
        "artifact_memory_preview": artifact_memory_preview,
        "route_state": route_state,
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
) -> dict[str, Any]:
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
    auto_compact_token_limit = max(1, int(context_window * _AUTO_COMPACT_RATIO))
    serialized = _build_serialized_context(
        session=payload,
        pending_message=pending_message,
        retained_raw_turns=retained_raw_turns,
    )
    estimated_payload_tokens = count_tokens(serialized, model)
    estimated_tokens = estimated_payload_tokens + _STATIC_OVERHEAD_TOKENS
    context_window_known = threshold_source != "fallback_budget"
    warning = ""
    if not context_window_known:
        warning = "当前模型未提供稳定 context window，以下为基于保守预算的估算。"
    retained_ids = list(runtime_view.get("retained_turn_ids") or [])
    return {
        "enabled": True,
        "mode": "token_budget",
        "replacement_history_mode": True,
        "generation": max(0, int(compaction_state.get("generation") or 0)),
        "compacted_history_present": bool(str(compaction_state.get("compacted_history") or "").strip()),
        "compacted_history_chars": len(str(compaction_state.get("compacted_history") or "")),
        "compacted_until_turn_id": str(compaction_state.get("compacted_until_turn_id") or ""),
        "retained_turn_ids": retained_ids,
        "retained_turn_count": len(retained_ids),
        "estimated_context_tokens": int(estimated_tokens),
        "estimated_payload_tokens": int(estimated_payload_tokens),
        "effective_context_window": int(context_window),
        "auto_compact_token_limit": int(auto_compact_token_limit),
        "threshold_source": threshold_source,
        "context_window_known": bool(context_window_known),
        "last_compacted_at": str(last_compacted_at or compaction_state.get("last_compacted_at") or ""),
        "last_compaction_reason": str(compaction_state.get("last_compaction_reason") or ""),
        "last_compaction_phase": str(compaction_state.get("last_compaction_phase") or ""),
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
    state["threshold_source"] = str(status.get("threshold_source") or "")
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
) -> dict[str, Any]:
    status = build_compaction_status(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at,
    )
    estimated_tokens = int(status.get("estimated_context_tokens") or 0)
    estimated_payload_tokens = int(status.get("estimated_payload_tokens") or 0)
    auto_compact_token_limit = int(status.get("auto_compact_token_limit") or 0)
    used_ratio = 0.0
    if auto_compact_token_limit > 0:
        used_ratio = min(1.0, float(estimated_tokens) / float(auto_compact_token_limit))
    remaining_ratio = max(0.0, 1.0 - used_ratio)
    return {
        "estimated_tokens": estimated_tokens,
        "estimated_payload_tokens": estimated_payload_tokens,
        "overhead_tokens": int(_STATIC_OVERHEAD_TOKENS),
        "context_window": int(status.get("effective_context_window") or 0),
        "auto_compact_token_limit": auto_compact_token_limit,
        "used_ratio": round(used_ratio, 6),
        "remaining_ratio": round(remaining_ratio, 6),
        "used_percent": int(round(used_ratio * 100)),
        "remaining_percent": int(round(remaining_ratio * 100)),
        "threshold_source": str(status.get("threshold_source") or ""),
        "context_window_known": bool(status.get("context_window_known")),
        "compaction_enabled": bool(status.get("enabled")),
        "last_compacted_at": str(status.get("last_compacted_at") or ""),
        "warning": str(status.get("warning") or ""),
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


def _build_compacted_history(
    *,
    session: dict[str, Any],
    compacted_turns: list[dict[str, Any]],
    next_generation: int,
) -> str:
    thread_memory = session_context_impl.get_thread_memory(session)
    current_task_focus = session_context_impl.get_current_task_focus(session)
    artifact_memory_preview = session_context_impl.get_artifact_memory_preview(session)
    recent_tasks = list(thread_memory.get("recent_tasks") or [])[:6]
    lines = [
        "Compacted thread history.",
        f"generation: {next_generation}",
        f"covered_turn_count: {len(compacted_turns)}",
    ]
    if recent_tasks:
        lines.append("recent_tasks:")
        for item in recent_tasks:
            lines.append(
                "- "
                + _shorten(
                    f"{str(item.get('user_request') or item.get('goal') or '').strip()} -> {str(item.get('result_digest') or '').strip()}",
                    260,
                )
            )
    if current_task_focus:
        lines.append("current_focus:")
        lines.append(f"- goal: {_shorten(str(current_task_focus.get('goal') or ''), 220)}")
        lines.append(f"- cwd: {_shorten(str(current_task_focus.get('cwd') or ''), 220)}")
        active_files = [
            _shorten(str(item or ""), 180)
            for item in list(current_task_focus.get("active_files") or [])[:6]
            if str(item or "").strip()
        ]
        if active_files:
            lines.append("- active_files: " + " | ".join(active_files))
        active_attachments = [
            _shorten(str(item.get("name") or item.get("path") or item.get("id") or ""), 120)
            for item in list(current_task_focus.get("active_attachments") or [])[:6]
            if isinstance(item, dict)
        ]
        if active_attachments:
            lines.append("- active_attachments: " + " | ".join(active_attachments))
    if artifact_memory_preview:
        lines.append("recent_artifacts:")
        for item in artifact_memory_preview[:6]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                + _shorten(
                    f"[{str(item.get('kind') or 'artifact')}] {str(item.get('name') or item.get('path') or '')}: {str(item.get('summary_digest') or '')}",
                    260,
                )
            )
    if compacted_turns:
        lines.append("older_turn_digest:")
        digest_turns = compacted_turns[:2] + compacted_turns[-(_COMPACTED_HISTORY_DIGEST_LIMIT - 2) :]
        seen_ids: set[str] = set()
        for item in digest_turns:
            turn_id = str(item.get("id") or "").strip()
            if turn_id and turn_id in seen_ids:
                continue
            if turn_id:
                seen_ids.add(turn_id)
            lines.append(_turn_digest(item))
    compacted = "\n".join(line for line in lines if str(line).strip())
    return _shorten(compacted, _COMPACTED_HISTORY_CHAR_LIMIT)


def maybe_auto_compact_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None = None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    phase: str = "pre_turn",
    retained_raw_turns: int = _DEFAULT_RETAINED_RAW_TURNS,
) -> dict[str, Any]:
    payload = dict(session or {})
    status_before = build_compaction_status(
        session=payload,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        retained_raw_turns=retained_raw_turns,
    )
    _persist_compaction_estimates(session, status=status_before)
    if int(status_before.get("estimated_context_tokens") or 0) < int(status_before.get("auto_compact_token_limit") or 0):
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
    compacted_history = _build_compacted_history(
        session=session or {},
        compacted_turns=compacted_turns,
        next_generation=next_generation,
    )
    last_turn_id = str(compacted_turns[-1].get("id") or "").strip()
    state.update(
        {
            "generation": next_generation,
            "compacted_history": compacted_history,
            "compacted_until_turn_id": last_turn_id,
            "retained_turn_ids": [str(item.get("id") or "").strip() for item in retained_turns if str(item.get("id") or "").strip()],
            "last_compacted_at": _now_iso(),
            "last_compaction_reason": (
                f"context_budget_exceeded:{int(status_before.get('estimated_context_tokens') or 0)}/"
                f"{int(status_before.get('auto_compact_token_limit') or 0)}"
            ),
            "last_compaction_phase": str(phase or "pre_turn"),
            "mode": "token_budget",
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
    )
    _persist_compaction_estimates(session, status=status_after)
    return {
        "compacted": True,
        "status_before": status_before,
        "status_after": status_after,
        "compacted_turn_count": len(compacted_turns),
    }
