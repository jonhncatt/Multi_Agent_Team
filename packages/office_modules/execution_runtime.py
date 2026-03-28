from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import json
from pathlib import Path
from threading import Lock
from typing import Any

from packages.runtime_core.legacy_host_support import kernel_host_snapshot, read_kernel_host_getattr_metrics


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

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_HELPER_SURFACE_METRICS_PATH = REPO_ROOT / "artifacts" / "platform_metrics" / "office_legacy_helper_surface_calls.json"
_LEGACY_HELPER_SURFACE_METRICS_LOCK = Lock()
_LEGACY_HELPER_SURFACE_METRICS_CACHE: dict[str, Any] | None = None


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
        blackboard: Any | None = None,
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

    @abstractmethod
    def route_request_by_rules(
        self,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def build_session_route_state(self, route: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def normalize_route_decision(
        self,
        *,
        route: dict[str, Any],
        fallback: dict[str, Any] | None = None,
        settings: Any | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def sanitize_final_answer(
        self,
        text: str,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        tool_events: list[Any] | None = None,
        inline_followup_context: bool = False,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def _debug_kernel_module_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_kernel_host_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_tool_registry_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_role_contract_matrix(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_capability_multi_module_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_route_runtime_override_attachment_context_requires_tooling(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _debug_route_runtime_override_force_tool_followup(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _summarize_validation_context(self, tool_events: list[Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _hook_before_route_finalize(
        self,
        *,
        route: dict[str, Any],
        router_raw: str,
        planner_user_message: str,
        attachment_issues: list[str],
        followup_has_attachments: bool,
        followup_attachment_requires_tools: bool,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def _build_followup_topic_hint(self, *, user_message: str, history_turns: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    @abstractmethod
    def _should_force_initial_tool_execution(
        self,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
    ) -> bool:
        raise NotImplementedError


def _default_legacy_helper_surface_metrics() -> dict[str, Any]:
    return {
        "updated_at": "",
        "run_chat_calls": 0,
        "method_calls": {},
        "attribute_accesses": {},
    }


def _load_legacy_helper_surface_metrics() -> dict[str, Any]:
    global _LEGACY_HELPER_SURFACE_METRICS_CACHE
    if _LEGACY_HELPER_SURFACE_METRICS_CACHE is not None:
        return _LEGACY_HELPER_SURFACE_METRICS_CACHE
    if LEGACY_HELPER_SURFACE_METRICS_PATH.exists():
        try:
            loaded = json.loads(LEGACY_HELPER_SURFACE_METRICS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metrics = _default_legacy_helper_surface_metrics()
                metrics.update(loaded)
                metrics["method_calls"] = dict(metrics.get("method_calls") or {})
                metrics["attribute_accesses"] = dict(metrics.get("attribute_accesses") or {})
                _LEGACY_HELPER_SURFACE_METRICS_CACHE = metrics
                return metrics
        except (OSError, ValueError, TypeError):
            pass
    _LEGACY_HELPER_SURFACE_METRICS_CACHE = _default_legacy_helper_surface_metrics()
    return _LEGACY_HELPER_SURFACE_METRICS_CACHE


def _persist_legacy_helper_surface_metrics(metrics: dict[str, Any]) -> None:
    LEGACY_HELPER_SURFACE_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEGACY_HELPER_SURFACE_METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_legacy_helper_surface_usage(name: str, *, kind: str) -> None:
    with _LEGACY_HELPER_SURFACE_METRICS_LOCK:
        metrics = _load_legacy_helper_surface_metrics()
        bucket = metrics["attribute_accesses"] if kind == "attribute" else metrics["method_calls"]
        bucket[name] = int(bucket.get(name) or 0) + 1
        if name == "run_chat" and kind == "method":
            metrics["run_chat_calls"] = int(metrics.get("run_chat_calls") or 0) + 1
        metrics["updated_at"] = datetime.now(timezone.utc).isoformat()
        _persist_legacy_helper_surface_metrics(metrics)


def read_legacy_helper_surface_metrics() -> dict[str, Any]:
    with _LEGACY_HELPER_SURFACE_METRICS_LOCK:
        metrics = _load_legacy_helper_surface_metrics()
        return {
            "updated_at": str(metrics.get("updated_at") or ""),
            "run_chat_calls": int(metrics.get("run_chat_calls") or 0),
            "method_calls": dict(metrics.get("method_calls") or {}),
            "attribute_accesses": dict(metrics.get("attribute_accesses") or {}),
        }


def reset_legacy_helper_surface_metrics() -> None:
    global _LEGACY_HELPER_SURFACE_METRICS_CACHE
    with _LEGACY_HELPER_SURFACE_METRICS_LOCK:
        _LEGACY_HELPER_SURFACE_METRICS_CACHE = _default_legacy_helper_surface_metrics()
        if LEGACY_HELPER_SURFACE_METRICS_PATH.exists():
            LEGACY_HELPER_SURFACE_METRICS_PATH.unlink()


class LegacyOfficeHelperAdapter(OfficeLegacyHelperSurface):
    def __init__(self, legacy_runtime: Any) -> None:
        self._legacy_runtime = legacy_runtime

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._legacy_runtime, name)
        if callable(value):
            @wraps(value)
            def _wrapped(*args: Any, **kwargs: Any) -> Any:
                _record_legacy_helper_surface_usage(name, kind="method")
                return value(*args, **kwargs)

            return _wrapped
        _record_legacy_helper_surface_usage(name, kind="attribute")
        return value

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
        _record_legacy_helper_surface_usage("run_chat", kind="method")
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

    def route_request_by_rules(
        self,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "route_request_by_rules", None)
        if callable(method):
            return dict(
                method(
                    user_message=user_message,
                    attachment_metas=attachment_metas,
                    settings=settings,
                    route_state=route_state,
                    inline_followup_context=inline_followup_context,
                )
                or {}
            )
        _record_legacy_helper_surface_usage("_route_request_by_rules", kind="method")
        return dict(
            self._legacy_runtime._route_request_by_rules(
                user_message=user_message,
                attachment_metas=attachment_metas,
                settings=settings,
                route_state=route_state,
                inline_followup_context=inline_followup_context,
            )
            or {}
        )

    def build_session_route_state(self, route: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "build_session_route_state", None)
        if callable(method):
            return dict(method(route) or {})
        _record_legacy_helper_surface_usage("_build_session_route_state", kind="method")
        return dict(self._legacy_runtime._build_session_route_state(route) or {})

    def normalize_route_decision(
        self,
        *,
        route: dict[str, Any],
        fallback: dict[str, Any] | None = None,
        settings: Any | None = None,
    ) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "normalize_route_decision", None)
        if callable(method):
            return dict(method(route=route, fallback=fallback, settings=settings) or {})
        _record_legacy_helper_surface_usage("_normalize_route_decision_impl", kind="method")
        return dict(
            self._legacy_runtime._normalize_route_decision_impl(
                route=route,
                fallback=fallback,
                settings=settings,
            )
            or {}
        )

    def sanitize_final_answer(
        self,
        text: str,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        tool_events: list[Any] | None = None,
        inline_followup_context: bool = False,
    ) -> str:
        method = getattr(self._legacy_runtime, "sanitize_final_answer", None)
        if callable(method):
            return str(
                method(
                    text,
                    user_message=user_message,
                    attachment_metas=attachment_metas,
                    tool_events=tool_events,
                    inline_followup_context=inline_followup_context,
                )
                or ""
            )
        _record_legacy_helper_surface_usage("_sanitize_final_answer_text_impl", kind="method")
        return str(
            self._legacy_runtime._sanitize_final_answer_text_impl(
                text,
                user_message=user_message,
                attachment_metas=attachment_metas,
                tool_events=tool_events,
                inline_followup_context=inline_followup_context,
            )
            or ""
        )

    def _debug_kernel_module_snapshot(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_kernel_module_snapshot", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_kernel_module_snapshot")

    def _debug_kernel_host_snapshot(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_kernel_host_snapshot", None)
        if callable(method):
            return dict(method() or {})
        capability_runtime = getattr(self._legacy_runtime, "_capability_runtime", None)
        if capability_runtime is not None:
            return kernel_host_snapshot(
                agent_modules=tuple(capability_runtime.agent_modules),
                primary_agent_module=capability_runtime.primary_agent_module,
                tool_modules=tuple(capability_runtime.tool_modules),
                primary_tool_module=capability_runtime.primary_tool_module,
                output_modules=tuple(capability_runtime.output_modules),
                primary_output_module=capability_runtime.primary_output_module,
                memory_modules=tuple(capability_runtime.memory_modules),
                primary_memory_module=capability_runtime.primary_memory_module,
                capability_runtime=capability_runtime,
                blackboard=None,
                getattr_metrics=read_kernel_host_getattr_metrics(),
            )
        raise AttributeError("_debug_kernel_host_snapshot")

    def _debug_tool_registry_snapshot(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_tool_registry_snapshot", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_tool_registry_snapshot")

    def _debug_role_contract_matrix(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_role_contract_matrix", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_role_contract_matrix")

    def _debug_capability_multi_module_snapshot(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_capability_multi_module_snapshot", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_capability_multi_module_snapshot")

    def _debug_route_runtime_override_attachment_context_requires_tooling(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_route_runtime_override_attachment_context_requires_tooling", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_route_runtime_override_attachment_context_requires_tooling")

    def _debug_route_runtime_override_force_tool_followup(self) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_debug_route_runtime_override_force_tool_followup", None)
        if callable(method):
            return dict(method() or {})
        raise AttributeError("_debug_route_runtime_override_force_tool_followup")

    def _summarize_validation_context(self, tool_events: list[Any]) -> dict[str, Any]:
        method = getattr(self._legacy_runtime, "_summarize_validation_context", None)
        if callable(method):
            return dict(method(tool_events) or {})
        raise AttributeError("_summarize_validation_context")

    def _hook_before_route_finalize(
        self,
        *,
        route: dict[str, Any],
        router_raw: str,
        planner_user_message: str,
        attachment_issues: list[str],
        followup_has_attachments: bool,
        followup_attachment_requires_tools: bool,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
    ) -> Any:
        method = getattr(self._legacy_runtime, "_hook_before_route_finalize", None)
        if callable(method):
            return method(
                route=route,
                router_raw=router_raw,
                planner_user_message=planner_user_message,
                attachment_issues=attachment_issues,
                followup_has_attachments=followup_has_attachments,
                followup_attachment_requires_tools=followup_attachment_requires_tools,
                attachment_metas=attachment_metas,
                settings=settings,
            )
        raise AttributeError("_hook_before_route_finalize")

    def _build_followup_topic_hint(self, *, user_message: str, history_turns: list[dict[str, Any]]) -> str:
        method = getattr(self._legacy_runtime, "_build_followup_topic_hint", None)
        if callable(method):
            return str(method(user_message=user_message, history_turns=history_turns) or "")
        raise AttributeError("_build_followup_topic_hint")

    def _should_force_initial_tool_execution(
        self,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
    ) -> bool:
        method = getattr(self._legacy_runtime, "_should_force_initial_tool_execution", None)
        if callable(method):
            return bool(method(user_message, attachment_metas))
        raise AttributeError("_should_force_initial_tool_execution")


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
        blackboard: Any | None = None,
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
                blackboard=blackboard,
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
    "read_legacy_helper_surface_metrics",
    "reset_legacy_helper_surface_metrics",
]
