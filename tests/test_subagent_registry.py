from __future__ import annotations

from pathlib import Path

import pytest

from app.subagent_registry import BuiltinSubagentRegistry, SubagentSpecError


ROOT = Path(__file__).resolve().parents[1]


def test_repository_builtin_subagent_specs_are_valid_and_distinct() -> None:
    registry = BuiltinSubagentRegistry(ROOT / "agents" / "builtin")

    specs = registry.list()

    assert [item.name for item in specs] == ["analyst", "explorer", "summarizer", "tester"]
    assert len({item.developer_instructions for item in specs}) == 4
    assert all(item.tool_scope == "read_only" for item in specs)
    assert "exec_command" in registry.load("tester").allowed_tools
    assert "exec_command" not in registry.load("explorer").allowed_tools


def test_builtin_subagent_registry_rejects_unknown_role(tmp_path: Path) -> None:
    registry = BuiltinSubagentRegistry(tmp_path)

    with pytest.raises(SubagentSpecError, match="Unknown builtin Subagent"):
        registry.load("missing")


def test_builtin_subagent_registry_rejects_unknown_fields(tmp_path: Path) -> None:
    (tmp_path / "explorer.toml").write_text(
        'name = "explorer"\n'
        'description = "Explore"\n'
        'developer_instructions = "Read evidence."\n'
        'unexpected = true\n',
        encoding="utf-8",
    )
    registry = BuiltinSubagentRegistry(tmp_path)

    with pytest.raises(SubagentSpecError, match="Unsupported builtin Subagent fields"):
        registry.load("explorer")
