from __future__ import annotations

from app.context_meter import build_compaction_status, ensure_compaction_state


def test_compaction_status_uses_phase_reason_fields() -> None:
    session = {
        "compaction_state": {
            "last_compaction_phase": "pre_turn",
            "last_compaction_reason": "context_limit:100/90",
            "before_tokens": 100,
            "after_tokens": 60,
        }
    }

    state = ensure_compaction_state(session)
    status = build_compaction_status(session=session, model="gpt-test", pending_message="hello")

    assert state["phase"] == "pre_turn"
    assert status["phase"] == "pre_turn"
    assert status["reason"] == "context_limit"
    assert status["before_tokens"] == 100
    assert status["after_tokens"] == 60


def test_context_meter_counts_typed_transcript_not_harness_memory() -> None:
    base = {
        "thread_transcript": {
            "schema_version": 1,
            "items": [
                {"id": "u1", "role": "user", "content": "hello", "created_at": "now"},
                {"id": "a1", "role": "assistant", "content": "world", "created_at": "now"},
            ],
        },
        "context_manager": {"working_summary": "X" * 100_000},
        "thread_memory": {"summary": "Y" * 100_000},
        "route_state": {"raw": "Z" * 100_000},
    }
    clean = {"thread_transcript": base["thread_transcript"]}

    with_harness_state = build_compaction_status(session=base, model="gpt-5.4", estimate_mode="quick")
    transcript_only = build_compaction_status(session=clean, model="gpt-5.4", estimate_mode="quick")

    assert with_harness_state["estimated_context_tokens"] == transcript_only["estimated_context_tokens"]


def test_compacted_transcript_meter_replaces_older_items_with_summary() -> None:
    session = {
        "thread_transcript": {
            "schema_version": 1,
            "items": [
                {"id": "u1", "turn_id": "u1", "role": "user", "content": "old " + "A" * 20_000},
                {"id": "a1", "turn_id": "a1", "role": "assistant", "content": "old answer " + "B" * 20_000},
                {"id": "u2", "turn_id": "u2", "role": "user", "content": "new request"},
            ],
        },
        "compaction_state": {
            "compacted_history": "short summary",
            "compacted_until_turn_id": "a1",
        },
    }

    compacted = build_compaction_status(session=session, model="gpt-5.4", estimate_mode="quick")
    uncompressed = build_compaction_status(
        session={"thread_transcript": session["thread_transcript"]},
        model="gpt-5.4",
        estimate_mode="quick",
    )

    assert compacted["estimated_context_tokens"] < uncompressed["estimated_context_tokens"]
