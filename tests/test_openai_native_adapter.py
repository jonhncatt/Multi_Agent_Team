from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.llm.openai_native as openai_native_module
from app.llm.openai_native import OpenAINativeLLMAdapter
from app.llm.types import AIMessage, HumanMessage, RuntimeStructuredTool, SystemMessage


def _usage(*, prompt_tokens=5, completion_tokens=7, total_tokens=12):
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _response(*, content="", tool_calls=None, finish_reason="stop", usage=None):
    return SimpleNamespace(
        id="resp_1",
        model="gpt-test",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=list(tool_calls or [])),
                finish_reason=finish_reason,
            )
        ],
        usage=usage or _usage(),
    )


def _tool_call_delta(*, index=0, id="", name="", arguments=""):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(*, content="", tool_calls=None, finish_reason="", usage=None, choices=True):
    return SimpleNamespace(
        id="resp_stream",
        model="gpt-test",
        choices=(
            [
                SimpleNamespace(
                    delta=SimpleNamespace(content=content, tool_calls=list(tool_calls or [])),
                    finish_reason=finish_reason,
                )
            ]
            if choices
            else []
        ),
        usage=usage,
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
    assert message.response_metadata["request_summary"]["tools_exposed"] is True
    assert message.response_metadata["request_summary"]["tool_choice"] == "auto"
    assert message.response_metadata["assistant_response_summary"]["assistant_tool_calls_count"] == 0


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


def test_openai_native_adapter_streams_text_deltas_and_usage(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            captured.append(dict(kwargs))
            assert kwargs["stream"] is True
            assert kwargs["stream_options"] == {"include_usage": True}
            return iter(
                [
                    _chunk(content="hello "),
                    _chunk(content="world", finish_reason="stop", usage=_usage(prompt_tokens=11, completion_tokens=13, total_tokens=24)),
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
    events: list[dict[str, object]] = []

    message = adapter.invoke_with_events([HumanMessage(content="stream this")], event_cb=events.append)

    assert message.content == "hello world"
    assert [event["type"] for event in events] == [
        "response.output_text.delta",
        "response.output_text.delta",
        "response.completed",
    ]
    assert [event["delta"] for event in events[:-1]] == ["hello ", "world"]
    assert message.response_metadata["stream_diagnostics"]["text_delta_count"] == 2
    assert message.response_metadata["stream_diagnostics"]["event_count"] == 2
    assert message.response_metadata["token_usage"]["total_tokens"] == 24
    assert message.response_metadata["request_summary"]["streaming"] is True
    assert message.response_metadata["request_summary"]["tools_exposed"] is False
    assert message.response_metadata["assistant_response_summary"]["assistant_content_chars"] == len("hello world")
    assert captured[0]["messages"] == [{"role": "user", "content": "stream this"}]


def test_openai_native_adapter_streaming_tool_call_assembles_raw_arguments(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        @staticmethod
        def _create(**kwargs):
            _ = kwargs
            return iter(
                [
                    _chunk(tool_calls=[_tool_call_delta(index=0, id="call_1", name="web_", arguments='{"url":"https://')]),
                    _chunk(tool_calls=[_tool_call_delta(index=0, name="fetch", arguments='example.com"}')], finish_reason="tool_calls"),
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

    message = adapter.invoke_with_events([HumanMessage(content="Need tool help")], event_cb=lambda _event: None)

    assert message.content == ""
    assert message.tool_calls == [
        {
            "name": "web_fetch",
            "args": {"url": "https://example.com"},
            "raw_args": '{"url":"https://example.com"}',
            "id": "call_1",
            "type": "tool_call",
        }
    ]
    assert message.response_metadata["assistant_response_summary"]["assistant_tool_calls_count"] == 1
    assert message.response_metadata["assistant_response_summary"]["tool_calls"][0]["args_parse_status"] == "valid_object"


def test_openai_native_adapter_streaming_preserves_invalid_tool_json(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        @staticmethod
        def _create(**kwargs):
            _ = kwargs
            return iter(
                [
                    _chunk(tool_calls=[_tool_call_delta(index=0, id="call_bad", name="web_fetch", arguments='{"url"')]),
                    _chunk(tool_calls=[_tool_call_delta(index=0, arguments=':')], finish_reason="tool_calls"),
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

    message = adapter.invoke_with_events([HumanMessage(content="Need malformed tool help")], event_cb=lambda _event: None)

    assert message.tool_calls[0]["name"] == "web_fetch"
    assert message.tool_calls[0]["args"] == {}
    assert message.tool_calls[0]["raw_args"] == '{"url":'
    assert message.response_metadata["assistant_response_summary"]["tool_calls"][0]["args_parse_status"] == "invalid_json"


def test_openai_native_adapter_retries_stream_without_usage_when_needed(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            requests.append(dict(kwargs))
            if kwargs.get("stream") and kwargs.get("stream_options"):
                raise RuntimeError("stream_options.include_usage is unsupported by this provider")
            return iter([_chunk(content="fallback stream", finish_reason="stop")])

    monkeypatch.setattr(openai_native_module, "OpenAI", FakeOpenAI)

    adapter = OpenAINativeLLMAdapter(
        api_key="test-key",
        base_url=None,
        model="gpt-test",
        max_output_tokens=256,
        temperature=None,
        ai_message_cls=AIMessage,
    )

    message = adapter.invoke_with_events([HumanMessage(content="hello")], event_cb=lambda _event: None)

    assert message.content == "fallback stream"
    assert len(requests) == 2
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert "stream_options" not in requests[1]


def test_openai_native_adapter_falls_back_to_non_streaming_when_stream_is_unsupported(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            _ = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            requests.append(dict(kwargs))
            if kwargs.get("stream"):
                raise RuntimeError("stream is not supported by this provider")
            return _response(content="non-stream fallback")

    monkeypatch.setattr(openai_native_module, "OpenAI", FakeOpenAI)

    adapter = OpenAINativeLLMAdapter(
        api_key="test-key",
        base_url=None,
        model="gpt-test",
        max_output_tokens=256,
        temperature=None,
        ai_message_cls=AIMessage,
    )
    events: list[dict[str, object]] = []

    message = adapter.invoke_with_events([HumanMessage(content="hello")], event_cb=events.append)

    assert message.content == "non-stream fallback"
    assert len(requests) == 2
    assert requests[0]["stream"] is True
    assert "stream" not in requests[1]
    assert [event["type"] for event in events] == ["response.completed"]
    assert message.response_metadata["stream_diagnostics"]["text_delta_count"] == 0
    assert message.response_metadata["request_summary"]["streaming"] is False


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
