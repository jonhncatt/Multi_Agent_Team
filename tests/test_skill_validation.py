from __future__ import annotations

from pathlib import Path

from scripts.validate_skills import validate_repository_skills


def _write_skill(path: Path, *, name: str, body: str = "# Skill") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: Use when validating {name}.\nenabled: true\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_validate_repository_skills_accepts_clean_global_catalog(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills" / "builtin" / "creator" / "SKILL.md", name="creator")
    _write_skill(tmp_path / "skills" / "team" / "protocol" / "SKILL.md", name="protocol")

    report = validate_repository_skills(tmp_path)

    assert report["ok"] is True
    assert report["builtin_count"] == 1
    assert report["team_count"] == 1


def test_validate_repository_skills_rejects_duplicates_secrets_and_personal_paths(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills" / "builtin" / "duplicate" / "SKILL.md", name="duplicate")
    _write_skill(
        tmp_path / "skills" / "team" / "duplicate" / "SKILL.md",
        name="duplicate",
        body="# Bad\n\npassword=abcdefghijklmnop\nC:\\Users\\alice\\private",
    )

    report = validate_repository_skills(tmp_path)

    assert report["ok"] is False
    assert {item["kind"] for item in report["errors"]} == {"duplicate_name", "personal_path", "secret"}
