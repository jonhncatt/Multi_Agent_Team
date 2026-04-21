from __future__ import annotations

from typing import Any, Callable

from packages.runtime_core.capability_loader import ToolModule

from app.local_tools import LocalToolExecutor


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
        self._allowed_casefold = {
            key.lower(): key for key in self.allowed_tool_names
        }
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

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
    ) -> None:
        self._executor.set_runtime_context(
            execution_mode=execution_mode,
            session_id=session_id,
            project_id=project_id,
            project_root=project_root,
            cwd=cwd,
            model=model,
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


def _build_scoped_executor_factory(
    *,
    module_id: str,
    title: str,
    group: str,
    tool_names: tuple[str, ...],
) -> Callable[[Any], ScopedToolExecutor]:
    def factory(config: Any) -> ScopedToolExecutor:
        return ScopedToolExecutor(
            config,
            module_id=module_id,
            title=title,
            group=group,
            allowed_tool_names=tool_names,
        )

    return factory


_CODEX_CORE_TOOL_NAMES = (
    "exec_command",
    "write_stdin",
    "apply_patch",
    "update_plan",
    "request_user_input",
)
_FS_CONTENT_TOOL_NAMES = (
    "read",
    "search_file",
    "search_file_multi",
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
    _CODEX_CORE_TOOL_NAMES
    + _FS_CONTENT_TOOL_NAMES
    + _WEB_CONTEXT_TOOL_NAMES
    + _SESSION_CONTEXT_TOOL_NAMES
    + _MEDIA_CONTEXT_TOOL_NAMES
    + _CONTENT_UNPACK_TOOL_NAMES
    + _BROWSER_TOOL_NAMES
)


def get_tool_executor(config: Any) -> ScopedToolExecutor:
    return ScopedToolExecutor(
        config,
        module_id="office_tools",
        title="Office Tool Module",
        group="office",
        allowed_tool_names=_ALL_TOOL_NAMES,
    )


def build_office_tool_modules() -> tuple[ToolModule, ...]:
    return (
        ToolModule(
            module_id="codex_core_tools",
            title="Codex Core Tool Module",
            description="Codex 风格的主工具集合。",
            build_executor=_build_scoped_executor_factory(
                module_id="codex_core_tools",
                title="Codex Core Tool Module",
                group="codex_core",
                tool_names=_CODEX_CORE_TOOL_NAMES,
            ),
            default=True,
            tool_names=_CODEX_CORE_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "codex_core"},
        ),
        ToolModule(
            module_id="fs_content_tools",
            title="FS Content Tool Module",
            description="统一的文件、目录、长文读取与结构化代码搜索工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="fs_content_tools",
                title="FS Content Tool Module",
                group="fs_content",
                tool_names=_FS_CONTENT_TOOL_NAMES,
            ),
            default=False,
            tool_names=_FS_CONTENT_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "fs_content"},
        ),
        ToolModule(
            module_id="web_context_tools",
            title="Web Context Tool Module",
            description="网页搜索、抓取与远程文件下载工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="web_context_tools",
                title="Web Context Tool Module",
                group="web_context",
                tool_names=_WEB_CONTEXT_TOOL_NAMES,
            ),
            default=False,
            tool_names=_WEB_CONTEXT_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "web_context"},
        ),
        ToolModule(
            module_id="session_context_tools",
            title="Session Context Tool Module",
            description="列出和回看本地历史会话。",
            build_executor=_build_scoped_executor_factory(
                module_id="session_context_tools",
                title="Session Context Tool Module",
                group="session_context",
                tool_names=_SESSION_CONTEXT_TOOL_NAMES,
            ),
            default=False,
            tool_names=_SESSION_CONTEXT_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "session_context"},
        ),
        ToolModule(
            module_id="media_context_tools",
            title="Media Context Tool Module",
            description="本地图片基础检查与图片内容读取工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="media_context_tools",
                title="Media Context Tool Module",
                group="media_context",
                tool_names=_MEDIA_CONTEXT_TOOL_NAMES,
            ),
            default=False,
            tool_names=_MEDIA_CONTEXT_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "media_context"},
        ),
        ToolModule(
            module_id="content_unpack_tools",
            title="Content Unpack Tool Module",
            description="ZIP 与 Outlook MSG 附件提取工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="content_unpack_tools",
                title="Content Unpack Tool Module",
                group="content_unpack",
                tool_names=_CONTENT_UNPACK_TOOL_NAMES,
            ),
            default=False,
            tool_names=_CONTENT_UNPACK_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "content_unpack"},
        ),
        ToolModule(
            module_id="browser_tools",
            title="Browser Tool Module",
            description="基于浏览器的页面打开、交互、快照与截图工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="browser_tools",
                title="Browser Tool Module",
                group="browser",
                tool_names=_BROWSER_TOOL_NAMES,
            ),
            default=False,
            tool_names=_BROWSER_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "browser"},
        ),
    )


__all__ = [
    "ScopedToolExecutor",
    "build_office_tool_modules",
    "get_tool_executor",
]
