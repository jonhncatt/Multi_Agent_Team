from __future__ import annotations

from typing import Any

from packages.office_modules.module_wrapper_surface import normalize_with_office_policy


class PolicyResolverModule:
    module_id = "policy_resolver"
    version = "1.0.0"

    def normalize_route(
        self,
        *,
        agent: Any,
        route: dict[str, Any],
        fallback: dict[str, Any],
        settings: Any,
    ) -> dict[str, Any]:
        return normalize_with_office_policy(
            agent,
            route=route,
            fallback=fallback,
            settings=settings,
        )
