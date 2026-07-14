from __future__ import annotations

from pathlib import Path

import pytest

from app.workbench import WorkbenchStore


def _store(repository_root: Path, *, configured_workspace_root: Path | None = None) -> WorkbenchStore:
    agent_dir = repository_root / "agents" / "vintage_programmer"
    agent_dir.mkdir(parents=True, exist_ok=True)
    config_root = configured_workspace_root or repository_root
    config_root.mkdir(parents=True, exist_ok=True)
    return WorkbenchStore(
        config=type("Cfg", (), {"workspace_root": config_root, "default_locale": "zh-CN"})(),
        agent_dir=agent_dir,
    )


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


def test_workbench_lists_builtin_and_team_skills_without_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.builtin_skills_dir / "repo_triage" / "SKILL.md", name="repo_triage", description="built in")
    _write_skill(store.team_skills_dir / "protocol_review" / "SKILL.md", name="protocol_review", description="team")

    entries = store.list_skill_entries()

    assert [item["key"] for item in entries] == ["builtin:repo_triage", "team:protocol_review"]
    assert [item["scope"] for item in entries] == ["builtin", "team"]
    assert all(item["content"] == "" for item in entries)
    assert entries[0]["read_only"] is True
    assert entries[1]["read_only"] is False
    assert (store.skill_registry.state_dir / "skill_index.json").is_file()


def test_workbench_rejects_old_skill_frontmatter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.team_skills_dir / "old_skill" / "SKILL.md"
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


def test_workbench_builtin_skills_are_read_only_but_toggle_uses_runtime_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.builtin_skills_dir / "system_refactor" / "SKILL.md", name="system_refactor", description="built in")

    disabled = store.set_skill_enabled("system_refactor", False, scope="builtin")

    assert disabled["enabled"] is False
    assert (store.skill_registry.state_dir / "skill_overrides.json").is_file()
    with pytest.raises(PermissionError):
        store.save_skill("system_refactor", disabled["content"], scope="builtin")
    with pytest.raises(PermissionError):
        store.delete_skill("system_refactor", scope="builtin")


def test_workbench_old_scope_aliases_resolve_to_canonical_scopes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.builtin_skills_dir / "builtin_helper" / "SKILL.md", name="builtin_helper", description="built in")
    _write_skill(store.team_skills_dir / "team_helper" / "SKILL.md", name="team_helper", description="team")

    assert store.load_skill("system:builtin_helper")["key"] == "builtin:builtin_helper"
    assert store.load_skill("workspace:team_helper")["key"] == "team:team_helper"


def test_workbench_unscoped_duplicate_requires_explicit_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.builtin_skills_dir / "same_name" / "SKILL.md", name="same_name", description="built in")
    _write_skill(store.team_skills_dir / "same_name" / "SKILL.md", name="same_name", description="team")

    with pytest.raises(ValueError, match="ambiguous"):
        store.load_skill("same_name")

    assert store.load_skill("team:same_name")["key"] == "team:same_name"
    assert store.load_skill("builtin:same_name")["key"] == "builtin:same_name"


def test_workbench_save_skill_uses_vp_repository_not_configured_business_project(tmp_path: Path) -> None:
    repository_root = tmp_path / "vintage-programmer"
    business_project = tmp_path / "business-code"
    store = _store(repository_root, configured_workspace_root=business_project)

    saved = store.save_skill_from_parts(
        name="repo-triage",
        description="Use when investigating repository structure.",
        body="# Repo Triage\n\nInspect entry points first.",
    )

    assert saved["key"] == "team:repo-triage"
    assert saved["scope"] == "team"
    assert saved["read_only"] is False
    assert (repository_root / "skills" / "team" / "repo-triage" / "SKILL.md").is_file()
    assert not (business_project / "skills").exists()
    assert not (business_project / "workspace" / "skills").exists()


def test_workbench_catalog_is_stable_across_business_project_switches(tmp_path: Path) -> None:
    repository_root = tmp_path / "vintage-programmer"
    first = _store(repository_root, configured_workspace_root=tmp_path / "project-a")
    _write_skill(first.team_skills_dir / "shared" / "SKILL.md", name="shared", description="global team skill")

    second = _store(repository_root, configured_workspace_root=tmp_path / "project-b")

    assert [item["key"] for item in first.list_skill_entries()] == ["team:shared"]
    assert [item["key"] for item in second.list_skill_entries()] == ["team:shared"]


def test_workbench_save_skill_requires_overwrite_and_rejects_builtin_name(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.builtin_skills_dir / "reserved" / "SKILL.md", name="reserved", description="built in")
    with pytest.raises(FileExistsError, match="built-in"):
        store.save_skill_from_parts(name="reserved", description="Use for conflict.", body="# Conflict")

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


