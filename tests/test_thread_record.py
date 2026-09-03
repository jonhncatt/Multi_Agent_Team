from __future__ import annotations

import json
from pathlib import Path

from app.run_record import encode_run_record
from app.storage import SessionStore
from app.thread_record import encode_thread_record, project_turns_from_thread


THREAD_KEYS = {
    "thread_record_schema_version",
    "id",
    "created_at",
    "updated_at",
    "activity_at",
    "activity_revision",
    "activity_kind",
    "title",
    "auto_title",
    "title_generation",
    "pinned",
    "pin_updated_at",
    "project_id",
    "project_title",
    "project_root",
    "git_branch",
    "cwd",
    "thread_transcript",
    "thread_schema_version",
    "active_attachment_ids",
    "attachment_context_cleared",
    "compaction",
    "pending_interaction",
}


def test_thread_encoder_has_one_minimal_persistence_shape() -> None:
    encoded = encode_thread_record(
        {
            "id": "thread-1",
            "project_root": "/workspace",
            "thread_transcript": {
                "schema_version": 1,
                "items": [{"id": "u1", "role": "user", "content": "hello"}],
            },
            "active_attachment_ids": ["file-1"],
            "compaction_state": {
                "generation": 2,
                "compacted_history": "older context",
                "compacted_until_turn_id": "u1",
                "last_compacted_at": "2026-01-01T00:00:00Z",
                "context_meter": {"ratio": 0.9},
            },
            "agent_state": {"last_run_id": "run-1"},
            "task_state": {"goal": "must not persist"},
            "work_cursor": {"cwd": "/legacy"},
            "thread_memory": {"summary": "duplicate"},
            "turns": [{"id": "legacy", "role": "assistant", "text": "duplicate"}],
        }
    )

    assert set(encoded) == THREAD_KEYS
    assert encoded["cwd"] == "/workspace"
    assert encoded["compaction"] == {
        "generation": 2,
        "summary": "older context",
        "compacted_until_item_id": "u1",
        "compacted_at": "2026-01-01T00:00:00Z",
    }
    assert [item["content"] for item in encoded["thread_transcript"]["items"]] == ["hello"]


def test_old_session_auto_migrates_once_with_backup_and_keeps_chat(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_path = sessions_dir / "legacy-thread.json"
    legacy = {
        "thread_record_schema_version": 2,
        "id": "legacy-thread",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "title": "Existing chat",
        "project_id": "project-1",
        "project_title": "Project",
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "turns": [
            {"id": "u1", "role": "user", "text": "old question", "created_at": "2026-01-01T00:00:02Z"},
            {
                "id": "a1",
                "role": "assistant",
                "text": "old answer",
                "created_at": "2026-01-01T00:00:03Z",
                "activity": {"run_id": "run-old", "status": "completed"},
            },
        ],
        "context_manager": {"working_summary": "older summarized chat"},
        "compaction_state": {
            "generation": 1,
            "compacted_until_turn_id": "u1",
            "last_compacted_at": "2026-01-01T00:01:00Z",
        },
        "agent_state": {
            "last_run_id": "run-old",
            "pending_turn": {"type": "request_user_input", "turn_id": "turn-pending"},
            "pending_user_input": {"summary": "Choose one"},
        },
        "task_state": {"plan_items": [{"step": "Wait for choice", "status": "in_progress"}]},
        "thread_memory": {"summary": "legacy duplicate"},
        "work_cursor": {
            "cwd": str(tmp_path),
            "active_attachments": [{"id": "attachment-1", "name": "spec.pdf"}],
        },
    }
    session_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")

    store = SessionStore(sessions_dir)
    loaded = store.load("legacy-thread")

    assert loaded is not None
    assert [item["text"] for item in loaded["turns"][:2]] == ["old question", "old answer"]
    assert loaded["active_attachment_ids"] == ["attachment-1"]
    assert loaded["compaction"]["summary"] == "older summarized chat"
    assert loaded["pending_interaction"]["turn"]["turn_id"] == "turn-pending"
    assert loaded["pending_interaction"]["turn"]["plan"][0]["step"] == "Wait for choice"

    backup_path = tmp_path / "session_backups" / "legacy-thread.v2.json"
    assert json.loads(backup_path.read_text(encoding="utf-8")) == legacy
    backup_bytes = backup_path.read_bytes()
    persisted_once = session_path.read_bytes()
    persisted = json.loads(persisted_once)
    assert set(persisted) == THREAD_KEYS
    assert persisted["thread_record_schema_version"] == 6
    assert [item["content"] for item in persisted["thread_transcript"]["items"]] == [
        "old question",
        "old answer",
    ]

    reloaded = store.load("legacy-thread")
    assert reloaded is not None
    assert session_path.read_bytes() == persisted_once
    assert backup_path.read_bytes() == backup_bytes


def test_run_encoder_keeps_one_status_and_no_thread_semantic_state() -> None:
    encoded = encode_run_record(
        {
            "session_id": "thread-1",
            "run_id": "run-1",
            "turn_status": "needs_user_input",
            "activity": {
                "status": "blocked",
                "run_duration_ms": 42,
                "plan": [{"step": "Ask", "status": "in_progress"}],
                "trace_events": [{"type": "tool.started"}],
                "live_items": [{"type": "toolCall", "status": "inProgress"}],
            },
            "task_state": {"goal": "duplicate"},
            "work_cursor": {"cwd": "/duplicate"},
            "current_task_focus": {"goal": "duplicate"},
            "inspector": {"run_state": {"task_state": {"goal": "duplicate"}, "phase": "execute"}},
        }
    )

    assert encoded["status"] == "waiting_user"
    assert encoded["duration_ms"] == 42
    assert encoded["details"]["plan"][0]["step"] == "Ask"
    assert encoded["events"] == [{"type": "tool.started"}]
    assert encoded["items"] == [{"type": "toolCall", "status": "inProgress"}]
    for key in ("turn_status", "activity", "task_state", "work_cursor", "current_task_focus", "trace_events", "live_items"):
        assert key not in encoded
    assert encoded["debug"]["inspector"]["run_state"] == {"phase": "execute"}


def test_model_only_subagent_mailbox_item_is_persisted_but_hidden_from_ui_turns() -> None:
    session = {
        "thread_transcript": {
            "schema_version": 1,
            "items": [
                {"id": "u1", "role": "user", "content": "start"},
                {"id": "a1", "role": "assistant", "content": "parent done"},
                {
                    "id": "subagent-result-1",
                    "role": "user",
                    "content": "[background_subagent_result]late finding[/background_subagent_result]",
                    "model_only": True,
                },
            ],
        }
    }

    encoded = encode_thread_record(session)

    assert encoded["thread_transcript"]["items"][-1]["model_only"] is True
    assert [turn["text"] for turn in project_turns_from_thread(encoded)] == ["start", "parent done"]


def test_ui_only_user_input_response_is_persisted_and_visible_in_ui_turns() -> None:
    session = {
        "thread_transcript": {
            "schema_version": 3,
            "items": [
                {"id": "u1", "role": "user", "content": "Prepare the report."},
                {
                    "id": "choice",
                    "role": "user",
                    "content": "Markdown",
                    "ui_only": True,
                },
                {"id": "a1", "role": "assistant", "content": "Done."},
            ],
        }
    }

    encoded = encode_thread_record(session)

    assert encoded["thread_transcript"]["items"][1]["ui_only"] is True
    assert [turn["text"] for turn in project_turns_from_thread(encoded)] == [
        "Prepare the report.",
        "Markdown",
        "Done.",
    ]
