from __future__ import annotations

import json
from pathlib import Path

from app.storage import SessionStore


def _project(tmp_path: Path) -> dict[str, str]:
    return {
        "project_id": "project-test",
        "title": "Test Project",
        "root_path": str(tmp_path),
        "git_branch": "main",
    }


def _build_sidecar_session(tmp_path: Path) -> tuple[SessionStore, dict[str, object], dict[str, object]]:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))
    logical_turn_id = "turn-1"
    user_turn = store.append_turn(session, role="user", text="inspect", logical_turn_id=logical_turn_id)
    store.append_thread_items(
        session,
        [
            {
                "id": "assistant-tool-1",
                "turn_id": logical_turn_id,
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}],
            },
            {
                "id": "tool-result-1",
                "turn_id": logical_turn_id,
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "read_file",
                "content": '{"ok": true}',
            },
        ],
    )
    assistant_turn = store.append_turn(
        session,
        role="assistant",
        text="done",
        logical_turn_id=logical_turn_id,
        answer_bundle={"summary": "done", "claims": [], "citations": [], "warnings": []},
        activity={
            "run_id": "run-1",
            "status": "completed",
            "summary": "read and answered",
            "activity_summary": "read and answered",
            "run_duration_ms": 12,
            "turn_changes": {
                "files": [
                    {"path": "app/main.py", "kind": "modified"},
                    {"path": "tests/test_main.py", "kind": "modified"},
                ],
                "count": 2,
                "retained": False,
                "possible_untracked_changes": False,
                "verification": {
                    "status": "passed",
                    "tool": "exec_command",
                    "summary": "2 passed",
                },
            },
            "triggering_user_message": "inspect",
            "tool_boundary_clean": True,
            "plan": [{"step": "inspect", "status": "completed"}],
            "plan_explanation": "plan detail",
            "trace_events": [
                {"id": "trace-1", "type": "tool.started", "timestamp": 10.0, "payload": {"call_id": "call-1"}},
                {"id": "trace-2", "type": "tool.finished", "timestamp": 10.02, "payload": {"call_id": "call-1"}},
            ],
            "llm_exchanges": [
                {
                    "round": 1,
                    "model": "gpt-test",
                    "status": "completed",
                    "duration_ms": 7,
                    "sent_messages_exact": [
                        {"role": "developer", "content": "[agent.md]\nRules"},
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
                    "round": 2,
                    "model": "gpt-test",
                    "status": "completed",
                    "duration_ms": 5,
                    "sent_messages_exact": [
                        {"role": "developer", "content": "[agent.md]\nRules"},
                        {"role": "user", "content": "inspect"},
                        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}]},
                        {"role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": '{"ok": true}'},
                    ],
                    "request_composition": {"bound_tool_names": ["read_file"]},
                    "model_returned_exact": {"role": "assistant", "content": "done", "finish_reason": "stop"},
                },
            ],
            "model_draft": "draft",
            "final_answer": "done",
            "runtime_error": {"kind": "debug"},
            "tool_items": [{"type": "toolCall", "tool": "read_file"}],
            "live_items": [{"type": "model_draft", "text": "draft"}],
        },
    )
    store.persist_turn_artifact(
        session,
        turn_id=str(assistant_turn["id"]),
        run_id="run-1",
        activity=assistant_turn["activity"],
        answer_bundle=assistant_turn["answer_bundle"],
        logical_turn_id=logical_turn_id,
        tool_events=[
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
        inspector={"run_state": {"turn_status": "completed"}},
        extra={"effective_model": "gpt-test", "permission_profile": "auto", "turn_status": "completed"},
    )
    store.save(session)
    raw_session = json.loads((tmp_path / "sessions" / f"{session['id']}.json").read_text(encoding="utf-8"))
    return store, session, raw_session


def _assistant_item(raw_session: dict[str, object]) -> dict[str, object]:
    items = list((raw_session.get("thread_transcript") or {}).get("items") or [])
    return next(dict(item) for item in reversed(items) if isinstance(item, dict) and item.get("role") == "assistant")


def _projected_assistant_turn(store: SessionStore, session_id: str) -> dict[str, object]:
    loaded = store.load(session_id)
    assert loaded is not None
    return dict(loaded["turns"][-1])


def test_assistant_activity_is_slimmed_to_turn_trace(tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    raw_trace = dict(_assistant_item(raw_session).get("trace") or {})
    assert raw_trace["trace_ref"] == f"turn_traces/{session['id']}/turn-1"
    assert raw_trace["tool_count"] == 1
    assert set(raw_trace) <= {
        "trace_ref",
        "status",
        "tool_count",
        "duration_ms",
        "turn_changes",
    }
    assert raw_trace["turn_changes"] == {
        "files": [
            {"path": "app/main.py", "kind": "modified"},
            {"path": "tests/test_main.py", "kind": "modified"},
        ],
        "count": 2,
        "retained": False,
        "possible_untracked_changes": False,
        "verification": {
            "status": "passed",
            "tool": "exec_command",
            "summary": "2 passed",
        },
    }
    for heavy_key in (
        "trace_events",
        "llm_exchanges",
        "tool_events",
        "tool_items",
        "live_items",
        "model_draft",
        "runtime_error",
        "plan",
        "plan_explanation",
        "tool_boundary_clean",
        "triggering_user_message",
        "answer_bundle",
        "inspector",
    ):
        assert heavy_key not in raw_trace
    assert "turns" not in raw_session
    assert "latest_run_id" not in raw_session

    trace = json.loads((tmp_path / "turn_traces" / session["id"] / "turn-1.json").read_text(encoding="utf-8"))
    assert trace["turn_trace_schema_version"] == 1
    assert trace["turn_id"] == "turn-1"
    assert trace["contexts"] == [
        {
            "context_id": "context-1",
            "developer_message": "[agent.md]\nRules",
            "components": ["agent.md"],
            "supporting_messages": [],
            "tool_names": ["read_file"],
        }
    ]
    raw_items = list((raw_session.get("thread_transcript") or {}).get("items") or [])
    user_item_id = str(next(item["id"] for item in raw_items if item.get("role") == "user"))
    final_assistant_id = str(_assistant_item(raw_session)["id"])
    assert [(step["type"], step.get("item_id")) for step in trace["steps"]] == [
        ("user_received", user_item_id),
        ("assistant_generated", "assistant-tool-1"),
        ("tool_completed", "tool-result-1"),
        ("assistant_generated", final_assistant_id),
    ]
    tool_step = trace["steps"][2]
    assert tool_step["requested_by_item_id"] == "assistant-tool-1"
    assert tool_step["tool_call_id"] == "call-1"
    assert tool_step["duration_ms"] in {19, 20}

    projected_turn = _projected_assistant_turn(store, str(session["id"]))
    summary_turn = store.expand_turn_for_view(session["id"], projected_turn, view="summary")
    assert summary_turn["answer_bundle"] == {}
    assert summary_turn["activity"]["turn_changes"] == raw_trace["turn_changes"]
    assert "trace_events" not in summary_turn["activity"]
    assert "model_draft" not in summary_turn["activity"]
    assert "runtime_error" not in summary_turn["activity"]

    activity_turn = store.expand_turn_for_view(session["id"], projected_turn, view="activity")
    assert activity_turn["activity"]["activity_loaded"] is True
    assert activity_turn["activity"]["debug_loaded"] is False
    assert activity_turn["activity"]["full_loaded"] is False
    assert activity_turn["activity"]["trace_events"] == []
    assert activity_turn["activity"]["tool_items"][0]["raw_tool_call"]["id"] == "call-1"
    assert activity_turn["activity"]["tool_items"][0]["raw_arguments"] == {"path": "README.md"}
    assert activity_turn["activity"]["tool_items"][0]["normalized_arguments"] == {"path": "README.md"}
    assert activity_turn["activity"]["tool_items"][0]["validation_result"] == {
        "allowed": True,
        "code": "allowed",
    }
    assert activity_turn["activity"]["tool_items"][0]["schema_validation"] == {"status": "valid"}
    assert activity_turn["activity"]["tool_items"][0]["result_preview"] == {
        "ok": True,
        "content": "preview",
    }
    assert "llm_exchanges" not in activity_turn["activity"]
    assert "model_draft" not in activity_turn["activity"]
    assert "final_answer" not in activity_turn["activity"]
    assert "runtime_error" not in activity_turn["activity"]
    assert "triggering_user_message" not in activity_turn["activity"]
    assert "answer_stream" not in activity_turn["activity"]
    assert activity_turn["answer_bundle"] == {}
    assert activity_turn["run_artifact"] == {}

    debug_turn = store.expand_turn_for_view(session["id"], projected_turn, view="debug")
    assert debug_turn["activity"]["activity_loaded"] is True
    assert debug_turn["activity"]["debug_loaded"] is True
    assert debug_turn["activity"]["full_loaded"] is False
    assert debug_turn["activity"]["turn_trace"]["turn_id"] == "turn-1"
    assert "llm_exchanges" not in debug_turn["activity"]
    assert "triggering_user_message" not in debug_turn["activity"]
    assert "answer_stream" not in debug_turn["activity"]
    assert debug_turn["answer_bundle"] == {}
    assert debug_turn["run_artifact"] == {}

    full_turn = store.expand_turn_for_view(session["id"], projected_turn, view="full")
    assert full_turn["answer_bundle"] == {}
    assert full_turn["activity"]["full_loaded"] is True
    assert full_turn["activity"]["turn_trace"]["turn_id"] == "turn-1"
    assert full_turn["run_artifact"] == {}


def test_expand_turn_summary_does_not_load_turn_trace(monkeypatch, tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("summary view should not load run artifacts")

    monkeypatch.setattr(store.run_artifact_store, "load_by_ref", _boom)
    monkeypatch.setattr(store.run_artifact_store, "load", _boom)
    monkeypatch.setattr(store.turn_trace_store, "load_by_ref", _boom)

    projected_turn = _projected_assistant_turn(store, str(session["id"]))
    summary_turn = store.expand_turn_for_view(session["id"], projected_turn, view="summary")

    assert summary_turn["activity"] == projected_turn["activity"]
    assert summary_turn["answer_bundle"] == {}
    assert summary_turn["run_artifact"] == {}


def test_expand_turn_debug_loads_turn_trace_without_legacy_run(monkeypatch, tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    calls = {"load": 0, "load_by_ref": 0}
    original_load_by_ref = store.turn_trace_store.load_by_ref

    def _load_by_ref(trace_ref: str):
        calls["load_by_ref"] += 1
        return original_load_by_ref(trace_ref)

    monkeypatch.setattr(store.turn_trace_store, "load_by_ref", _load_by_ref)

    projected_turn = _projected_assistant_turn(store, str(session["id"]))
    full_turn = store.expand_turn_for_view(session["id"], projected_turn, view="debug")

    assert calls["load_by_ref"] == 1
    assert calls["load"] == 0
    assert full_turn["activity"]["turn_trace"]["turn_id"] == "turn-1"
    assert full_turn["run_artifact"] == {}


def test_turn_trace_reload_is_idempotent(tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    persisted_once = session_path.read_bytes()

    loaded = store.load(str(session["id"]), default_project=_project(tmp_path))
    reloaded = store.load(str(session["id"]), default_project=_project(tmp_path))

    assert loaded is not None and reloaded is not None
    assert session_path.read_bytes() == persisted_once
    assert dict(_assistant_item(raw_session).get("trace") or {})["status"] == "completed"


def test_session_list_reads_metadata_without_parsing_session_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))
    store.append_turn(session, role="user", text="hello")
    store.save(session)

    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    session_path.write_text("{not-json", encoding="utf-8")

    rows = store.list_recent_sessions(limit=10, project_id="project-test")
    assert [row["session_id"] for row in rows] == [session["id"]]
    assert rows[0]["title"] == "hello"


def test_empty_thread_metadata_keeps_default_title_unlocalized(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))

    rows = store.list_recent_sessions(limit=10, project_id="project-test")
    assert rows[0]["title"] == ""
    assert rows[0]["has_custom_title"] is False

    meta_path = store.session_meta_store._path(session["id"])  # noqa: SLF001 - legacy metadata regression
    legacy_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    legacy_meta["title"] = "新会话"
    meta_path.write_text(json.dumps(legacy_meta, ensure_ascii=False), encoding="utf-8")

    migrated_rows = store.list_recent_sessions(limit=10, project_id="project-test")
    assert migrated_rows[0]["title"] == ""


def test_thread_activity_clock_controls_listing_without_following_unrelated_saves(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    first = store.create(_project(tmp_path))
    second = store.create(_project(tmp_path))

    store.mark_activity(first, kind="user_message", at="2026-07-15T10:00:00+00:00")
    store.save(first)
    store.mark_activity(second, kind="turn_completed", at="2026-07-15T09:00:00+00:00")
    store.save(second)

    # Saving non-activity metadata must not move an older Thread above new progress.
    second["title"] = "renamed without new activity"
    store.save(second)

    rows = store.list_recent_sessions(limit=10, project_id="project-test")
    assert [row["session_id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["activity_revision"] == 1
    assert rows[0]["activity_kind"] == "user_message"


def test_legacy_session_activity_fields_migrate_idempotently(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    legacy = {
        "id": "legacy-activity",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
        "turns": [],
    }

    normalized, changed = store._normalize_session(legacy)  # noqa: SLF001 - migration regression
    normalized_again, changed_again = store._normalize_session(normalized)  # noqa: SLF001

    assert changed is True
    assert normalized["activity_at"] == legacy["updated_at"]
    assert normalized["activity_revision"] == 0
    assert normalized["activity_kind"] == ""
    assert normalized_again == normalized
    # Other legacy compatibility shims may still report a normalization pass;
    # the activity migration itself must not advance or rewrite its clock.
    assert isinstance(changed_again, bool)


def test_session_load_discards_legacy_derived_memory_fields(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))
    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["recent_tasks"] = [
        {
            "task_id": "legacy-task",
            "turn_id": "turn-1",
            "user_request": "继续旧任务",
            "goal": "旧任务",
            "cwd": str(tmp_path),
            "artifact_refs": ["legacy-artifact"],
            "active_files": ["app.py"],
            "result_digest": "done",
            "updated_at": "2026-06-01T00:00:00Z",
        }
    ]
    payload["artifact_memory_preview"] = [
        {
            "artifact_id": "legacy-artifact",
            "kind": "document",
            "name": "legacy.pdf",
            "path": str(tmp_path / "legacy.pdf"),
            "created_at": "2026-06-01T00:00:00Z",
        }
    ]
    payload["context_meter"] = {
        "estimated_tokens": 1234,
        "context_window": 8192,
        "auto_compact_token_limit": 7000,
        "threshold_source": "model_registry",
    }
    payload["compaction_status"] = {
        "generation": 2,
        "last_compacted_at": "2026-06-01T00:00:01Z",
        "last_compaction_phase": "pre_turn",
        "reason": "context_limit",
    }
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = store.load(session["id"], default_project=_project(tmp_path))
    assert loaded is not None
    assert "recent_tasks" not in loaded
    assert "artifact_memory_preview" not in loaded
    assert "context_meter" not in loaded
    assert "compaction_status" not in loaded
    assert "thread_memory" not in loaded
    assert "artifact_memory" not in loaded
    assert loaded["compaction_state"]["generation"] == 2
    assert loaded["compaction"]["compacted_at"] == "2026-06-01T00:00:01Z"

    persisted = json.loads(session_path.read_text(encoding="utf-8"))
    for key in ("recent_tasks", "artifact_memory_preview", "context_meter", "compaction_status"):
        assert key not in persisted
    assert persisted["compaction"] == {
        "generation": 2,
        "summary": "",
        "compacted_until_item_id": "",
        "compacted_at": "2026-06-01T00:00:01Z",
    }
