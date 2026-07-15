from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import tomllib
from typing import Any


_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_KEYS = {
    "name",
    "description",
    "developer_instructions",
    "tool_scope",
    "allowed_tools",
    "model",
}


class SubagentSpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SubagentSpec:
    name: str
    description: str
    developer_instructions: str
    tool_scope: str = "read_only"
    allowed_tools: tuple[str, ...] = ()
    model: str = ""

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_tools"] = list(self.allowed_tools)
        return payload


class BuiltinSubagentRegistry:
    """Read-only registry for application-owned Subagent definitions."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _path_for(self, name: str) -> Path:
        normalized = str(name or "").strip().lower()
        if not _AGENT_NAME_RE.fullmatch(normalized):
            raise SubagentSpecError(f"Invalid Subagent name: {name}")
        path = (self.root / f"{normalized}.toml").resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise SubagentSpecError(f"Subagent path escaped the builtin registry: {name}") from exc
        return path

    def load(self, name: str) -> SubagentSpec:
        path = self._path_for(name)
        if not path.is_file():
            raise SubagentSpecError(f"Unknown builtin Subagent: {name}")
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SubagentSpecError(f"Invalid builtin Subagent TOML: {path.name}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SubagentSpecError(f"Builtin Subagent must be a TOML table: {path.name}")
        unknown = sorted(set(payload) - _ALLOWED_KEYS)
        if unknown:
            raise SubagentSpecError(
                f"Unsupported builtin Subagent fields in {path.name}: {', '.join(unknown)}"
            )
        spec_name = str(payload.get("name") or "").strip().lower()
        description = str(payload.get("description") or "").strip()
        instructions = str(payload.get("developer_instructions") or "").strip()
        tool_scope = str(payload.get("tool_scope") or "read_only").strip().lower()
        if spec_name != path.stem:
            raise SubagentSpecError(f"Builtin Subagent name must match filename: {path.name}")
        if not description:
            raise SubagentSpecError(f"Builtin Subagent description is required: {path.name}")
        if not instructions:
            raise SubagentSpecError(f"Builtin Subagent developer_instructions are required: {path.name}")
        if tool_scope not in {"none", "read_only", "all"}:
            raise SubagentSpecError(f"Invalid tool_scope in {path.name}: {tool_scope}")
        raw_allowed_tools = payload.get("allowed_tools") or []
        if not isinstance(raw_allowed_tools, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_allowed_tools
        ):
            raise SubagentSpecError(f"allowed_tools must be a list of names: {path.name}")
        allowed_tools = tuple(dict.fromkeys(str(item).strip() for item in raw_allowed_tools))
        return SubagentSpec(
            name=spec_name,
            description=description,
            developer_instructions=instructions,
            tool_scope=tool_scope,
            allowed_tools=allowed_tools,
            model=str(payload.get("model") or "").strip(),
        )

    def list(self) -> list[SubagentSpec]:
        if not self.root.is_dir():
            return []
        return [self.load(path.stem) for path in sorted(self.root.glob("*.toml"))]
