from __future__ import annotations

from typing import Any


class ToolRegistryModule:
    module_id = "tool_registry"
    version = "1.0.0"

    def build_langchain_tools(self, *, agent: Any) -> list[Any]:
        public_builder = getattr(agent, "build_langchain_tools", None)
        if callable(public_builder):
            return list(public_builder() or [])
        return list(agent._build_langchain_tools() or [])

    def describe_tools(self, *, agent: Any) -> dict[str, Any]:
        tools = self.build_langchain_tools(agent=agent)
        items: list[dict[str, Any]] = []
        for tool in tools:
            items.append(
                {
                    "name": str(getattr(tool, "name", "") or ""),
                    "description": str(getattr(tool, "description", "") or "")[:200],
                }
            )
        return {
            "module_id": self.module_id,
            "version": self.version,
            "tool_count": len(items),
            "tools": items,
        }
