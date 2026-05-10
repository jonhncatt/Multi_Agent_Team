from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.llm.openai_native as openai_native_module
from app.llm.openai_native import OpenAINativeLLMAdapter
from app.llm.types import AIMessage, HumanMessage, RuntimeStructuredTool, SystemMessage


def _response(*, content="", tool_calls=None, finish_reason="stop"):
    return SimpleNamespace(
        id="resp_1",
        model="gpt-test",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=list(tool_calls or [])),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12),
    )


def test_openai_native_adapter_builds_chat_completions_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            captured["request_kwargs"] = kwargs
            return _response(content="final answer")

    monkeypatch.setattr(openai_native_module, "OpenAI", FakeOpenAI)

    tool = RuntimeStructuredTool.from_function(
        name="search_codebase",
        description="Search code.",
        func=lambda query: {"query": query},
    )
    adapter = OpenAINativeLLMAdapter(
        api_key="test-key",
        base_url="https://gateway.example.com/v1",
        model="gpt-test",
        max_output_tokens=256,
        temperature=0.2,
        ai_message_cls=AIMessage,
        tools=[tool],
    )

    message = adapter.invoke([SystemMessage(content="system"), HumanMessage(content="hello")])

    assert message.content == "final answer"
    assert captured["client_kwargs"]["api_key"] == "test-key"
    assert captured["client_kwargs"]["base_url"] == "https://gateway.example.com/v1"
    request_kwargs = captured["request_kwargs"]
    assert request_kwargs["model"] == "gpt-test"
    assert request_kwargs["max_tokens"] == 256
    assert request_kwargs["temperature"] == 0.2
    assert request_kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]
    assert request_kwargs["tools"][0]["function"]["name"] == "search_codebase"
    assert request_kwargs["tool_choice"] == "auto"


def test_openai_native_adapter_preserves_raw_tool_arguments(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        @staticmethod
        def _create(**kwargs):
            _ = kwargs
            return _response(
                tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(name="web_search", arguments='{"query":"PLAN.md"}'),
                    ),
                    SimpleNamespace(
                        id="call_2",
                        function=SimpleNamespace(name="web_fetch", arguments='{"url":'),
                    ),
                ]
            )

    monkeypatch.setattr(openai_native_module, "OpenAI", FakeOpenAI)

    adapter = OpenAINativeLLMAdapter(
        api_key="test-key",
        base_url=None,
        model="gpt-test",
        max_output_tokens=256,
        temperature=None,
        ai_message_cls=AIMessage,
    )

    message = adapter.invoke([HumanMessage(content="Need tool help")])

    assert message.content == ""
    assert len(message.tool_calls) == 2
    assert message.tool_calls[0]["args"] == {"query": "PLAN.md"}
    assert message.tool_calls[0]["raw_args"] == '{"query":"PLAN.md"}'
    assert message.tool_calls[1]["args"] == {}
    assert message.tool_calls[1]["raw_args"] == '{"url":'


def test_openai_native_adapter_raises_on_empty_choices(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        @staticmethod
        def _create(**kwargs):
            _ = kwargs
            return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0))

    monkeypatch.setattr(openai_native_module, "OpenAI", FakeOpenAI)

    adapter = OpenAINativeLLMAdapter(
        api_key="test-key",
        base_url=None,
        model="gpt-test",
        max_output_tokens=128,
        temperature=None,
        ai_message_cls=AIMessage,
    )

    with pytest.raises(RuntimeError, match="no choices"):
        adapter.invoke([HumanMessage(content="hello")])
