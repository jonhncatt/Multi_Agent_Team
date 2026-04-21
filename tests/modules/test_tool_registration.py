from __future__ import annotations

from packages.office_modules import tools as tools_module


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
        _ = model
        return None

    def clear_runtime_context(self) -> None:
        return None

    def docker_available(self) -> bool:
        return False

    def docker_status(self) -> tuple[bool, str]:
        return False, "stub"

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "name": name, "arguments": arguments}


def test_codex_core_tool_module_exposes_core_tools() -> None:
    modules = tools_module.build_office_tool_modules()
    module_ids = {item.module_id for item in modules}
    workspace = next(item for item in modules if item.module_id == "codex_core_tools")
    fs_tools = next(item for item in modules if item.module_id == "fs_content_tools")
    web_tools = next(item for item in modules if item.module_id == "web_context_tools")
    session_tools = next(item for item in modules if item.module_id == "session_context_tools")
    media_tools = next(item for item in modules if item.module_id == "media_context_tools")
    unpack_tools = next(item for item in modules if item.module_id == "content_unpack_tools")
    tool_names = set(workspace.tool_names)

    assert {
        "codex_core_tools",
        "fs_content_tools",
        "web_context_tools",
        "session_context_tools",
        "media_context_tools",
        "content_unpack_tools",
        "browser_tools",
    }.issubset(module_ids)
    assert "exec_command" in tool_names
    assert "write_stdin" in tool_names
    assert "apply_patch" in tool_names
    assert "update_plan" in tool_names
    assert set(fs_tools.tool_names) == {
        "read",
        "search_file",
        "search_file_multi",
        "read_section",
        "table_extract",
        "fact_check_file",
        "search_codebase",
    }
    assert set(web_tools.tool_names) == {"web_search", "web_fetch", "web_download"}
    assert set(session_tools.tool_names) == {"sessions_list", "sessions_history"}
    assert set(media_tools.tool_names) == {"image_inspect", "image_read"}
    assert set(unpack_tools.tool_names) == {"archive_extract", "mail_extract_attachments"}


def test_scoped_executor_accepts_case_variant_tool_name(monkeypatch) -> None:
    monkeypatch.setattr(tools_module, "LocalToolExecutor", _StubLocalToolExecutor)
    executor = tools_module.ScopedToolExecutor(
        config=object(),
        module_id="codex_core_tools",
        title="Codex Core Tool Module",
        group="codex_core",
        allowed_tool_names=("exec_command",),
    )

    result = executor.execute("Exec_Command", {"cmd": "pwd"})

    assert bool(result.get("ok")) is True
    assert result.get("name") == "exec_command"
