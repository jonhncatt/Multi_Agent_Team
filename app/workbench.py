from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.i18n import normalize_locale
from app.skill_registry import (
    SKILL_SCOPE_BUILTIN,
    SKILL_SCOPE_TEAM,
    SkillRegistry,
    normalize_skill_scope,
    split_frontmatter,
    validate_skill_name,
)
from app.tool_metadata import TOOL_GROUP_ORDER, get_tool_metadata


SPEC_FILE_NAMES = ("soul.md", "identity.md", "agent.md", "tools.md")
BASE_SPEC_LOCALE = "zh-CN"

# Public compatibility constants. Canonical descriptors and keys always use
# builtin/team; system/workspace are accepted only as transition aliases.
SKILL_SCOPE_SYSTEM = "system"
SKILL_SCOPE_WORKSPACE = "workspace"


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


def validate_skill_id(skill_id: str) -> str:
    return validate_skill_name(skill_id)


class WorkbenchStore:
    """Workbench facade for agent specs, tools, and the global Skill Registry."""

    def __init__(
        self,
        *,
        config: AppConfig,
        agent_dir: Path,
        skill_repository_root: Path | None = None,
    ) -> None:
        self._config = config
        self._agent_dir = agent_dir.resolve()
        repository_root = (
            skill_repository_root.expanduser().resolve()
            if skill_repository_root is not None
            else self._agent_dir.parent.parent.resolve()
        )
        legacy_roots_enabled = skill_repository_root is None
        self._skill_registry = SkillRegistry(
            repository_root=repository_root,
            state_dir=repository_root / "app" / "data" / "runtime" / "skills",
            legacy_system_roots=[self._agent_dir / "skills"] if legacy_roots_enabled else [],
            legacy_workspace_roots=(
                [repository_root / "workspace" / "skills", config.workspace_root / "workspace" / "skills"]
                if legacy_roots_enabled
                else []
            ),
        )

    @property
    def skills_dir(self) -> Path:
        return self._skill_registry.team_skills_dir

    @property
    def builtin_skills_dir(self) -> Path:
        return self._skill_registry.builtin_skills_dir

    @property
    def team_skills_dir(self) -> Path:
        return self._skill_registry.team_skills_dir

    @property
    def system_skills_dir(self) -> Path:
        """Deprecated alias for builtin_skills_dir."""

        return self._skill_registry.builtin_skills_dir

    @property
    def workspace_skills_dir(self) -> Path:
        """Deprecated alias for team_skills_dir."""

        return self._skill_registry.team_skills_dir

    @property
    def skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    @property
    def skill_migration_report(self) -> dict[str, Any]:
        return self._skill_registry.migration_report

    @property
    def reserved_skill_roots(self) -> list[str]:
        return self._skill_registry.reserved_roots

    @property
    def agent_dir(self) -> Path:
        return self._agent_dir

    @staticmethod
    def _ensure_within(path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError("path escaped allowed workbench root")

    def list_skill_entries(self, *, include_content: bool = False) -> list[dict[str, Any]]:
        return self._skill_registry.list_skills(include_content=include_content)

    def get_skill(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_TEAM) -> dict[str, Any]:
        return self._skill_registry.get_skill(skill_name, scope=scope)

    def create_skill(self, content: str) -> dict[str, Any]:
        return self._skill_registry.create_team_skill(content)

    def save_skill(self, skill_name: str, content: str, *, scope: str | None = SKILL_SCOPE_TEAM) -> dict[str, Any]:
        if normalize_skill_scope(scope) != SKILL_SCOPE_TEAM:
            raise PermissionError("built-in skills are read-only")
        return self._skill_registry.save_team_skill(skill_name, content, overwrite=True)

    def save_skill_from_parts(
        self,
        *,
        name: str,
        description: str,
        body: str,
        enabled: bool = True,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        return self._skill_registry.save_team_skill_from_parts(
            name=name,
            description=description,
            body=body,
            enabled=enabled,
            overwrite=overwrite,
        )

    def set_skill_enabled(
        self,
        skill_name: str,
        enabled: bool | None = None,
        *,
        scope: str | None = SKILL_SCOPE_TEAM,
    ) -> dict[str, Any]:
        return self._skill_registry.set_skill_enabled(skill_name, enabled, scope=scope)

    def delete_skill(self, skill_name: str, *, scope: str | None = SKILL_SCOPE_TEAM) -> None:
        if normalize_skill_scope(scope) != SKILL_SCOPE_TEAM:
            raise PermissionError("built-in skills are read-only")
        self._skill_registry.delete_team_skill(skill_name)

    def enabled_skills_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        return self._skill_registry.enabled_skills(agent_id=agent_id)

    def resolve_skill_reference(self, reference: str, *, agent_id: str = "vintage_programmer") -> dict[str, Any]:
        return self._skill_registry.resolve(reference, agent_id=agent_id)

    def load_skill(self, reference: str, *, agent_id: str = "vintage_programmer") -> dict[str, Any]:
        return self._skill_registry.load(reference, agent_id=agent_id)

    def list_skill_resources(self, reference: str, *, agent_id: str = "vintage_programmer") -> list[str]:
        return self._skill_registry.list_resources(reference, agent_id=agent_id)

    def load_skill_resource(
        self,
        reference: str,
        resource: str,
        *,
        agent_id: str = "vintage_programmer",
    ) -> dict[str, Any]:
        return self._skill_registry.load_resource(reference, resource, agent_id=agent_id)

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
            "validation_status": "missing",
        }

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
