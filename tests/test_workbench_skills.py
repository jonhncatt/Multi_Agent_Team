from __future__ import annotations

from pathlib import Path

import pytest

from app.workbench import WorkbenchStore


def _store(tmp_path: Path) -> WorkbenchStore:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return WorkbenchStore(config=type("Cfg", (), {"workspace_root": tmp_path, "default_locale": "zh-CN"})(), agent_dir=agent_dir)


def _write_skill(path: Path, *, name: str, description: str, enabled: bool = True, body: str = "# Skill\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"enabled: {'true' if enabled else 'false'}\n"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )


def test_workbench_lists_system_and_workspace_skills_without_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.system_skills_dir / "repo_triage" / "SKILL.md", name="repo_triage", description="built in")
    _write_skill(store.workspace_skills_dir / "repo_triage" / "SKILL.md", name="repo_triage", description="workspace")

    entries = store.list_skill_entries()

    assert [item["key"] for item in entries] == ["system:repo_triage", "workspace:repo_triage"]
    assert [item["scope"] for item in entries] == ["system", "workspace"]
    assert all(item["content"] == "" for item in entries)
    assert entries[0]["read_only"] is True
    assert entries[1]["read_only"] is False
    assert (store.workspace_skills_dir / ".vp_skill_index.json").is_file()


def test_workbench_rejects_old_skill_frontmatter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.workspace_skills_dir / "old_skill" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "id: old_skill\n"
        "title: Old Skill\n"
        "enabled: true\n"
        "summary: old format\n"
        "---\n\n"
        "# Old\n",
        encoding="utf-8",
    )

    [entry] = store.list_skill_entries()

    assert entry["validation_status"] == "invalid"
    assert "unsupported" in entry["description"]


def test_workbench_system_skills_are_read_only_but_toggle_uses_override(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.system_skills_dir / "system_refactor" / "SKILL.md", name="system_refactor", description="built in")

    disabled = store.set_skill_enabled("system_refactor", False, scope="system")

    assert disabled["enabled"] is False
    assert (store.workspace_skills_dir / ".vp_skill_overrides.json").is_file()
    with pytest.raises(PermissionError):
        store.save_skill("system_refactor", disabled["content"], scope="system")
    with pytest.raises(PermissionError):
        store.delete_skill("system_refactor", scope="system")


def test_workbench_load_skill_prefers_workspace_for_unscoped_reference(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.system_skills_dir / "same_name" / "SKILL.md", name="same_name", description="built in")
    _write_skill(store.workspace_skills_dir / "same_name" / "SKILL.md", name="same_name", description="workspace")

    loaded = store.load_skill("same_name")

    assert loaded["key"] == "workspace:same_name"
    assert loaded["content"].startswith("---\nname: same_name")


def test_workbench_save_skill_from_parts_creates_workspace_skill(tmp_path: Path) -> None:
    store = _store(tmp_path)

    saved = store.save_skill_from_parts(
        name="repo-triage",
        description="Use when investigating repository structure.",
        body="# Repo Triage\n\nInspect entry points first.",
    )

    assert saved["key"] == "workspace:repo-triage"
    assert saved["scope"] == "workspace"
    assert saved["read_only"] is False
    assert saved["enabled"] is True
    assert (store.workspace_skills_dir / "repo-triage" / "SKILL.md").is_file()
    assert "description: Use when investigating repository structure." in saved["content"]


def test_workbench_save_skill_from_parts_requires_overwrite_for_existing_skill(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_skill_from_parts(
        name="repeatable",
        description="Use for the first version.",
        body="# Repeatable\n\nFirst body.",
    )

    with pytest.raises(FileExistsError):
        store.save_skill_from_parts(
            name="repeatable",
            description="Use for the second version.",
            body="# Repeatable\n\nSecond body.",
        )

    saved = store.save_skill_from_parts(
        name="repeatable",
        description="Use for the second version.",
        body="# Repeatable\n\nSecond body.",
        enabled=False,
        overwrite=True,
    )

    assert saved["enabled"] is False
    assert "Second body." in saved["content"]
