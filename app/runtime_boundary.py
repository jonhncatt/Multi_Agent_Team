from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import AppConfig, normalize_permission_profile
from app.runtime_contract import RuntimeContract


class RuntimeBoundary(BaseModel):
    """Logical runtime boundary used by ContextPack and ActionValidator."""

    tool_policy: str = "use_when_needed"
    workspace_read_allowed: bool = True
    workspace_write_allowed: bool = True
    shell_allowed: bool = True
    network_allowed: bool = False
    permission_profile: str = "code"
    approval_policy: str = "avoid_unnecessary_confirmation"
    allowed_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)
    command_allowed_roots: list[str] = Field(default_factory=list)
    cwd: str = "."
    project_root: str = "."
    max_output_tokens: int = 4096
    timeout_sec: int = 120

    def to_model_view(self) -> dict[str, Any]:
        """Return the concise boundary view sent to the model.

        The complete boundary, including root lists and limits, stays internal for
        ActionValidator. The model only needs broad capability and location data.
        """
        return {
            "permission_profile": str(self.permission_profile or "code"),
            "workspace_read_allowed": bool(self.workspace_read_allowed),
            "workspace_write_allowed": bool(self.workspace_write_allowed),
            "shell_allowed": bool(self.shell_allowed),
            "network_allowed": bool(self.network_allowed),
            "approval_policy": str(self.approval_policy or ""),
            "cwd": str(self.cwd or ""),
            "project_root": str(self.project_root or ""),
            "file_read_scope": self._scope_label(self.allowed_roots, default="current project + imported files"),
            "file_write_scope": self._scope_label(self.writable_roots, default="current project" if self.workspace_write_allowed else "none"),
            "command_scope": self._scope_label(self.command_allowed_roots, default="current project" if self.shell_allowed else "none"),
        }

    @staticmethod
    def _scope_label(roots: list[str], *, default: str) -> str:
        if not roots:
            return "none" if default == "none" else default
        if len(roots) == 1:
            return "current project"
        return "current project + imported files"


def _dedup_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def build_turn_runtime_boundary(
    *,
    config: AppConfig,
    runtime_contract: RuntimeContract | None = None,
    project_root: str | Path | None = None,
    cwd: str | Path | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> RuntimeBoundary:
    contract = runtime_contract or RuntimeContract(
        network_allowed=bool(getattr(config, "web_allow_all_domains", False) or getattr(config, "web_allowed_domains", [])),
    )
    root = Path(project_root or config.workspace_root).expanduser().resolve()
    current_cwd = Path(cwd or root).expanduser()
    if not current_cwd.is_absolute():
        current_cwd = root / current_cwd
    current_cwd = current_cwd.resolve()

    profile = normalize_permission_profile(
        getattr(contract, "permission_profile", "") or getattr(config, "permission_profile", "code")
    )

    imported_roots: list[Path] = []
    uploads_dir = getattr(config, "uploads_dir", None)
    if uploads_dir is not None:
        try:
            imported_roots.append(Path(uploads_dir).expanduser().resolve())
        except Exception:
            pass

    for item in list(attachments or []):
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        try:
            imported_roots.append(Path(raw_path).expanduser().resolve().parent)
        except Exception:
            continue

    extra_roots = []
    if profile == "full_dev":
        extra_roots = [Path(item).expanduser().resolve() for item in list(getattr(config, "default_extra_allowed_roots", []) or [])]
        extra_roots.extend(Path(item).expanduser().resolve() for item in list(getattr(config, "allowed_roots", []) or []) if Path(item).expanduser().resolve() != root)
        if bool(getattr(config, "allow_workspace_sibling_access", False)) and getattr(config, "workspace_sibling_root", None):
            extra_roots.append(Path(getattr(config, "workspace_sibling_root")).expanduser().resolve())

    allowed_roots = _dedup_paths([root, *imported_roots, *extra_roots])
    workspace_write_allowed = bool(contract.workspace_write_allowed) and profile in {"code", "full_dev"}
    shell_allowed = bool(contract.shell_allowed) and profile in {"code", "full_dev"}
    network_allowed = bool(contract.network_allowed) if profile == "full_dev" else False
    writable_roots = _dedup_paths([root] if workspace_write_allowed else [])
    command_roots = _dedup_paths([root] if shell_allowed else [])
    return RuntimeBoundary(
        tool_policy=str(contract.tool_policy or "use_when_needed"),
        workspace_read_allowed=True,
        workspace_write_allowed=workspace_write_allowed,
        shell_allowed=shell_allowed,
        network_allowed=network_allowed,
        permission_profile=profile,
        approval_policy=str(contract.approval_policy or "avoid_unnecessary_confirmation"),
        allowed_roots=[str(path) for path in allowed_roots],
        writable_roots=[str(path) for path in writable_roots],
        command_allowed_roots=[str(path) for path in command_roots],
        cwd=str(current_cwd),
        project_root=str(root),
        max_output_tokens=int(getattr(config, "max_output_tokens", 4096) or 4096),
    )


def build_runtime_boundary(
    *,
    config: AppConfig,
    runtime_contract: RuntimeContract | None = None,
    project_root: str | Path | None = None,
    cwd: str | Path | None = None,
) -> RuntimeBoundary:
    return build_turn_runtime_boundary(
        config=config,
        runtime_contract=runtime_contract,
        project_root=project_root,
        cwd=cwd,
        attachments=None,
    )
