from __future__ import annotations

from app.context_pack import build_context_pack
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model


def test_context_pack_compat_returns_model_context_top_level_keys() -> None:
    boundary = RuntimeBoundary(cwd="/tmp/project", project_root="/tmp/project", allowed_roots=["/tmp/project"])
    pack = dump_model(
        build_context_pack(
            message="hello",
            context={},
            current_task_focus={},
            runtime_boundary_model_view=boundary.to_model_view(),
        )
    )

    assert set(pack) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert "legacy_context" not in pack
    assert "route_hints" not in pack
    assert "route_state" not in pack


def test_full_user_message_lives_only_in_task_user_request() -> None:
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

    assert pack["task"]["user_request"] == message.replace("\n", " ")
    assert pack["conversation"]["recent_turns"] == [{"role": "assistant", "text": "ok"}]
    assert "current_turn" not in pack


def test_plan_state_maps_to_model_context_plan() -> None:
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

    assert [item["status"] for item in pack["plan"]["items"]] == ["completed", "in_progress"]


def test_permissions_view_excludes_internal_roots() -> None:
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

    assert pack["workspace"]["cwd"] == "/tmp/project"
    assert "allowed_roots" not in pack["permissions"]
    assert "writable_roots" not in pack["permissions"]
    assert "max_output_tokens" not in pack["permissions"]


def test_compaction_summary_feeds_clean_memory() -> None:
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

    assert pack["memory"]["clean_summary"] == "Older context summary"
    assert "compaction" not in pack


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
                        "role": "assistant",
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

    payload_text = str(pack)
    assert "/old/root" not in payload_text
    assert "/new/root/app" not in payload_text
    assert "app/local_tools.py" in payload_text
    assert "app/action_validator.py" in payload_text
