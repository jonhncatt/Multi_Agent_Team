from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


LEGACY_RUN_CHAT_FIELDS: tuple[str, ...] = (
    "text",
    "tool_events",
    "attachment_note",
    "execution_plan",
    "execution_trace",
    "pipeline_hooks",
    "debug_flow",
    "agent_panels",
    "active_roles",
    "current_role",
    "role_states",
    "answer_bundle",
    "usage_total",
    "effective_model",
    "route_state",
)


@dataclass(slots=True)
class OfficeExecutionResult:
    text: str = ""
    tool_events: list[Any] = field(default_factory=list)
    attachment_note: str = ""
    execution_plan: list[str] = field(default_factory=list)
    execution_trace: list[str] = field(default_factory=list)
    pipeline_hooks: list[dict[str, Any]] = field(default_factory=list)
    debug_flow: list[dict[str, Any]] = field(default_factory=list)
    agent_panels: list[dict[str, Any]] = field(default_factory=list)
    active_roles: list[str] = field(default_factory=list)
    current_role: str | None = None
    role_states: list[dict[str, Any]] = field(default_factory=list)
    answer_bundle: dict[str, Any] = field(default_factory=dict)
    usage_total: dict[str, Any] = field(default_factory=dict)
    effective_model: str = ""
    route_state: dict[str, Any] = field(default_factory=dict)
    raw_result: Any = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "text": self.text,
            "tool_events": list(self.tool_events),
            "attachment_note": self.attachment_note,
            "execution_plan": list(self.execution_plan),
            "execution_trace": list(self.execution_trace),
            "pipeline_hooks": list(self.pipeline_hooks),
            "debug_flow": list(self.debug_flow),
            "agent_panels": list(self.agent_panels),
            "active_roles": list(self.active_roles),
            "current_role": self.current_role,
            "role_states": list(self.role_states),
            "answer_bundle": dict(self.answer_bundle),
            "usage_total": dict(self.usage_total),
            "effective_model": self.effective_model,
            "route_state": dict(self.route_state),
        }
        if self.raw_result is not None and not isinstance(self.raw_result, tuple):
            payload["raw"] = self.raw_result
        return payload


def normalize_legacy_run_chat_result(run: Any) -> OfficeExecutionResult:
    if not isinstance(run, tuple):
        return OfficeExecutionResult(text=str(run or ""), raw_result=run)

    values = list(run)
    payload = {name: (values[idx] if idx < len(values) else None) for idx, name in enumerate(LEGACY_RUN_CHAT_FIELDS)}
    return OfficeExecutionResult(
        text=str(payload.get("text") or ""),
        tool_events=list(payload.get("tool_events") or []),
        attachment_note=str(payload.get("attachment_note") or ""),
        execution_plan=[str(item or "") for item in (payload.get("execution_plan") or []) if str(item or "").strip()],
        execution_trace=[str(item or "") for item in (payload.get("execution_trace") or []) if str(item or "").strip()],
        pipeline_hooks=list(payload.get("pipeline_hooks") or []),
        debug_flow=list(payload.get("debug_flow") or []),
        agent_panels=list(payload.get("agent_panels") or []),
        active_roles=[str(item or "") for item in (payload.get("active_roles") or []) if str(item or "").strip()],
        current_role=str(payload.get("current_role") or "").strip() or None,
        role_states=list(payload.get("role_states") or []),
        answer_bundle=dict(payload.get("answer_bundle") or {}),
        usage_total=dict(payload.get("usage_total") or {}),
        effective_model=str(payload.get("effective_model") or ""),
        route_state=dict(payload.get("route_state") or {}),
        raw_result=run,
    )


class OfficeExecutionRuntime(ABC):
    @abstractmethod
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
    ) -> OfficeExecutionResult:
        raise NotImplementedError


class OfficeLegacyHelperSurface(ABC):
    @abstractmethod
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
        **extra: Any,
    ) -> Any:
        raise NotImplementedError


class LegacyOfficeHelperAdapter(OfficeLegacyHelperSurface):
    def __init__(self, legacy_runtime: Any) -> None:
        self._legacy_runtime = legacy_runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self._legacy_runtime, name)

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
        **extra: Any,
    ) -> Any:
        return self._legacy_runtime.run_chat(
            history_turns,
            summary,
            user_message,
            attachment_metas,
            settings,
            session_id=session_id,
            route_state=route_state,
            progress_cb=progress_cb,
            **extra,
        )


class LegacyOfficeExecutionRuntimeAdapter(OfficeExecutionRuntime):
    def __init__(self, legacy_surface: OfficeLegacyHelperSurface) -> None:
        self._legacy_surface = legacy_surface

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
    ) -> OfficeExecutionResult:
        return normalize_legacy_run_chat_result(
            self._legacy_surface.run_chat(
                history_turns,
                summary,
                user_message,
                attachment_metas,
                settings,
                session_id=session_id,
                route_state=route_state,
                progress_cb=progress_cb,
            )
        )


def adapt_office_legacy_helper_surface(value: Any) -> OfficeLegacyHelperSurface:
    if isinstance(value, OfficeLegacyHelperSurface):
        return value
    return LegacyOfficeHelperAdapter(value)


def adapt_office_execution_runtime(value: Any) -> OfficeExecutionRuntime:
    if isinstance(value, OfficeExecutionRuntime):
        return value
    return LegacyOfficeExecutionRuntimeAdapter(adapt_office_legacy_helper_surface(value))


__all__ = [
    "LEGACY_RUN_CHAT_FIELDS",
    "LegacyOfficeExecutionRuntimeAdapter",
    "LegacyOfficeHelperAdapter",
    "OfficeExecutionResult",
    "OfficeExecutionRuntime",
    "OfficeLegacyHelperSurface",
    "adapt_office_execution_runtime",
    "adapt_office_legacy_helper_surface",
    "normalize_legacy_run_chat_result",
]
