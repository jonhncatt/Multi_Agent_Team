from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config import AppConfig, normalize_permission_profile
from app.models import ChatSettings


@dataclass(slots=True)
class RuntimeContract:
    mode: str = "full_auto"
    tool_policy: str = "use_when_needed"
    tools_available: bool = True
    workspace_write_allowed: bool = True
    shell_allowed: bool = True
    network_allowed: bool = False
    permission_profile: str = "code"
    sandbox_scope: str = "workspace"
    approval_policy: str = "avoid_unnecessary_confirmation"
    reason: str = "codex_style_full_auto"
    hint_source: str = ""

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_full_auto_runtime_contract(
    *,
    settings: ChatSettings,
    config: AppConfig,
    context: dict[str, Any] | None = None,
) -> RuntimeContract:
    _ = context
    tools_available = bool(getattr(settings, "enable_tools", False))
    requested_profile = normalize_permission_profile(
        getattr(settings, "permission_profile", "") or getattr(config, "permission_profile", "code")
    )
    if not tools_available:
        return RuntimeContract(
            tool_policy="no_tools",
            tools_available=False,
            workspace_write_allowed=False,
            shell_allowed=False,
            network_allowed=False,
            permission_profile=requested_profile,
            hint_source="",
        )
    network_enabled = bool(getattr(config, "web_allow_all_domains", False) or getattr(config, "web_allowed_domains", []))
    if requested_profile == "chat":
        return RuntimeContract(
            tool_policy="use_when_needed",
            tools_available=True,
            workspace_write_allowed=False,
            shell_allowed=False,
            network_allowed=False,
            permission_profile="chat",
            hint_source="",
        )
    if requested_profile == "full_dev":
        return RuntimeContract(
            tool_policy="use_when_needed",
            tools_available=True,
            workspace_write_allowed=True,
            shell_allowed=True,
            network_allowed=network_enabled,
            permission_profile="full_dev",
            hint_source="",
        )
    return RuntimeContract(
        tool_policy="use_when_needed",
        tools_available=True,
        workspace_write_allowed=True,
        shell_allowed=True,
        network_allowed=False,
        permission_profile="code",
        hint_source="",
    )
