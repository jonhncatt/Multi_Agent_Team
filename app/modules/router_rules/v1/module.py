from __future__ import annotations

from typing import Any

from packages.office_modules.module_wrapper_surface import route_with_office_router


class RouterRulesModule:
    module_id = "router_rules"
    version = "1.0.0"

    def route(
        self,
        *,
        agent: Any,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> dict[str, Any]:
        return route_with_office_router(
            agent,
            user_message=user_message,
            attachment_metas=attachment_metas,
            settings=settings,
            route_state=route_state,
            inline_followup_context=inline_followup_context,
        )
