from __future__ import annotations

import threading
import time
from typing import Any

from app.vp_runtime_backend import VPRuntimeBackend


class _Message:
    def __init__(self, *, content: str = "", additional_kwargs: dict[str, Any] | None = None) -> None:
        self.content = content
        self.additional_kwargs = dict(additional_kwargs or {})


class _Tools:
    def __init__(self, cancel_event: threading.Event) -> None:
        self.cancel_event = cancel_event

    def _current_cancel_event(self) -> threading.Event:
        return self.cancel_event


class _BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def invoke(self, _messages: list[Any]) -> _Message:
        self.started.set()
        self.release.wait(timeout=10)
        return _Message(content="late result")


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
