from __future__ import annotations

from app.session_context import focus_from_work_cursor_task_state, merge_task_state_after_turn, merge_task_state_delta


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


def test_task_state_delta_completes_modify_step_only_with_modify_evidence() -> None:
    previous = {
        "task_id": "task-delta-1",
        "goal": "Patch validator",
        "status": "in_progress",
        "plan_items": [
            {"step": "Patch task_state merge", "status": "in_progress"},
            {"step": "Run focused tests", "status": "pending"},
        ],
    }
    plan_items = list(previous["plan_items"])
    first_id = merge_task_state_after_turn(previous, plan_items, [], [], "running", {}, {})["plan_items"][0]["id"]
    second_id = merge_task_state_after_turn(previous, plan_items, [], [], "running", {}, {})["plan_items"][1]["id"]

    state, validation = merge_task_state_delta(
        previous,
        plan_items,
        {
            "step_updates": [
                {
                    "step_id": first_id,
                    "status": "completed",
                    "progress_basis": ["apply_patch: updated app/session_context.py"],
                    "evidence_refs": [{"tool": "apply_patch", "ref": "app/session_context.py"}],
                }
            ],
            "next_required_action": "Run focused tests",
        },
        [
            {
                "name": "apply_patch",
                "status": "ok",
                "summary": "Patched app/session_context.py",
                "source_refs": ["app/session_context.py"],
                "result_preview": {"files": ["app/session_context.py"]},
            }
        ],
        "completed",
        {},
        {},
    )

    assert validation["accepted"] is True
    assert state["plan_items"][0]["status"] == "completed"
    assert state["completed_steps"][-1]["id"] == first_id
    assert state["current_step_id"] == second_id
    assert state["next_required_action"] == "Run focused tests"


def test_task_state_delta_rejects_read_only_evidence_for_modify_step() -> None:
    previous = {
        "task_id": "task-delta-2",
        "goal": "Patch validator",
        "status": "in_progress",
        "plan_items": [{"step": "Patch task_state merge", "status": "in_progress"}],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    step_id = baseline["plan_items"][0]["id"]

    state, validation = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "step_updates": [
                {
                    "step_id": step_id,
                    "status": "completed",
                    "evidence_refs": [{"tool": "read_file", "ref": "app/session_context.py"}],
                }
            ]
        },
        [
            {
                "name": "read_file",
                "status": "ok",
                "summary": "Read app/session_context.py",
                "source_refs": ["app/session_context.py"],
            }
        ],
        "completed",
        {},
        {},
    )

    assert state["plan_items"][0]["status"] == "in_progress"
    assert state["completed_steps"] == []
    assert validation["rejected_step_ids"] == [step_id]
    assert validation["validation_warnings"][0]["code"] == "insufficient_modify_evidence"


def test_task_state_delta_rejects_non_test_evidence_for_verify_step() -> None:
    previous = {
        "task_id": "task-delta-3",
        "goal": "Verify patch",
        "status": "in_progress",
        "plan_items": [{"step": "Run focused tests", "status": "in_progress"}],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    step_id = baseline["plan_items"][0]["id"]

    state, validation = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "step_updates": [
                {
                    "step_id": step_id,
                    "status": "completed",
                    "evidence_refs": [{"tool": "read_file", "ref": "tests/test_task_state_progression.py"}],
                }
            ]
        },
        [
            {
                "name": "read_file",
                "status": "ok",
                "summary": "Read tests/test_task_state_progression.py",
                "source_refs": ["tests/test_task_state_progression.py"],
            }
        ],
        "completed",
        {},
        {},
    )

    assert state["plan_items"][0]["status"] == "in_progress"
    assert state["completed_steps"] == []
    assert validation["validation_warnings"][0]["code"] == "insufficient_verify_evidence"