def test_workbench_migrates_legacy_workspace_and_user_system_skills_idempotently(tmp_path: Path) -> None:
    legacy_workspace = tmp_path / "workspace" / "skills" / "old_workspace"
    legacy_system = tmp_path / "agents" / "vintage_programmer" / "skills" / "old_company"
    _write_skill(legacy_workspace / "SKILL.md", name="old_workspace", description="legacy workspace")
    (legacy_workspace / "references").mkdir()
    (legacy_workspace / "references" / "notes.md").write_text("legacy reference\n", encoding="utf-8")
    _write_skill(legacy_system / "SKILL.md", name="old_company", description="user-created in old system")

    first = _store(tmp_path)
    assert (first.team_skills_dir / "old_workspace" / "SKILL.md").is_file()
    assert (first.team_skills_dir / "old_workspace" / "references" / "notes.md").read_text(encoding="utf-8") == "legacy reference\n"
    assert (first.team_skills_dir / "old_company" / "SKILL.md").is_file()
    assert {item["name"] for item in first.skill_migration_report["migrated"]} == {"old_workspace", "old_company"}

    second = _store(tmp_path)
    assert second.skill_migration_report["migrated"] == []
    assert {item["name"] for item in second.skill_migration_report["already_present"]} == {"old_workspace", "old_company"}


def test_workbench_legacy_migration_reports_conflict_without_overwrite(tmp_path: Path) -> None:
    legacy = tmp_path / "workspace" / "skills" / "conflict" / "SKILL.md"
    canonical = tmp_path / "skills" / "team" / "conflict" / "SKILL.md"
    _write_skill(legacy, name="conflict", description="legacy", body="# Legacy\n")
    _write_skill(canonical, name="conflict", description="canonical", body="# Canonical\n")

    store = _store(tmp_path)

    assert store.skill_migration_report["status"] == "conflicts"
    assert store.skill_migration_report["conflicts"][0]["name"] == "conflict"
    assert "# Canonical" in canonical.read_text(encoding="utf-8")


def test_workbench_legacy_migration_merges_missing_resources_without_overwrite(tmp_path: Path) -> None:
    legacy_root = tmp_path / "workspace" / "skills" / "shared"
    canonical_root = tmp_path / "skills" / "team" / "shared"
    _write_skill(legacy_root / "SKILL.md", name="shared", description="same")
    _write_skill(canonical_root / "SKILL.md", name="shared", description="same")
    (legacy_root / "references").mkdir()
    (legacy_root / "references" / "rules.md").write_text("legacy rules\n", encoding="utf-8")

    store = _store(tmp_path)

    assert (canonical_root / "references" / "rules.md").read_text(encoding="utf-8") == "legacy rules\n"
    assert store.skill_migration_report["migrated"] == [
        {"source_scope": "workspace", "target_scope": "team", "name": "shared", "resources_copied": 1}
    ]


def test_workbench_legacy_migration_reports_resource_conflict_without_overwrite(tmp_path: Path) -> None:
    legacy_root = tmp_path / "workspace" / "skills" / "shared"
    canonical_root = tmp_path / "skills" / "team" / "shared"
    _write_skill(legacy_root / "SKILL.md", name="shared", description="same")
    _write_skill(canonical_root / "SKILL.md", name="shared", description="same")
    (legacy_root / "references").mkdir()
    (canonical_root / "references").mkdir()
    (legacy_root / "references" / "rules.md").write_text("legacy rules\n", encoding="utf-8")
    (canonical_root / "references" / "rules.md").write_text("team rules\n", encoding="utf-8")

    store = _store(tmp_path)

    assert store.skill_migration_report["status"] == "conflicts"
    assert "supporting resource" in store.skill_migration_report["conflicts"][0]["reason"]
    assert (canonical_root / "references" / "rules.md").read_text(encoding="utf-8") == "team rules\n"


def test_workbench_global_catalog_is_available_to_future_agent_ids(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write_skill(store.team_skills_dir / "shared" / "SKILL.md", name="shared", description="global")

    entries = store.enabled_skills_for_agent("future_document_agent")

    assert [item["key"] for item in entries] == ["team:shared"]


def test_workbench_loads_skill_resources_without_exposing_arbitrary_paths(tmp_path: Path) -> None:
    store = _store(tmp_path)
    skill_file = store.team_skills_dir / "with_reference" / "SKILL.md"
    _write_skill(skill_file, name="with_reference", description="uses a reference")
    reference = skill_file.parent / "references" / "rules.md"
    reference.parent.mkdir(parents=True)
    reference.write_text("# Rules\n\nUse error codes.\n", encoding="utf-8")

    assert store.list_skill_resources("team:with_reference") == ["references/rules.md"]
    loaded = store.load_skill_resource("team:with_reference", "references/rules.md")
    assert loaded["resource"] == "references/rules.md"
    assert "Use error codes." in loaded["content"]
    assert "path" not in loaded
    with pytest.raises(ValueError):
        store.load_skill_resource("team:with_reference", "../outside.md")


def test_workbench_exposes_enabled_skill_path_without_a_script_resolver(tmp_path: Path) -> None:
    store = _store(tmp_path)
    skill_file = store.team_skills_dir / "scripted" / "SKILL.md"
    _write_skill(skill_file, name="scripted", description="runs a checked script")
    script = skill_file.parent / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")
    (script.parent / "notes.txt").write_text("not executable\n", encoding="utf-8")

    enabled = store.enabled_skills_for_agent("vintage_programmer")

    assert [item["key"] for item in enabled] == ["team:scripted"]
    assert Path(enabled[0]["path"]) == skill_file.resolve()
    assert not hasattr(store, "resolve_skill_script")

    store.set_skill_enabled("scripted", False, scope="team")
    assert store.enabled_skills_for_agent("vintage_programmer") == []
