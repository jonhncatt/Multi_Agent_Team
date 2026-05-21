from __future__ import annotations

from app.answer_stream_state import answer_stream_diagnostics, new_answer_stream_state, start_answer_stream_call


def test_answer_stream_state_starts_with_stable_ids() -> None:
    state = new_answer_stream_state(run_id="run-1", thread_id="thread-1")

    assert state["turn_id"] == "run-1"
    assert state["thread_id"] == "thread-1"
    assert state["item_id"] == "run-1:agent_message"


def test_answer_stream_state_tracks_calls_and_diagnostics() -> None:
    state = new_answer_stream_state(run_id="run-1", thread_id="thread-1")
    first = start_answer_stream_call(state, model="gpt-test", phase="initial", tool_round=0)
    second = start_answer_stream_call(state, model="gpt-test", phase="followup", tool_round=1)
    state["delta_count"] = 3
    state["delta_chars"] = 18

    diagnostics = answer_stream_diagnostics(state)

    assert first["index"] == 1
    assert second["index"] == 2
    assert diagnostics["streamed"] is True
    assert diagnostics["delta_count"] == 3
    assert diagnostics["text_chars"] == 18
    assert diagnostics["call_count"] == 2
