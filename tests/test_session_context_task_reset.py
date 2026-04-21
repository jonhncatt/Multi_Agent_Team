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
                "last_completed_step": "read: app.py",
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


def test_recalled_attachment_prefers_matching_image_kind_over_latest_attachment() -> None:
    session = {
        "agent_state": {
            "current_task_focus": {
                "task_id": "task-mail",
                "goal": "解释邮件内容",
                "project_root": "/tmp/demo",
                "cwd": "/tmp/demo",
                "active_files": [],
                "active_attachments": [{"id": "mail-1", "name": "notice.msg", "kind": "document", "path": "/tmp/demo/notice.msg"}],
                "last_completed_step": "read: notice.msg",
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
                "source_tool": "read",
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

    assert resolved["effective_attachment_ids"] == ["img-1"]
    assert resolved["recalled_task"]["task_id"] == "task-image"
