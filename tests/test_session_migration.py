from __future__ import annotations

import json
from pathlib import Path

from app.context_pack import ContextManager, build_model_context
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model
from app.session_migration import (
    CONTEXT_SCHEMA_VERSION,
    has_context_manager_payload,
    has_legacy_context_payload,
    migrate_legacy_session_to_context_manager,
)


def test_session_migration_skips_existing_context_manager_payload(tmp_path: Path) -> None:
    payload = {
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "context_schema_version": CONTEXT_SCHEMA_VERSION,
        "context_manager": {
            "clean_summary": "已完成上下文迁移。",
            "clean_turns": [{"role": "assistant", "text": "上一轮已完成 clean history 更新。"}],
            "recent_observations": [{"source": "tool", "tool": "read_file", "summary": "确认 app/main.py 入口。", "status": "ok"}],
            "active_files": ["app/main.py"],
            "plan": [{"step": "继续拆 runtime helper", "status": "pending"}],
            "context_version": 2,
        },
    }

    migrated, changed = migrate_legacy_session_to_context_manager(payload)

    assert has_context_manager_payload(payload) is True
    assert has_legacy_context_payload(payload) is False
    assert changed is False
    assert migrated["context_schema_version"] == CONTEXT_SCHEMA_VERSION
    assert ContextManager.from_payload(migrated["context_manager"]).to_session_payload() == ContextManager.from_payload(
        payload["context_manager"]
    ).to_session_payload()


def test_session_migration_migrates_summary_from_legacy_sources(tmp_path: Path) -> None:
    migrated, changed = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "summary": "  这是旧摘要。 \n\n 包含多余空白。 ",
            "thread_memory": {"summary": "thread memory summary should lose"},
            "compaction_status": {"summary": "compaction summary should lose"},
        }
    )
    manager = ContextManager.from_payload(migrated["context_manager"])

    assert has_legacy_context_payload(migrated) is True
    assert changed is True
    assert manager.clean_summary == "这是旧摘要。 包含多余空白。"
    assert manager.context_version >= 1


def test_session_migration_filters_clean_turns_from_legacy_messages(tmp_path: Path) -> None:
    migrated, changed = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "先看仓库"},
                {"role": "assistant", "content": "We need to inspect files before answering."},
                {"role": "tool", "content": "raw tool output"},
                {"role": "assistant", "content": "我已经确认 runtime 入口在 app/main.py。"},
            ],
        }
    )
    manager = ContextManager.from_payload(migrated["context_manager"])

    assert changed is True
    assert manager.clean_turns == [
        {"role": "user", "text": "先看仓库"},
        {"role": "assistant", "text": "我已经确认 runtime 入口在 app/main.py。"},
    ]


def test_session_migration_extracts_active_files_without_copying_focus_objects(tmp_path: Path) -> None:
    migrated, changed = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "current_task_focus": {
                "cwd": str(tmp_path),
                "active_files": [str(tmp_path / "app" / "main.py"), str(tmp_path / "docs" / "spec.md")],
            },
            "active_task_focus": {
                "cwd": str(tmp_path),
                "active_files": [str(tmp_path / "app" / "main.py"), str(tmp_path / "README.md")],
            },
        }
    )
    encoded = json.dumps(migrated["context_manager"], ensure_ascii=False)
    manager = ContextManager.from_payload(migrated["context_manager"])

    assert changed is True
    assert manager.active_files == ["app/main.py", "docs/spec.md", "README.md"]
    assert "current_task_focus" not in encoded
    assert "active_task_focus" not in encoded


def test_session_migration_normalizes_legacy_plan_items(tmp_path: Path) -> None:
    migrated, changed = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "plan_state": {
                "items": [
                    {"step": "检查 ActionValidator", "status": "in_progress"},
                    {"step": "补测试", "status": "unknown_status"},
                    {"step": "", "status": "completed"},
                ]
            },
        }
    )
    manager = ContextManager.from_payload(migrated["context_manager"])

    assert changed is True
    assert [dump_model(item) for item in manager.plan] == [
        {"step": "检查 ActionValidator", "status": "in_progress"},
        {"step": "补测试", "status": "pending"},
    ]


def test_session_migration_does_not_copy_raw_trace_or_route_state_into_context_manager(tmp_path: Path) -> None:
    migrated, changed = migrate_legacy_session_to_context_manager(
        {
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "summary": "保留这个摘要",
            "recent_tool_results": [{"tool": "read_file", "target": str(tmp_path / "app.py"), "summary": "读取 app.py", "status": "ok"}],
            "route_state": {"task_checkpoint": {"goal": "legacy goal"}},
            "agent_state": {"current_task_focus": {"goal": "legacy focus"}},
            "trace_events": [{"type": "tool.started", "payload": {"raw": "secret"}}],
            "execution_trace": [{"raw": "provider payload"}],
            "answer_bundle": {"summary": "raw answer bundle"},
        }
    )
    encoded = json.dumps(migrated["context_manager"], ensure_ascii=False)

    assert changed is True
    assert "route_state" not in encoded
    assert "agent_state" not in encoded
    assert "trace_events" not in encoded
    assert "execution_trace" not in encoded
    assert "answer_bundle" not in encoded
    assert str(tmp_path) not in encoded


def test_session_migration_is_idempotent(tmp_path: Path) -> None:
    legacy_session = {
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
        "summary": "旧 session 的干净摘要",
        "turns": [
            {"role": "assistant", "text": "上一轮完成了文件定位。"},
            {"role": "assistant", "text": "We need to keep thinking before answering."},
        ],
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
    }

    migrated_once, changed_once = migrate_legacy_session_to_context_manager(legacy_session)
    migrated_twice, changed_twice = migrate_legacy_session_to_context_manager(migrated_once)

    assert changed_once is True
    assert changed_twice is False
    assert migrated_twice["context_schema_version"] == CONTEXT_SCHEMA_VERSION
    assert migrated_twice["context_manager"] == migrated_once["context_manager"]


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
