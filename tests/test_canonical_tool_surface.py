from __future__ import annotations

import ast
from pathlib import Path
import re

from app.config import load_config
from app.local_tools import LocalToolExecutor
from app.tool_metadata import TOOL_METADATA, get_tool_metadata
from app.vintage_programmer_runtime import _READ_ONLY_TOOL_NAMES
from app.workbench import build_tool_descriptors


CANONICAL_TOOL_NAMES = (
    "update_plan",
    "request_user_input",
    "spawn_subagent",
    "wait_subagents",
    "read_tool_result",
    "save_skill",
    "list_tasks",
    "save_task",
    "exec_command",
    "write_stdin",
    "apply_patch",
    "read_file",
    "list_dir",
    "glob_file_search",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "read_section",
    "search_codebase",
    "table_extract",
    "fact_check_file",
    "web_search",
    "web_fetch",
    "web_download",
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_scroll",
    "browser_snapshot",
    "browser_screenshot",
    "image_inspect",
    "image_read",
    "sessions_list",
    "sessions_history",
    "archive_extract",
    "mail_extract_attachments",
)

LEGACY_TOOL_NAMES = (
    "load_skill",
    "run_skill_script",
    "read_text_file",
    "search_text_in_file",
    "multi_query_search",
    "read_section_by_heading",
    "download_web_file",
    "view_image",
    "list_sessions",
    "read_session_history",
    "read",
    "search_file",
    "search_file_multi",
    "search_web",
    "fetch_web",
)

HIDDEN_NON_CANONICAL_DISPATCH_NAMES = (
    "run_shell",
    "list_directory",
    "doc_index_build",
    "copy_file",
    "extract_zip",
    "extract_msg_attachments",
    "write_text_file",
    "append_text_file",
    "replace_in_file",
    "list_skills",
    "read_skill",
    "write_skill",
    "toggle_skill",
    "list_agent_specs",
    "read_agent_spec",
    "write_agent_spec",
)


def _config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    return config


def _registered_tool_names(tmp_path: Path) -> list[str]:
    executor = LocalToolExecutor(_config(tmp_path))
    return [str(item.get("name") or "") for item in executor.tool_specs if str(item.get("name") or "")]


