from __future__ import annotations

from typing import Any

from app.agents.role_catalog import ROLE_KINDS
from app.role_runtime import RoleContext, RoleResult, RoleSpec


def make_role_spec(
    agent: Any,
    role: str,
    *,
    description: str = "",
    tool_names: list[str] | tuple[str, ...] | None = None,
    output_keys: list[str] | tuple[str, ...] | None = None,
) -> RoleSpec:
    role_key = str(role or "").strip().lower()
    kind = ROLE_KINDS.get(role_key, "agent")
    return RoleSpec(
        role=role_key,
        kind=kind,
        llm_driven=kind != "processor",
        description=description,
        tool_names=tuple(tool_names or ()),
        output_keys=tuple(output_keys or ()),
    )


def role_payload_dict(value: RoleResult | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, RoleResult):
        return value.payload
    if isinstance(value, dict):
        return value
    return {}


def make_role_context(
    agent: Any,
    role: str,
    *,
    requested_model: str = "",
    user_message: str = "",
    effective_user_message: str = "",
    history_summary: str = "",
    attachment_metas: list[dict[str, Any]] | None = None,
    tool_events: list[Any] | None = None,
    planner_brief: RoleResult | dict[str, Any] | None = None,
    reviewer_brief: RoleResult | dict[str, Any] | None = None,
    conflict_brief: RoleResult | dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
    execution_trace: list[str] | None = None,
    response_text: str = "",
    user_content: Any = None,
    extra: dict[str, Any] | None = None,
) -> RoleContext:
    return RoleContext(
        role=str(role or "").strip().lower(),
        requested_model=requested_model,
        user_message=user_message,
        effective_user_message=effective_user_message,
        history_summary=history_summary,
        attachment_metas=list(attachment_metas or []),
        tool_events=list(tool_events or []),
        planner_brief=dict(role_payload_dict(planner_brief)),
        reviewer_brief=dict(role_payload_dict(reviewer_brief)),
        conflict_brief=dict(role_payload_dict(conflict_brief)),
        route=dict(route or {}),
        execution_trace=list(execution_trace or []),
        response_text=response_text,
        user_content=user_content,
        extra=dict(extra or {}),
    )


def make_role_result(agent: Any, spec: RoleSpec, context: RoleContext, payload: dict[str, Any], raw_text: str) -> RoleResult:
    summary = str(payload.get("summary") or payload.get("objective") or "").strip()
    return RoleResult(
        spec=spec,
        context=context,
        payload=payload,
        raw_text=raw_text,
        summary=summary,
        usage=payload.get("usage") or agent._empty_usage(),
        effective_model=str(payload.get("effective_model") or context.requested_model).strip(),
        notes=agent._normalize_string_list(payload.get("notes") or [], limit=6, item_limit=220),
    )


def make_default_role_result(
    agent: Any,
    role: str,
    *,
    payload: dict[str, Any],
    requested_model: str = "",
    user_message: str = "",
    effective_user_message: str = "",
    history_summary: str = "",
    attachment_metas: list[dict[str, Any]] | None = None,
    tool_events: list[Any] | None = None,
    planner_brief: RoleResult | dict[str, Any] | None = None,
    reviewer_brief: RoleResult | dict[str, Any] | None = None,
    conflict_brief: RoleResult | dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
    execution_trace: list[str] | None = None,
    response_text: str = "",
    user_content: Any = None,
    extra: dict[str, Any] | None = None,
    description: str = "",
    tool_names: list[str] | tuple[str, ...] | None = None,
    output_keys: list[str] | tuple[str, ...] | None = None,
    raw_text: str = "",
) -> RoleResult:
    context = make_role_context(
        agent,
        role,
        requested_model=requested_model,
        user_message=user_message,
        effective_user_message=effective_user_message,
        history_summary=history_summary,
        attachment_metas=attachment_metas,
        tool_events=tool_events,
        planner_brief=planner_brief,
        reviewer_brief=reviewer_brief,
        conflict_brief=conflict_brief,
        route=route,
        execution_trace=execution_trace,
        response_text=response_text,
        user_content=user_content,
        extra=extra,
    )
    spec = make_role_spec(agent, role, description=description, tool_names=tool_names, output_keys=output_keys)
    return make_role_result(agent, spec, context, payload, raw_text)
