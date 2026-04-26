from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config import AppConfig
from app.models import ChatSettings


@dataclass(slots=True)
class RuntimeContract:
    mode: str = "full_auto"
    tool_policy: str = "use_when_needed"
    tools_available: bool = True
    workspace_write_allowed: bool = True
    shell_allowed: bool = True
    network_allowed: bool = False
    sandbox_scope: str = "workspace"
    approval_policy: str = "avoid_unnecessary_confirmation"
    reason: str = "codex_style_full_auto"
    requires_tools_hint: bool = False
    hint_source: str = ""

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_full_auto_runtime_contract(
    *,
    settings: ChatSettings,
    config: AppConfig,
    context: dict[str, Any] | None = None,
    requires_tools_hint: bool = False,
) -> RuntimeContract:
    _ = context
    tools_available = bool(getattr(settings, "enable_tools", False))
    if not tools_available:
        return RuntimeContract(
            tool_policy="no_tools",
            tools_available=False,
            workspace_write_allowed=False,
            shell_allowed=False,
            network_allowed=False,
            requires_tools_hint=bool(requires_tools_hint),
            hint_source="request_likely_requires_tools",
        )
    return RuntimeContract(
        tool_policy="use_when_needed",
        tools_available=True,
        workspace_write_allowed=True,
        shell_allowed=True,
        network_allowed=bool(getattr(config, "web_allow_all_domains", False) or getattr(config, "web_allowed_domains", [])),
        requires_tools_hint=bool(requires_tools_hint),
        hint_source="request_likely_requires_tools",
    )
