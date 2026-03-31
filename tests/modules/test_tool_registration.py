from __future__ import annotations

from packages.office_modules import tools as tools_module


class _StubLocalToolExecutor:
    def __init__(self, config: object) -> None:
        self.tool_specs = [{"name": "run_shell"}]

    def set_runtime_context(self, *, execution_mode: str | None = None, session_id: str | None = None) -> None:
        return None

    def clear_runtime_context(self) -> None:
        return None

    def docker_available(self) -> bool:
        return False

    def docker_status(self) -> tuple[bool, str]:
        return False, "stub"

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "name": name, "arguments": arguments}


def test_workspace_tool_module_exposes_kernel_upgrade_tools() -> None:
    modules = tools_module.build_office_tool_modules()
    workspace = next(item for item in modules if item.module_id == "workspace_tools")
    tool_names = set(workspace.tool_names)

    assert "kernel_runtime_status" in tool_names
    assert "kernel_shadow_pipeline" in tool_names
    assert "kernel_shadow_self_upgrade" in tool_names


def test_scoped_executor_accepts_case_variant_tool_name(monkeypatch) -> None:
    monkeypatch.setattr(tools_module, "LocalToolExecutor", _StubLocalToolExecutor)
    executor = tools_module.ScopedToolExecutor(
        config=object(),
        module_id="workspace_tools",
        title="Workspace Tool Module",
        group="workspace",
        allowed_tool_names=("run_shell",),
    )

    result = executor.execute("Run_Shell", {"command": "pwd"})

    assert bool(result.get("ok")) is True
    assert result.get("name") == "run_shell"
