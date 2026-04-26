from __future__ import annotations

from app.trace_events import make_trace_event


def test_make_trace_event_populates_required_fields() -> None:
    payload = make_trace_event(
        run_id="run-1",
        type="runtime_contract.selected",
        title="Full Auto runtime enabled",
        detail="Tool policy: use when needed",
        status="success",
        payload={"mode": "full_auto"},
    )

    assert payload["id"]
    assert payload["run_id"] == "run-1"
    assert payload["type"] == "runtime_contract.selected"
    assert payload["title"] == "Full Auto runtime enabled"
    assert payload["detail"] == "Tool policy: use when needed"
    assert payload["status"] == "success"
    assert payload["payload"] == {"mode": "full_auto"}
    assert isinstance(payload["timestamp"], float)
    assert payload["visible"] is True


def test_make_trace_event_defaults_payload_and_parent() -> None:
    payload = make_trace_event(run_id="", type="run.started", title="Started")

    assert payload["payload"] == {}
    assert payload["parent_id"] is None
    assert payload["duration_ms"] is None
