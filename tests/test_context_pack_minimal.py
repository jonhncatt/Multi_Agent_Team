from __future__ import annotations

from app.context_pack import build_context_pack
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model


def test_context_pack_has_only_approved_top_level_keys() -> None:
    boundary = RuntimeBoundary(cwd="/tmp/project", project_root="/tmp/project", allowed_roots=["/tmp/project"])
    pack = dump_model(
        build_context_pack(
            message="hello",
            context={},
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert set(pack) == {
        "current_turn",
        "conversation_window",
        "turn_memory",
        "plan_state",
        "compaction",
        "runtime_boundary",
    }
    assert "legacy_context" not in pack
    assert "route_hints" not in pack
    assert "route_state" not in pack


def test_user_message_preview_is_bounded_and_not_full_message() -> None:
    message = "第一行\n第二行 " + ("内容" * 80)
    boundary = RuntimeBoundary()
    pack = dump_model(
        build_context_pack(
            message=message,
            context={"history_turns": [{"role": "user", "text": message}, {"role": "assistant", "text": "ok"}]},
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert len(pack["current_turn"]["user_message_preview"]) <= 80
    assert "\n" not in pack["current_turn"]["user_message_preview"]
    assert "user_message" not in pack["current_turn"]
    assert pack["conversation_window"]["recent_turns"] == [{"role": "assistant", "text": "ok"}]


def test_plan_state_is_first_class_and_active_when_unfinished() -> None:
    boundary = RuntimeBoundary()
    pack = dump_model(
        build_context_pack(
            message="继续",
            context={
                "plan_state": {
                    "items": [
                        {"step": "Inspect context builder", "status": "completed"},
                        {"step": "Update tests", "status": "in_progress"},
                    ],
                    "updated_at_turn": "turn-9",
                }
            },
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert pack["plan_state"]["active"] is True
    assert pack["plan_state"]["updated_at_turn"] == "turn-9"
    assert [item["status"] for item in pack["plan_state"]["items"]] == ["completed", "in_progress"]


def test_runtime_boundary_model_view_excludes_internal_roots() -> None:
    boundary = RuntimeBoundary(
        cwd="/tmp/project",
        project_root="/tmp/project",
        allowed_roots=["/tmp/project", "/tmp/uploads"],
        writable_roots=["/tmp/project"],
        max_output_tokens=8192,
    )
    pack = dump_model(
        build_context_pack(
            message="hello",
            context={},
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert pack["runtime_boundary"]["cwd"] == "/tmp/project"
    assert "allowed_roots" not in pack["runtime_boundary"]
    assert "writable_roots" not in pack["runtime_boundary"]
    assert "max_output_tokens" not in pack["runtime_boundary"]


def test_compaction_view_is_minimal_and_summary_backed() -> None:
    boundary = RuntimeBoundary()
    pack = dump_model(
        build_context_pack(
            message="继续",
            context={
                "summary": "Older context summary",
                "compaction_status": {
                    "phase": "mid_turn",
                    "reason": "context_limit:10000/8000",
                    "before_tokens": 10000,
                    "after_tokens": 5000,
                },
            },
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert pack["turn_memory"]["summary"] == "Older context summary"
    assert pack["compaction"] == {
        "active": True,
        "phase": "mid_turn",
        "reason": "context_limit",
        "summary_available": True,
    }


def test_context_pack_rebases_known_absolute_paths_for_model() -> None:
    boundary = RuntimeBoundary(cwd="/new/root", project_root="/new/root", allowed_roots=["/new/root"])
    pack = dump_model(
        build_context_pack(
            message="继续",
            context={
                "project": {
                    "project_root": "/new/root",
                    "previous_project_roots": ["/old/root"],
                },
                "summary": "Reviewed /old/root/app/local_tools.py and /new/root/app/action_validator.py",
                "history_turns": [
                    {
                        "role": "tool",
                        "tool": "read_file",
                        "text": "Read /old/root/app/local_tools.py",
                    }
                ],
                "recent_tool_results": [
                    {
                        "tool": "read_file",
                        "target": "/old/root/app/local_tools.py",
                        "summary": "Found path payload in /new/root/app/local_tools.py",
                    }
                ],
            },
            current_task_focus={
                "cwd": "/new/root",
                "active_files": ["/old/root/app/local_tools.py", "/new/root/app/action_validator.py"],
            },
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    encoded = dump_model(pack)
    payload_text = str(encoded)
    assert "/old/root" not in payload_text
    assert "/new/root/app" not in payload_text
    assert "app/local_tools.py" in payload_text
    assert "app/action_validator.py" in payload_text
