from __future__ import annotations

import re
from typing import Any

from app.context_pack import (
    ContextManager,
    RecentObservation,
    _has_context_manager_data,
    _known_previous_project_roots,
    _normalize_clean_turns,
    _normalize_plan_items,
    _normalize_recent_observations,
    _rebase_text_paths_for_model,
    _rebase_value_paths_for_model,
    _unique_strings,
)
from app.serialization import dump_model
from app.session_context import normalize_current_task_focus


CONTEXT_SCHEMA_VERSION = 3

_LEGACY_SESSION_KEYS = (
    "summary",
    "thread_memory",
    "compaction_status",
    "history_turns",
    "messages",
    "turns",
    "current_task_focus",
    "active_task_focus",
    "plan_state",
    "plan",
    "recent_tool_results",
    "recent_errors",
    "attachment_evidence_pack",
    "route_state",
    "agent_state",
)


def _clean_text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _raw_context_manager(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("context_manager")
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def has_context_manager_payload(session_payload: dict[str, Any] | None) -> bool:
    payload = dict(session_payload or {})
    return _has_context_manager_data(_raw_context_manager(payload))


def has_legacy_context_payload(session_payload: dict[str, Any] | None) -> bool:
    payload = dict(session_payload or {})
    for key in _LEGACY_SESSION_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, dict)) and value:
            return True
    return False


def _legacy_focus_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("current_task_focus", "active_task_focus"):
        value = payload.get(key)
        if isinstance(value, dict) and value:
            candidates.append(value)
    route_state = payload.get("route_state")
    if isinstance(route_state, dict):
        for key in ("current_task_focus", "task_checkpoint"):
            value = route_state.get(key)
            if isinstance(value, dict) and value:
                candidates.append(value)
    agent_state = payload.get("agent_state")
    if isinstance(agent_state, dict):
        for key in ("current_task_focus", "task_checkpoint"):
            value = agent_state.get(key)
            if isinstance(value, dict) and value:
                candidates.append(value)
    return candidates


def _legacy_active_files(payload: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for focus in _legacy_focus_candidates(payload):
        normalized = normalize_current_task_focus(focus)
        files.extend(str(item) for item in list(normalized.get("active_files") or []) if str(item or "").strip())
    for result in list(payload.get("recent_tool_results") or []):
        if not isinstance(result, dict):
            continue
        for key in ("target", "path", "file"):
            value = str(result.get(key) or "").strip()
            if value:
                files.append(value)
        for ref in list(result.get("source_refs") or []):
            if not isinstance(ref, dict):
                continue
            value = str(ref.get("path") or ref.get("file") or "").strip()
            if value:
                files.append(value)
    return _unique_strings(files, limit=10, max_chars=500)


def _legacy_summary(payload: dict[str, Any]) -> str:
    thread_memory = payload.get("thread_memory")
    compaction_status = payload.get("compaction_status")
    if not isinstance(thread_memory, dict):
        thread_memory = {}
    if not isinstance(compaction_status, dict):
        compaction_status = {}
    return _clean_text(
        payload.get("summary") or thread_memory.get("summary") or compaction_status.get("summary"),
        limit=4000,
    )


def _legacy_turns(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("history_turns", "messages", "turns"):
        raw_turns = payload.get(key)
        if raw_turns:
            return _normalize_clean_turns(raw_turns, current_message="", limit=16)
    return []


def _legacy_observations(payload: dict[str, Any]) -> list[RecentObservation]:
    raw_items: list[Any] = []
    raw_items.extend(list(payload.get("recent_observations") or []))
    raw_items.extend(
        {
            "source": "tool",
            "tool": str(item.get("tool") or item.get("name") or ""),
            "target": str(item.get("target") or item.get("path") or item.get("file") or ""),
            "status": str(item.get("status") or ""),
            "summary": str(item.get("summary") or item.get("message") or item.get("text") or ""),
        }
        for item in list(payload.get("recent_tool_results") or [])
        if isinstance(item, dict)
    )
    raw_items.extend(
        {
            "source": "error",
            "tool": str(item.get("tool") or item.get("name") or ""),
            "target": str(item.get("target") or item.get("path") or item.get("file") or ""),
            "status": str(item.get("status") or "error"),
            "summary": str(item.get("summary") or item.get("message") or item.get("error") or ""),
        }
        for item in list(payload.get("recent_errors") or [])
        if isinstance(item, dict)
    )
    raw_items.extend(
        {
            "source": "attachment",
            "tool": str(item.get("tool") or item.get("kind") or ""),
            "target": str(item.get("name") or item.get("path") or ""),
            "status": str(item.get("status") or "ready"),
            "summary": str(item.get("summary") or item.get("message") or ""),
        }
        for item in list(payload.get("attachment_evidence_pack") or [])
        if isinstance(item, dict)
    )
    return _normalize_recent_observations(raw_items)


def _legacy_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_plan = payload.get("plan")
    if not raw_plan:
        raw_plan_state = payload.get("plan_state")
        if isinstance(raw_plan_state, dict):
            raw_plan = raw_plan_state.get("items") or raw_plan_state.get("plan") or []
        else:
            raw_plan = raw_plan_state or []
    return [dump_model(item) for item in _normalize_plan_items(raw_plan)]


def _manager_from_legacy_session(payload: dict[str, Any]) -> ContextManager:
    return ContextManager(
        clean_summary=_legacy_summary(payload),
        clean_turns=_legacy_turns(payload),
        recent_observations=_legacy_observations(payload),
        active_files=_legacy_active_files(payload),
        plan=_normalize_plan_items(_legacy_plan(payload)),
        context_version=1,
    )


def _rebase_manager_paths(
    manager: ContextManager,
    *,
    project_root: str,
    previous_roots: list[str] | None = None,
) -> ContextManager:
    if not str(project_root or "").strip():
        return manager
    rebased_turns = _rebase_value_paths_for_model(
        manager.clean_turns,
        project_root=project_root,
        previous_roots=previous_roots,
    )
    rebased_observations = [
        RecentObservation(
            **_rebase_value_paths_for_model(
                dump_model(item),
                project_root=project_root,
                previous_roots=previous_roots,
            )
        )
        for item in manager.recent_observations
    ]
    rebased_active_files = _unique_strings(
        _rebase_value_paths_for_model(
            manager.active_files,
            project_root=project_root,
            previous_roots=previous_roots,
        ),
        limit=10,
        max_chars=500,
    )
    return ContextManager(
        clean_summary=_rebase_text_paths_for_model(
            manager.clean_summary,
            project_root=project_root,
            previous_roots=previous_roots,
        )[:4000],
        clean_turns=rebased_turns,
        recent_observations=rebased_observations,
        active_files=rebased_active_files,
        plan=list(manager.plan),
        context_version=max(0, int(manager.context_version)),
    )


def migrate_legacy_session_to_context_manager(session: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    payload = dict(session or {})
    migrated = False

    if has_context_manager_payload(payload):
        manager = ContextManager.from_payload(_raw_context_manager(payload))
    elif has_legacy_context_payload(payload):
        manager = _manager_from_legacy_session(payload)
        migrated = True
    else:
        manager = ContextManager()

    project_root = str(payload.get("project_root") or payload.get("cwd") or "").strip()
    manager = _rebase_manager_paths(
        manager,
        project_root=project_root,
        previous_roots=_known_previous_project_roots(payload),
    )
    if migrated:
        manager.context_version = max(1, int(manager.context_version or 0))

    payload["context_manager"] = manager.to_session_payload()
    payload["context_schema_version"] = CONTEXT_SCHEMA_VERSION
    return payload, migrated
