from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import build_provider_config, load_config
from scripts.check_developer_role import (
    DEFAULT_PROVIDER,
    DEVELOPER_MARKER,
    DEVELOPER_TEXT_MARKER,
    SYSTEM_MARKER,
    TOOL_MARKER,
    TOOL_NAME,
    USER_MARKER,
    _parser,
    build_summary,
    classify_precedence_reply,
    probe_developer_precedence,
    probe_developer_text,
    probe_developer_with_tools,
    probe_system_control,
)


def _response(*, content: str = "", tool_calls: list[object] | None = None) -> object:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _client(*responses: object) -> object:
    return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(list(responses))))


def test_classify_precedence_reply_is_exact() -> None:
    assert classify_precedence_reply(f"  {DEVELOPER_MARKER}\n") == "developer_won"
    assert classify_precedence_reply(USER_MARKER) == "user_won"
    assert classify_precedence_reply(f"Answer: {DEVELOPER_MARKER}") == "unexpected_reply"


def test_probe_defaults_to_openai_compatible_environment_group(monkeypatch) -> None:
    monkeypatch.setenv("VP_OPENAI_COMPAT_API_KEY", "test-company-key")
    monkeypatch.setenv("VP_OPENAI_COMPAT_BASE_URL", "https://company.example/v1")
    monkeypatch.setenv("VP_OPENAI_COMPAT_CA_CERT_PATH", "/tmp/company-ca.pem")
    monkeypatch.setenv("VP_OPENAI_COMPAT_DEFAULT_MODEL", "company-gpt-5.6")
    args = _parser().parse_args([])
    config = build_provider_config(load_config(), args.provider)

    assert DEFAULT_PROVIDER == "openai_compatible"
    assert args.provider == "openai_compatible"
    assert config.openai_base_url == "https://company.example/v1"
    assert config.openai_ca_cert_path == "/tmp/company-ca.pem"
    assert config.default_model == "company-gpt-5.6"


def test_system_control_uses_legacy_system_role() -> None:
    client = _client(_response(content=SYSTEM_MARKER))

    result = probe_system_control(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    request = client.chat.completions.requests[0]
    assert [message["role"] for message in request["messages"]] == ["system", "user"]
    assert result["ok"] is True
    assert result["result"] == "system_control_ok"


def test_developer_text_probe_has_no_conflicting_user_instruction() -> None:
    client = _client(_response(content=DEVELOPER_TEXT_MARKER))

    result = probe_developer_text(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    request = client.chat.completions.requests[0]
    assert [message["role"] for message in request["messages"]] == ["developer", "user"]
    assert DEVELOPER_TEXT_MARKER in request["messages"][0]["content"]
    assert DEVELOPER_TEXT_MARKER not in request["messages"][1]["content"]
    assert result["ok"] is True
    assert result["result"] == "developer_text_ok"


def test_precedence_probe_sends_developer_and_conflicting_user_messages() -> None:
    client = _client(_response(content=DEVELOPER_MARKER))

    result = probe_developer_precedence(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    request = client.chat.completions.requests[0]
    assert [message["role"] for message in request["messages"]] == ["developer", "user"]
    assert DEVELOPER_MARKER in request["messages"][0]["content"]
    assert USER_MARKER in request["messages"][1]["content"]
    assert "ignore" not in str(request["messages"]).lower()
    assert "regardless" not in str(request["messages"]).lower()
    assert result["ok"] is True
    assert result["result"] == "developer_won"


def test_precedence_probe_detects_gateway_that_drops_developer_semantics() -> None:
    client = _client(_response(content=USER_MARKER))

    result = probe_developer_precedence(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    assert result["ok"] is False
    assert result["request_accepted"] is True
    assert result["result"] == "user_won"


def test_tool_probe_requires_correct_marker_from_developer_instruction() -> None:
    function = SimpleNamespace(name=TOOL_NAME, arguments=json.dumps({"marker": TOOL_MARKER}))
    tool_call = SimpleNamespace(function=function)
    client = _client(_response(tool_calls=[tool_call]))

    result = probe_developer_with_tools(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    request = client.chat.completions.requests[0]
    assert request["messages"][0]["role"] == "developer"
    assert request["tool_choice"] == {"type": "function", "function": {"name": TOOL_NAME}}
    assert result["ok"] is True
    assert result["result"] == "tool_call_correct"


def test_tool_probe_rejects_wrong_marker() -> None:
    function = SimpleNamespace(name=TOOL_NAME, arguments=json.dumps({"marker": "WRONG"}))
    tool_call = SimpleNamespace(function=function)
    client = _client(_response(tool_calls=[tool_call]))

    result = probe_developer_with_tools(client, model="gpt-5.6", timeout_sec=10, secrets=[])

    assert result["ok"] is False
    assert result["result"] == "wrong_tool_marker"


def test_full_migration_requires_all_four_checks() -> None:
    assert build_summary(
        {
            "system_control": {"ok": True},
            "developer_text": {"ok": True},
            "developer_precedence": {"ok": True},
            "developer_with_tools": {"ok": True},
        }
    )["safe_to_migrate_to_developer"] is True
    incomplete = build_summary(
        {
            "system_control": {"ok": True},
            "developer_text": {"ok": True},
            "developer_precedence": {"ok": True},
            "developer_with_tools": {"ok": False},
        }
    )
    assert incomplete["safe_to_migrate_to_developer"] is False
    assert incomplete["diagnosis"] == "developer_with_tools_not_confirmed"
