from __future__ import annotations

from app.context_pack import ContextManager, build_model_context
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model


def _pack(*, message: str, manager: ContextManager, boundary: RuntimeBoundary) -> dict:
    return dump_model(
        build_model_context(
            user_request=message,
            context_manager=manager,
            runtime_boundary=boundary,
            project_root=boundary.project_root,
            cwd=boundary.cwd,
        )
    )


def test_model_context_returns_only_current_top_level_keys() -> None:
    boundary = RuntimeBoundary(cwd="/tmp/project", project_root="/tmp/project", allowed_roots=["/tmp/project"])
    pack = _pack(message="hello", manager=ContextManager(), boundary=boundary)

    assert set(pack) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert "legacy_context" not in pack
    assert "route_hints" not in pack
    assert "route_state" not in pack


def test_full_user_message_lives_only_in_task_user_request() -> None:
    message = "第一行\n第二行 " + ("内容" * 80)
    boundary = RuntimeBoundary(cwd="/tmp/project", project_root="/tmp/project")
    manager = ContextManager.from_payload(
        {"clean_turns": [{"role": "user", "text": message}, {"role": "assistant", "text": "ok"}]}
    )
    pack = _pack(message=message, manager=manager, boundary=boundary)

    assert pack["task"]["user_request"] == message.replace("\n", " ")
    assert pack["conversation"]["recent_turns"] == [{"role": "assistant", "text": "ok"}]
    assert "current_turn" not in pack


def test_plan_and_current_step_come_from_context_manager() -> None:
    boundary = RuntimeBoundary(cwd="/tmp/project", project_root="/tmp/project")
    manager = ContextManager.from_payload(
        {
            "recent_observations": [{"tool": "read_file", "summary": "已读取 app/main.py", "status": "ok"}],
            "plan": [
                {"step": "Inspect context builder", "status": "completed"},
                {"step": "Update tests", "status": "in_progress"},
            ],
        }
    )
    pack = _pack(message="继续", manager=manager, boundary=boundary)

    assert pack["task"]["current_step"] == "已读取 app/main.py"
    assert pack["task"]["next_action"] == "Update tests"
    assert [item["status"] for item in pack["plan"]["items"]] == ["completed", "in_progress"]


def test_permissions_view_excludes_internal_roots() -> None:
    boundary = RuntimeBoundary(
        cwd="/tmp/project",
        project_root="/tmp/project",
        allowed_roots=["/tmp/project", "/tmp/uploads"],
        writable_roots=["/tmp/project"],
        max_output_tokens=8192,
    )
    pack = _pack(message="hello", manager=ContextManager(), boundary=boundary)

    assert pack["workspace"]["cwd"] == "/tmp/project"
    assert "allowed_roots" not in pack["permissions"]
    assert "writable_roots" not in pack["permissions"]
    assert "max_output_tokens" not in pack["permissions"]
