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
    store.append_turn(session, role="user", text="inspect")
    assistant_turn = store.append_turn(
        session,
        role="assistant",
        text="done",
        answer_bundle={"summary": "done", "claims": [], "citations": [], "warnings": []},
        activity={
            "run_id": "run-1",
            "status": "completed",
            "summary": "read and answered",
            "activity_summary": "read and answered",
            "run_duration_ms": 12,
            "triggering_user_message": "inspect",
            "tool_boundary_clean": True,
            "plan": [{"step": "inspect", "status": "completed"}],
            "plan_explanation": "plan detail",
            "trace_events": [{"id": "trace-1", "type": "tool.started", "payload": {"call_id": "call-1"}}],
            "llm_exchanges": [{"round": 1, "status": "completed"}],
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
        tool_events=[{"name": "read_file", "status": "ok", "summary": "read"}],
        inspector={"run_state": {"turn_status": "completed"}},
        extra={
            "task_state": {
                "task_id": "task-1",
                "goal": "Inspect sidecar payload",
                "status": "in_progress",
                "current_step_id": "step-2",
                "completed_steps": [{"id": "step-1", "step": "Read activity", "progress_basis": ["read_file: app/static/app.js"]}],
                "failed_attempts": [],
                "progress_basis": ["read_file: app/static/app.js"],
                "evidence_refs": [{"tool": "read_file", "ref": "app/static/app.js"}],
                "validation_warnings": [],
            },
            "task_state_delta": {
                "current_step_id": "step-2",
                "step_updates": [{"step_id": "step-1", "status": "completed", "evidence_refs": [{"tool": "read_file", "ref": "app/static/app.js"}]}],
                "next_required_action": "Run focused tests",
            },
            "task_state_validation": {
                "accepted": True,
                "applied_step_ids": ["step-1"],
                "rejected_step_ids": [],
                "validation_warnings": [],
            },
        },
    )
    store.save(session)
    raw_session = json.loads((tmp_path / "sessions" / f"{session['id']}.json").read_text(encoding="utf-8"))
    return store, session, raw_session


def test_assistant_activity_is_slimmed_to_run_sidecar(tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    raw_activity = raw_session["turns"][-1]["activity"]
    assert raw_activity["trace_ref"] == f"{session['id']}/run-1"
    assert raw_activity["tool_count"] == 1
    assert set(raw_activity) <= {
        "run_id",
        "trace_ref",
        "status",
        "summary",
        "activity_summary",
        "tool_count",
        "run_duration_ms",
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
        assert heavy_key not in raw_activity
    assert raw_session["turns"][-1]["answer_bundle"] == {}

    sidecar = json.loads((tmp_path / "runs" / session["id"] / "run-1.json").read_text(encoding="utf-8"))
    assert sidecar["activity"]["trace_events"][0]["id"] == "trace-1"
    assert sidecar["answer_bundle"]["summary"] == "done"
    assert sidecar["tool_events"][0]["name"] == "read_file"
    assert sidecar["task_state"]["current_step_id"] == "step-2"
    assert sidecar["task_state_delta"]["step_updates"][0]["step_id"] == "step-1"
    assert sidecar["task_state_validation"]["accepted"] is True

    summary_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="summary")
    assert summary_turn["answer_bundle"] == {}
    assert "trace_events" not in summary_turn["activity"]
    assert "model_draft" not in summary_turn["activity"]
    assert "runtime_error" not in summary_turn["activity"]

    full_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="full")
    assert full_turn["answer_bundle"]["summary"] == "done"
    assert full_turn["activity"]["full_loaded"] is True
    assert full_turn["activity"]["trace_events"][0]["id"] == "trace-1"
    assert full_turn["activity"]["llm_exchanges"][0]["round"] == 1
    assert full_turn["activity"]["model_draft"] == "draft"
    assert full_turn["activity"]["runtime_error"]["kind"] == "debug"
    assert full_turn["run_artifact"]["inspector"]["run_state"]["turn_status"] == "completed"
    assert full_turn["run_artifact"]["task_state"]["current_step_id"] == "step-2"
    assert full_turn["run_artifact"]["task_state_delta"]["step_updates"][0]["step_id"] == "step-1"
    assert full_turn["run_artifact"]["task_state_validation"]["accepted"] is True


def test_expand_turn_summary_does_not_load_run_artifact(monkeypatch, tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("summary view should not load run artifacts")

    monkeypatch.setattr(store.run_artifact_store, "load_by_ref", _boom)
    monkeypatch.setattr(store.run_artifact_store, "load", _boom)

    summary_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="summary")

    assert summary_turn["activity"] == raw_session["turns"][-1]["activity"]
    assert summary_turn["answer_bundle"] == {}
    assert summary_turn["run_artifact"] == {}


def test_expand_turn_full_loads_run_artifact(monkeypatch, tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    calls = {"load": 0, "load_by_ref": 0}
    original_load = store.run_artifact_store.load
    original_load_by_ref = store.run_artifact_store.load_by_ref

    def _load_by_ref(trace_ref: str):
        calls["load_by_ref"] += 1
        return original_load_by_ref(trace_ref)

    def _load(*, session_id: str, run_id: str):
        calls["load"] += 1
        return original_load(session_id=session_id, run_id=run_id)

    monkeypatch.setattr(store.run_artifact_store, "load_by_ref", _load_by_ref)
    monkeypatch.setattr(store.run_artifact_store, "load", _load)

    full_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="full")

    assert calls["load_by_ref"] == 1
    assert calls["load"] == 1
    assert full_turn["answer_bundle"]["summary"] == "done"
    assert full_turn["run_artifact"]["run_id"] == "run-1"


def test_session_load_backfills_missing_light_activity_from_sidecar_once(monkeypatch, tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["turns"][-1]["activity"] = {
        "run_id": raw_session["turns"][-1]["activity"]["run_id"],
        "trace_ref": raw_session["turns"][-1]["activity"]["trace_ref"],
    }
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = store.load(session["id"], default_project=_project(tmp_path))

    assert loaded is not None
    restored_activity = loaded["turns"][-1]["activity"]
    assert restored_activity["status"] == "completed"
    assert restored_activity["tool_count"] == 1
    assert restored_activity["summary"] == "read and answered"
    assert restored_activity["activity_summary"] == "read and answered"

    persisted = json.loads(session_path.read_text(encoding="utf-8"))
    assert persisted["turns"][-1]["activity"] == restored_activity

    def _boom(*args, **kwargs):
        raise AssertionError("backfilled summary activity should not reload run artifacts")

    monkeypatch.setattr(store.run_artifact_store, "load_by_ref", _boom)
    monkeypatch.setattr(store.run_artifact_store, "load", _boom)

    reloaded = store.load(session["id"], default_project=_project(tmp_path))
    assert reloaded is not None
    assert reloaded["turns"][-1]["activity"] == restored_activity


def test_rebuild_metadata_index_backfills_missing_light_activity(tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["turns"][-1]["activity"] = {
        "run_id": raw_session["turns"][-1]["activity"]["run_id"],
        "trace_ref": raw_session["turns"][-1]["activity"]["trace_ref"],
    }
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rebuilt = store.rebuild_metadata_index(default_project=_project(tmp_path))

    assert rebuilt == 1
    persisted = json.loads(session_path.read_text(encoding="utf-8"))
    assert persisted["turns"][-1]["activity"]["status"] == "completed"
    assert persisted["turns"][-1]["activity"]["tool_count"] == 1


def test_repair_sessions_reuses_backfill_and_is_idempotent(tmp_path: Path) -> None:
    store, session, raw_session = _build_sidecar_session(tmp_path)
    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["turns"][-1]["activity"] = {
        "run_id": raw_session["turns"][-1]["activity"]["run_id"],
        "trace_ref": raw_session["turns"][-1]["activity"]["trace_ref"],
    }
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    first = store.repair_sessions(default_project=_project(tmp_path))
    assert first["scanned_sessions"] == 1
    assert first["migrated_sessions"] == 1
    assert first["backfilled_turns"] == 1
    assert first["rebuilt_meta"] == 1
    assert first["errors"] == []

    repaired = json.loads(session_path.read_text(encoding="utf-8"))
    assert repaired["turns"][-1]["activity"]["status"] == "completed"
    assert repaired["turns"][-1]["activity"]["tool_count"] == 1

    second = store.repair_sessions(default_project=_project(tmp_path))
    assert second["scanned_sessions"] == 1
    assert second["migrated_sessions"] == 0
    assert second["backfilled_turns"] == 0
    assert second["skipped"] == 1
    assert second["errors"] == []


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


def test_session_load_migrates_derived_top_level_memory_fields(tmp_path: Path) -> None:
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
    assert loaded["thread_memory"]["recent_tasks"][0]["task_id"] == "legacy-task"
    assert loaded["artifact_memory"][0]["artifact_id"] == "legacy-artifact"
    assert loaded["compaction_state"]["generation"] == 2
    assert loaded["compaction_state"]["estimated_context_tokens"] == 1234

    persisted = json.loads(session_path.read_text(encoding="utf-8"))
    for key in ("recent_tasks", "artifact_memory_preview", "context_meter", "compaction_status"):
        assert key not in persisted
