from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml

from app.config import AppConfig


SPEC_FILE_NAMES = ("soul.md", "identity.md", "agent.md", "tools.md")
SKILL_FILE_NAME = "SKILL.md"
SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "exec_command": {"group": "codex_core", "source": "codex_core", "read_only": False, "requires_evidence": False},
    "write_stdin": {"group": "codex_core", "source": "codex_core", "read_only": False, "requires_evidence": False},
    "apply_patch": {"group": "codex_core", "source": "codex_core", "read_only": False, "requires_evidence": False},
    "update_plan": {"group": "codex_core", "source": "codex_core", "read_only": True, "requires_evidence": False},
    "request_user_input": {"group": "codex_core", "source": "codex_core", "read_only": True, "requires_evidence": False},
    "read": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "search_file": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "search_file_multi": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "read_section": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "table_extract": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "fact_check_file": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "search_codebase": {"group": "fs_content", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "web_search": {"group": "web_context", "source": "local_hosted", "read_only": True, "requires_evidence": True},
    "web_fetch": {"group": "web_context", "source": "local_hosted", "read_only": True, "requires_evidence": True},
    "web_download": {"group": "web_context", "source": "local_specialized", "read_only": False, "requires_evidence": True},
    "sessions_list": {"group": "session_context", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "sessions_history": {"group": "session_context", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "image_inspect": {"group": "media_context", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "image_read": {"group": "media_context", "source": "openclaw_inspired", "read_only": True, "requires_evidence": True},
    "archive_extract": {"group": "content_unpack", "source": "local_specialized", "read_only": False, "requires_evidence": False},
    "mail_extract_attachments": {"group": "content_unpack", "source": "local_specialized", "read_only": False, "requires_evidence": False},
    "browser_open": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
    "browser_click": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
    "browser_type": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
    "browser_wait": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
    "browser_snapshot": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
    "browser_screenshot": {"group": "browser_fallback", "source": "openclaw_fallback", "read_only": True, "requires_evidence": True},
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


def build_tool_descriptors(tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_order = {
        "codex_core": 0,
        "fs_content": 1,
        "web_context": 2,
        "session_context": 3,
        "media_context": 4,
        "content_unpack": 5,
        "browser_fallback": 6,
        "other": 9,
    }
    out: list[dict[str, Any]] = []
    for item in tool_specs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        meta = dict(_TOOL_METADATA.get(name) or {})
        out.append(
            {
                "name": name,
                "group": str(meta.get("group") or "workspace"),
                "source": str(meta.get("source") or "native"),
                "enabled": True,
                "read_only": bool(meta.get("read_only")),
                "requires_evidence": bool(meta.get("requires_evidence")),
                "summary": str(item.get("description") or "").strip(),
            }
        )
    out.sort(key=lambda row: (group_order.get(str(row.get("group") or ""), 5), str(row.get("group") or ""), str(row.get("name") or "")))
    return out


def tool_descriptor_by_name(tool_specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name") or "").strip(): item
        for item in build_tool_descriptors(tool_specs)
        if str(item.get("name") or "").strip()
    }


def validate_skill_id(skill_id: str) -> str:
    value = str(skill_id or "").strip()
    if not SKILL_ID_PATTERN.fullmatch(value):
        raise ValueError("skill id must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    return value


def _coerce_bind_to(value: Any) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item or "").strip() for item in value if str(item or "").strip()]
        return cleaned
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class WorkbenchStore:
    def __init__(self, *, config: AppConfig, agent_dir: Path) -> None:
        self._config = config
        self._agent_dir = agent_dir.resolve()
        self._skills_dir = (config.workspace_root / "workspace" / "skills").resolve()
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    @property
    def agent_dir(self) -> Path:
        return self._agent_dir

    def _skill_file(self, skill_id: str) -> Path:
        valid = validate_skill_id(skill_id)
        return (self._skills_dir / valid / SKILL_FILE_NAME).resolve()

    def _ensure_within(self, path: Path, root: Path) -> None:
        if path != root and root not in path.parents:
            raise ValueError("path escaped allowed workbench root")

    def _parse_skill_content(self, text: str, *, expected_id: str | None = None) -> dict[str, Any]:
        meta, body = split_frontmatter(text)
        skill_id = validate_skill_id(str(meta.get("id") or expected_id or "").strip())
        if expected_id and skill_id != expected_id:
            raise ValueError(f"skill id mismatch: expected {expected_id}, got {skill_id}")
        title = str(meta.get("title") or "").strip()
        summary = str(meta.get("summary") or "").strip()
        bind_to = _coerce_bind_to(meta.get("bind_to"))
        enabled = bool(meta.get("enabled"))
        if not title:
            raise ValueError("skill frontmatter must include title")
        if not summary:
            raise ValueError("skill frontmatter must include summary")
        if not bind_to:
            raise ValueError("skill frontmatter must include bind_to")
        content = dump_frontmatter(
            {
                "id": skill_id,
                "title": title,
                "enabled": enabled,
                "bind_to": bind_to,
                "summary": summary,
            },
            body,
        )
        return {
            "id": skill_id,
            "title": title,
            "enabled": enabled,
            "bind_to": bind_to,
            "summary": summary,
            "content": content,
            "body": body.strip(),
        }

    def _read_skill_file(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        parsed = self._parse_skill_content(raw, expected_id=path.parent.name)
        return {
            "id": parsed["id"],
            "title": parsed["title"],
            "path": str(path),
            "enabled": parsed["enabled"],
            "bind_to": list(parsed["bind_to"]),
            "summary": parsed["summary"],
            "validation_status": "valid",
            "content": parsed["content"],
        }

    def list_skills(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self._skills_dir.glob(f"*/{SKILL_FILE_NAME}")):
            try:
                out.append(self._read_skill_file(path))
            except Exception as exc:
                skill_id = path.parent.name
                out.append(
                    {
                        "id": skill_id,
                        "title": skill_id,
                        "path": str(path),
                        "enabled": False,
                        "bind_to": [],
                        "summary": str(exc),
                        "validation_status": "invalid",
                        "content": path.read_text(encoding="utf-8"),
                    }
                )
        return out

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        path = self._skill_file(skill_id)
        self._ensure_within(path, self._skills_dir)
        if not path.is_file():
            raise FileNotFoundError(f"Skill not found: {skill_id}")
        return self._read_skill_file(path)

    def create_skill(self, content: str) -> dict[str, Any]:
        parsed = self._parse_skill_content(content)
        path = self._skill_file(parsed["id"])
        self._ensure_within(path, self._skills_dir)
        if path.exists():
            raise FileExistsError(f"Skill already exists: {parsed['id']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(parsed["id"])

    def write_skill(self, skill_id: str, content: str) -> dict[str, Any]:
        parsed = self._parse_skill_content(content, expected_id=validate_skill_id(skill_id))
        path = self._skill_file(skill_id)
        self._ensure_within(path, self._skills_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed["content"], encoding="utf-8")
        return self.get_skill(skill_id)

    def toggle_skill(self, skill_id: str, enabled: bool | None = None) -> dict[str, Any]:
        current = self.get_skill(skill_id)
        parsed = self._parse_skill_content(current["content"], expected_id=skill_id)
        next_enabled = (not bool(parsed["enabled"])) if enabled is None else bool(enabled)
        content = dump_frontmatter(
            {
                "id": parsed["id"],
                "title": parsed["title"],
                "enabled": next_enabled,
                "bind_to": parsed["bind_to"],
                "summary": parsed["summary"],
            },
            parsed["body"],
        )
        return self.write_skill(skill_id, content)

    def enabled_skills_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        wanted = str(agent_id or "").strip()
        out: list[dict[str, Any]] = []
        for item in self.list_skills():
            if item.get("validation_status") != "valid":
                continue
            if not bool(item.get("enabled")):
                continue
            bind_to = [str(value or "").strip() for value in item.get("bind_to") or []]
            if wanted and wanted in bind_to:
                out.append(item)
        return out

    def list_agent_specs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in SPEC_FILE_NAMES:
            path = (self._agent_dir / name).resolve()
            self._ensure_within(path, self._agent_dir)
            out.append(
                {
                    "name": name,
                    "path": str(path),
                    "editable": True,
                    "validation_status": "valid" if path.is_file() else "missing",
                }
            )
        return out

    def get_agent_spec(self, name: str) -> dict[str, Any]:
        spec_name = str(name or "").strip()
        if spec_name not in SPEC_FILE_NAMES:
            raise ValueError(f"Unsupported spec: {spec_name}")
        path = (self._agent_dir / spec_name).resolve()
        self._ensure_within(path, self._agent_dir)
        if not path.is_file():
            raise FileNotFoundError(f"Spec not found: {spec_name}")
        content = path.read_text(encoding="utf-8")
        validation_status = "valid"
        if spec_name == "agent.md":
            try:
                split_frontmatter(content)
            except Exception:
                validation_status = "invalid"
        return {
            "name": spec_name,
            "path": str(path),
            "editable": True,
            "validation_status": validation_status,
            "content": content,
        }

    def write_agent_spec(self, name: str, content: str) -> dict[str, Any]:
        spec_name = str(name or "").strip()
        if spec_name not in SPEC_FILE_NAMES:
            raise ValueError(f"Unsupported spec: {spec_name}")
        body = str(content or "")
        if spec_name in {"soul.md", "identity.md", "agent.md"} and not body.strip():
            raise ValueError(f"{spec_name} cannot be empty")
        if spec_name == "agent.md":
            split_frontmatter(body)
        path = (self._agent_dir / spec_name).resolve()
        self._ensure_within(path, self._agent_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return self.get_agent_spec(spec_name)
