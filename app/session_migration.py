from __future__ import annotations

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
    _truncate,
    _unique_strings,
)
from app.serialization import dump_model
from app.session_context import normalize_current_task_focus


CONTEXT_SCHEMA_VERSION = 3


def _raw_context_manager(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("context_manager")
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _legacy_focus(payload: dict[str, Any]) -> dict[str, Any]:
    agent_state = payload.get("agent_state")
    route_state = payload.get("route_state")
    focus = payload.get("current_task_focus")
    if not isinstance(focus, dict):
        focus = {}
    if focus:
        return normalize_current_task_focus(focus)
    if isinstance(agent_state, dict):
        candidate = agent_state.get("current_task_focus") or agent_state.get("task_checkpoint")
        if isinstance(candidate, dict) and candidate:
            return normalize_current_task_focus(candidate)
    if isinstance(route_state, dict):
        candidate = route_state.get("current_task_focus") or route_state.get("task_checkpoint")
        if isinstance(candidate, dict) and candidate:
            return normalize_current_task_focus(candidate)
    return normalize_current_task_focus({})


def _legacy_observations(payload: dict[str, Any]) -> list[RecentObservation]:
    raw_items: list[Any] = []
    raw_items.extend(list(payload.get("recent_observations") or []))
    raw_items.extend(list(payload.get("recent_tool_results") or []))
    raw_items.extend(list(payload.get("recent_errors") or []))
    raw_items.extend(
        {
            "source": "attachment_evidence",
            "tool": str(item.get("tool") or item.get("kind") or ""),
            "target": str(item.get("name") or item.get("path") or ""),
            "status": str(item.get("status") or "ready"),
            "summary": str(item.get("summary") or ""),
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
    thread_memory = payload.get("thread_memory")
    compaction_status = payload.get("compaction_status")
    if not isinstance(thread_memory, dict):
        thread_memory = {}
    if not isinstance(compaction_status, dict):
        compaction_status = {}
    focus = _legacy_focus(payload)
    return ContextManager(
        clean_summary=_truncate(
            payload.get("summary") or thread_memory.get("summary") or compaction_status.get("summary"),
            4000,
        ),
        clean_turns=_normalize_clean_turns(payload.get("turns") or payload.get("history_turns"), current_message="", limit=16),
        recent_observations=_legacy_observations(payload),
        active_files=_unique_strings(focus.get("active_files"), limit=10, max_chars=500),
        plan=_normalize_plan_items(_legacy_plan(payload)),
        context_version=0,
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
    existing_manager = _raw_context_manager(payload)
    if _has_context_manager_data(existing_manager):
        manager = ContextManager.from_payload(existing_manager)
    else:
        manager = _manager_from_legacy_session(payload)

    project_root = str(payload.get("project_root") or payload.get("cwd") or "").strip()
    rebased_manager = _rebase_manager_paths(
        manager,
        project_root=project_root,
        previous_roots=_known_previous_project_roots(payload),
    )
    next_context_manager = rebased_manager.to_session_payload()
    try:
        previous_schema = int(payload.get("context_schema_version") or 0)
    except Exception:
        previous_schema = 0
    changed = bool(payload.get("context_manager") != next_context_manager or previous_schema != CONTEXT_SCHEMA_VERSION)
    payload["context_manager"] = next_context_manager
    payload["context_schema_version"] = CONTEXT_SCHEMA_VERSION
    return payload, changed
