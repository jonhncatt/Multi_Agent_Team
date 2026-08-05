from __future__ import annotations

import json

from app.turn_trace import build_turn_trace


def test_turn_trace_uses_thread_item_ids_as_its_timeline() -> None:
    items = [
        {"id": "u1", "turn_id": "t1", "role": "user", "content": "inspect"},
        {
            "id": "a1",
            "turn_id": "t1",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}],
        },
        {
            "id": "tool-1",
            "turn_id": "t1",
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": '{"ok": true}',
        },
        {"id": "a2", "turn_id": "t1", "role": "assistant", "content": "done"},
    ]
    trace = build_turn_trace(
        {
            "thread_id": "thread-1",
            "turn_id": "t1",
            "status": "completed",
            "activity": {
                "trace_events": [
                    {
                        "type": "tool.started",
                        "timestamp": 10.0,
                        "payload": {"raw_tool_call": {"id": "call-1"}},
                    },
                    {
                        "type": "tool.finished",
                        "timestamp": 10.1,
                        "duration_ms": 100,
                        "payload": {"raw_tool_call": {"id": "call-1"}},
                    },
                ],
                "llm_exchanges": [
                    {
                        "model": "gpt-test",
                        "status": "completed",
                        "sent_messages_exact": [
                            {"role": "system", "content": "[agent.md]\nRules"},
                            {"role": "user", "content": "inspect"},
                        ],
                        "request_composition": {"bound_tool_names": ["read_file"]},
                        "model_returned_exact": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}],
                            "finish_reason": "tool_calls",
                        },
                    },
                    {
                        "model": "gpt-test",
                        "status": "completed",
                        "sent_messages_exact": [
                            {"role": "system", "content": "[agent.md]\nRules"},
                            {"role": "user", "content": "inspect"},
                            {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "name": "read_file"}]},
                            {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
                        ],
                        "request_composition": {"bound_tool_names": ["read_file"]},
                        "model_returned_exact": {"role": "assistant", "content": "done", "finish_reason": "stop"},
                    },
                ],
            },
            "tool_events": [
                {
                    "name": "read_file",
                    "status": "ok",
                    "raw_tool_call": {"id": "call-1", "name": "read_file"},
                    "raw_arguments": {"path": "README.md"},
                    "normalized_arguments": {"path": "README.md"},
                    "validation_result": {"call_id": "call-1", "allowed": True, "code": "allowed"},
                    "schema_validation": {"status": "valid"},
                    "result_preview": {"ok": True, "content": "preview"},
                }
            ],
        },
        thread_items=items,
        turn_id="t1",
    )

    assert [(step["sequence"], step["type"], step.get("item_id")) for step in trace["steps"]] == [
        (1, "user_received", "u1"),
        (2, "assistant_generated", "a1"),
        (3, "tool_completed", "tool-1"),
        (4, "assistant_generated", "a2"),
    ]
    assert trace["steps"][2]["requested_by_item_id"] == "a1"
    assert trace["steps"][2]["tool_call_id"] == "call-1"
    assert trace["steps"][2]["duration_ms"] == 100
    assert trace["steps"][2]["audit"] == {
        "raw_arguments": {"path": "README.md"},
        "normalized_arguments": {"path": "README.md"},
        "schema_validation": {"status": "valid"},
        "result_preview": {"ok": True, "content": "preview"},
    }
    assert trace["contexts"][0]["system_message"] == "[agent.md]\nRules"
    assert trace["contexts"][0]["components"] == ["agent.md"]
    assert len(trace["contexts"]) == 1
    assert "sha256" not in json.dumps(trace)


def test_turn_trace_preserves_skipped_as_non_failure_step_type() -> None:
    items = [
        {
            "id": "a1",
            "turn_id": "t1",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "name": "search_codebase", "args": {"query": "PLP"}}],
        },
        {
            "id": "tool-1",
            "turn_id": "t1",
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "search_codebase",
            "content": '{"ok": false, "error": {"kind": "tool_skipped"}}',
        },
    ]

    trace = build_turn_trace(
        {
            "thread_id": "thread-1",
            "turn_id": "t1",
            "status": "failed",
            "activity": {
                "tool_events": [
                    {
                        "name": "search_codebase",
                        "status": "skipped",
                        "raw_tool_call": {"id": "call-1", "name": "search_codebase"},
                        "validation_result": {"call_id": "call-1", "allowed": False, "code": "tool_skipped"},
                        "result_preview": {"ok": False, "error": {"kind": "tool_skipped"}},
                    }
                ]
            },
            "tool_events": [
                {
                    "name": "search_codebase",
                    "status": "skipped",
                    "raw_tool_call": {"id": "call-1", "name": "search_codebase"},
                    "validation_result": {"call_id": "call-1", "allowed": False, "code": "tool_skipped"},
                    "result_preview": {"ok": False, "error": {"kind": "tool_skipped"}},
                }
            ],
        },
        thread_items=items,
        turn_id="t1",
    )

    tool_step = next(step for step in trace["steps"] if step.get("item_id") == "tool-1")
    assert tool_step["type"] == "tool_skipped"
    assert tool_step["status"] == "skipped"


