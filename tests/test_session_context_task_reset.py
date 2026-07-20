from __future__ import annotations

from app import session_context


def _session_with_checkpoint() -> dict[str, object]:
    return {
        "agent_state": {
            "task_checkpoint": {
                "task_id": "task-1",
                "goal": "Inspect current code",
                "project_root": "/tmp/demo",
                "cwd": "/tmp/demo",
                "active_files": ["/tmp/demo/app.py"],
                "active_attachments": [],
                "last_completed_step": "read_file: app.py",
                "next_action": "patch app.py",
            }
        },
        "route_state": {},
    }


def test_should_start_new_task_for_explicit_new_request() -> None:
    session = _session_with_checkpoint()

    assert session_context.should_start_new_task(session, message="另外帮我看个新问题", requested_attachment_ids=[]) is True


def test_should_not_start_new_task_for_current_folder_followup() -> None:
    session = _session_with_checkpoint()

    assert session_context.should_start_new_task(session, message="就在当前文件夹", requested_attachment_ids=[]) is False


def test_should_not_start_new_task_for_short_modify_followup_when_active_file_exists() -> None:
    session = _session_with_checkpoint()

    assert session_context.should_start_new_task(session, message="修一下", requested_attachment_ids=[]) is False


def test_should_not_start_new_task_for_short_file_target_followup() -> None:
    session = _session_with_checkpoint()

    assert session_context.should_start_new_task(session, message="修改 app.py", requested_attachment_ids=[]) is False


def test_should_start_new_task_when_new_attachment_arrives_without_followup_language() -> None:
    session = _session_with_checkpoint()

    assert session_context.should_start_new_task(session, message="解释图片内容", requested_attachment_ids=["img-2"]) is True


def test_message_requests_latest_user_question_is_detected() -> None:
    assert session_context.message_requests_task_recall("我刚刚问你什么了") is True
    assert session_context.message_requests_latest_user_question("我刚刚问你什么了") is True


def test_derive_current_turn_context_classifies_subject_followup_after_email() -> None:
    session = _session_with_checkpoint()
    session["turns"] = [
        {"role": "user", "text": "帮我写个请假邮件"},
        {"role": "assistant", "text": "当然，下面是一封请假邮件。"},
    ]
    session["agent_state"]["task_checkpoint"]["goal"] = "帮我写个请假邮件"

    current_turn = session_context.derive_current_turn_context(
        session,
        message="题目",
        history_turns=session["turns"],
    )

    assert current_turn["followup_type"] == "subject_request"
    assert current_turn["goal"] == "Provide only a subject/title for the previous email or draft."
    assert current_turn["recent_user_messages"] == ["帮我写个请假邮件"]


def test_derive_current_turn_context_uses_recent_user_history_for_recall() -> None:
    session = _session_with_checkpoint()
    session["turns"] = [
        {"role": "user", "text": "帮我写个请假邮件"},
        {"role": "assistant", "text": "邮件正文"},
        {"role": "user", "text": "题目"},
        {"role": "assistant", "text": "件名：明日の検査に伴う休暇取得のお願い"},
    ]

    current_turn = session_context.derive_current_turn_context(
        session,
        message="我刚刚问你什么了",
        history_turns=session["turns"],
    )

    assert current_turn["followup_type"] == "recent_user_message_recall"
    assert current_turn["goal"] == "Answer what the previous user message was in this thread."
    assert current_turn["recent_user_messages"] == ["帮我写个请假邮件", "题目"]


def test_attachment_context_uses_explicit_sticky_ids_without_semantic_recall() -> None:
    session = {
        "agent_state": {
            "current_task_focus": {
                "task_id": "task-mail",
                "goal": "解释邮件内容",
                "project_root": "/tmp/demo",
                "cwd": "/tmp/demo",
                "active_files": [],
                "active_attachments": [{"id": "mail-1", "name": "notice.msg", "kind": "document", "path": "/tmp/demo/notice.msg"}],
                "last_completed_step": "read_file: notice.msg",
                "next_action": "",
            }
        },
        "active_attachment_ids": ["mail-1"],
        "artifact_memory": [
            {
                "artifact_id": "mail-1",
                "kind": "document",
                "name": "notice.msg",
                "path": "/tmp/demo/notice.msg",
                "mime": "application/vnd.ms-outlook",
                "turn_id": "turn-mail",
                "source_tool": "read_file",
                "summary_digest": "邮件摘要",
                "created_at": "2026-04-21T00:00:02Z",
            },
            {
                "artifact_id": "img-1",
                "kind": "image",
                "name": "screen.png",
                "path": "/tmp/demo/screen.png",
                "mime": "image/png",
                "turn_id": "turn-image",
                "source_tool": "image_read",
                "summary_digest": "图片摘要",
                "created_at": "2026-04-21T00:00:01Z",
            },
        ],
        "thread_memory": {
            "recent_tasks": [
                {
                    "task_id": "task-mail",
                    "turn_id": "turn-mail",
                    "user_request": "解释邮件内容",
                    "goal": "解释邮件内容",
                    "cwd": "/tmp/demo",
                    "artifact_refs": ["mail-1"],
                    "active_files": [],
                    "result_digest": "邮件摘要",
                    "updated_at": "2026-04-21T00:00:02Z",
                },
                {
                    "task_id": "task-image",
                    "turn_id": "turn-image",
                    "user_request": "解释图片内容",
                    "goal": "解释图片内容",
                    "cwd": "/tmp/demo",
                    "artifact_refs": ["img-1"],
                    "active_files": [],
                    "result_digest": "图片摘要",
                    "updated_at": "2026-04-21T00:00:01Z",
                },
            ],
        },
    }

    resolved = session_context.resolve_attachment_context(session, message="我之前让你解释的图片内容，你还记得吗？", requested_attachment_ids=[])

    assert resolved["effective_attachment_ids"] == ["mail-1"]
    assert resolved["auto_linked_attachment_ids"] == ["mail-1"]
    assert resolved["recalled_artifacts"] == []
    assert resolved["recalled_task"] == {}
