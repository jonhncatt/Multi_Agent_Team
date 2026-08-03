from __future__ import annotations

from typing import Any

from app.llm_exchange import snapshot_ai_message, snapshot_error, snapshot_messages


class _SystemMessage:
    def __init__(self, *, content: str) -> None:
        self.content = content


class _DeveloperMessage:
    role = "developer"

    def __init__(self, *, content: str) -> None:
        self.content = content


class _ToolMessage:
    def __init__(self, *, content: str, tool_call_id: str, name: str) -> None:
        self.content = content
        self.tool_call_id = tool_call_id
        self.name = name


class _AIMessage:
    def __init__(
        self,
        *,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        additional_kwargs: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        usage_metadata: dict[str, Any] | None = None,
        invalid_tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = list(tool_calls or [])
        self.additional_kwargs = dict(additional_kwargs or {})
        self.response_metadata = dict(response_metadata or {})
        self.usage_metadata = dict(usage_metadata or {})
        self.invalid_tool_calls = list(invalid_tool_calls or [])


def test_snapshot_messages_truncates_content_and_preserves_tool_call_id() -> None:
    snapshots = snapshot_messages(
        [
            _DeveloperMessage(content="developer rules"),
            _ToolMessage(content="x" * 25050, tool_call_id="tc-1", name="web_search"),
        ],
        max_content_chars=50,
    )

    assert snapshots[0]["role"] == "developer"
    assert snapshots[1]["role"] == "tool"
    assert snapshots[1]["tool_call_id"] == "tc-1"
    assert snapshots[1]["name"] == "web_search"
    assert snapshots[1]["truncated"] is True
    assert snapshots[1]["original_chars"] == 25050


def test_snapshot_ai_message_bounds_tool_calls_and_metadata() -> None:
    snapshot = snapshot_ai_message(
        _AIMessage(
            content="I will inspect the folder.",
            tool_calls=[
                {
                    "id": "tc-1",
                    "name": "search_codebase",
                    "args": {"query": "x" * 12050},
                }
            ],
            additional_kwargs={"provider_debug": "y" * 13050},
            response_metadata={"finish_reason": "tool_calls"},
            usage_metadata={"total_tokens": 12},
        ),
    )

    assert snapshot["tool_calls"][0]["id"] == "tc-1"
    assert snapshot["tool_calls"][0]["args"]["truncated"] is True
    assert snapshot["additional_kwargs"]["truncated"] is True
    assert snapshot["finish_reason"] == "tool_calls"
    assert snapshot["usage_metadata"]["total_tokens"] == 12


def test_snapshot_error_uses_classified_payload_and_truncates_traceback() -> None:
    exc = AttributeError("'NoneType' object has no attribute 'model_dump'")
    snapshot = snapshot_error(
        exc,
        classified={
            "kind": "llm_empty_response",
            "message": "LLM provider returned empty response before ChatResult creation.",
            "traceback_tail": "t" * 9000,
        },
    )

    assert snapshot["kind"] == "llm_empty_response"
    assert snapshot["message"] == "LLM provider returned empty response before ChatResult creation."
    assert snapshot["exception_type"] == "AttributeError"
    assert snapshot["raw_message"] == "'NoneType' object has no attribute 'model_dump'"
    assert snapshot["traceback_tail_truncated"] is True