def test_turn_trace_keeps_duplicate_provider_call_ids_as_separate_transactions() -> None:
    items = [
        {
            "id": "assistant-1",
            "turn_id": "t1",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "duplicate-call", "name": "read_file", "args": {"path": "one.md"}}],
        },
        {
            "id": "tool-1",
            "turn_id": "t1",
            "role": "tool",
            "tool_call_id": "duplicate-call",
            "name": "read_file",
            "content": '{"ok": true, "path": "one.md"}',
        },
        {
            "id": "assistant-2",
            "turn_id": "t1",
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "duplicate-call", "name": "read_file", "args": {"path": "two.md"}}],
        },
        {
            "id": "tool-2",
            "turn_id": "t1",
            "role": "tool",
            "tool_call_id": "duplicate-call",
            "name": "read_file",
            "content": '{"ok": true, "path": "two.md"}',
        },
    ]
    tool_events = [
        {
            "name": "read_file",
            "status": "ok",
            "raw_tool_call": {"id": "duplicate-call", "name": "read_file"},
            "normalized_arguments": {"path": path},
            "result_preview": {"ok": True, "path": path},
        }
        for path in ("one.md", "two.md")
    ]
    trace_events = [
        {
            "type": event_type,
            "timestamp": timestamp,
            "duration_ms": duration_ms,
            "payload": {"raw_tool_call": {"id": "duplicate-call"}},
        }
        for event_type, timestamp, duration_ms in (
            ("tool.failed", 10.01, 10),
            ("tool.started", 20.0, 0),
            ("tool.finished", 20.02, 20),
        )
    ]

    trace = build_turn_trace(
        {
            "thread_id": "thread-1",
            "turn_id": "t1",
            "status": "completed",
            "activity": {"trace_events": trace_events},
            "tool_events": tool_events,
        },
        thread_items=items,
        turn_id="t1",
    )

    tool_steps = [step for step in trace["steps"] if str(step.get("type") or "").startswith("tool_")]
    assert len(tool_steps) == 2
    assert [step["requested_by_item_id"] for step in tool_steps] == ["assistant-1", "assistant-2"]
    assert [step["audit"]["normalized_arguments"]["path"] for step in tool_steps] == ["one.md", "two.md"]
    assert [step["duration_ms"] for step in tool_steps] == [10, 20]
    assert [step["tool_call_id_occurrence"] for step in tool_steps] == [1, 2]
    assert all(step["tool_call_id_collision"] is True for step in tool_steps)
    assert all(step["tool_call_id_collision_count"] == 2 for step in tool_steps)


def test_turn_trace_matches_repeated_history_to_the_latest_item() -> None:
    items = [
        {"id": "old-user", "turn_id": "old", "role": "user", "content": "hi"},
        {"id": "old-ai", "turn_id": "old", "role": "assistant", "content": "hello"},
        {"id": "new-user", "turn_id": "new", "role": "user", "content": "hi"},
        {"id": "new-ai", "turn_id": "new", "role": "assistant", "content": "hello again"},
    ]
    trace = build_turn_trace(
        {
            "thread_id": "thread-1",
            "turn_id": "new",
            "activity": {
                "llm_exchanges": [
                    {
                        "status": "completed",
                        "sent_messages_exact": [
                            {"role": "system", "content": "rules"},
                            {"role": "user", "content": "hi"},
                        ],
                        "model_returned_exact": {"role": "assistant", "content": "hello again"},
                    }
                ]
            },
        },
        thread_items=items,
        turn_id="new",
    )

    assistant_step = next(step for step in trace["steps"] if step["type"] == "assistant_generated")
    assert assistant_step["input_item_ids"] == ["new-user"]


def test_turn_trace_keeps_bounded_invalid_model_failure_without_raw_response() -> None:
    trace = build_turn_trace(
        {
            "thread_id": "thread-1",
            "turn_id": "t1",
            "status": "failed",
            "activity": {
                "llm_exchanges": [
                    {
                        "model": "gpt-test",
                        "status": "failed",
                        "sent_messages_exact": [{"role": "system", "content": "rules"}],
                        "model_returned_exact": {
                            "role": "assistant",
                            "invalid_tool_calls": [{"name": "apply_patch", "error": "invalid arguments"}],
                        },
                        "error": {"kind": "invalid_tool_calls", "message": "Provider returned an invalid call"},
                    }
                ]
            },
        },
        thread_items=[],
        turn_id="t1",
    )

    failed = trace["steps"][0]
    assert failed["type"] == "model_failed"
    assert failed["error_kind"] == "invalid_tool_calls"
    assert failed["invalid_tool_calls"] == [{"name": "apply_patch", "error": "invalid arguments"}]
    assert "model_returned_exact" not in json.dumps(trace)
