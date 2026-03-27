from __future__ import annotations

from typing import Any

import pytest

from app.core.bootstrap import _shadow_patch_worker_result_payload, _shadow_replay_result_payload
from app.evals import _run_agent_case
from app.models import ChatSettings, ToolEvent
import packages.office_modules.execution_runtime as execution_runtime_mod
from packages.office_modules.execution_runtime import (
    LegacyOfficeHelperAdapter,
    OfficeExecutionResult,
    read_legacy_helper_surface_metrics,
    reset_legacy_helper_surface_metrics,
)


class _FakeExecutionRuntime:
    def __init__(self, result: OfficeExecutionResult) -> None:
        self._result = result

    def run_chat(self, *args: Any, **kwargs: Any) -> OfficeExecutionResult:
        _ = args, kwargs
        return self._result


class _FakeLegacyRuntime:
    @property
    def tools(self) -> dict[str, str]:
        return {"provider": "local"}

    def run_chat(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        _ = args, kwargs
        return ("ok", [], "", [], [], [], [], [], [], None, [], {}, {}, "", {})

    def _route_request_by_rules(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        _ = args, kwargs
        return {"execution_policy": "standard_safe_pipeline"}


def test_shadow_replay_payload_uses_structured_result() -> None:
    payload = _shadow_replay_result_payload(
        OfficeExecutionResult(
            text="structured replay output",
            tool_events=[{"name": "workspace.read"}],
            execution_plan=["router", "worker"],
            execution_trace=["trace:1", "trace:2"],
            pipeline_hooks=[{"phase": "before_route"}],
            active_roles=["router", "worker"],
            current_role="worker",
            answer_bundle={"summary": "done"},
            usage_total={"total_tokens": 12},
            effective_model="gpt-test",
            route_state={"top_intent": "understanding"},
        ),
        selected_modules={"router": "router@1.0.0"},
    )

    assert payload["text_preview"] == "structured replay output"
    assert payload["tool_event_count"] == 1
    assert payload["execution_plan"] == ["router", "worker"]
    assert payload["execution_trace"] == ["trace:1", "trace:2"]
    assert payload["pipeline_hook_count"] == 1
    assert payload["current_role"] == "worker"
    assert payload["selected_modules"] == {"router": "router@1.0.0"}


def test_shadow_patch_worker_payload_uses_structured_result() -> None:
    payload = _shadow_patch_worker_result_payload(
        OfficeExecutionResult(
            text="worker output",
            tool_events=[{"name": "workspace.write"}],
            execution_plan=["planner", "worker_tools"],
            execution_trace=["trace:1", "trace:2", "trace:3"],
            pipeline_hooks=[{"phase": "before_execute"}],
            active_roles=["planner", "worker"],
            current_role="worker",
            answer_bundle={"summary": "patched"},
            usage_total={"total_tokens": 21},
            effective_model="gpt-worker",
            route_state={"execution_policy": "patch_worker"},
        )
    )

    assert payload["tool_event_count"] == 1
    assert payload["execution_plan"] == ["planner", "worker_tools"]
    assert payload["execution_trace_tail"] == ["trace:1", "trace:2", "trace:3"]
    assert payload["text_preview"] == "worker output"
    assert payload["effective_model"] == "gpt-worker"
    assert payload["route_state"] == {"execution_policy": "patch_worker"}


def test_eval_agent_case_consumes_structured_runtime_result() -> None:
    payload = _run_agent_case(
        {
            "message": "hello",
            "settings": {"enable_tools": True},
            "route_state": {"top_intent": "understanding"},
        },
        _FakeExecutionRuntime(
            OfficeExecutionResult(
                text="structured agent response",
                attachment_note="note",
                execution_plan=["router", "worker_tools"],
                execution_trace=["trace:1"],
                pipeline_hooks=[{"phase": "before_route"}],
                debug_flow=[{"stage": "route"}],
                agent_panels=[{"title": "router"}],
                active_roles=["router", "worker"],
                current_role="worker",
                role_states=[{"role": "worker", "status": "done"}],
                answer_bundle={"summary": "done"},
                tool_events=[ToolEvent(name="workspace.read", output_preview="ok")],
                usage_total={"total_tokens": 9},
                effective_model="gpt-eval",
                route_state={"top_intent": "understanding"},
            )
        ),
    )

    assert payload["text"] == "structured agent response"
    assert payload["attachment_note"] == "note"
    assert payload["tool_events_count"] == 1
    assert payload["tool_events"][0]["name"] == "workspace.read"
    assert payload["effective_model"] == "gpt-eval"
    assert payload["route_state"]["top_intent"] == "understanding"


def test_legacy_helper_surface_records_call_counts(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_path = tmp_path / "office_legacy_helper_surface_calls.json"
    monkeypatch.setattr(execution_runtime_mod, "LEGACY_HELPER_SURFACE_METRICS_PATH", metrics_path)
    reset_legacy_helper_surface_metrics()
    adapter = LegacyOfficeHelperAdapter(_FakeLegacyRuntime())

    _ = adapter.tools
    adapter._route_request_by_rules(user_message="hello")
    adapter.run_chat([], "", "hello", [], ChatSettings())

    metrics = read_legacy_helper_surface_metrics()
    reset_legacy_helper_surface_metrics()

    assert metrics["run_chat_calls"] == 1
    assert metrics["method_calls"]["_route_request_by_rules"] == 1
    assert metrics["attribute_accesses"]["tools"] == 1
