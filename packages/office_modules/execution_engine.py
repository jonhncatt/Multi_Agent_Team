from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from packages.office_modules.execution_runtime import (
    OfficeExecutionResult,
    OfficeExecutionRuntime,
    normalize_legacy_run_chat_result,
)


class OfficeExecutionBackend(Protocol):
    def run_chat(
        self,
        history_turns: list[dict[str, Any]],
        summary: str,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        *,
        session_id: str | None = None,
        route_state: dict[str, Any] | None = None,
        progress_cb: Any | None = None,
        blackboard: Any | None = None,
    ) -> Any: ...


@dataclass(slots=True)
class OfficeExecutionEngine(OfficeExecutionRuntime):
    """Minimal canonical office execution runtime.

    Responsibilities are intentionally narrow:
    - accept the formal office execution call
    - forward blackboard compatibility kwargs
    - normalize the result to OfficeExecutionResult
    """

    backend: OfficeExecutionBackend

    def run_chat(
        self,
        history_turns: list[dict[str, Any]],
        summary: str,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        *,
        session_id: str | None = None,
        route_state: dict[str, Any] | None = None,
        progress_cb: Any | None = None,
        blackboard: Any | None = None,
    ) -> OfficeExecutionResult:
        raw_result = self.backend.run_chat(
            history_turns,
            summary,
            user_message,
            attachment_metas,
            settings,
            session_id=session_id,
            route_state=route_state,
            progress_cb=progress_cb,
            blackboard=blackboard,
        )
        return normalize_legacy_run_chat_result(raw_result)

