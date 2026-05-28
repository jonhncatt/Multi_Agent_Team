from __future__ import annotations

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


def _config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    return config


def _registered_tool_names(tmp_path: Path) -> list[str]:
    executor = LocalToolExecutor(_config(tmp_path))
    return [str(item.get("name") or "") for item in executor.tool_specs if str(item.get("name") or "")]


def test_registered_tools_match_metadata(tmp_path: Path) -> None:
    registered = _registered_tool_names(tmp_path)

    assert set(registered) == set(CANONICAL_TOOL_NAMES)
    assert set(registered) == set(TOOL_METADATA)


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


def test_browser_screenshot_is_not_read_only() -> None:
    meta = get_tool_metadata("browser_screenshot")

    assert "browser_screenshot" not in _READ_ONLY_TOOL_NAMES
    assert meta["read_only"] is False
    assert meta["requires"]["workspace_write"] is True
