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
    ) -> None:
        self._executor.set_runtime_context(
            execution_mode=execution_mode,
            session_id=session_id,
            project_id=project_id,
            project_root=project_root,
            cwd=cwd,
        )

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


_WORKSPACE_TOOL_NAMES = (
    "run_shell",
    "list_directory",
    "search_codebase",
    "copy_file",
    "extract_zip",
    "extract_msg_attachments",
    "kernel_runtime_status",
    "kernel_shadow_pipeline",
    "kernel_shadow_self_upgrade",
)
_FILE_TOOL_NAMES = (
    "read_text_file",
    "search_text_in_file",
    "multi_query_search",
    "doc_index_build",
    "read_section_by_heading",
    "table_extract",
    "fact_check_file",
)
_WEB_TOOL_NAMES = (
    "fetch_web",
    "download_web_file",
    "search_web",
)
_PATCH_TOOL_NAMES = (
    "write_text_file",
    "append_text_file",
    "replace_in_file",
    "apply_patch",
)
_BROWSER_TOOL_NAMES = (
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_snapshot",
    "browser_screenshot",
)
_IMAGE_TOOL_NAMES = ("view_image",)
_SESSION_TOOL_NAMES = (
    "list_sessions",
    "read_session_history",
)
_SKILL_TOOL_NAMES = (
    "list_skills",
    "read_skill",
    "write_skill",
    "toggle_skill",
)
_AGENT_SPEC_TOOL_NAMES = (
    "list_agent_specs",
    "read_agent_spec",
    "write_agent_spec",
)
_ALL_TOOL_NAMES = (
    _WORKSPACE_TOOL_NAMES
    + _FILE_TOOL_NAMES
    + _WEB_TOOL_NAMES
    + _PATCH_TOOL_NAMES
    + _BROWSER_TOOL_NAMES
    + _IMAGE_TOOL_NAMES
    + _SESSION_TOOL_NAMES
    + _SKILL_TOOL_NAMES
    + _AGENT_SPEC_TOOL_NAMES
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
            module_id="workspace_tools",
            title="Workspace Tool Module",
            description="工作区与代码库操作工具模块。",
            build_executor=_build_scoped_executor_factory(
                module_id="workspace_tools",
                title="Workspace Tool Module",
                group="workspace",
                tool_names=_WORKSPACE_TOOL_NAMES,
            ),
            default=True,
            tool_names=_WORKSPACE_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "workspace"},
        ),
        ToolModule(
            module_id="file_tools",
            title="File Tool Module",
            description="文档读取、检索、结构提取与事实核验。",
            build_executor=_build_scoped_executor_factory(
                module_id="file_tools",
                title="File Tool Module",
                group="file",
                tool_names=_FILE_TOOL_NAMES,
            ),
            default=False,
            tool_names=_FILE_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "file"},
        ),
        ToolModule(
            module_id="web_tools",
            title="Web Tool Module",
            description="联网抓取、搜索与网页下载工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="web_tools",
                title="Web Tool Module",
                group="web",
                tool_names=_WEB_TOOL_NAMES,
            ),
            default=False,
            tool_names=_WEB_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "web"},
        ),
        ToolModule(
            module_id="write_tools",
            title="Write Tool Module",
            description="文本写入、追加和精确替换工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="write_tools",
                title="Write Tool Module",
                group="write",
                tool_names=_PATCH_TOOL_NAMES,
            ),
            default=False,
            tool_names=_PATCH_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "write"},
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
        ToolModule(
            module_id="image_tools",
            title="Image Tool Module",
            description="本地图像读取与元信息查看工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="image_tools",
                title="Image Tool Module",
                group="images",
                tool_names=_IMAGE_TOOL_NAMES,
            ),
            default=False,
            tool_names=_IMAGE_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "images"},
        ),
        ToolModule(
            module_id="session_tools",
            title="Session Tool Module",
            description="跨会话浏览与历史检索工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="session_tools",
                title="Session Tool Module",
                group="session",
                tool_names=_SESSION_TOOL_NAMES,
            ),
            default=False,
            tool_names=_SESSION_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "session"},
        ),
        ToolModule(
            module_id="skill_tools",
            title="Skill Tool Module",
            description="本地 skills 列表、读取、编辑与启停工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="skill_tools",
                title="Skill Tool Module",
                group="skills",
                tool_names=_SKILL_TOOL_NAMES,
            ),
            default=False,
            tool_names=_SKILL_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "skills"},
        ),
        ToolModule(
            module_id="agent_spec_tools",
            title="Agent Spec Tool Module",
            description="主 agent 规范文件的读取与编辑工具。",
            build_executor=_build_scoped_executor_factory(
                module_id="agent_spec_tools",
                title="Agent Spec Tool Module",
                group="agent_specs",
                tool_names=_AGENT_SPEC_TOOL_NAMES,
            ),
            default=False,
            tool_names=_AGENT_SPEC_TOOL_NAMES,
            metadata={"family": "office", "executor": "ScopedToolExecutor", "group": "agent_specs"},
        ),
    )


__all__ = [
    "ScopedToolExecutor",
    "build_office_tool_modules",
    "get_tool_executor",
]
