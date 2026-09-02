from __future__ import annotations

from pathlib import Path

from app.storage import SessionStore
from app.thread_transcript import (
    append_transcript_item,
    append_transcript_items,
    default_thread_transcript,
    migrate_session_to_thread_transcript,
    normalize_thread_transcript,
    pending_tool_calls,
    transcript_items_after_compaction,
)


def test_legacy_turns_migrate_to_typed_transcript_idempotently() -> None:
    legacy = {
        "id": "session-1",
        "turns": [
            {"id": "u1", "role": "user", "text": "帮我写代码", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "a1", "role": "assistant", "text": "先看规格", "created_at": "2026-01-01T00:00:01Z"},
        ],
    }

    migrated, changed = migrate_session_to_thread_transcript(legacy)
    migrated_again, changed_again = migrate_session_to_thread_transcript(migrated)

    assert changed is True
    assert changed_again is False
    assert migrated_again["thread_transcript"]["items"] == [
        {
            "id": "u1",
            "role": "user",
            "content": "帮我写代码",
            "created_at": "2026-01-01T00:00:00Z",
            "turn_id": "u1",
        },
        {
            "id": "a1",
            "role": "assistant",
            "content": "先看规格",
            "created_at": "2026-01-01T00:00:01Z",
            "turn_id": "a1",
        },
    ]


def test_transcript_preserves_assistant_tool_call_and_tool_result() -> None:
    transcript = default_thread_transcript()
    append_transcript_item(transcript, role="user", content="运行测试", item_id="u1")
    append_transcript_item(
        transcript,
        role="assistant",
        content="",
        item_id="a-tool",
        tool_calls=[{"id": "call-1", "name": "exec_command", "args": {"cmd": "pytest"}}],
    )
    append_transcript_item(
        transcript,
        role="tool",
        content='{"ok":true}',
        item_id="t1",
        tool_call_id="call-1",
        name="exec_command",
    )

    items = normalize_thread_transcript(transcript)["items"]
    assert [item["role"] for item in items] == ["user", "assistant", "tool"]
    assert items[1]["tool_calls"][0]["args"] == {"cmd": "pytest"}
    assert items[2]["tool_call_id"] == "call-1"


def test_transcript_defers_background_message_until_parallel_tool_batch_closes() -> None:
    transcript = default_thread_transcript()
    calls = [
        {"id": f"call-{index}", "name": "read_file", "args": {"path": f"{index}.txt"}}
        for index in range(1, 6)
    ]
    append_transcript_item(
        transcript,
        role="assistant",
        content="",
        item_id="assistant-tools",
        tool_calls=calls,
    )
    append_transcript_items(
        transcript,
        [
            {
                "role": "tool",
                "content": "ok",
                "tool_call_id": f"call-{index}",
                "name": "read_file",
            }
            for index in range(1, 5)
        ],
    )
    append_transcript_item(
        transcript,
        role="user",
        content="[background_subagent_result]late[/background_subagent_result]",
        item_id="late-subagent",
    )

    assert [call["id"] for call in pending_tool_calls(transcript)] == ["call-5"]
    assert [item["id"] for item in transcript["deferred_items"]] == ["late-subagent"]
    assert all(item["id"] != "late-subagent" for item in transcript["items"])

    append_transcript_item(
        transcript,
        role="tool",
        content="approved",
        item_id="approved-tool",
        tool_call_id="call-5",
        name="read_file",
    )

    assert pending_tool_calls(transcript) == []
    assert transcript["deferred_items"] == []
    assert [item["role"] for item in transcript["items"]] == [
        "assistant",
        "tool",
        "tool",
        "tool",
        "tool",
        "tool",
        "user",
    ]
    assert transcript["items"][-1]["id"] == "late-subagent"


def test_normalization_repairs_interleaved_legacy_tool_transaction() -> None:
    normalized = normalize_thread_transcript(
        {
            "schema_version": 2,
            "items": [
                {
                    "id": "assistant-tools",
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call-1", "name": "read_file", "args": {}},
                        {"id": "call-2", "name": "exec_command", "args": {}},
                    ],
                },
                {"id": "tool-1", "role": "tool", "content": "ok", "tool_call_id": "call-1"},
                {"id": "late", "role": "user", "content": "late result", "model_only": True},
                {"id": "tool-2", "role": "tool", "content": "ok", "tool_call_id": "call-2"},
                {"id": "next", "role": "user", "content": "next message"},
            ],
        }
    )

    assert normalized["deferred_items"] == []
    assert [item["id"] for item in normalized["items"]] == [
        "assistant-tools",
        "tool-1",
        "tool-2",
        "late",
        "next",
    ]


def test_duplicate_tool_result_is_idempotent() -> None:
    transcript = default_thread_transcript()
    append_transcript_item(
        transcript,
        role="assistant",
        content="",
        tool_calls=[{"id": "call-1", "name": "exec_command", "args": {}}],
    )
    result = {
        "role": "tool",
        "content": "done",
        "tool_call_id": "call-1",
        "name": "exec_command",
    }
    append_transcript_items(transcript, [result, result])

    assert len([item for item in transcript["items"] if item["role"] == "tool"]) == 1


