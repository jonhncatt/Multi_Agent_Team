from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import AppConfig, get_access_roots
from app.runtime_contract import RuntimeContract


class RuntimeBoundary(BaseModel):
    """Logical runtime boundary used by ContextPack and ActionValidator."""

    tool_policy: str = "use_when_needed"
    workspace_read_allowed: bool = True
    workspace_write_allowed: bool = True
    shell_allowed: bool = True
    network_allowed: bool = False
    approval_policy: str = "avoid_unnecessary_confirmation"
    allowed_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)
    cwd: str = "."
    project_root: str = "."
    max_output_tokens: int = 4096
    timeout_sec: int = 120


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

    try:
        access_roots = [path.expanduser().resolve() for path in get_access_roots(config)]
    except Exception:
        access_roots = [root]
    if root not in access_roots:
        access_roots.insert(0, root)

    for item in list(attachments or []):
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        try:
            access_roots.append(Path(raw_path).expanduser().resolve().parent)
        except Exception:
            continue

    allowed_roots = _dedup_paths(access_roots)
    writable_roots = _dedup_paths(access_roots if bool(contract.workspace_write_allowed) else [])
    return RuntimeBoundary(
        tool_policy=str(contract.tool_policy or "use_when_needed"),
        workspace_read_allowed=True,
        workspace_write_allowed=bool(contract.workspace_write_allowed),
        shell_allowed=bool(contract.shell_allowed),
        network_allowed=bool(contract.network_allowed),
        approval_policy=str(contract.approval_policy or "avoid_unnecessary_confirmation"),
        allowed_roots=[str(path) for path in allowed_roots],
        writable_roots=[str(path) for path in writable_roots],
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
