from __future__ import annotations

from app.session_context import (
    focus_from_work_cursor_task_state,
    merge_task_state_after_turn,
    merge_task_state_delta,
    normalize_task_plan_items,
)


def test_completed_steps_are_derived_from_completed_plan_items() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-1",
            "goal": "Create and run a script",
            "status": "in_progress",
            "plan_items": [
                {"step": "创建 Python 脚本，内容是 print(1+1)", "status": "in_progress"},
                {"step": "执行脚本并确认输出", "status": "pending"},
            ],
        },
        [
            {"step": "创建 Python 脚本，内容是 print(1+1)", "status": "completed"},
            {"step": "执行脚本并确认输出", "status": "completed"},
        ],
        [],
        [],
        "completed",
        {},
        {},
    )

    assert state["status"] == "completed"
    assert [item["step"] for item in state["completed_steps"]] == [
        "创建 Python 脚本，内容是 print(1+1)",
        "执行脚本并确认输出",
    ]


def test_completed_step_focus_uses_latest_plan_step() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-2",
            "goal": "Inspect and patch",
            "status": "in_progress",
            "plan_items": [
                {"step": "Inspect current implementation", "status": "completed"},
                {"step": "Patch task_state merge path", "status": "completed"},
            ],
        },
        [
            {"step": "Inspect current implementation", "status": "completed"},
            {"step": "Patch task_state merge path", "status": "completed"},
        ],
        [],
        [],
        "completed",
        {},
        {},
    )

    focus = focus_from_work_cursor_task_state({"cwd": "/repo"}, state)
    assert focus["last_completed_step"] == "Patch task_state merge path"


def test_task_state_delta_ignores_step_updates_and_keeps_plan_as_source_of_truth() -> None:
    previous = {
        "task_id": "task-3",
        "goal": "Mark two steps complete",
        "status": "in_progress",
        "plan_items": [
            {"step": "创建 Python 脚本，内容是 print(1+1)", "status": "in_progress"},
            {"step": "执行脚本并确认输出", "status": "pending"},
        ],
    }
    completed_plan = [
        {"step": "创建 Python 脚本，内容是 print(1+1)", "status": "completed"},
        {"step": "执行脚本并确认输出", "status": "completed"},
    ]

    state, validation = merge_task_state_delta(
        previous,
        completed_plan,
        {
            "step_updates": [
                {"step_id": "创建 Python 脚本，内容是 print(1+1)", "status": "completed"},
                {"step_id": "执行脚本并确认输出", "status": "completed"},
            ],
            "progress_basis": ["脚本已创建并成功执行，输出为 2"],
            "evidence_refs": [
                {"tool": "exec_command", "ref": "session_id: 1"},
                {"tool": "exec_command", "ref": "session_id: 2"},
            ],
        },
        [],
        "completed",
        {},
        {},
    )

    assert validation == {}
    assert state["status"] == "completed"
    assert [item["status"] for item in state["plan_items"]] == ["completed", "completed"]
    assert [item["step"] for item in state["completed_steps"]] == [
        "创建 Python 脚本，内容是 print(1+1)",
        "执行脚本并确认输出",
    ]
    assert state["validation_warnings"] == []
    assert state["progress_basis"] == ["脚本已创建并成功执行，输出为 2"]


def test_task_state_delta_can_merge_supplemental_runtime_metadata() -> None:
    previous = {
        "task_id": "task-4",
        "goal": "Run focused tests",
        "status": "in_progress",
        "plan_items": [{"step": "运行测试", "status": "in_progress"}],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    step_id = normalize_task_plan_items(previous["plan_items"])[0]["id"]

    state, validation = merge_task_state_delta(
        baseline,
        previous["plan_items"],
        {
            "current_step_id": step_id,
            "status": "blocked",
            "blocked_reason": "pytest failed",
            "next_required_action": "查看 pytest 输出并修复失败",
            "failed_attempts": [
                {
                    "tool": "exec_command",
                    "summary": "pytest failed",
                    "step_id": step_id,
                    "evidence_refs": [{"tool": "exec_command", "ref": "pytest.log"}],
                }
            ],
        },
        [],
        "blocked",
        {"message": "pytest failed"},
        {},
    )

    assert validation == {}
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "pytest failed"
    assert state["next_required_action"] == "查看 pytest 输出并修复失败"
    assert state["failed_attempts"][0]["summary"] == "pytest failed"
    assert state["validation_warnings"] == []


def test_update_plan_validation_error_does_not_pollute_failed_attempts_or_warnings() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-5",
            "goal": "Fix update_plan schema",
            "status": "in_progress",
            "plan_items": [{"step": "Align update_plan schema", "status": "in_progress"}],
        },
        [{"step": "Align update_plan schema", "status": "in_progress"}],
        [
            {
                "name": "update_plan",
                "status": "blocked",
                "summary": "update_plan `plan` must be a non-empty list.",
            }
        ],
        [],
        "running",
        {},
        {},
    )

    assert state["failed_attempts"] == []
    assert state["validation_warnings"] == []
