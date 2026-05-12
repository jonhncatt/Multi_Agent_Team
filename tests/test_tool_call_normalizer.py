from __future__ import annotations

from types import SimpleNamespace

from app.tool_call_normalizer import canonicalize_tool_call


def test_args_dict_is_accepted() -> None:
    raw = {"id": "1", "name": "read_file", "args": {"path": "AGENT.MD"}}

    canonical = canonicalize_tool_call(raw)

    assert canonical.args == {"path": "AGENT.MD"}
    assert canonical.arguments_parse_status == "valid_object"
    assert canonical.raw_args == '{"path": "AGENT.MD"}'


def test_arguments_json_string_is_parsed() -> None:
    raw = {"id": "1", "name": "read_file", "arguments": '{"path":"AGENT.MD"}'}

    canonical = canonicalize_tool_call(raw)

    assert canonical.args == {"path": "AGENT.MD"}
    assert canonical.arguments_parse_status == "valid_object"
    assert "arguments_json_string_parsed" in canonical.normalization_notes


def test_raw_args_json_string_is_parsed() -> None:
    raw = {"id": "1", "name": "read_file", "raw_args": '{"path":"AGENT.MD"}'}

    canonical = canonicalize_tool_call(raw)

    assert canonical.args == {"path": "AGENT.MD"}
    assert canonical.arguments_parse_status == "valid_object"
    assert canonical.raw_args == '{"path":"AGENT.MD"}'


def test_function_arguments_json_string_is_parsed() -> None:
    raw = {
        "id": "1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"AGENT.MD"}'},
    }

    canonical = canonicalize_tool_call(raw)

    assert canonical.name == "read_file"
    assert canonical.raw_name == "read_file"
    assert canonical.args == {"path": "AGENT.MD"}
    assert canonical.arguments_parse_status == "valid_object"


def test_openai_sdk_object_shape_is_parsed() -> None:
    raw = SimpleNamespace(
        id="sdk-1",
        function=SimpleNamespace(name="read_file", arguments='{"path":"AGENT.MD","max_chars":2000}'),
    )

    canonical = canonicalize_tool_call(raw)

    assert canonical.id == "sdk-1"
    assert canonical.name == "read_file"
    assert canonical.args == {"path": "AGENT.MD", "max_chars": 2000}


def test_json_list_is_rejected_as_not_object() -> None:
    raw = {"name": "read_file", "arguments": '["AGENT.MD"]'}

    canonical = canonicalize_tool_call(raw)

    assert canonical.arguments_parse_status == "not_object"
    assert canonical.args == {}


def test_invalid_json_is_rejected() -> None:
    raw = {"name": "read_file", "arguments": '{"path":'}

    canonical = canonicalize_tool_call(raw)

    assert canonical.arguments_parse_status == "invalid_json"
    assert canonical.args == {}
    assert canonical.error


def test_empty_arguments_becomes_empty_object() -> None:
    raw = {"name": "update_plan", "arguments": ""}

    canonical = canonicalize_tool_call(raw)

    assert canonical.args == {}
    assert canonical.arguments_parse_status == "empty_object"


def test_invalid_raw_args_is_not_hidden_by_empty_args_dict() -> None:
    raw = {"id": "1", "name": "web_search", "args": {}, "raw_args": '{"query":'}

    canonical = canonicalize_tool_call(raw)

    assert canonical.arguments_parse_status == "invalid_json"
    assert canonical.raw_args == '{"query":'
    assert canonical.args == {}


def test_langchain_style_shape_still_round_trips() -> None:
    raw = {"name": "read_file", "args": {"path": "AGENT.MD"}}

    canonical = canonicalize_tool_call(raw)

    assert canonical.name == "read_file"
    assert canonical.raw_name == "read_file"
    assert canonical.args == {"path": "AGENT.MD"}
