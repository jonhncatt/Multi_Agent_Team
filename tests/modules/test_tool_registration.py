from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.vp_support import tools as tools_module


class _StubLocalToolExecutor:
    def __init__(self, config: object) -> None:
        self.tool_specs = [{"name": "exec_command"}]

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        _ = (execution_mode, session_id, model)
        return None

    def clear_runtime_context(self) -> None:
        return None

    def docker_available(self) -> bool:
        return False

    def docker_status(self) -> tuple[bool, str]:
        return False, "stub"

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "name": name, "arguments": arguments}


def test_vp_tool_executor_exposes_canonical_tool_groups() -> None:
    executor = tools_module.get_tool_executor(load_config())
    tool_names = {item["name"] for item in executor.tool_specs}

    assert "exec_command" in tool_names
    assert "web_search" in tool_names
    assert "browser_open" in tool_names

    web_meta = executor.dispatch_meta_for_tool("web_search")
    browser_meta = executor.dispatch_meta_for_tool("browser_open")

    assert web_meta.module_id == "web_context_tools"
    assert web_meta.group == "web_context"
    assert browser_meta.module_id == "browser_tools"
    assert browser_meta.group == "browser"


def test_scoped_executor_accepts_case_variant_tool_name(monkeypatch) -> None:
    monkeypatch.setattr(tools_module, "LocalToolExecutor", _StubLocalToolExecutor)
    executor = tools_module.ScopedToolExecutor(
        config=object(),
        module_id="workspace_core_tools",
        title="Workspace Core Tool Module",
        group="control",
        allowed_tool_names=("exec_command",),
    )

    result = executor.execute("Exec_Command", {"cmd": "pwd"})

    assert bool(result.get("ok")) is True
    assert result.get("name") == "exec_command"


def test_vintage_programmer_specs_only_expose_canonical_file_tool_names() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_files = (
        repo_root / "agents" / "vintage_programmer" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "tools.md",
    )

    for path in spec_files:
        content = path.read_text(encoding="utf-8")
        assert "\n  - read\n" not in content
        assert "read_file" in content
        assert "search_contents_in_file" in content
