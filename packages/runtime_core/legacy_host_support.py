from __future__ import annotations

from typing import Any

from packages.runtime_core.blackboard import Blackboard


def build_primary_agent(
    *,
    config: Any,
    kernel_runtime: Any,
    capability_runtime: Any,
    tool_executor: Any,
    host: Any,
) -> Any:
    primary_agent_module = capability_runtime.primary_agent_module
    if primary_agent_module is None:
        raise RuntimeError("No AgentModule is available in capability runtime")
    builder = primary_agent_module.build_runtime
    if builder is None:
        raise RuntimeError(f"AgentModule {primary_agent_module.module_id} does not expose build_runtime")
    return builder(
        config=config,
        kernel_runtime=kernel_runtime,
        capability_runtime=capability_runtime,
        tool_executor=tool_executor,
        host=host,
    )


def create_blackboard(
    *,
    session_id: str | None,
    user_message: str,
    attachment_metas: list[dict[str, Any]] | None,
    primary_agent_module: Any,
    primary_tool_module: Any,
    primary_output_module: Any,
    primary_memory_module: Any,
    capability_runtime: Any,
) -> Blackboard:
    return Blackboard.create(
        session_id=session_id,
        user_message=user_message,
        attachment_ids=[
            str((item or {}).get("id") or "").strip()
            for item in (attachment_metas or [])
            if str((item or {}).get("id") or "").strip()
        ],
        selected_agent_module_id=primary_agent_module.module_id,
        selected_tool_module_id=primary_tool_module.module_id,
        selected_output_module_id=primary_output_module.module_id if primary_output_module else "",
        selected_memory_module_id=primary_memory_module.module_id if primary_memory_module else "",
        selected_capability_modules=[item.module_id for item in capability_runtime.bundles],
    )


def complete_blackboard(blackboard: Blackboard, result: Any) -> None:
    blackboard.complete(
        effective_model=str(result[13] if len(result) > 13 else ""),
        route_state=result[14] if len(result) > 14 and isinstance(result[14], dict) else {},
        execution_plan=result[3] if len(result) > 3 and isinstance(result[3], list) else [],
        execution_trace=result[4] if len(result) > 4 and isinstance(result[4], list) else [],
        tool_events=result[1] if len(result) > 1 and isinstance(result[1], list) else [],
        answer_bundle=result[11] if len(result) > 11 and isinstance(result[11], dict) else {},
    )


def kernel_host_snapshot(
    *,
    agent_modules: tuple[Any, ...],
    primary_agent_module: Any,
    tool_modules: tuple[Any, ...],
    primary_tool_module: Any,
    output_modules: tuple[Any, ...],
    primary_output_module: Any,
    memory_modules: tuple[Any, ...],
    primary_memory_module: Any,
    capability_runtime: Any,
    blackboard: Blackboard | None,
) -> dict[str, Any]:
    return {
        "agent_modules": [
            {
                "module_id": item.module_id,
                "title": item.title,
                "description": item.description,
                "roles": list(item.roles),
                "profiles": list(item.profiles),
            }
            for item in agent_modules
        ],
        "primary_agent_module": {
            "module_id": primary_agent_module.module_id,
            "title": primary_agent_module.title,
            "description": primary_agent_module.description,
            "roles": list(primary_agent_module.roles),
            "profiles": list(primary_agent_module.profiles),
        }
        if primary_agent_module
        else {},
        "tool_modules": [
            {
                "module_id": item.module_id,
                "title": item.title,
                "description": item.description,
                "tool_names": list(item.tool_names),
                "group": str(item.metadata.get("group") or ""),
            }
            for item in tool_modules
        ],
        "primary_tool_module": {
            "module_id": primary_tool_module.module_id,
            "title": primary_tool_module.title,
            "description": primary_tool_module.description,
            "tool_names": list(primary_tool_module.tool_names),
        }
        if primary_tool_module
        else {},
        "output_modules": [
            {
                "module_id": item.module_id,
                "title": item.title,
                "description": item.description,
                "output_kinds": list(item.output_kinds),
            }
            for item in output_modules
        ],
        "memory_modules": [
            {
                "module_id": item.module_id,
                "title": item.title,
                "description": item.description,
                "signal_kinds": list(item.signal_kinds),
            }
            for item in memory_modules
        ],
        "primary_output_module": {
            "module_id": primary_output_module.module_id,
            "title": primary_output_module.title,
            "description": primary_output_module.description,
            "output_kinds": list(primary_output_module.output_kinds),
        }
        if primary_output_module
        else {},
        "primary_memory_module": {
            "module_id": primary_memory_module.module_id,
            "title": primary_memory_module.title,
            "description": primary_memory_module.description,
            "signal_kinds": list(primary_memory_module.signal_kinds),
        }
        if primary_memory_module
        else {},
        "capability_modules": list(capability_runtime.metadata.get("module_paths") or []),
        "loaded_capability_bundles": [item.get("module_id") for item in capability_runtime.metadata.get("modules") or []],
        "tool_dispatch_modules": list(capability_runtime.metadata.get("tool_dispatch_modules") or []),
        "role_sources": dict(capability_runtime.metadata.get("role_sources") or {}),
        "blackboard": blackboard.snapshot() if blackboard else {},
    }


__all__ = [
    "build_primary_agent",
    "complete_blackboard",
    "create_blackboard",
    "kernel_host_snapshot",
]
