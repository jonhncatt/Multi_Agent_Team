from __future__ import annotations

from app.llm.message_codec import encode_messages
from app.llm.types import AIMessage, HumanMessage, SystemMessage, ToolMessage


def test_encode_messages_converts_basic_roles() -> None:
    messages = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="user prompt"),
        AIMessage(content="assistant reply"),
    ]

    encoded = encode_messages(messages)

    assert encoded == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
        {"role": "assistant", "content": "assistant reply"},
    ]


def test_encode_messages_converts_assistant_tool_call_with_raw_arguments() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "web_search",
                    "args": {"query": "PLAN.md"},
                    "raw_args": '{"query":"PLAN.md"}',
                }
            ],
        )
    ]

    encoded = encode_messages(messages)

    assert encoded == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query":"PLAN.md"}',
                    },
                }
            ],
        }
    ]


def test_encode_messages_converts_tool_result_messages() -> None:
    messages = [
        ToolMessage(content="tool output", tool_call_id="call_1", name="web_search"),
    ]

    encoded = encode_messages(messages)

    assert encoded == [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "tool output",
        }
    ]
