from __future__ import annotations

import json
from pathlib import Path

from app.context_pack import ContextManager, build_model_context
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model
from app.session_migration import CONTEXT_SCHEMA_VERSION, migrate_legacy_session_to_context_manager


def test_legacy_session_migration_builds_clean_context_manager_once(tmp_path: Path) -> None:
    legacy_session = {
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "summary": "旧 session 的干净摘要",
        "turns": [
            {"role": "assistant", "text": "上一轮完成了文件定位。"},
            {"role": "assistant", "text": "We need to keep thinking before answering."},
        ],
        "thread_memory": {"summary": "should not win over summary"},
        "current_task_focus": {
            "cwd": str(tmp_path),
            "active_files": [str(tmp_path / "app" / "main.py")],
        },
        "plan_state": {
            "items": [
                {"step": "检查 ActionValidator", "status": "in_progress"},
                {"step": "补测试", "status": "pending"},
            ]
        },
        "recent_tool_results": [
            {
                "tool": "read_file",
                "target": str(tmp_path / "app" / "main.py"),
                "summary": f"读取 {tmp_path}/app/main.py 并确认 runtime 入口。",
                "status": "ok",
            }
        ],
        "route_state": {"task_checkpoint": {"goal": "legacy goal"}},
        "agent_state": {"goal": "legacy agent goal"},
        "recent_tasks": [{"goal": "legacy recent task"}],
        "answer_bundle": {"summary": "legacy answer bundle"},
    }

    migrated, changed = migrate_legacy_session_to_context_manager(legacy_session)
    manager = ContextManager.from_payload(migrated["context_manager"])
    encoded = json.dumps(migrated["context_manager"], ensure_ascii=False)

    assert changed is True
    assert migrated["context_schema_version"] == CONTEXT_SCHEMA_VERSION
    assert manager.clean_summary == "旧 session 的干净摘要"
    assert manager.clean_turns == [{"role": "assistant", "text": "上一轮完成了文件定位。"}]
    assert manager.recent_observations[0].summary == "读取 app/main.py 并确认 runtime 入口。"
    assert manager.active_files == ["app/main.py"]
    assert [item.step for item in manager.plan] == ["检查 ActionValidator", "补测试"]
    assert "route_state" not in encoded
    assert "agent_state" not in encoded
    assert "answer_bundle" not in encoded
    assert str(tmp_path) not in encoded


def test_normal_model_context_ignores_legacy_session_fields_after_migration(tmp_path: Path) -> None:
    migrated, _ = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "summary": "旧摘要",
            "current_turn": {"goal": "legacy current turn goal"},
            "current_task_focus": {"goal": "legacy focus goal", "active_files": [str(tmp_path / "app" / "main.py")]},
            "plan_state": {"items": [{"step": "旧计划", "status": "pending"}]},
            "turns": [{"role": "assistant", "text": "已完成旧工作。"}],
        }
    )
    model_context = build_model_context(
        user_request="继续检查新的运行时边界",
        context_manager=ContextManager.from_payload(migrated["context_manager"]),
        runtime_boundary=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    payload = dump_model(model_context)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["task"]["goal"] == "继续检查新的运行时边界"
    assert payload["task"]["next_action"] == "旧计划"
    assert payload["memory"]["clean_summary"] == "旧摘要"
    assert payload["workspace"]["model_visible_paths"] == ["app/main.py"]
    assert "legacy current turn goal" not in encoded
    assert "legacy focus goal" not in encoded
