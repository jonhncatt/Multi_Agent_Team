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


def test_vintage_programmer_tool_docs_only_expose_canonical_file_tool_names() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tool_docs = (
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "tools.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md",
    )
    agent_specs = (
        repo_root / "agents" / "vintage_programmer" / "locales" / "en" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "ja-JP" / "agent.md",
        repo_root / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "agent.md",
    )

    for path in tool_docs:
        content = path.read_text(encoding="utf-8")
        assert "\n  - read\n" not in content
        assert "read_file" in content
        assert "search_contents_in_file" in content

    for path in agent_specs:
        content = path.read_text(encoding="utf-8")
        assert "allowed_tools:" not in content
        assert "\n  - read\n" not in content
