from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from app.config import AppConfig
from app.i18n import normalize_locale
from app.tool_metadata import TOOL_GROUP_ORDER, get_tool_metadata


SPEC_FILE_NAMES = ("soul.md", "identity.md", "agent.md", "tools.md")
SKILL_FILE_NAME = "SKILL.md"
SKILL_INDEX_FILE_NAME = ".vp_skill_index.json"
SKILL_OVERRIDES_FILE_NAME = ".vp_skill_overrides.json"
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SKILL_FRONTMATTER_FIELDS = {"name", "description", "enabled"}
SKILL_SCOPE_SYSTEM = "system"
SKILL_SCOPE_WORKSPACE = "workspace"
BASE_SPEC_LOCALE = "zh-CN"


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


def build_tool_descriptors(tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in tool_specs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        meta = get_tool_metadata(name)
        out.append(
            {
                "name": name,
                "group": str(meta.get("group") or "unknown"),
                "source": str(meta.get("source") or "unknown"),
                "enabled": True,
                "read_only": bool(meta.get("read_only")),
                "requires_evidence": bool(meta.get("requires_evidence")),
                "summary": str(meta.get("summary") or item.get("description") or "").strip(),
            }
        )
    out.sort(
        key=lambda row: (
            TOOL_GROUP_ORDER.get(str(row.get("group") or ""), TOOL_GROUP_ORDER["unknown"]),
            str(row.get("group") or ""),
            str(row.get("name") or ""),
        )
    )
    return out


def tool_descriptor_by_name(tool_specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name") or "").strip(): item
        for item in build_tool_descriptors(tool_specs)
        if str(item.get("name") or "").strip()
    }


def validate_skill_name(skill_name: str) -> str:
    value = str(skill_name or "").strip()
    if not SKILL_NAME_PATTERN.fullmatch(value):
        raise ValueError("skill name must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    return value


def validate_skill_id(skill_id: str) -> str:
    return validate_skill_name(skill_id)


def _normalize_skill_scope(scope: str | None) -> str:
    value = str(scope or SKILL_SCOPE_WORKSPACE).strip().lower()
    if value not in {SKILL_SCOPE_SYSTEM, SKILL_SCOPE_WORKSPACE}:
        raise ValueError("skill scope must be system or workspace")
    return value


class WorkbenchStore:
    def __init__(self, *, config: AppConfig, agent_dir: Path) -> None:
        self._config = config
        self._agent_dir = agent_dir.resolve()
        self._system_skills_dir = (self._agent_dir / "skills").resolve()
        self._workspace_skills_dir = (config.workspace_root / "workspace" / "skills").resolve()
        self._workspace_skills_dir.mkdir(parents=True, exist_ok=True)

    @property
    def skills_dir(self) -> Path:
        return self._workspace_skills_dir

    @property
    def system_skills_dir(self) -> Path:
        return self._system_skills_dir

    @property
    def workspace_skills_dir(self) -> Path:
        return self._workspace_skills_dir

    @property
    def agent_dir(self) -> Path:
        return self._agent_dir

    def _skill_root(self, scope: str | None) -> Path:
        resolved_scope = _normalize_skill_scope(scope)
        return self._system_skills_dir if resolved_scope == SKILL_SCOPE_SYSTEM else self._workspace_skills_dir

    def _skill_file(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_WORKSPACE) -> Path:
        valid = validate_skill_name(skill_name)
        return (self._skill_root(scope) / valid / SKILL_FILE_NAME).resolve()

    def _skill_key(self, *, scope: str, name: str) -> str:
        return f"{_normalize_skill_scope(scope)}:{validate_skill_name(name)}"

    def _ensure_within(self, path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError("path escaped allowed workbench root")

    def _normalize_spec_locale(self, locale: str | None) -> str:
        fallback_locale = str(getattr(self._config, "default_locale", "ja-JP") or "ja-JP")
        return normalize_locale(locale, fallback_locale)

    def _base_spec_path(self, spec_name: str) -> Path:
        path = (self._agent_dir / spec_name).resolve()
        self._ensure_within(path, self._agent_dir)
        return path

    def _localized_spec_path(self, spec_name: str, locale: str) -> Path:
        path = (self._agent_dir / "locales" / locale / spec_name).resolve()
        self._ensure_within(path, self._agent_dir)
        return path

    def _resolve_spec_paths(self, spec_name: str, locale: str | None) -> dict[str, Any]:
        normalized_locale = self._normalize_spec_locale(locale)
        target_path = self._localized_spec_path(spec_name, normalized_locale)
        if target_path.is_file():
            return {
                "locale": normalized_locale,
                "path": str(target_path),
                "resolved_path": str(target_path),
                "fallback_from_base": False,
                "validation_status": "valid",
            }
        base_path = self._base_spec_path(spec_name)
        if base_path.is_file():
            return {
                "locale": normalized_locale,
                "path": str(target_path),
                "resolved_path": str(base_path),
                "fallback_from_base": True,
                "validation_status": "valid",
            }
        return {
            "locale": normalized_locale,
            "path": str(target_path),
            "resolved_path": str(target_path),
            "fallback_from_base": False,
            "validation_status": "valid" if target_path.is_file() else "missing",
        }

    def _skill_index_path(self) -> Path:
        return (self._workspace_skills_dir / SKILL_INDEX_FILE_NAME).resolve()

    def _skill_overrides_path(self) -> Path:
        return (self._workspace_skills_dir / SKILL_OVERRIDES_FILE_NAME).resolve()

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).rstrip() + "\n"
        path.write_text(body, encoding="utf-8")

    def _read_skill_overrides(self) -> dict[str, Any]:
        return self._read_json_file(self._skill_overrides_path())

    def _write_skill_overrides(self, payload: dict[str, Any]) -> None:
        self._write_json_file(self._skill_overrides_path(), payload)

    def _system_skill_override(self, skill_name: str) -> bool | None:
        key = self._skill_key(scope=SKILL_SCOPE_SYSTEM, name=skill_name)
        overrides = self._read_skill_overrides()
        value = overrides.get(key)
        if isinstance(value, dict) and isinstance(value.get("enabled"), bool):
            return bool(value["enabled"])
        return None

    def _set_system_skill_override(self, skill_name: str, enabled: bool) -> None:
        key = self._skill_key(scope=SKILL_SCOPE_SYSTEM, name=skill_name)
        overrides = self._read_skill_overrides()
        overrides[key] = {"enabled": bool(enabled)}
        self._write_skill_overrides(overrides)

    def _read_skill_frontmatter(self, path: Path) -> tuple[dict[str, Any], str]:
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
        return parsed, ""

    def _parse_skill_meta(self, meta: dict[str, Any], *, expected_name: str | None = None) -> dict[str, Any]:
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
        return {
            "name": skill_name,
            "description": description,
            "enabled": enabled,
        }

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
        return {
            **parsed,
            "content": content,
            "body": body.strip(),
        }

    def _skill_descriptor(
        self,
        *,
        scope: str,
        path: Path,
        parsed: dict[str, Any],
        validation_status: str = "valid",
        content: str = "",
    ) -> dict[str, Any]:
        skill_name = str(parsed.get("name") or path.parent.name or "").strip()
        description = str(parsed.get("description") or "").strip()
        enabled = bool(parsed.get("enabled"))
        if scope == SKILL_SCOPE_SYSTEM and validation_status == "valid":
            override = self._system_skill_override(skill_name)
            if override is not None:
                enabled = override
        key = self._skill_key(scope=scope, name=skill_name) if validation_status == "valid" else f"{scope}:{skill_name}"
        return {
            "key": key,
            "scope": scope,
            "name": skill_name,
            "description": description,
            "path": str(path),
            "enabled": enabled,
            "read_only": scope == SKILL_SCOPE_SYSTEM,
            "validation_status": validation_status,
            "content": content,
            "id": skill_name,
            "title": skill_name,
            "summary": description,
        }

    def _read_skill_file(self, path: Path, *, scope: str, include_content: bool = True) -> dict[str, Any]:
        expected_name = validate_skill_name(path.parent.name)
        if include_content:
            raw = path.read_text(encoding="utf-8")
            parsed = self._parse_skill_content(raw, expected_name=expected_name)
            return self._skill_descriptor(scope=scope, path=path, parsed=parsed, content=parsed["content"])
        meta, _ = self._read_skill_frontmatter(path)
        parsed = self._parse_skill_meta(meta, expected_name=expected_name)
        return self._skill_descriptor(scope=scope, path=path, parsed=parsed)

    def _invalid_skill_entry(self, path: Path, *, scope: str, error: BaseException, include_content: bool) -> dict[str, Any]:
        skill_name = str(path.parent.name or "").strip()
        content = ""
        if include_content:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                content = ""
        return self._skill_descriptor(
            scope=scope,
            path=path,
            parsed={"name": skill_name, "description": str(error), "enabled": False},
            validation_status="invalid",
            content=content,
        )

    def _scan_skill_entries_for_scope(self, *, scope: str, include_content: bool) -> list[dict[str, Any]]:
        root = self._skill_root(scope)
        if not root.exists():
            return []
        self._ensure_within(root, self._agent_dir if scope == SKILL_SCOPE_SYSTEM else self._workspace_skills_dir)
        out: list[dict[str, Any]] = []
        for path in sorted(root.glob(f"*/{SKILL_FILE_NAME}")):
            try:
                self._ensure_within(path.resolve(), root)
                out.append(self._read_skill_file(path.resolve(), scope=scope, include_content=include_content))
            except Exception as exc:
                out.append(self._invalid_skill_entry(path.resolve(), scope=scope, error=exc, include_content=include_content))
        return out

    def _skill_source_signature(self) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []
        for scope in (SKILL_SCOPE_SYSTEM, SKILL_SCOPE_WORKSPACE):
            root = self._skill_root(scope)
            if not root.exists():
                continue
            for path in sorted(root.glob(f"*/{SKILL_FILE_NAME}")):
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
        overrides_path = self._skill_overrides_path()
        overrides_signature: dict[str, Any] = {}
        try:
            stat = overrides_path.stat()
            overrides_signature = {
                "path": str(overrides_path),
                "mtime_ns": int(stat.st_mtime_ns),
                "size": int(stat.st_size),
            }
        except Exception:
            overrides_signature = {"path": str(overrides_path), "missing": True}
        return {"sources": sources, "overrides": overrides_signature}

    def _read_skill_index_snapshot(self, signature: dict[str, Any]) -> list[dict[str, Any]] | None:
        payload = self._read_json_file(self._skill_index_path())
        if int(payload.get("version") or 0) != 1:
            return None
        if payload.get("signature") != signature:
            return None
        skills = payload.get("skills")
        if not isinstance(skills, list):
            return None
        entries = [dict(item) for item in skills if isinstance(item, dict)]
        for item in entries:
            item["content"] = ""
        return entries

    def _write_skill_index_snapshot(self, entries: list[dict[str, Any]], *, signature: dict[str, Any]) -> None:
        snapshot_entries = [
            {
                key: value
                for key, value in dict(item).items()
                if key != "content"
            }
            for item in entries
        ]
        try:
            self._write_json_file(
                self._skill_index_path(),
                {
                    "version": 1,
                    "signature": signature,
                    "skills": snapshot_entries,
                },
            )
        except Exception:
            return

    def list_skill_entries(self, *, include_content: bool = False) -> list[dict[str, Any]]:
        signature = self._skill_source_signature()
        if not include_content:
            cached = self._read_skill_index_snapshot(signature)
            if cached is not None:
                return cached
        out = [
            *self._scan_skill_entries_for_scope(scope=SKILL_SCOPE_SYSTEM, include_content=include_content),
            *self._scan_skill_entries_for_scope(scope=SKILL_SCOPE_WORKSPACE, include_content=include_content),
        ]
        out.sort(key=lambda item: (0 if item.get("scope") == SKILL_SCOPE_SYSTEM else 1, str(item.get("name") or "")))
        if not include_content:
            self._write_skill_index_snapshot(out, signature=signature)
        return out

    def get_skill(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_WORKSPACE) -> dict[str, Any]:
        resolved_scope = _normalize_skill_scope(scope)
        path = self._skill_file(skill_name, scope=resolved_scope)
        self._ensure_within(path, self._skill_root(resolved_scope))
        if not path.is_file():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        try:
            return self._read_skill_file(path, scope=resolved_scope, include_content=True)
        except Exception as exc:
            return self._invalid_skill_entry(path, scope=resolved_scope, error=exc, include_content=True)

    def create_skill(self, content: str) -> dict[str, Any]:
        parsed = self._parse_skill_content(content)
        path = self._skill_file(parsed["name"], scope=SKILL_SCOPE_WORKSPACE)
        self._ensure_within(path, self._workspace_skills_dir)
        if path.exists():
            raise FileExistsError(f"Skill already exists: {parsed['name']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(parsed["name"], scope=SKILL_SCOPE_WORKSPACE)

    def save_skill(self, skill_name: str, content: str, *, scope: str | None = SKILL_SCOPE_WORKSPACE) -> dict[str, Any]:
        resolved_scope = _normalize_skill_scope(scope)
        if resolved_scope != SKILL_SCOPE_WORKSPACE:
            raise PermissionError("system skills are read-only")
        parsed = self._parse_skill_content(content, expected_name=validate_skill_name(skill_name))
        path = self._skill_file(skill_name, scope=SKILL_SCOPE_WORKSPACE)
        self._ensure_within(path, self._workspace_skills_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(skill_name, scope=SKILL_SCOPE_WORKSPACE)

    def save_skill_from_parts(
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
        if not skill_description:
            raise ValueError("skill description is required")
        body_text = str(body or "").strip()
        if not body_text:
            raise ValueError("skill body is required")
        if body_text.startswith("---\n"):
            raise ValueError("skill body must not include YAML frontmatter")
        path = self._skill_file(skill_name, scope=SKILL_SCOPE_WORKSPACE)
        self._ensure_within(path, self._workspace_skills_dir)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Skill already exists: {skill_name}")
        content = dump_frontmatter(
            {
                "name": skill_name,
                "description": skill_description,
                "enabled": bool(enabled),
            },
            body_text,
        )
        return self.save_skill(skill_name, content, scope=SKILL_SCOPE_WORKSPACE)

    def set_skill_enabled(self, skill_name: str, enabled: bool | None = None, *, scope: str | None = SKILL_SCOPE_WORKSPACE) -> dict[str, Any]:
        resolved_scope = _normalize_skill_scope(scope)
        current = self.get_skill(skill_name, scope=resolved_scope)
        if current.get("validation_status") != "valid":
            raise ValueError(str(current.get("description") or "skill is invalid"))
        next_enabled = (not bool(current["enabled"])) if enabled is None else bool(enabled)
        if resolved_scope == SKILL_SCOPE_SYSTEM:
            self._set_system_skill_override(skill_name, next_enabled)
            return self.get_skill(skill_name, scope=SKILL_SCOPE_SYSTEM)
        parsed = self._parse_skill_content(current["content"], expected_name=validate_skill_name(skill_name))
        content = dump_frontmatter(
            {
                "name": parsed["name"],
                "description": parsed["description"],
                "enabled": next_enabled,
            },
            parsed["body"],
        )
        return self.save_skill(skill_name, content, scope=SKILL_SCOPE_WORKSPACE)

    def delete_skill(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_WORKSPACE) -> None:
        resolved_scope = _normalize_skill_scope(scope)
        if resolved_scope != SKILL_SCOPE_WORKSPACE:
            raise PermissionError("system skills are read-only")
        path = self._skill_file(skill_name, scope=SKILL_SCOPE_WORKSPACE)
        self._ensure_within(path, self._workspace_skills_dir)
        if not path.is_file():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        skill_dir = path.parent.resolve()
        self._ensure_within(skill_dir, self._workspace_skills_dir)
        shutil.rmtree(skill_dir)

    def enabled_skills_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        wanted = str(agent_id or "").strip()
        if wanted and wanted != "vintage_programmer":
            return []
        out: list[dict[str, Any]] = []
        for item in self.list_skill_entries():
            if item.get("validation_status") != "valid":
                continue
            if not bool(item.get("enabled")):
                continue
            out.append(item)
        return out

    def _parse_skill_reference(self, reference: str) -> tuple[str | None, str]:
        value = str(reference or "").strip()
        if not value:
            raise ValueError("skill key is required")
        if ":" in value:
            scope, name = value.split(":", 1)
            return _normalize_skill_scope(scope), validate_skill_name(name)
        return None, validate_skill_name(value)

    def resolve_skill_reference(self, reference: str, *, agent_id: str = "vintage_programmer") -> dict[str, Any]:
        wanted = str(agent_id or "").strip()
        if wanted and wanted != "vintage_programmer":
            raise FileNotFoundError(f"Skill not available for agent: {agent_id}")
        scope, name = self._parse_skill_reference(reference)
        scopes = [scope] if scope else [SKILL_SCOPE_WORKSPACE, SKILL_SCOPE_SYSTEM]
        for candidate_scope in scopes:
            if not candidate_scope:
                continue
            try:
                item = self.get_skill(name, scope=candidate_scope)
            except FileNotFoundError:
                continue
            if item.get("validation_status") == "valid":
                return item
        raise FileNotFoundError(f"Skill not found: {reference}")

    def load_skill(self, reference: str, *, agent_id: str = "vintage_programmer") -> dict[str, Any]:
        item = self.resolve_skill_reference(reference, agent_id=agent_id)
        if not bool(item.get("enabled")):
            raise ValueError(f"Skill is disabled: {item.get('key') or reference}")
        return item

    def list_spec_entries(self, *, locale: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in SPEC_FILE_NAMES:
            resolved = self._resolve_spec_paths(name, locale)
            out.append(
                {
                    "name": name,
                    "path": str(resolved.get("path") or ""),
                    "resolved_path": str(resolved.get("resolved_path") or ""),
                    "locale": str(resolved.get("locale") or BASE_SPEC_LOCALE),
                    "fallback_from_base": bool(resolved.get("fallback_from_base")),
                    "editable": True,
                    "validation_status": str(resolved.get("validation_status") or "valid"),
                }
            )
        return out

    def get_agent_spec(self, name: str, *, locale: str | None = None) -> dict[str, Any]:
        spec_name = str(name or "").strip()
        if spec_name not in SPEC_FILE_NAMES:
            raise ValueError(f"Unsupported spec: {spec_name}")
        resolved = self._resolve_spec_paths(spec_name, locale)
        read_path = Path(str(resolved.get("resolved_path") or "")).resolve()
        self._ensure_within(read_path, self._agent_dir)
        if not read_path.is_file():
            raise FileNotFoundError(f"Spec not found: {spec_name}")
        content = read_path.read_text(encoding="utf-8")
        validation_status = str(resolved.get("validation_status") or "valid")
        if spec_name == "agent.md":
            try:
                split_frontmatter(content)
            except Exception:
                validation_status = "invalid"
        return {
            "name": spec_name,
            "path": str(resolved.get("path") or ""),
            "resolved_path": str(read_path),
            "locale": str(resolved.get("locale") or BASE_SPEC_LOCALE),
            "fallback_from_base": bool(resolved.get("fallback_from_base")),
            "editable": True,
            "validation_status": validation_status,
            "content": content,
        }

    def save_agent_spec(self, name: str, content: str, *, locale: str | None = None) -> dict[str, Any]:
        spec_name = str(name or "").strip()
        if spec_name not in SPEC_FILE_NAMES:
            raise ValueError(f"Unsupported spec: {spec_name}")
        body = str(content or "")
        if spec_name in {"soul.md", "identity.md", "agent.md"} and not body.strip():
            raise ValueError(f"{spec_name} cannot be empty")
        if spec_name == "agent.md":
            split_frontmatter(body)
        normalized_locale = self._normalize_spec_locale(locale)
        path = self._localized_spec_path(spec_name, normalized_locale)
        self._ensure_within(path, self._agent_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return self.get_agent_spec(spec_name, locale=normalized_locale)
