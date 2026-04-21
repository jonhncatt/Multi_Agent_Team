from __future__ import annotations

from packages.runtime_core.capability_loader import ToolModule
from packages.runtime_core.tool_execution_bus import ToolExecutionBus


class _LegacyExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.tool_specs = [{"name": "legacy_tool"}]

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "execution_mode": execution_mode,
                "session_id": session_id,
                "project_id": project_id,
                "project_root": project_root,
                "cwd": cwd,
            }
        )


class _ModernExecutor(_LegacyExecutor):
    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "execution_mode": execution_mode,
                "session_id": session_id,
                "project_id": project_id,
                "project_root": project_root,
                "cwd": cwd,
                "model": model,
            }
        )


def test_tool_execution_bus_set_runtime_context_supports_legacy_and_modern_executors() -> None:
    legacy = _LegacyExecutor()
    modern = _ModernExecutor()
    modules = (
        ToolModule(module_id="legacy", title="Legacy", tool_names=("legacy_tool",)),
        ToolModule(module_id="modern", title="Modern", tool_names=("modern_tool",)),
    )
    bus = ToolExecutionBus(
        primary_executor=modern,
        tool_modules=modules,
        executors_by_module={
            "legacy": legacy,
            "modern": modern,
        },
    )

    bus.set_runtime_context(
        execution_mode="host",
        session_id="s-1",
        project_id="project_demo",
        project_root="/tmp/project",
        cwd="/tmp/project",
        model="gpt-test",
    )

    assert legacy.calls == [
        {
            "execution_mode": "host",
            "session_id": "s-1",
            "project_id": "project_demo",
            "project_root": "/tmp/project",
            "cwd": "/tmp/project",
        }
    ]
    assert modern.calls == [
        {
            "execution_mode": "host",
            "session_id": "s-1",
            "project_id": "project_demo",
            "project_root": "/tmp/project",
            "cwd": "/tmp/project",
            "model": "gpt-test",
        }
    ]
