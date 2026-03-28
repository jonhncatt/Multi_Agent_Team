from __future__ import annotations

from typing import Any

from packages.office_modules.execution_runtime import (
    LEGACY_RUN_CHAT_FIELDS,
    LegacyOfficeExecutionRuntimeAdapter,
    normalize_legacy_run_chat_result,
)
from packages.office_modules.execution_engine import OfficeExecutionEngine


def _make_legacy_tuple(**overrides: Any) -> tuple[Any, ...]:
    payload: dict[str, Any] = {
        "text": "hello",
        "tool_events": [],
        "attachment_note": "",
        "execution_plan": [],
        "execution_trace": [],
        "pipeline_hooks": [],
        "debug_flow": [],
        "agent_panels": [],
        "active_roles": [],
        "current_role": None,
        "role_states": [],
        "answer_bundle": {},
        "usage_total": {},
        "effective_model": "gpt-test",
        "route_state": {},
    }
    payload.update(overrides)
    return tuple(payload[name] for name in LEGACY_RUN_CHAT_FIELDS)


class _FakeLegacySurface:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def run_chat(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": list(args), "kwargs": dict(kwargs)})
        return self._result


def test_normalize_legacy_run_chat_result_golden_basic_chat() -> None:
    result = normalize_legacy_run_chat_result(_make_legacy_tuple(text="basic chat", current_role="worker"))

    assert result.text == "basic chat"
    assert result.current_role == "worker"
    assert result.execution_plan == []
    assert result.tool_events == []
    assert result.effective_model == "gpt-test"


def test_normalize_legacy_run_chat_result_golden_tools_and_trace() -> None:
    result = normalize_legacy_run_chat_result(
        _make_legacy_tuple(
            tool_events=[{"name": "workspace.read"}],
            execution_plan=["router", "worker_tools"],
            execution_trace=["trace:1", "trace:2"],
            active_roles=["router", "worker"],
        )
    )

    assert result.tool_events == [{"name": "workspace.read"}]
    assert result.execution_plan == ["router", "worker_tools"]
    assert result.execution_trace == ["trace:1", "trace:2"]
    assert result.active_roles == ["router", "worker"]


def test_normalize_legacy_run_chat_result_golden_route_state_bundle_and_panels() -> None:
    result = normalize_legacy_run_chat_result(
        _make_legacy_tuple(
            route_state={"top_intent": "understanding", "execution_policy": "qa_direct"},
            answer_bundle={"summary": "done"},
            agent_panels=[{"title": "router"}],
            pipeline_hooks=[{"phase": "before_route_finalize"}],
            debug_flow=[{"stage": "route"}],
        )
    )

    assert result.route_state["top_intent"] == "understanding"
    assert result.answer_bundle["summary"] == "done"
    assert result.agent_panels == [{"title": "router"}]
    assert result.pipeline_hooks == [{"phase": "before_route_finalize"}]
    assert result.debug_flow == [{"stage": "route"}]


def test_execution_runtime_adapter_returns_structured_result_from_legacy_surface() -> None:
    runtime = LegacyOfficeExecutionRuntimeAdapter(
        _FakeLegacySurface(
            _make_legacy_tuple(
                text="adapter result",
                execution_plan=["router"],
                route_state={"top_intent": "understanding"},
                answer_bundle={"summary": "adapter"},
            )
        )
    )

    result = runtime.run_chat([], "", "hello", [], {}, session_id="s-1", route_state={}, progress_cb=None)

    assert result.text == "adapter result"
    assert result.execution_plan == ["router"]
    assert result.route_state["top_intent"] == "understanding"
    assert result.answer_bundle["summary"] == "adapter"


def test_office_execution_engine_returns_structured_result() -> None:
    backend = _FakeLegacySurface(
        _make_legacy_tuple(
            text="engine result",
            execution_plan=["router", "worker"],
            effective_model="gpt-engine",
            route_state={"top_intent": "generation"},
        )
    )
    runtime = OfficeExecutionEngine(backend=backend)

    result = runtime.run_chat([], "", "hello", [], {}, session_id="s-2", route_state={"x": 1}, progress_cb=None)

    assert result.text == "engine result"
    assert result.execution_plan == ["router", "worker"]
    assert result.effective_model == "gpt-engine"
    assert result.route_state["top_intent"] == "generation"


def test_office_execution_engine_forwards_blackboard_compatibility_kwarg() -> None:
    backend = _FakeLegacySurface(_make_legacy_tuple(text="engine with blackboard"))
    runtime = OfficeExecutionEngine(backend=backend)
    marker = object()

    result = runtime.run_chat(
        [],
        "",
        "hello",
        [],
        {},
        session_id="s-3",
        route_state={},
        progress_cb=None,
        blackboard=marker,
    )

    assert result.text == "engine with blackboard"
    assert backend.calls[-1]["kwargs"]["blackboard"] is marker