def test_task_state_delta_failed_test_evidence_creates_failed_attempt() -> None:
    previous = {
        "task_id": "task-delta-4",
        "goal": "Run focused tests",
        "status": "in_progress",
        "plan_items": [{"step": "Run focused tests", "status": "in_progress"}],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    step_id = baseline["plan_items"][0]["id"]

    state, validation = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "status": "blocked",
            "blocked_reason": "pytest failed",
            "step_updates": [
                {
                    "step_id": step_id,
                    "status": "blocked",
                    "summary": "pytest failed",
                    "evidence_refs": [{"tool": "exec_command", "cmd": "pytest"}],
                }
            ],
        },
        [
            {
                "name": "exec_command",
                "status": "error",
                "summary": "pytest failed",
                "source_refs": ["pytest.log"],
                "normalized_arguments": {"cmd": "pytest -q"},
                "diagnostics": {"returncode": 1},
            }
        ],
        "blocked",
        {},
        {},
    )

    assert validation["accepted"] is True
    assert state["status"] == "blocked"
    assert state["plan_items"][0]["status"] == "blocked"
    assert state["failed_attempts"][0]["summary"] == "pytest failed"
    assert state["blocked_reason"] == "pytest failed"


def test_task_state_delta_rejects_unknown_step_id() -> None:
    previous = {
        "task_id": "task-delta-5",
        "goal": "Run focused tests",
        "status": "in_progress",
        "plan_items": [{"step": "Run focused tests", "status": "in_progress"}],
    }

    state, validation = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "step_updates": [
                {
                    "step_id": "step-missing",
                    "status": "completed",
                    "evidence_refs": [{"tool": "exec_command", "cmd": "pytest"}],
                }
            ]
        },
        [],
        "completed",
        {},
        {},
    )

    assert state["completed_steps"] == []
    assert validation["rejected_step_ids"] == ["step-missing"]
    assert validation["validation_warnings"][0]["code"] == "unknown_step_id"


def test_task_state_delta_preserves_prior_completed_steps() -> None:
    previous = {
        "task_id": "task-delta-6",
        "goal": "Patch and verify",
        "status": "in_progress",
        "plan_items": [
            {"step": "Inspect current implementation", "status": "completed"},
            {"step": "Patch task_state merge", "status": "in_progress"},
        ],
        "completed_steps": [
            {
                "id": "step-old",
                "step": "Inspect current implementation",
                "completed_at": "2026-06-01T00:00:00Z",
                "progress_basis": ["read_file: app/session_context.py"],
                "evidence_refs": [{"tool": "read_file", "ref": "app/session_context.py"}],
            }
        ],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    new_step_id = baseline["plan_items"][1]["id"]

    state, _ = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "step_updates": [
                {
                    "step_id": new_step_id,
                    "status": "completed",
                    "evidence_refs": [{"tool": "apply_patch", "ref": "app/session_context.py"}],
                }
            ]
        },
        [
            {
                "name": "apply_patch",
                "status": "ok",
                "summary": "Patched app/session_context.py",
                "source_refs": ["app/session_context.py"],
                "result_preview": {"files": ["app/session_context.py"]},
            }
        ],
        "completed",
        {},
        {},
    )

    assert [item["step"] for item in state["completed_steps"]] == [
        "Inspect current implementation",
        "Patch task_state merge",
    ]


def test_task_state_delta_replaces_generic_next_action_with_current_step() -> None:
    previous = {
        "task_id": "task-delta-7",
        "goal": "Patch and verify",
        "status": "in_progress",
        "plan_items": [{"step": "Run focused tests", "status": "in_progress"}],
    }
    baseline = merge_task_state_after_turn(previous, previous["plan_items"], [], [], "running", {}, {})
    step_id = baseline["plan_items"][0]["id"]

    state, validation = merge_task_state_delta(
        previous,
        previous["plan_items"],
        {
            "current_step_id": step_id,
            "next_required_action": "continue",
        },
        [],
        "completed",
        {},
        {},
    )

    assert state["next_required_action"] == "Continue current step: Run focused tests"
    assert validation["validation_warnings"][0]["code"] == "generic_next_required_action"


def test_update_plan_validation_error_does_not_pollute_failed_attempts() -> None:
    state = merge_task_state_after_turn(
        {
            "task_id": "task-plan-warning",
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
    assert state["validation_warnings"][0]["code"] == "update_plan_validation_error"
    assert "non-empty list" in state["validation_warnings"][0]["message"]
