from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


PROFILE_SCOPE_BUILTIN = "builtin"
PROFILE_SCOPE_TEAM = "team"
PROFILE_FILE_NAME = "profile.json"
PROFILE_INSTRUCTIONS_FILE_NAME = "AGENTS.md"
DEFAULT_PROFILE_INSTRUCTIONS_MAX_BYTES = 32 * 1024

_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROFILE_SCOPES = (PROFILE_SCOPE_BUILTIN, PROFILE_SCOPE_TEAM)


class ProjectProfileError(ValueError):
    pass


class ProjectProfileRegistry:
    """Version-controlled project guidance shared by every VP Agent."""

    def __init__(
        self,
        repository_root: Path,
        *,
        max_instruction_bytes: int = DEFAULT_PROFILE_INSTRUCTIONS_MAX_BYTES,
    ) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.root = (self.repository_root / "project_profiles").resolve()
        self.max_instruction_bytes = max(1024, int(max_instruction_bytes))

    @staticmethod
    def _validate_profile_id(profile_id: str) -> str:
        normalized = str(profile_id or "").strip().lower()
        if not _PROFILE_ID_RE.fullmatch(normalized):
            raise ProjectProfileError(f"Invalid project profile id: {profile_id}")
        return normalized

    @staticmethod
    def _validate_scope(scope: str) -> str:
        normalized = str(scope or "").strip().lower()
        if normalized not in _PROFILE_SCOPES:
            raise ProjectProfileError(f"Invalid project profile scope: {scope}")
        return normalized

    @classmethod
    def normalize_key(cls, profile_key: str) -> str:
        raw = str(profile_key or "").strip().lower()
        if not raw or ":" not in raw:
            raise ProjectProfileError("Project profile key must use <scope>:<profile_id>.")
        scope, profile_id = raw.split(":", 1)
        return f"{cls._validate_scope(scope)}:{cls._validate_profile_id(profile_id)}"

    def _profile_dir(self, profile_key: str) -> tuple[str, str, Path]:
        normalized = self.normalize_key(profile_key)
        scope, profile_id = normalized.split(":", 1)
        scope_root = (self.root / scope).resolve()
        profile_dir = (scope_root / profile_id).resolve()
        try:
            profile_dir.relative_to(scope_root)
        except ValueError as exc:
            raise ProjectProfileError("Project profile path escaped its registry scope.") from exc
        return scope, profile_id, profile_dir

    def _load_profile_dir(self, *, scope: str, profile_id: str, profile_dir: Path) -> dict[str, Any]:
        manifest_path = profile_dir / PROFILE_FILE_NAME
        instructions_path = profile_dir / PROFILE_INSTRUCTIONS_FILE_NAME
        if not manifest_path.is_file() or not instructions_path.is_file():
            raise ProjectProfileError(f"Incomplete project profile: {scope}:{profile_id}")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProjectProfileError(f"Invalid project profile manifest: {scope}:{profile_id}") from exc
        if not isinstance(payload, dict):
            raise ProjectProfileError(f"Invalid project profile manifest: {scope}:{profile_id}")
        manifest_id = self._validate_profile_id(str(payload.get("profile_id") or ""))
        if manifest_id != profile_id:
            raise ProjectProfileError(f"Project profile id must match its directory: {scope}:{profile_id}")
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            raise ProjectProfileError(f"Project profile display_name is required: {scope}:{profile_id}")
        return {
            "profile_key": f"{scope}:{profile_id}",
            "profile_id": profile_id,
            "scope": scope,
            "display_name": display_name[:120],
            "description": str(payload.get("description") or "").strip()[:500],
            "manifest_path": str(manifest_path),
            "instructions_path": str(instructions_path),
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for scope in _PROFILE_SCOPES:
            scope_root = self.root / scope
            if not scope_root.is_dir():
                continue
            for profile_dir in sorted(path for path in scope_root.iterdir() if path.is_dir()):
                try:
                    profile_id = self._validate_profile_id(profile_dir.name)
                    rows.append(
                        self._load_profile_dir(
                            scope=scope,
                            profile_id=profile_id,
                            profile_dir=profile_dir.resolve(),
                        )
                    )
                except ProjectProfileError:
                    continue
        return sorted(
            rows,
            key=lambda item: (
                0 if item["scope"] == PROFILE_SCOPE_BUILTIN else 1,
                str(item["display_name"]).casefold(),
                str(item["profile_key"]),
            ),
        )

    def get(self, profile_key: str) -> dict[str, Any]:
        scope, profile_id, profile_dir = self._profile_dir(profile_key)
        return self._load_profile_dir(scope=scope, profile_id=profile_id, profile_dir=profile_dir)

    def read_instructions(self, profile_key: str) -> tuple[dict[str, Any], str]:
        profile = self.get(profile_key)
        path = Path(profile["instructions_path"])
        raw = path.read_bytes()[: self.max_instruction_bytes]
        return profile, raw.decode("utf-8", errors="ignore").strip()
