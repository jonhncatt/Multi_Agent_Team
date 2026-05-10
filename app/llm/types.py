from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


@dataclass(slots=True)
class NativeLLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""


@dataclass(slots=True)
class NativeLLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: Any | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[NativeLLMToolCall] = field(default_factory=list)


@dataclass(slots=True)
class NativeLLMResponse:
    content: str
    tool_calls: list[NativeLLMToolCall] = field(default_factory=list)
    raw: Any | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    response_id: str = ""
    model: str = ""


class RuntimeMessage:
    type = "base"

    def __init__(self, content: Any = "", **kwargs: Any) -> None:
        self.content = content
        self.name = kwargs.pop("name", None)
        self.tool_call_id = kwargs.pop("tool_call_id", None)
        self.tool_calls = list(kwargs.pop("tool_calls", []) or [])
        self.usage_metadata = dict(kwargs.pop("usage_metadata", {}) or {})
        self.response_metadata = dict(kwargs.pop("response_metadata", {}) or {})
        self.additional_kwargs = dict(kwargs.pop("additional_kwargs", {}) or {})
        self.kwargs = dict(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)


class SystemMessage(RuntimeMessage):
    type = "system"


class HumanMessage(RuntimeMessage):
    type = "human"


class AIMessage(RuntimeMessage):
    type = "ai"


class ToolMessage(RuntimeMessage):
    type = "tool"


@dataclass(slots=True)
class RuntimeStructuredTool:
    name: str
    description: str
    func: Callable[..., Any]
    args_schema: Any | None = None

    @classmethod
    def from_function(
        cls,
        *,
        name: str,
        description: str,
        func: Callable[..., Any],
        args_schema: Any | None = None,
    ) -> "RuntimeStructuredTool":
        return cls(
            name=str(name or "").strip(),
            description=str(description or "").strip(),
            func=func,
            args_schema=args_schema,
        )

    def invoke(self, arguments: dict[str, Any] | None = None) -> Any:
        payload = arguments if isinstance(arguments, dict) else {}
        if self.args_schema is not None and hasattr(self.args_schema, "model_validate"):
            validated = self.args_schema.model_validate(payload)
            if hasattr(validated, "model_dump"):
                payload = dict(validated.model_dump())
        return self.func(**payload)
