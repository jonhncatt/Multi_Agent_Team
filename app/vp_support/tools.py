from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.local_tools import LocalToolExecutor


@dataclass(frozen=True, slots=True)
class ToolDispatchMeta:
    tool_name: str
    module_id: str
    module_title: str
    group: str


_WORKSPACE_CORE_TOOL_NAMES = (
    "exec_command",
    "write_stdin",
    "apply_patch",
    "update_plan",
    "request_user_input",
)
_FS_CONTENT_TOOL_NAMES = (
    "read_file",
    "list_dir",
    "glob_file_search",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "read_section",
    "table_extract",
    "fact_check_file",
    "search_codebase",
)
_WEB_CONTEXT_TOOL_NAMES = (
    "web_search",
    "web_fetch",
    "web_download",
)
_SESSION_CONTEXT_TOOL_NAMES = (
    "sessions_list",
    "sessions_history",
)
_MEDIA_CONTEXT_TOOL_NAMES = ("image_inspect", "image_read")
_CONTENT_UNPACK_TOOL_NAMES = (
    "archive_extract",
    "mail_extract_attachments",
)
_BROWSER_TOOL_NAMES = (
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_snapshot",
    "browser_screenshot",
)
_ALL_TOOL_NAMES = (
    _WORKSPACE_CORE_TOOL_NAMES
    + _FS_CONTENT_TOOL_NAMES
    + _WEB_CONTEXT_TOOL_NAMES
    + _SESSION_CONTEXT_TOOL_NAMES
    + _MEDIA_CONTEXT_TOOL_NAMES
    + _CONTENT_UNPACK_TOOL_NAMES
    + _BROWSER_TOOL_NAMES
)

_TOOL_GROUP_SPECS = (
    ("workspace_core_tools", "Workspace Core Tool Module", "control", _WORKSPACE_CORE_TOOL_NAMES),
    ("fs_content_tools", "FS Content Tool Module", "fs_content", _FS_CONTENT_TOOL_NAMES),
    ("web_context_tools", "Web Context Tool Module", "web_context", _WEB_CONTEXT_TOOL_NAMES),
    ("session_context_tools", "Session Context Tool Module", "session_context", _SESSION_CONTEXT_TOOL_NAMES),
    ("media_context_tools", "Media Context Tool Module", "media_context", _MEDIA_CONTEXT_TOOL_NAMES),
    ("content_unpack_tools", "Content Unpack Tool Module", "content_unpack", _CONTENT_UNPACK_TOOL_NAMES),
    ("browser_tools", "Browser Tool Module", "browser", _BROWSER_TOOL_NAMES),
)

_TOOL_DISPATCH_META = {
    tool_name: ToolDispatchMeta(
        tool_name=tool_name,
        module_id=module_id,
        module_title=module_title,
        group=group,
    )
    for module_id, module_title, group, tool_names in _TOOL_GROUP_SPECS
    for tool_name in tool_names
}


class ScopedToolExecutor:
    def __init__(
        self,
        config: Any,
        *,
        module_id: str,
        title: str,
        group: str,
        allowed_tool_names: tuple[str, ...],
    ) -> None:
        self.config = config
        self.module_id = str(module_id or "").strip()
        self.title = str(title or "").strip()
        self.group = str(group or "").strip()
        self.allowed_tool_names = tuple(str(item or "").strip() for item in allowed_tool_names if str(item or "").strip())
        self._allowed = set(self.allowed_tool_names)
        self._allowed_casefold = {key.lower(): key for key in self.allowed_tool_names}
        self._executor = LocalToolExecutor(config)
        self._all_tool_names = {
            str(item.get("name") or "").strip()
            for item in list(getattr(self._executor, "tool_specs", []) or [])
            if str(item.get("name") or "").strip()
        }

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in list(getattr(self._executor, "tool_specs", []) or [])
            if str(item.get("name") or "").strip() in self._allowed
        ]

    def dispatch_meta_for_tool(self, name: str) -> ToolDispatchMeta:
        tool_name = self._resolve_tool_name(name)
        return _TOOL_DISPATCH_META.get(
            tool_name,
            ToolDispatchMeta(
                tool_name=tool_name,
                module_id=self.module_id,
                module_title=self.title,
                group=self.group or "unknown",
            ),
        )

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        locale: str | None = None,
    ) -> None:
        self._executor.set_runtime_context(
            execution_mode=execution_mode,
            session_id=session_id,
            project_id=project_id,
            project_root=project_root,
            cwd=cwd,
            model=model,
            locale=locale,
        )

    def set_image_read_handler(self, handler: Callable[..., dict[str, Any]] | None) -> None:
        self._executor.set_image_read_handler(handler)

    def clear_runtime_context(self) -> None:
        self._executor.clear_runtime_context()

    def docker_available(self) -> bool:
        return self._executor.docker_available()

    def docker_status(self) -> tuple[bool, str]:
        return self._executor.docker_status()

    def _resolve_tool_name(self, name: str) -> str:
        tool_name = str(name or "").strip()
        if tool_name in self._allowed:
            return tool_name
        lowered = tool_name.lower()
        if lowered in self._allowed_casefold:
            return self._allowed_casefold[lowered]
        return tool_name

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_name = self._resolve_tool_name(name)
        if tool_name not in self._allowed:
            raise ValueError(f"Tool {tool_name!r} is not registered in module {self.module_id}")
        return self._executor.execute(tool_name, arguments)

    def __getattr__(self, name: str) -> Any:
        attr_name = str(name or "").strip()
        if attr_name in self._all_tool_names and attr_name not in self._allowed:
            raise AttributeError(f"{attr_name!r} is not exposed by ScopedToolExecutor({self.module_id})")
        return getattr(self._executor, name)


def get_tool_executor(config: Any) -> ScopedToolExecutor:
    return ScopedToolExecutor(
        config,
        module_id="vp_tools",
        title="Vintage Programmer Tool Executor",
        group="vp",
        allowed_tool_names=_ALL_TOOL_NAMES,
    )


__all__ = [
    "ScopedToolExecutor",
    "ToolDispatchMeta",
    "get_tool_executor",
]
