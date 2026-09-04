from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import openai

from app.vp_runtime_backend import VPRuntimeBackend


class _Message:
    def __init__(self, *, content: str = "", additional_kwargs: dict[str, Any] | None = None) -> None:
        self.content = content
        self.additional_kwargs = dict(additional_kwargs or {})


class _Tools:
    def __init__(self, cancel_event: threading.Event, *, run_id: str = "") -> None:
        self.cancel_event = cancel_event
        self.run_id = run_id

    def _current_cancel_event(self) -> threading.Event:
        return self.cancel_event

    def _current_run_id(self) -> str:
        return self.run_id


class _BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def invoke(self, _messages: list[Any]) -> _Message:
        self.started.set()
        self.release.wait(timeout=10)
        return _Message(content="late result")


class _SharedClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RunnerWithSharedClient(_BlockingRunner):
    def __init__(self, shared_client: _SharedClient) -> None:
        super().__init__()
        self.root_client = shared_client


def test_build_llm_forwards_explicit_reasoning_effort() -> None:
    captured: dict[str, Any] = {}
    backend = object.__new__(VPRuntimeBackend)
    backend.config = SimpleNamespace(
        openai_use_responses_api=False,
        openai_temperature=None,
        openai_base_url="",
        openai_ca_cert_path="",
    )
    backend._new_owned_http_client = lambda: None

    def fake_chat_openai(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    backend._chat_openai_cls = lambda: fake_chat_openai
    backend._build_llm_direct_fallback(
        auth=SimpleNamespace(api_key="test-key"),
        model="gpt-5.6-sol",
        max_output_tokens=1024,
        reasoning_effort="xhigh",
    )

    assert captured["reasoning_effort"] == "xhigh"


def test_build_llm_omits_reasoning_effort_for_non_gpt_56_models() -> None:
    captured: dict[str, Any] = {}
    backend = object.__new__(VPRuntimeBackend)
    backend.config = SimpleNamespace(
        openai_use_responses_api=False,
        openai_temperature=None,
        openai_base_url="",
        openai_ca_cert_path="",
    )
    backend._new_owned_http_client = lambda: None

    def fake_chat_openai(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    backend._chat_openai_cls = lambda: fake_chat_openai
    backend._build_llm_direct_fallback(
        auth=SimpleNamespace(api_key="test-key"),
        model="gpt-5.4",
        max_output_tokens=1024,
        reasoning_effort="max",
    )

    assert "reasoning_effort" not in captured


def test_model_invocation_returns_cancelled_sentinel_without_waiting_for_provider() -> None:
    cancel_event = threading.Event()
    backend = object.__new__(VPRuntimeBackend)
    backend.tools = _Tools(cancel_event)
    backend._AIMessage = _Message
    runner = _BlockingRunner()

    def cancel() -> None:
        assert runner.started.wait(timeout=2)
        cancel_event.set()

    trigger = threading.Thread(target=cancel)
    trigger.start()
    started_at = time.monotonic()
    try:
        response = backend._invoke_runner(runner, [])
    finally:
        runner.release.set()
        trigger.join(timeout=2)

    assert time.monotonic() - started_at < 1.0
    assert response.content == ""
    assert response.additional_kwargs["vp_model_invocation_cancelled"] is True


def test_model_cancellation_does_not_close_a_shared_provider_client() -> None:
    cancel_event = threading.Event()
    backend = object.__new__(VPRuntimeBackend)
    backend.tools = _Tools(cancel_event)
    backend._AIMessage = _Message
    shared_client = _SharedClient()
    runner = _RunnerWithSharedClient(shared_client)

    def cancel() -> None:
        assert runner.started.wait(timeout=2)
        cancel_event.set()

    trigger = threading.Thread(target=cancel)
    trigger.start()
    try:
        response = backend._invoke_runner(runner, [])
    finally:
        runner.release.set()
        trigger.join(timeout=2)

    assert response.additional_kwargs["vp_model_invocation_cancelled"] is True
    assert shared_client.closed is False


def test_agent_run_owns_and_releases_its_provider_client(monkeypatch) -> None:
    backend = object.__new__(VPRuntimeBackend)
    backend.tools = _Tools(threading.Event(), run_id="run-1")
    backend._run_http_clients_lock = threading.Lock()
    backend._run_http_clients = {}
    owned_client = _SharedClient()
    monkeypatch.setattr(openai, "DefaultHttpxClient", lambda: owned_client)

    assert backend._new_owned_http_client() is owned_client
    assert backend.release_model_run(run_id="other-run") == 0
    assert owned_client.closed is False
    assert backend.release_model_run(run_id="run-1") == 1
    assert owned_client.closed is True
    assert backend.release_model_run(run_id="run-1") == 0
