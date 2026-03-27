from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.business_modules.office_module.manifest import OFFICE_MODULE_COMPATIBILITY_SHIMS, OFFICE_MODULE_MANIFEST
from app.business_modules.office_module.pipeline.demo import run_minimal_demo
from app.business_modules.office_module.pipeline.runtime import build_office_pipeline_trace
from app.business_modules.office_module.policies.catalog import OFFICE_MODULE_POLICY_SET
from app.business_modules.office_module.workflow import ROLE_CHAIN, build_office_workflow_plan
from app.contracts import HealthReport, TaskRequest, TaskResponse
from app.kernel.runtime_context import RuntimeContext
from app.models import ChatSettings
from packages.office_modules.agent_module import create_office_agent, create_office_runtime
from packages.office_modules.execution_runtime import (
    OfficeExecutionRuntime,
    OfficeLegacyHelperSurface,
    adapt_office_execution_runtime,
    adapt_office_legacy_helper_surface,
)


class OfficeModule:
    """Standard business-module entrypoint.

    The execution core still relies on the legacy OfficeAgent runtime for now.
    This module is the formal business-module surface and is treated as the
    compatibility boundary for legacy orchestration logic.
    """

    manifest = OFFICE_MODULE_MANIFEST

    def __init__(
        self,
        *,
        config: Any,
        legacy_host: Any | None = None,
        kernel_runtime: Any | None = None,
    ) -> None:
        self._config = config
        self._kernel_context: Any = None
        self._legacy_host = legacy_host
        self._kernel_runtime = kernel_runtime
        self._execution_runtime: OfficeExecutionRuntime | None = None
        self._legacy_surface: OfficeLegacyHelperSurface | None = None

    def init(self, kernel_context: Any) -> None:
        self._kernel_context = kernel_context

    def bind_legacy_host(self, legacy_host: Any) -> None:
        self._legacy_host = legacy_host
        self._execution_runtime = None
        self._legacy_surface = None

    def _helper_surface(self) -> OfficeLegacyHelperSurface:
        if self._legacy_surface is not None:
            return self._legacy_surface
        if self._legacy_host is not None:
            self._legacy_surface = adapt_office_legacy_helper_surface(self._legacy_host)
            return self._legacy_surface
        self._legacy_surface = create_office_agent(self._config, kernel_runtime=self._kernel_runtime)
        return self._legacy_surface

    def _runtime(self) -> OfficeExecutionRuntime:
        if self._execution_runtime is not None:
            return self._execution_runtime
        if self._legacy_host is not None:
            self._execution_runtime = adapt_office_execution_runtime(self._legacy_host)
            return self._execution_runtime
        self._execution_runtime = create_office_runtime(self._config, kernel_runtime=self._kernel_runtime)
        return self._execution_runtime

    def health_check(self) -> HealthReport:
        return HealthReport(
            component_id=self.manifest.module_id,
            status="healthy",
            summary="office module active",
            details={
                "roles": list(ROLE_CHAIN),
                "compatibility_level": self.manifest.compatibility_level,
                "required_tools": list(self.manifest.required_tools),
                "optional_tools": list(self.manifest.optional_tools),
            },
        )

    def shutdown(self) -> None:
        self._execution_runtime = None
        self._legacy_surface = None

    def handle(self, request: TaskRequest, context: RuntimeContext) -> TaskResponse:
        if self._should_run_minimal_demo(request):
            return run_minimal_demo(
                request=request,
                context=context,
                kernel_context=self._kernel_context,
                module_id=self.manifest.module_id,
            )
        runtime = self._runtime()
        request_context = dict(request.context or {})
        context.selected_roles = list(context.selected_roles or ROLE_CHAIN)
        context.selected_tools = list(context.selected_tools or [*self.manifest.required_tools, *self.manifest.optional_tools])
        context.metadata.setdefault("compatibility_shims", list(OFFICE_MODULE_COMPATIBILITY_SHIMS))
        context.metadata.setdefault("policy_set", list(OFFICE_MODULE_POLICY_SET))
        try:
            settings_obj = self._normalize_settings(request.settings)
            result = runtime.run_chat(
                request_context.get("history_turns") or [],
                str(request_context.get("summary") or ""),
                request.message,
                request.attachments,
                settings_obj,
                session_id=request_context.get("session_id"),
                route_state=request_context.get("route_state") if isinstance(request_context.get("route_state"), dict) else None,
                progress_cb=request_context.get("progress_cb"),
            )
            payload = result.to_payload()
            payload["module_id"] = self.manifest.module_id
            payload["selected_roles"] = list(context.selected_roles)
            payload["selected_tools"] = list(context.selected_tools)
            payload["selected_providers"] = list(context.selected_providers)
            payload["compatibility_shims"] = list(OFFICE_MODULE_COMPATIBILITY_SHIMS)
            payload["module_pipeline"] = build_office_pipeline_trace(
                active_roles=payload.get("active_roles"),
                current_role=payload.get("current_role"),
            )
            return TaskResponse(
                ok=True,
                task_id=request.task_id,
                text=str(payload.get("text") or ""),
                payload=payload,
            )
        except Exception as exc:
            context.health_state = "degraded"
            return TaskResponse(
                ok=False,
                task_id=request.task_id,
                error=str(exc),
                warnings=["office_module handle failed"],
            )

    def invoke(self, request: TaskRequest) -> TaskResponse:
        return self.handle(request, RuntimeContext(request_id=request.task_id, module_id=self.manifest.module_id))

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
    ) -> Any:
        runtime = self._helper_surface()
        return runtime.run_chat(
            history_turns,
            summary,
            user_message,
            attachment_metas,
            self._normalize_settings(settings),
            session_id=session_id,
            route_state=route_state,
            progress_cb=progress_cb,
        )

    def workflow_plan(self) -> list[str]:
        return build_office_workflow_plan()

    def _should_run_minimal_demo(self, request: TaskRequest) -> bool:
        task_type = str(request.task_type or "").strip().lower()
        if task_type in {"demo.minimal", "task.demo.minimal"}:
            return True
        return str(request.context.get("demo_mode") or "").strip().lower() == "minimal"

    def _normalize_settings(self, value: Any) -> ChatSettings:
        if isinstance(value, ChatSettings):
            return value
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            payload = dict(value)
            try:
                return ChatSettings(**payload)
            except Exception:
                pass
        return ChatSettings()
