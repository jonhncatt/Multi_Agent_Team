from __future__ import annotations

from typing import Any

from packages.office_modules.module_wrapper_surface import sanitize_with_office_finalizer


class FinalizerModule:
    module_id = "finalizer"
    version = "1.0.0"

    def sanitize(
        self,
        *,
        agent: Any,
        text: str,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        tool_events: list[Any] | None = None,
        inline_followup_context: bool = False,
    ) -> str:
        return sanitize_with_office_finalizer(
            agent,
            text,
            user_message=user_message,
            attachment_metas=attachment_metas,
            tool_events=tool_events,
            inline_followup_context=inline_followup_context,
        )
