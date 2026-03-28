from __future__ import annotations

from typing import Any

from app.models import ChatSettings, ToolEvent
from app.modules.finalizer.v1.module import FinalizerModule
from app.modules.policy_resolver.v1.module import PolicyResolverModule
from app.modules.router_rules.v1.module import RouterRulesModule
from app.modules.router_rules.v2.module import RouterRulesModuleV2


class _PublicOnlyOfficeSurface:
    def route_request_by_rules(
        self,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> dict[str, Any]:
        _ = settings
        return {
            "task_type": "simple_understanding",
            "execution_policy": "attachment_understanding_direct",
            "echo_message": user_message,
            "attachment_count": len(attachment_metas),
            "inline_followup_context": inline_followup_context,
            "route_state": dict(route_state or {}),
        }

    def normalize_route_decision(
        self,
        *,
        route: dict[str, Any],
        fallback: dict[str, Any] | None = None,
        settings: Any | None = None,
    ) -> dict[str, Any]:
        _ = fallback, settings
        return {
            "task_type": str(route.get("task_type") or ""),
            "execution_policy": str(route.get("execution_policy") or ""),
            "normalized": True,
        }

    def sanitize_final_answer(
        self,
        text: str,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        tool_events: list[Any] | None = None,
        inline_followup_context: bool = False,
    ) -> str:
        _ = user_message, attachment_metas, tool_events, inline_followup_context
        return text.strip().upper()


class _PrivateOnlyOfficeSurface:
    def _route_request_by_rules(
        self,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> dict[str, Any]:
        _ = settings
        return {
            "task_type": "simple_understanding",
            "execution_policy": "attachment_understanding_direct",
            "echo_message": user_message,
            "attachment_count": len(attachment_metas),
            "inline_followup_context": inline_followup_context,
            "route_state": dict(route_state or {}),
        }

    def _normalize_route_decision_impl(
        self,
        *,
        route: dict[str, Any],
        fallback: dict[str, Any] | None = None,
        settings: Any | None = None,
    ) -> dict[str, Any]:
        _ = fallback, settings
        return {
            "task_type": str(route.get("task_type") or ""),
            "execution_policy": str(route.get("execution_policy") or ""),
            "normalized": True,
        }

    def _sanitize_final_answer_text_impl(
        self,
        text: str,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        tool_events: list[ToolEvent] | None = None,
        inline_followup_context: bool = False,
    ) -> str:
        _ = user_message, attachment_metas, tool_events, inline_followup_context
        return text.strip().upper()


def test_router_wrappers_use_explicit_router_surface() -> None:
    agent = _PublicOnlyOfficeSurface()
    v1 = RouterRulesModule()
    v2 = RouterRulesModuleV2()

    route_v1 = v1.route(
        agent=agent,
        user_message="解释这个设计",
        attachment_metas=[{"name": "spec.pdf"}],
        settings=ChatSettings(),
        route_state={"active_task": "review"},
        inline_followup_context=True,
    )
    route_v2 = v2.route(
        agent=agent,
        user_message="解释这个设计",
        attachment_metas=[{"name": "spec.pdf"}],
        settings=ChatSettings(),
        route_state={"active_task": "review"},
        inline_followup_context=True,
    )

    assert route_v1["echo_message"] == "解释这个设计"
    assert route_v1["attachment_count"] == 1
    assert route_v1["inline_followup_context"] is True
    assert route_v2 == route_v1


def test_policy_wrapper_uses_explicit_policy_surface() -> None:
    normalized = PolicyResolverModule().normalize_route(
        agent=_PublicOnlyOfficeSurface(),
        route={"task_type": "simple_understanding", "execution_policy": "attachment_understanding_direct"},
        fallback={"execution_policy": "standard_safe_pipeline"},
        settings=ChatSettings(),
    )

    assert normalized["normalized"] is True
    assert normalized["execution_policy"] == "attachment_understanding_direct"


def test_finalizer_wrapper_uses_explicit_finalizer_surface() -> None:
    sanitized = FinalizerModule().sanitize(
        agent=_PublicOnlyOfficeSurface(),
        text="  hello world  ",
        user_message="say hi",
        attachment_metas=[],
        tool_events=[],
        inline_followup_context=False,
    )

    assert sanitized == "HELLO WORLD"


def test_wrapper_surfaces_still_support_private_legacy_fallbacks() -> None:
    agent = _PrivateOnlyOfficeSurface()

    route = RouterRulesModule().route(
        agent=agent,
        user_message="继续",
        attachment_metas=[],
        settings=ChatSettings(),
        route_state={},
        inline_followup_context=False,
    )
    normalized = PolicyResolverModule().normalize_route(
        agent=agent,
        route=route,
        fallback=route,
        settings=ChatSettings(),
    )
    sanitized = FinalizerModule().sanitize(
        agent=agent,
        text="  done  ",
        user_message="继续",
        attachment_metas=[],
        tool_events=[],
        inline_followup_context=False,
    )

    assert route["execution_policy"] == "attachment_understanding_direct"
    assert normalized["normalized"] is True
    assert sanitized == "DONE"
