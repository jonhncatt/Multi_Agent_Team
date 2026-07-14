from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
from typing import Any, Iterable

import yaml


SKILL_FILE_NAME = "SKILL.md"
SKILL_INDEX_FILE_NAME = "skill_index.json"
SKILL_OVERRIDES_FILE_NAME = "skill_overrides.json"
SKILL_MIGRATION_FILE_NAME = "skill_migration.json"
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SKILL_FRONTMATTER_FIELDS = {"name", "description", "enabled"}

SKILL_SCOPE_BUILTIN = "builtin"
SKILL_SCOPE_TEAM = "team"
SKILL_SCOPE_ALIASES = {
    "builtin": SKILL_SCOPE_BUILTIN,
    "system": SKILL_SCOPE_BUILTIN,
    "team": SKILL_SCOPE_TEAM,
    "workspace": SKILL_SCOPE_TEAM,
}


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    raw = str(text or "")
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    frontmatter = raw[4:end]
    body = raw[end + 5 :]
    parsed = yaml.safe_load(frontmatter) or {}
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a mapping")
    return parsed, body


def dump_frontmatter(meta: dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    body_text = str(body or "").rstrip()
    return f"---\n{rendered}\n---\n\n{body_text}\n"


def validate_skill_name(skill_name: str) -> str:
    value = str(skill_name or "").strip()
    if not SKILL_NAME_PATTERN.fullmatch(value):
        raise ValueError("skill name must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    return value


def normalize_skill_scope(scope: str | None, *, default: str = SKILL_SCOPE_TEAM) -> str:
    value = str(scope or default).strip().lower()
    resolved = SKILL_SCOPE_ALIASES.get(value)
    if not resolved:
        raise ValueError("skill scope must be builtin or team")
    return resolved


class SkillRegistry:
    """Global Built-in/Team skill catalog owned by the VP installation.

    The registry root is the Vintage Programmer repository, never the active
    business project. Legacy system/workspace locations are read only as
    migration sources and old scope names remain accepted as API aliases.
    """

    _LEGACY_BUILTIN_ALLOWLIST = {"create-workspace-skill"}

    def __init__(
        self,
        *,
        repository_root: Path,
        state_dir: Path | None = None,
        legacy_system_roots: Iterable[Path] = (),
        legacy_workspace_roots: Iterable[Path] = (),
        migrate_legacy: bool = True,
    ) -> None:
        self._repository_root = repository_root.expanduser().resolve()
        self._skills_root = (self._repository_root / "skills").resolve()
        self._builtin_skills_dir = (self._skills_root / SKILL_SCOPE_BUILTIN).resolve()
        self._team_skills_dir = (self._skills_root / SKILL_SCOPE_TEAM).resolve()
        self._state_dir = (
            state_dir.expanduser().resolve()
            if state_dir is not None
            else (self._repository_root / "app" / "data" / "runtime" / "skills").resolve()
        )
        self._legacy_system_roots = self._dedupe_roots(legacy_system_roots)
        self._legacy_workspace_roots = self._dedupe_roots(legacy_workspace_roots)
        self._builtin_skills_dir.mkdir(parents=True, exist_ok=True)
        self._team_skills_dir.mkdir(parents=True, exist_ok=True)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._last_migration_report: dict[str, Any] = {
            "version": 1,
            "status": "not_run",
            "migrated": [],
            "already_present": [],
            "conflicts": [],
            "skipped": [],
        }
        if migrate_legacy:
            self._last_migration_report = self.migrate_legacy_skills()

    @staticmethod
    def _dedupe_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
        out: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            try:
                resolved = root.expanduser().resolve()
            except Exception:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            out.append(resolved)
        return tuple(out)

    @property
    def repository_root(self) -> Path:
        return self._repository_root

    @property
    def skills_root(self) -> Path:
        return self._skills_root

    @property
    def builtin_skills_dir(self) -> Path:
        return self._builtin_skills_dir

    @property
    def team_skills_dir(self) -> Path:
        return self._team_skills_dir

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    @property
    def reserved_roots(self) -> list[str]:
        return [str(self._builtin_skills_dir), str(self._team_skills_dir)]

    @property
    def migration_report(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._last_migration_report, ensure_ascii=False))

    def _scope_root(self, scope: str | None) -> Path:
        resolved = normalize_skill_scope(scope)
        return self._builtin_skills_dir if resolved == SKILL_SCOPE_BUILTIN else self._team_skills_dir

    def _skill_file(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_TEAM) -> Path:
        valid = validate_skill_name(skill_name)
        return (self._scope_root(scope) / valid / SKILL_FILE_NAME).resolve()

    @staticmethod
    def _skill_key(*, scope: str, name: str) -> str:
        return f"{normalize_skill_scope(scope)}:{validate_skill_name(name)}"

    @staticmethod
    def _ensure_within(path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError("path escaped allowed skill root")

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).rstrip() + "\n"
        path.write_text(body, encoding="utf-8")

    def _index_path(self) -> Path:
        return (self._state_dir / SKILL_INDEX_FILE_NAME).resolve()

    def _overrides_path(self) -> Path:
        return (self._state_dir / SKILL_OVERRIDES_FILE_NAME).resolve()

    def _migration_path(self) -> Path:
        return (self._state_dir / SKILL_MIGRATION_FILE_NAME).resolve()

    def _legacy_override_paths(self) -> list[Path]:
        return [(root / ".vp_skill_overrides.json").resolve() for root in self._legacy_workspace_roots]

    def _read_skill_overrides(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in [*self._legacy_override_paths(), self._overrides_path()]:
            for raw_key, value in self._read_json_file(path).items():
                key = str(raw_key or "").strip()
                if ":" in key:
                    raw_scope, name = key.split(":", 1)
                    try:
                        key = self._skill_key(scope=raw_scope, name=name)
                    except ValueError:
                        continue
                merged[key] = value
        return merged

    def _write_skill_overrides(self, payload: dict[str, Any]) -> None:
        self._write_json_file(self._overrides_path(), payload)

    def _builtin_skill_override(self, skill_name: str) -> bool | None:
        key = self._skill_key(scope=SKILL_SCOPE_BUILTIN, name=skill_name)
        value = self._read_skill_overrides().get(key)
        if isinstance(value, dict) and isinstance(value.get("enabled"), bool):
            return bool(value["enabled"])
        return None

    def _set_builtin_skill_override(self, skill_name: str, enabled: bool) -> None:
        key = self._skill_key(scope=SKILL_SCOPE_BUILTIN, name=skill_name)
        overrides = self._read_skill_overrides()
        overrides[key] = {"enabled": bool(enabled)}
        self._write_skill_overrides(overrides)

    @staticmethod
    def _read_skill_frontmatter(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.readline()
            if first != "---\n":
                raise ValueError("skill frontmatter must start with ---")
            lines: list[str] = []
            size = 0
            for line in handle:
                if line == "---\n":
                    break
                size += len(line)
                if size > 65536:
                    raise ValueError("skill frontmatter is too large")
                lines.append(line)
            else:
                raise ValueError("skill frontmatter must end with ---")
        parsed = yaml.safe_load("".join(lines)) or {}
        if not isinstance(parsed, dict):
            raise ValueError("frontmatter must be a mapping")
        return parsed

    @staticmethod
    def _parse_skill_meta(meta: dict[str, Any], *, expected_name: str | None = None) -> dict[str, Any]:
        unknown_fields = sorted(set(meta) - SKILL_FRONTMATTER_FIELDS)
        if unknown_fields:
            joined = ", ".join(unknown_fields)
            raise ValueError(f"skill frontmatter may only include name, description, enabled; unsupported: {joined}")
        skill_name = validate_skill_name(str(meta.get("name") or "").strip())
        if expected_name and skill_name != expected_name:
            raise ValueError(f"skill name mismatch: expected {expected_name}, got {skill_name}")
        description = str(meta.get("description") or "").strip()
        if not description:
            raise ValueError("skill frontmatter must include description")
        enabled_raw = meta.get("enabled", True)
        if enabled_raw is None:
            enabled = True
        elif isinstance(enabled_raw, bool):
            enabled = enabled_raw
        else:
            raise ValueError("skill enabled must be true or false")
        return {"name": skill_name, "description": description, "enabled": enabled}

    def _parse_skill_content(self, text: str, *, expected_name: str | None = None) -> dict[str, Any]:
        meta, body = split_frontmatter(text)
        parsed = self._parse_skill_meta(meta, expected_name=expected_name)
        content = dump_frontmatter(
            {
                "name": parsed["name"],
                "description": parsed["description"],
                "enabled": parsed["enabled"],
            },
            body,
        )
        return {**parsed, "content": content, "body": body.strip()}

    def _descriptor(
        self,
        *,
        scope: str,
        path: Path,
        parsed: dict[str, Any],
        validation_status: str = "valid",
        content: str = "",
    ) -> dict[str, Any]:
        resolved_scope = normalize_skill_scope(scope)
        skill_name = str(parsed.get("name") or path.parent.name or "").strip()
        description = str(parsed.get("description") or "").strip()
        enabled = bool(parsed.get("enabled"))
        if resolved_scope == SKILL_SCOPE_BUILTIN and validation_status == "valid":
            override = self._builtin_skill_override(skill_name)
            if override is not None:
                enabled = override
        try:
            key = self._skill_key(scope=resolved_scope, name=skill_name)
        except ValueError:
            key = f"{resolved_scope}:{skill_name}"
        return {
            "key": key,
            "scope": resolved_scope,
            "source": resolved_scope,
            "name": skill_name,
            "description": description,
            "path": str(path),
            "enabled": enabled,
            "read_only": resolved_scope == SKILL_SCOPE_BUILTIN,
            "validation_status": validation_status,
            "content": content,
            "id": skill_name,
            "title": skill_name,
            "summary": description,
        }

    def _read_skill_file(self, path: Path, *, scope: str, include_content: bool) -> dict[str, Any]:
        expected_name = validate_skill_name(path.parent.name)
        if include_content:
            parsed = self._parse_skill_content(path.read_text(encoding="utf-8"), expected_name=expected_name)
            return self._descriptor(scope=scope, path=path, parsed=parsed, content=parsed["content"])
        meta = self._read_skill_frontmatter(path)
        parsed = self._parse_skill_meta(meta, expected_name=expected_name)
        return self._descriptor(scope=scope, path=path, parsed=parsed)

    def _invalid_entry(self, path: Path, *, scope: str, error: BaseException, include_content: bool) -> dict[str, Any]:
        content = ""
        if include_content:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                pass
        return self._descriptor(
            scope=scope,
            path=path,
            parsed={"name": path.parent.name, "description": str(error), "enabled": False},
            validation_status="invalid",
            content=content,
        )

    def _scan_scope(self, *, scope: str, include_content: bool) -> list[dict[str, Any]]:
        root = self._scope_root(scope)
        out: list[dict[str, Any]] = []
        for path in sorted(root.glob(f"*/{SKILL_FILE_NAME}")):
            resolved = path.resolve()
            try:
                self._ensure_within(resolved, root)
                out.append(self._read_skill_file(resolved, scope=scope, include_content=include_content))
            except Exception as exc:
                out.append(self._invalid_entry(resolved, scope=scope, error=exc, include_content=include_content))
        return out

    def _source_signature(self) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []
        for scope in (SKILL_SCOPE_BUILTIN, SKILL_SCOPE_TEAM):
            for path in sorted(self._scope_root(scope).glob(f"*/{SKILL_FILE_NAME}")):
                try:
                    stat = path.stat()
                except Exception:
                    continue
                sources.append(
                    {
                        "scope": scope,
                        "path": str(path.resolve()),
                        "mtime_ns": int(stat.st_mtime_ns),
                        "size": int(stat.st_size),
                    }
                )
        try:
            stat = self._overrides_path().stat()
            overrides = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            overrides = {"missing": True}
        return {"sources": sources, "overrides": overrides}

    def _read_index(self, signature: dict[str, Any]) -> list[dict[str, Any]] | None:
        payload = self._read_json_file(self._index_path())
        if int(payload.get("version") or 0) != 2 or payload.get("signature") != signature:
            return None
        skills = payload.get("skills")
        if not isinstance(skills, list):
            return None
        entries = [dict(item) for item in skills if isinstance(item, dict)]
        for item in entries:
            item["content"] = ""
        return entries

    def _write_index(self, entries: list[dict[str, Any]], *, signature: dict[str, Any]) -> None:
        snapshot = [{key: value for key, value in item.items() if key != "content"} for item in entries]
        try:
            self._write_json_file(self._index_path(), {"version": 2, "signature": signature, "skills": snapshot})
        except Exception:
            pass

    def list_skills(self, *, include_content: bool = False) -> list[dict[str, Any]]:
        signature = self._source_signature()
        if not include_content:
            cached = self._read_index(signature)
            if cached is not None:
                return cached
        out = [
            *self._scan_scope(scope=SKILL_SCOPE_BUILTIN, include_content=include_content),
            *self._scan_scope(scope=SKILL_SCOPE_TEAM, include_content=include_content),
        ]
        out.sort(key=lambda item: (0 if item.get("scope") == SKILL_SCOPE_BUILTIN else 1, str(item.get("name") or "")))
        if not include_content:
            self._write_index(out, signature=signature)
        return out

    def get_skill(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_TEAM) -> dict[str, Any]:
        resolved_scope = normalize_skill_scope(scope)
        path = self._skill_file(skill_name, scope=resolved_scope)
        self._ensure_within(path, self._scope_root(resolved_scope))
        if not path.is_file():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        try:
            return self._read_skill_file(path, scope=resolved_scope, include_content=True)
        except Exception as exc:
            return self._invalid_entry(path, scope=resolved_scope, error=exc, include_content=True)

    def create_team_skill(self, content: str) -> dict[str, Any]:
        parsed = self._parse_skill_content(content)
        path = self._skill_file(parsed["name"], scope=SKILL_SCOPE_TEAM)
        self._ensure_within(path, self._team_skills_dir)
        if path.exists():
            raise FileExistsError(f"Skill already exists: {parsed['name']}")
        if self._skill_file(parsed["name"], scope=SKILL_SCOPE_BUILTIN).is_file():
            raise FileExistsError(f"Skill name conflicts with a built-in skill: {parsed['name']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(parsed["name"], scope=SKILL_SCOPE_TEAM)

    def save_team_skill(self, skill_name: str, content: str, *, overwrite: bool = True) -> dict[str, Any]:
        valid_name = validate_skill_name(skill_name)
        if self._skill_file(valid_name, scope=SKILL_SCOPE_BUILTIN).is_file():
            raise FileExistsError(f"Skill name conflicts with a built-in skill: {valid_name}")
        parsed = self._parse_skill_content(content, expected_name=valid_name)
        path = self._skill_file(valid_name, scope=SKILL_SCOPE_TEAM)
        self._ensure_within(path, self._team_skills_dir)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Skill already exists: {valid_name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(valid_name, scope=SKILL_SCOPE_TEAM)

    def save_team_skill_from_parts(
        self,
        *,
        name: str,
        description: str,
        body: str,
        enabled: bool = True,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        skill_name = validate_skill_name(name)
        skill_description = str(description or "").strip()
        body_text = str(body or "").strip()
        if not skill_description:
            raise ValueError("skill description is required")
        if not body_text:
            raise ValueError("skill body is required")
        if body_text.startswith("---\n"):
            raise ValueError("skill body must not include YAML frontmatter")
        content = dump_frontmatter(
            {"name": skill_name, "description": skill_description, "enabled": bool(enabled)},
            body_text,
        )
        return self.save_team_skill(skill_name, content, overwrite=overwrite)

    def set_skill_enabled(self, skill_name: str, enabled: bool | None = None, *, scope: str | None = SKILL_SCOPE_TEAM) -> dict[str, Any]:
        resolved_scope = normalize_skill_scope(scope)
        current = self.get_skill(skill_name, scope=resolved_scope)
        if current.get("validation_status") != "valid":
            raise ValueError(str(current.get("description") or "skill is invalid"))
        next_enabled = (not bool(current["enabled"])) if enabled is None else bool(enabled)
        if resolved_scope == SKILL_SCOPE_BUILTIN:
            self._set_builtin_skill_override(skill_name, next_enabled)
            return self.get_skill(skill_name, scope=SKILL_SCOPE_BUILTIN)
        parsed = self._parse_skill_content(current["content"], expected_name=validate_skill_name(skill_name))
        content = dump_frontmatter(
            {"name": parsed["name"], "description": parsed["description"], "enabled": next_enabled},
            parsed["body"],
        )
        return self.save_team_skill(skill_name, content, overwrite=True)

    def delete_team_skill(self, skill_name: str) -> None:
        path = self._skill_file(skill_name, scope=SKILL_SCOPE_TEAM)
        self._ensure_within(path, self._team_skills_dir)
        if not path.is_file():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        shutil.rmtree(path.parent.resolve())

    def enabled_skills(self, *, agent_id: str = "", capabilities: set[str] | None = None) -> list[dict[str, Any]]:
        # Storage and discovery are global. The optional capability argument is
        # the stable extension point for future multi-agent filtering.
        del agent_id, capabilities
        return [
            item
            for item in self.list_skills()
            if item.get("validation_status") == "valid" and bool(item.get("enabled"))
        ]

    @staticmethod
    def _parse_reference(reference: str) -> tuple[str | None, str]:
        value = str(reference or "").strip()
        if not value:
            raise ValueError("skill key is required")
        if ":" in value:
            scope, name = value.split(":", 1)
            return normalize_skill_scope(scope), validate_skill_name(name)
        return None, validate_skill_name(value)

    def resolve(self, reference: str, *, agent_id: str = "") -> dict[str, Any]:
        del agent_id
        scope, name = self._parse_reference(reference)
        if scope:
            return self.get_skill(name, scope=scope)
        matches: list[dict[str, Any]] = []
        for candidate_scope in (SKILL_SCOPE_TEAM, SKILL_SCOPE_BUILTIN):
            try:
                item = self.get_skill(name, scope=candidate_scope)
            except FileNotFoundError:
                continue
            if item.get("validation_status") == "valid":
                matches.append(item)
        if not matches:
            raise FileNotFoundError(f"Skill not found: {reference}")
        if len(matches) > 1:
            keys = ", ".join(str(item.get("key") or "") for item in matches)
            raise ValueError(f"Skill reference is ambiguous; use an explicit key: {keys}")
        return matches[0]

    def load(self, reference: str, *, agent_id: str = "") -> dict[str, Any]:
        item = self.resolve(reference, agent_id=agent_id)
        if not bool(item.get("enabled")):
            raise ValueError(f"Skill is disabled: {item.get('key') or reference}")
        return item

    def list_resources(self, reference: str, *, agent_id: str = "") -> list[str]:
        item = self.resolve(reference, agent_id=agent_id)
        skill_file = Path(str(item.get("path") or "")).resolve()
        skill_root = skill_file.parent.resolve()
        catalog_root = self._scope_root(str(item.get("scope") or ""))
        self._ensure_within(skill_root, catalog_root)
        resources: list[str] = []
        for candidate in sorted(skill_root.rglob("*")):
            if not candidate.is_file() or candidate.name == SKILL_FILE_NAME:
                continue
            try:
                resolved = candidate.resolve()
                self._ensure_within(resolved, skill_root)
            except Exception:
                continue
            resources.append(candidate.relative_to(skill_root).as_posix())
            if len(resources) >= 200:
                break
        return resources

    @staticmethod
    def _normalize_resource_path(resource: str) -> PurePosixPath:
        value = str(resource or "").replace("\\", "/").strip()
        while value.startswith("./"):
            value = value[2:]
        relative = PurePosixPath(value)
        if not value or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("skill resource must be a relative path inside the selected skill")
        return relative

    def load_resource(self, reference: str, resource: str, *, agent_id: str = "") -> dict[str, Any]:
        item = self.resolve(reference, agent_id=agent_id)
        relative = self._normalize_resource_path(resource)
        if relative.name == SKILL_FILE_NAME:
            raise ValueError("load the main SKILL.md without the resource argument")
        skill_root = Path(str(item.get("path") or "")).resolve().parent
        target = (skill_root / Path(*relative.parts)).resolve()
        self._ensure_within(target, skill_root)
        if not target.is_file():
            raise FileNotFoundError(f"Skill resource not found: {relative.as_posix()}")
        size = int(target.stat().st_size)
        if size > 2_000_000:
            raise ValueError("skill resource exceeds the 2,000,000 byte load limit")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("skill resource is not UTF-8 text") from exc
        return {
            "key": str(item.get("key") or reference),
            "scope": str(item.get("scope") or ""),
            "name": str(item.get("name") or ""),
            "resource": relative.as_posix(),
            "content": content,
            "size": size,
        }

    def resolve_python_script(self, reference: str, script: str, *, agent_id: str = "") -> dict[str, Any]:
        """Resolve an enabled Skill's Python resource for the trusted runner.

        This private execution descriptor contains physical paths and must not be
        sent to the model. Public tool results use only the logical key/resource.
        """

        item = self.load(reference, agent_id=agent_id)
        relative = self._normalize_resource_path(script)
        if relative.suffix.lower() != ".py":
            raise ValueError("run_skill_script supports Python (.py) resources only")
        skill_root = Path(str(item.get("path") or "")).resolve().parent
        target = skill_root.joinpath(*relative.parts)
        if target.is_symlink():
            raise ValueError("skill script symbolic links are not supported")
        target = target.resolve()
        self._ensure_within(target, skill_root)
        if not target.is_file():
            raise FileNotFoundError(f"Skill script not found: {relative.as_posix()}")
        size = int(target.stat().st_size)
        if size > 2_000_000:
            raise ValueError("skill script exceeds the 2,000,000 byte execution limit")
        try:
            target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("skill script is not UTF-8 text") from exc
        return {
            "key": str(item.get("key") or reference),
            "scope": str(item.get("scope") or ""),
            "name": str(item.get("name") or ""),
            "resource": relative.as_posix(),
            "path": str(target),
            "skill_root": str(skill_root),
            "size": size,
        }

    def _legacy_skill_files(self, skill_root: Path) -> list[tuple[Path, Path]]:
        """Return safe legacy files as (source, relative path) pairs."""

        resolved_root = skill_root.resolve()
        files: list[tuple[Path, Path]] = []
        for candidate in sorted(skill_root.rglob("*")):
            if candidate.is_symlink():
                raise ValueError("legacy skill contains an unsupported symbolic link")
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            self._ensure_within(resolved, resolved_root)
            files.append((resolved, resolved.relative_to(resolved_root)))
        return files

    def _merge_legacy_resources(self, *, source_root: Path, target_root: Path) -> tuple[int, str]:
        """Copy only missing supporting files after a conflict-free preflight."""

        missing: list[tuple[Path, Path]] = []
        for source, relative in self._legacy_skill_files(source_root):
            if relative.as_posix() == SKILL_FILE_NAME:
                continue
            target = (target_root / relative).resolve()
            self._ensure_within(target, target_root)
            if not target.exists():
                missing.append((source, target))
                continue
            if not target.is_file() or source.read_bytes() != target.read_bytes():
                return 0, "supporting resource conflicts with the Team Skill"

        for source, target in missing:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return len(missing), ""

    def migrate_legacy_skills(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "version": 1,
            "status": "completed",
            "migrated": [],
            "already_present": [],
            "conflicts": [],
            "skipped": [],
        }

        sources: list[tuple[str, Path, Path]] = []
        for root in self._legacy_system_roots:
            sources.extend(("system", root, path) for path in sorted(root.glob(f"*/{SKILL_FILE_NAME}")))
        for root in self._legacy_workspace_roots:
            sources.extend(("workspace", root, path) for path in sorted(root.glob(f"*/{SKILL_FILE_NAME}")))

        seen_sources: set[str] = set()
        for legacy_scope, source_catalog_root, raw_source_file in sources:
            source_file = raw_source_file.resolve()
            try:
                self._ensure_within(source_file, source_catalog_root.resolve())
                self._legacy_skill_files(raw_source_file.parent)
            except Exception as exc:
                report["skipped"].append(
                    {"source_scope": legacy_scope, "name": raw_source_file.parent.name, "reason": str(exc)[:240]}
                )
                continue
            if str(source_file) in seen_sources:
                continue
            seen_sources.add(str(source_file))
            source_name = source_file.parent.name
            try:
                parsed = self._parse_skill_content(source_file.read_text(encoding="utf-8"), expected_name=source_name)
            except Exception as exc:
                report["skipped"].append({"source_scope": legacy_scope, "name": source_name, "reason": str(exc)[:240]})
                continue

            if legacy_scope == "system" and source_name in self._LEGACY_BUILTIN_ALLOWLIST:
                report["skipped"].append(
                    {"source_scope": legacy_scope, "name": source_name, "reason": "replaced by the built-in create-team-skill"}
                )
                continue

            target_scope = SKILL_SCOPE_TEAM
            target_dir = (self._team_skills_dir / source_name).resolve()
            target_file = target_dir / SKILL_FILE_NAME
            self._ensure_within(target_dir, self._team_skills_dir)
            if target_file.is_file():
                try:
                    existing = self._parse_skill_content(target_file.read_text(encoding="utf-8"), expected_name=source_name)
                except Exception:
                    existing = {"content": ""}
                if existing.get("content") == parsed.get("content"):
                    try:
                        copied_count, resource_conflict = self._merge_legacy_resources(
                            source_root=raw_source_file.parent,
                            target_root=target_dir,
                        )
                    except Exception as exc:
                        copied_count, resource_conflict = 0, str(exc)[:240]
                    if resource_conflict:
                        report["conflicts"].append(
                            {
                                "source_scope": legacy_scope,
                                "target_scope": target_scope,
                                "name": source_name,
                                "reason": resource_conflict,
                            }
                        )
                    elif copied_count:
                        report["migrated"].append(
                            {
                                "source_scope": legacy_scope,
                                "target_scope": target_scope,
                                "name": source_name,
                                "resources_copied": copied_count,
                            }
                        )
                    else:
                        report["already_present"].append(
                            {"source_scope": legacy_scope, "target_scope": target_scope, "name": source_name}
                        )
                else:
                    report["conflicts"].append(
                        {"source_scope": legacy_scope, "target_scope": target_scope, "name": source_name, "reason": "target already exists with different content"}
                    )
                continue
            if self._skill_file(source_name, scope=SKILL_SCOPE_BUILTIN).is_file():
                report["conflicts"].append(
                    {"source_scope": legacy_scope, "target_scope": target_scope, "name": source_name, "reason": "name conflicts with a built-in skill"}
                )
                continue
            # The preflight above rejects symlinks and path escapes before the
            # complete legacy directory is copied into the Team catalog.
            shutil.copytree(raw_source_file.parent, target_dir)
            report["migrated"].append({"source_scope": legacy_scope, "target_scope": target_scope, "name": source_name})

        report["status"] = "conflicts" if report["conflicts"] else "completed"
        try:
            self._write_json_file(self._migration_path(), report)
        except Exception:
            pass
        return report
