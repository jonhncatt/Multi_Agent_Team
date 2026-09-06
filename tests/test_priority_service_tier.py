from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.models import ChatSettings
from app.vintage_programmer_runtime import VintageProgrammerRuntime
from app.vp_runtime_backend import VPRuntimeBackend


def _backend(client: httpx.Client) -> VPRuntimeBackend:
    backend = object.__new__(VPRuntimeBackend)
    backend.config = SimpleNamespace(
        openai_use_responses_api=False,
        openai_temperature=None,
        openai_base_url="https://company-gateway.invalid/openai/v1",
        openai_ca_cert_path="",
    )
    backend._auth_manager = SimpleNamespace(require=lambda: SimpleNamespace(api_key="test-key"))
    backend._new_owned_http_client = lambda: client
    backend._chat_openai_cls = lambda: ChatOpenAI
    backend._invoke_runner = lambda runner, messages, **kwargs: runner.invoke(messages)
    return backend


def _completion(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": json.loads(request.content)["model"],
        "service_tier": "default",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    })


def test_priority_setting_defaults_to_standard_and_rejects_unknown_tiers() -> None:
    assert ChatSettings().service_tier == "default"
    restored = ChatSettings.model_validate_json(ChatSettings(service_tier="priority").model_dump_json())
    assert restored.service_tier == "priority"
    with pytest.raises(ValidationError):
        ChatSettings(service_tier="auto")


@pytest.mark.parametrize("use_responses", [False, True])
def test_service_tier_reaches_sdk_payload_and_does_not_leak_between_runs(use_responses: bool) -> None:
    with httpx.Client(transport=httpx.MockTransport(_completion)) as client:
        backend = _backend(client)
        for tier in ("default", "priority", "default"):
            llm = backend._build_llm(
                model="gpt-5.6-sol", max_output_tokens=1024,
                reasoning_effort="max", service_tier=tier, use_responses_api=use_responses,
            )
            payload = llm._get_request_payload([("user", "hi")])
            assert payload["service_tier"] == tier
            if use_responses:
                assert payload["reasoning"]["effort"] == "max"
            else:
                assert payload["reasoning_effort"] == "max"


def test_chat_completions_sends_priority_and_preserves_provider_downgrade() -> None:
    requests: list[dict[str, Any]] = []

    def receive(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/v1/chat/completions"
        requests.append(json.loads(request.content))
        return _completion(request)

    with httpx.Client(transport=httpx.MockTransport(receive)) as client:
        backend = _backend(client)
        response, _, _ = backend._invoke_single_model(
            messages=[("user", "hi")], model="gpt-5.6-sol", max_output_tokens=1024,
            enable_tools=False, reasoning_effort="max", service_tier="priority",
        )
    assert requests[0]["service_tier"] == "priority"
    assert requests[0]["reasoning_effort"] == "max"
    assert response.response_metadata["service_tier"] == "default"


@pytest.mark.parametrize("tier", ["default", "priority"])
def test_api_mode_fallback_preserves_service_tier(tier: str) -> None:
    backend = object.__new__(VPRuntimeBackend)
    backend.config = SimpleNamespace(openai_use_responses_api=True)
    built: list[dict[str, Any]] = []

    def build(**kwargs: Any) -> object:
        built.append(kwargs)
        return object()

    def invoke(runner: Any, messages: Any, **kwargs: Any) -> str:
        if len(built) == 1:
            raise RuntimeError("405 Method Not Allowed")
        return "ok"

    backend._build_llm = build
    backend._invoke_runner = invoke
    result, _, _ = backend._invoke_single_model(
        messages=[], model="gpt-5.6-sol", max_output_tokens=1024,
        enable_tools=False, service_tier=tier,
    )
    assert result == "ok"
    assert [item["service_tier"] for item in built] == [tier, tier]
    assert built[1]["use_responses_api"] is False


def test_runner_recovery_and_model_failover_preserve_priority() -> None:
    backend = object.__new__(VPRuntimeBackend)
    backend._build_model_candidates = lambda model: [model, "backup-model"]
    backend._model_cooldown_left = lambda model: 0
    backend._mark_model_success = lambda model: None
    backend._mark_model_failure = lambda model: 1
    backend._is_failover_error = lambda exc: True
    invocations: list[dict[str, Any]] = []

    def invoke_single(**kwargs: Any) -> Any:
        invocations.append(kwargs)
        if len(invocations) == 1:
            raise RuntimeError("provider unavailable")
        return "ok", object(), []

    def broken_runner(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("connection lost")

    backend._invoke_single_model = invoke_single
    backend._invoke_runner = broken_runner
    result, _, model, _ = backend._invoke_with_runner_recovery(
        runner=object(), messages=[], model="gpt-5.6-sol", max_output_tokens=1024,
        enable_tools=False, service_tier="priority",
    )
    assert result == "ok"
    assert model == "backup-model"
    assert [item["service_tier"] for item in invocations] == ["priority", "priority"]


def test_runtime_adapter_forwards_service_tier_when_explicitly_supported() -> None:
    assert VintageProgrammerRuntime._invoke_backend_method(
        lambda *, service_tier: service_tier, service_tier="priority",
    ) == "priority"
    assert VintageProgrammerRuntime._invoke_backend_method(
        lambda model: model, model="legacy", service_tier="priority",
    ) == "legacy"