def _execute_impl_dispatch_names() -> list[str]:
    path = Path("app/local_tools.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_execute_impl = False
            self.names: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.in_execute_impl
            if node.name == "_execute_impl":
                self.in_execute_impl = True
                self.generic_visit(node)
                self.in_execute_impl = previous
                return
            self.generic_visit(node)

        def visit_Compare(self, node: ast.Compare) -> None:
            if self.in_execute_impl and isinstance(node.left, ast.Name) and node.left.id == "name":
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                        self.names.append(comparator.value)
            self.generic_visit(node)

    visitor = Visitor()
    visitor.visit(tree)
    return sorted(set(visitor.names))


def test_registered_tools_match_metadata(tmp_path: Path) -> None:
    registered = _registered_tool_names(tmp_path)

    assert set(registered) == set(CANONICAL_TOOL_NAMES)
    assert set(registered) == set(TOOL_METADATA)


def test_execute_impl_dispatch_names_match_registered_tools(tmp_path: Path) -> None:
    registered = _registered_tool_names(tmp_path)
    dispatch_names = _execute_impl_dispatch_names()

    assert dispatch_names == sorted(registered)


def test_no_legacy_tools_registered(tmp_path: Path) -> None:
    registered = set(_registered_tool_names(tmp_path))

    assert registered.isdisjoint(LEGACY_TOOL_NAMES)


def test_no_legacy_tools_in_default_evals() -> None:
    legacy_tool_patterns = tuple(
        re.compile(rf'"(?:name|tool)"\s*:\s*"{re.escape(name)}"')
        for name in LEGACY_TOOL_NAMES
    )
    for path in (
        Path("evals/cases.json"),
        Path("evals/gate_cases.json"),
    ):
        content = path.read_text(encoding="utf-8")
        assert not any(pattern.search(content) for pattern in legacy_tool_patterns), path


def test_workbench_descriptors_are_canonical_only(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    descriptors = build_tool_descriptors(executor.tool_specs)
    names = {str(item.get("name") or "") for item in descriptors}

    assert names == set(CANONICAL_TOOL_NAMES)
    assert names.isdisjoint(LEGACY_TOOL_NAMES)


def test_legacy_tools_are_not_executable(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    sample_path = tmp_path / "README.md"
    sample_path.write_text("demo\n", encoding="utf-8")
    arguments_by_tool = {
        "load_skill": {"key": "team:demo"},
        "run_skill_script": {"key": "team:demo", "script": "scripts/demo.py"},
        "read_text_file": {"path": str(sample_path)},
        "search_text_in_file": {"path": str(sample_path), "query": "demo"},
        "multi_query_search": {"path": str(sample_path), "queries": ["demo"]},
        "read_section_by_heading": {"path": str(sample_path), "heading": "demo"},
        "download_web_file": {"url": "https://example.com"},
        "view_image": {"path": str(sample_path)},
        "list_sessions": {"max_sessions": 5},
        "read_session_history": {"session_id": "demo"},
        "search_web": {"query": "demo"},
        "fetch_web": {"url": "https://example.com"},
        "read": {"path": str(sample_path)},
        "search_file": {"path": str(sample_path), "query": "demo"},
        "search_file_multi": {"path": str(sample_path), "queries": ["demo"]},
    }

    for name in LEGACY_TOOL_NAMES:
        result = executor.execute(name, arguments_by_tool[name])
        assert result["ok"] is False
        assert result["error"]["kind"] == "unknown_tool"
        assert result["error"]["tool"] == name


def test_hidden_non_canonical_tools_are_not_executable(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    sample_path = tmp_path / "README.md"
    sample_path.write_text("demo\n", encoding="utf-8")
    arguments_by_tool = {
        "run_shell": {"command": "pwd"},
        "list_directory": {"path": "."},
        "doc_index_build": {"path": str(sample_path)},
        "copy_file": {"src_path": str(sample_path), "dst_path": str(tmp_path / "copy.md")},
        "extract_zip": {"zip_path": str(sample_path), "dst_dir": str(tmp_path / "out")},
        "extract_msg_attachments": {"msg_path": str(sample_path), "output_dir": str(tmp_path / "out")},
        "write_text_file": {"path": str(sample_path), "content": "demo"},
        "append_text_file": {"path": str(sample_path), "content": "demo"},
        "replace_in_file": {"path": str(sample_path), "old": "demo", "new": "updated"},
        "list_skills": {},
        "read_skill": {"skill_id": "example"},
        "write_skill": {"skill_id": "example", "content": "demo"},
        "toggle_skill": {"skill_id": "example", "enabled": True},
        "list_agent_specs": {},
        "read_agent_spec": {"name": "example"},
        "write_agent_spec": {"name": "example", "content": "demo"},
    }

    for name in HIDDEN_NON_CANONICAL_DISPATCH_NAMES:
        result = executor.execute(name, arguments_by_tool[name])
        assert result["ok"] is False
        assert result["error"]["kind"] == "unknown_tool"
        assert result["error"]["tool"] == name


def test_high_risk_hidden_write_tools_are_not_executable(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    sample_path = tmp_path / "README.md"
    sample_path.write_text("demo\n", encoding="utf-8")
    high_risk_arguments = {
        "write_text_file": {"path": str(sample_path), "content": "demo"},
        "append_text_file": {"path": str(sample_path), "content": "demo"},
        "replace_in_file": {"path": str(sample_path), "old": "demo", "new": "updated"},
        "copy_file": {"src_path": str(sample_path), "dst_path": str(tmp_path / "copy.md")},
    }

    for name, arguments in high_risk_arguments.items():
        result = executor.execute(name, arguments)
        assert result["ok"] is False
        assert result["error"]["kind"] == "unknown_tool"


def test_skill_and_agent_spec_tools_are_not_executable(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    admin_arguments = {
        "write_skill": {"skill_id": "example", "content": "demo"},
        "toggle_skill": {"skill_id": "example", "enabled": True},
        "write_agent_spec": {"name": "example", "content": "demo"},
    }

    for name, arguments in admin_arguments.items():
        result = executor.execute(name, arguments)
        assert result["ok"] is False
        assert result["error"]["kind"] == "unknown_tool"


def test_browser_screenshot_is_not_read_only() -> None:
    meta = get_tool_metadata("browser_screenshot")

    assert "browser_screenshot" not in _READ_ONLY_TOOL_NAMES
    assert meta["read_only"] is False
    assert meta["requires"]["workspace_write"] is True