def test_transcript_preserves_bounded_turn_change_summary() -> None:
    transcript = {
        "schema_version": 2,
        "items": [
            {
                "id": "a1",
                "role": "assistant",
                "content": "done",
                "trace": {
                    "trace_ref": "turn_traces/thread-1/turn-1",
                    "status": "completed",
                    "turn_changes": {
                        "files": [
                            {"path": "app/main.py", "kind": "modified"},
                            {"path": "app/main.py", "kind": "modified"},
                            {"path": "tests/test_main.py", "kind": "modified"},
                        ],
                        "count": 2,
                        "verification": {
                            "status": "passed",
                            "tool": "exec_command",
                            "summary": "2 passed",
                        },
                    },
                },
            }
        ],
    }

    [assistant] = normalize_thread_transcript(transcript)["items"]

    assert assistant["trace"]["turn_changes"] == {
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


def test_user_turn_preserves_hidden_task_context_without_changing_visible_text(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(
        {"project_id": "p1", "title": "Project", "root_path": str(tmp_path), "git_branch": "main"}
    )
    task_context = {
        "task_id": "task-1",
        "title": "Resume auth refactor",
        "goal": "Finish the auth refactor",
        "next_steps": ["Update login form"],
    }

    store.append_turn(
        session,
        role="user",
        text="加载当前任务",
        task_context=task_context,
    )
    store.save(session)
    reloaded = store.load(str(session["id"]))

    assert reloaded is not None
    [item] = reloaded["thread_transcript"]["items"]
    assert item["content"] == "加载当前任务"
    assert item["task_context"] == task_context
    assert reloaded["turns"][0]["text"] == "加载当前任务"


def test_compaction_summary_replaces_only_older_transcript_items() -> None:
    transcript = default_thread_transcript()
    append_transcript_item(transcript, role="user", content="old user", item_id="u1", turn_id="u1")
    append_transcript_item(transcript, role="assistant", content="old answer", item_id="a1", turn_id="a1")
    append_transcript_item(transcript, role="user", content="new user", item_id="u2", turn_id="u2")

    summary, items = transcript_items_after_compaction(
        transcript,
        {"compacted_history": "older exchange summary", "compacted_until_turn_id": "a1"},
    )

    assert summary == "older exchange summary"
    assert [item["id"] for item in items] == ["u2"]


def test_session_store_keeps_ui_turns_as_projection_and_transcript_as_model_history(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(
        {"project_id": "p1", "title": "Project", "root_path": str(tmp_path), "git_branch": "main"}
    )
    assert "context_manager" not in session
    user_turn = store.append_turn(session, role="user", text="hello")
    store.append_thread_items(
        session,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "read_file", "args": {"path": "README.md"}}],
            },
            {"role": "tool", "content": "read ok", "tool_call_id": "c1", "name": "read_file"},
        ],
    )
    assistant_turn = store.append_turn(session, role="assistant", text="done")
    store.save(session)
    reloaded = store.load(str(session["id"]))

    assert reloaded is not None
    assert [turn["id"] for turn in reloaded["turns"]] == [user_turn["id"], assistant_turn["id"]]
    assert [item["role"] for item in reloaded["thread_transcript"]["items"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


def test_session_store_preserves_unique_client_turn_id_and_rejects_collision(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(
        {"project_id": "p1", "title": "Project", "root_path": str(tmp_path), "git_branch": "main"}
    )

    first = store.append_turn(session, role="user", text="hi", turn_id="client-message-1")
    second = store.append_turn(session, role="user", text="again", turn_id="client-message-1")

    assert first["id"] == "client-message-1"
    assert second["id"] != "client-message-1"
    assert len({first["id"], second["id"]}) == 2
    assert [item["id"] for item in session["thread_transcript"]["items"]] == [
        first["id"],
        second["id"],
    ]


def test_existing_thread_transcript_wins_over_legacy_turn_projection() -> None:
    normalized = normalize_thread_transcript(
        {
            "schema_version": 1,
            "items": [{"id": "u1", "role": "user", "content": "canonical"}],
        },
        legacy_turns=[{"id": "u-old", "role": "user", "text": "projection"}],
    )

    assert [item["content"] for item in normalized["items"]] == ["canonical"]


def test_older_context_manager_only_session_migrates_history_and_summary() -> None:
    migrated, changed = migrate_session_to_thread_transcript(
        {
            "id": "old-context-only",
            "context_manager": {
                "schema_version": 2,
                "working_summary": "更早的对话已经完成规格梳理。",
                "recent_turns": [
                    {"role": "user", "text": "继续实现"},
                    {"role": "assistant", "text": "我先读取目标文件。"},
                ],
            },
        }
    )

    summary, items = transcript_items_after_compaction(
        migrated["thread_transcript"],
        migrated["compaction_state"],
    )
    assert changed is True
    assert summary == "更早的对话已经完成规格梳理。"
    assert [item["content"] for item in items] == ["继续实现", "我先读取目标文件。"]


def test_history_turns_only_session_migrates_without_context_manager() -> None:
    migrated, changed = migrate_session_to_thread_transcript(
        {
            "history_turns": [
                {"role": "user", "content": "legacy question"},
                {"role": "assistant", "content": "legacy answer"},
            ]
        }
    )

    assert changed is True
    assert [item["content"] for item in migrated["thread_transcript"]["items"]] == [
        "legacy question",
        "legacy answer",
    ]
