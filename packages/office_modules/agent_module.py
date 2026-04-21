from __future__ import annotations

from typing import Any

from packages.office_modules.execution_engine import OfficeExecutionEngine
from packages.office_modules.office_agent_runtime import create_office_runtime_backend
from packages.office_modules.execution_runtime import (
    LegacyOfficeHelperAdapter,
    OfficeExecutionRuntime,
    OfficeLegacyHelperSurface,
)
from packages.runtime_core.capability_loader import AgentModule


def create_office_legacy_surface(
    config: Any,
    *,
    kernel_runtime: Any,
    capability_runtime: Any | None = None,
    tool_executor: Any | None = None,
    host: Any | None = None,
    selected_agent_module_id: str = "office_agent",
    selected_tool_module_id: str = "codex_core_tools",
) -> OfficeLegacyHelperSurface:
    return LegacyOfficeHelperAdapter(
        create_office_runtime_backend(
            config,
            kernel_runtime=kernel_runtime,
            capability_runtime=capability_runtime,
            tool_executor=tool_executor,
            host=host,
            selected_agent_module_id=selected_agent_module_id,
            selected_tool_module_id=selected_tool_module_id,
        )
    )


def create_office_runtime(
    config: Any,
    *,
    kernel_runtime: Any,
    capability_runtime: Any | None = None,
    tool_executor: Any | None = None,
    host: Any | None = None,
    selected_agent_module_id: str = "office_agent",
    selected_tool_module_id: str = "codex_core_tools",
) -> OfficeExecutionRuntime:
    legacy_surface = create_office_legacy_surface(
        config,
        kernel_runtime=kernel_runtime,
        capability_runtime=capability_runtime,
        tool_executor=tool_executor,
        host=host,
        selected_agent_module_id=selected_agent_module_id,
        selected_tool_module_id=selected_tool_module_id,
    )
    return OfficeExecutionEngine(backend=legacy_surface)


def create_office_agent(
    config: Any,
    *,
    kernel_runtime: Any,
    capability_runtime: Any | None = None,
    tool_executor: Any | None = None,
    host: Any | None = None,
    selected_agent_module_id: str = "office_agent",
    selected_tool_module_id: str = "codex_core_tools",
) -> OfficeLegacyHelperSurface:
    return create_office_legacy_surface(
        config,
        kernel_runtime=kernel_runtime,
        capability_runtime=capability_runtime,
        tool_executor=tool_executor,
        host=host,
        selected_agent_module_id=selected_agent_module_id,
        selected_tool_module_id=selected_tool_module_id,
    )


def _build_office_agent_runtime(
    *,
    config: Any,
    kernel_runtime: Any,
    capability_runtime: Any,
    tool_executor: Any,
    host: Any,
):
    return create_office_agent(
        config,
        kernel_runtime=kernel_runtime,
        capability_runtime=capability_runtime,
        tool_executor=tool_executor,
        host=host,
        selected_agent_module_id="office_agent",
        selected_tool_module_id="codex_core_tools",
    )


def build_office_agent_modules() -> tuple[AgentModule, ...]:
    return (
        AgentModule(
            module_id="office_agent",
            title="Office Agent Module",
            description="默认办公智能体模块，内部运行多 agent pipeline。",
            build_runtime=_build_office_agent_runtime,
            default=True,
            roles=(
                "router",
                "coordinator",
                "worker",
                "planner",
                "researcher",
                "file_reader",
                "summarizer",
                "fixer",
                "conflict_detector",
                "reviewer",
                "revision",
                "structurer",
            ),
            profiles=("explainer", "evidence", "patch_worker"),
            metadata={"family": "office", "runtime": "multi_role"},
        ),
    )
