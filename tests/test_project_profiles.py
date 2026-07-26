from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.project_profiles import ProjectProfileError, ProjectProfileRegistry


def _write_profile(
    root: Path,
    *,
    scope: str,
    profile_id: str,
    display_name: str,
    instructions: str,
) -> Path:
    profile_dir = root / "project_profiles" / scope / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": profile_id,
                "display_name": display_name,
                "description": f"Description for {display_name}",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (profile_dir / "AGENTS.md").write_text(instructions, encoding="utf-8")
    return profile_dir


def test_project_profile_registry_lists_scoped_profiles_and_reads_instructions(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        scope="builtin",
        profile_id="vintage-programmer",
        display_name="Vintage Programmer",
        instructions="VP instructions",
    )
    _write_profile(
        tmp_path,
        scope="team",
        profile_id="pcbasher",
        display_name="PCBasher",
        instructions="PCBasher instructions",
    )
    registry = ProjectProfileRegistry(tmp_path)

    rows = registry.list_profiles()
    profile, instructions = registry.read_instructions("team:pcbasher")

    assert [item["profile_key"] for item in rows] == [
        "builtin:vintage-programmer",
        "team:pcbasher",
    ]
    assert profile["display_name"] == "PCBasher"
    assert instructions == "PCBasher instructions"


def test_project_profile_registry_ignores_incomplete_profiles_and_rejects_unknown_key(tmp_path: Path) -> None:
    incomplete = tmp_path / "project_profiles" / "team" / "incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "profile.json").write_text(
        '{"schema_version": 1, "profile_id": "incomplete", "display_name": "Incomplete"}',
        encoding="utf-8",
    )
    registry = ProjectProfileRegistry(tmp_path)

    assert registry.list_profiles() == []
    with pytest.raises(ProjectProfileError, match="Incomplete project profile"):
        registry.get("team:incomplete")
    with pytest.raises(ProjectProfileError, match="must use"):
        registry.get("incomplete")


def test_repository_builtin_vintage_programmer_profile_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = ProjectProfileRegistry(root)

    profile, instructions = registry.read_instructions("builtin:vintage-programmer")

    assert profile["display_name"] == "Vintage Programmer"
    assert "## Verification" in instructions
