from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.local_tools import LocalToolExecutor


def test_local_tool_executor_exposes_canonical_tools() -> None:
    executor = LocalToolExecutor(load_config())
    tool_names = {str(item.get("name") or "") for item in executor.tool_specs}

    assert "exec_command" in tool_names
    assert "web_search" in tool_names
    assert "browser_open" in tool_names


def test_vintage_programmer_specs_only_expose_canonical_file_tool_names() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_files = (
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md",
    )

    for path in spec_files:
        content = path.read_text(encoding="utf-8")
        assert "\n  - read\n" not in content
        assert "read_file" in content
        assert "search_contents_in_file" in content
