from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.llm.tool_schema import structured_tool_to_openai_tool
from app.llm.types import RuntimeStructuredTool


class SearchArgs(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=3, ge=1)


def test_structured_tool_to_openai_tool_preserves_pydantic_schema() -> None:
    tool = RuntimeStructuredTool.from_function(
        name="search_codebase",
        description="Search the codebase.",
        args_schema=SearchArgs,
        func=lambda query, limit=3: {"query": query, "limit": limit},
    )

    payload = structured_tool_to_openai_tool(tool)

    assert payload is not None
    assert payload["type"] == "function"
    assert payload["function"]["name"] == "search_codebase"
    assert payload["function"]["description"] == "Search the codebase."
    assert payload["function"]["parameters"]["type"] == "object"
    assert payload["function"]["parameters"]["properties"]["query"]["type"] == "string"
    assert payload["function"]["parameters"]["additionalProperties"] is False


def test_structured_tool_to_openai_tool_supports_no_args_tools() -> None:
    tool = RuntimeStructuredTool.from_function(
        name="sessions_list",
        description="List sessions.",
        func=lambda: {"ok": True},
    )

    payload = structured_tool_to_openai_tool(tool)

    assert payload is not None
    assert payload["function"]["parameters"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def test_structured_tool_to_openai_tool_falls_back_for_invalid_schema(caplog) -> None:
    class BadSchema:
        @staticmethod
        def model_json_schema():
            return {"type": "object", "properties": {"broken": {"enum": {1, 2}}}}

    tool = RuntimeStructuredTool.from_function(
        name="broken_tool",
        description="Broken schema.",
        args_schema=BadSchema,
        func=lambda **_: {"ok": True},
    )

    with caplog.at_level(logging.WARNING):
        payload = structured_tool_to_openai_tool(tool)

    assert payload is not None
    assert payload["function"]["parameters"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    assert "non-serializable schema" in caplog.text
