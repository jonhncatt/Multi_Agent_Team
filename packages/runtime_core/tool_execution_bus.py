from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable

from packages.runtime_core.capability_loader import ToolModule


@dataclass(frozen=True, slots=True)
class ToolDispatchMeta:
    tool_name: str
    module_id: str
    module_title: str
    group: str = ""


class ToolExecutionBus:
    def __init__(
        self,
        *,
        primary_executor: Any,
        tool_modules: tuple[ToolModule, ...],
        executors_by_module: dict[str, Any],
    ) -> None:
        self.primary_executor = primary_executor
        self.tool_modules = tuple(tool_modules)
        self.executors_by_module = dict(executors_by_module)
        self._tool_to_module: dict[str, ToolModule] = {}
        self._tool_to_executor: dict[str, Any] = {}
        self._unique_executors: list[Any] = []

        seen_executor_ids: set[int] = set()
        for executor in self.executors_by_module.values():
            marker = id(executor)
            if marker in seen_executor_ids:
                continue
            seen_executor_ids.add(marker)
            self._unique_executors.append(executor)

        for module in self.tool_modules:
            executor = self.executors_by_module.get(module.module_id) or self.primary_executor
            for tool_name in module.tool_names:
                self._tool_to_module[str(tool_name)] = module
                self._tool_to_executor[str(tool_name)] = executor

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for executor in self._unique_executors:
            specs = list(getattr(executor, "tool_specs", []) or [])
            for item in specs:
                name = str(item.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                merged.append(dict(item))
        return merged

    def module_for_tool(self, name: str) -> ToolModule | None:
        return self._tool_to_module.get(str(name or "").strip())

    def dispatch_meta_for_tool(self, name: str) -> ToolDispatchMeta:
        tool_name = str(name or "").strip()
        module = self.module_for_tool(tool_name)
        if module is None:
            return ToolDispatchMeta(tool_name=tool_name, module_id="", module_title="", group="")
        group = str(module.metadata.get("group") or "").strip()
        return ToolDispatchMeta(
            tool_name=tool_name,
            module_id=module.module_id,
            module_title=module.title,
            group=group,
        )

    def executor_for_tool(self, name: str) -> Any:
        return self._tool_to_executor.get(str(name or "").strip()) or self.primary_executor

    def describe_tool_modules(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for module in self.tool_modules:
            items.append(
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "description": module.description,
                    "tool_names": list(module.tool_names),
                    "group": str(module.metadata.get("group") or ""),
                    "executor": type(self.executors_by_module.get(module.module_id) or self.primary_executor).__name__,
                }
            )
        return items

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
        for executor in self._unique_executors:
            setter = getattr(executor, "set_runtime_context", None)
            if callable(setter):
                kwargs = {
                    "execution_mode": execution_mode,
                    "session_id": session_id,
                    "project_id": project_id,
                    "project_root": project_root,
                    "cwd": cwd,
                }
                if self._callable_accepts_kwarg(setter, "model"):
                    kwargs["model"] = model
                setter(**kwargs)

    @staticmethod
    def _callable_accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
            if parameter.name == name and parameter.kind in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }:
                return True
        return False

    def clear_runtime_context(self) -> None:
        for executor in self._unique_executors:
            clearer = getattr(executor, "clear_runtime_context", None)
            if callable(clearer):
                clearer()

    def docker_available(self) -> bool:
        checker = getattr(self.primary_executor, "docker_available", None)
        return bool(checker()) if callable(checker) else False

    def docker_status(self) -> tuple[bool, str]:
        checker = getattr(self.primary_executor, "docker_status", None)
        if callable(checker):
            return checker()
        return False, "docker_status unavailable"

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        executor = self.executor_for_tool(name)
        return executor.execute(name, arguments)

    def __getattr__(self, name: str) -> Any:
        tool_name = str(name or "").strip()
        module = self.module_for_tool(tool_name)
        executor = self.executor_for_tool(tool_name) if module is not None else self.primary_executor
        attr = getattr(executor, name)
        if not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return attr(*args, **kwargs)

        return wrapper
