from __future__ import annotations

from typing import Any

from packages.office_modules.execution_runtime import adapt_office_legacy_helper_surface


def route_with_office_router(
    agent: Any,
    *,
    user_message: str,
    attachment_metas: list[dict[str, Any]],
    settings: Any,
    route_state: dict[str, Any] | None = None,
    inline_followup_context: bool = False,
) -> dict[str, Any]:
    helper = adapt_office_legacy_helper_surface(agent)
    return helper.route_request_by_rules(
        user_message=user_message,
        attachment_metas=attachment_metas,
        settings=settings,
        route_state=route_state,
        inline_followup_context=inline_followup_context,
    )


def normalize_with_office_policy(
    agent: Any,
    *,
    route: dict[str, Any],
    fallback: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    helper = adapt_office_legacy_helper_surface(agent)
    return helper.normalize_route_decision(
        route=route,
        fallback=fallback,
        settings=settings,
    )


def sanitize_with_office_finalizer(
    agent: Any,
    text: str,
    *,
    user_message: str,
    attachment_metas: list[dict[str, Any]],
    tool_events: list[Any] | None = None,
    inline_followup_context: bool = False,
) -> str:
    helper = adapt_office_legacy_helper_surface(agent)
    return helper.sanitize_final_answer(
        text,
        user_message=user_message,
        attachment_metas=attachment_metas,
        tool_events=tool_events,
        inline_followup_context=inline_followup_context,
    )
