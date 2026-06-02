from __future__ import annotations

from app.session_context import focus_from_work_cursor_task_state, merge_task_state_after_turn


def test_task_state_completed_step_uses_plan_step_with_tool_evidence() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-1",
            "goal": "Implement lazy loading",
            "status": "in_progress",
            "plan_items": [
                {"step": "Inspect existing activity loading", "status": "in_progress"},
                {"step": "Patch lazy full endpoint usage", "status": "pending"},
            ],
        },
        [
            {"step": "Inspect existing activity loading", "status": "completed"},
            {"step": "Patch lazy full endpoint usage", "status": "in_progress"},
        ],
        [
            {
                "name": "read_file",
                "status": "ok",
                "summary": "Read app/static/app.js",
                "source_refs": ["/repo/app/static/app.js"],
            }
        ],
        [],
        "completed",
        {},
        {},
    )

    assert state["status"] == "in_progress"
    assert state["current_step_id"] == state["plan_items"][1]["id"]
    assert state["completed_steps"][-1]["step"] == "Inspect existing activity loading"
    assert state["completed_steps"][-1]["progress_basis"] == ["read_file: Read app/static/app.js"]
    assert state["completed_steps"][-1]["evidence_refs"][0]["tool"] == "read_file"
    assert state["completed_steps"][-1]["evidence_refs"][0]["ref"] == "/repo/app/static/app.js"

    focus = focus_from_work_cursor_task_state({"cwd": "/repo"}, state)
    assert focus["last_completed_step"] == "Inspect existing activity loading"
    assert focus["last_completed_step"] != "read_file: Read app/static/app.js"


def test_task_state_failed_tool_records_attempt_without_completing_step() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-2",
            "goal": "Fix tests",
            "status": "in_progress",
            "plan_items": [
                {"step": "Run focused tests", "status": "in_progress"},
                {"step": "Patch failures", "status": "pending"},
            ],
        },
        [
            {"step": "Run focused tests", "status": "in_progress"},
            {"step": "Patch failures", "status": "pending"},
        ],
        [
            {
                "name": "exec_command",
                "status": "error",
                "summary": "pytest failed",
                "source_refs": ["pytest.log"],
            }
        ],
        [],
        "failed",
        {"message": "Command failed", "traceback_tail": "raw traceback"},
        {},
    )

    assert state["status"] == "failed"
    assert state["current_step_id"] == state["plan_items"][0]["id"]
    assert state["completed_steps"] == []
    assert state["failed_attempts"][0]["tool"] == "exec_command"
    assert state["failed_attempts"][0]["summary"] == "pytest failed"
    assert state["failed_attempts"][0]["step_id"] == state["current_step_id"]
    assert state["blocked_reason"] == "Command failed"
    assert "traceback" not in state["blocked_reason"]
    assert state["next_required_action"] == "Run focused tests"
