from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
from app.context_pack import (
    ContextManager,
    build_model_context,
    classify_assistant_output,
    render_model_context,
)
from app.runtime_boundary import RuntimeBoundary, build_turn_runtime_boundary
from app.runtime_contract import RuntimeContract
from app.serialization import dump_model
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _FakeTools:
    tool_specs: list[dict[str, Any]] = []


class _FakeBackend:
    tools = _FakeTools()


def _model_context_payload(text: str) -> dict[str, Any]:
    return json.loads(text.split("model_context_json:\n", 1)[1])["model_context"]


def test_model_context_has_six_question_sections(tmp_path: Path) -> None:
    boundary = build_turn_runtime_boundary(
        config=load_config(),
        runtime_contract=RuntimeContract(permission_profile="code", shell_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )

    model_context = build_model_context(
        user_request="分析当前工具实现",
        context={
            "context_manager": {
                "clean_summary": "已经确认工具入口在 app/local_tools.py。",
                "clean_turns": [{"role": "assistant", "text": "上一轮已经完成工具入口定位。"}],
                "recent_observations": [{"tool": "read_file", "target": "app/local_tools.py", "status": "ok", "summary": "找到了 exec_command。"}],
                "active_files": ["app/local_tools.py"],
                "plan": [{"step": "检查 ActionValidator", "status": "pending"}],
                "context_version": 3,
            },
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
        },
        current_task_focus={"last_completed_step": "已读取 local_tools", "next_action": "继续检查 validator"},
        runtime_boundary_model_view=boundary.to_model_view(),
        permission_profile="code",
    )
    payload = dump_model(model_context)

    assert set(payload) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert payload["task"]["user_request"] == "分析当前工具实现"
    assert payload["workspace"]["project_root"] == str(tmp_path.resolve())
    assert payload["memory"]["clean_summary"]
    assert payload["task"]["current_step"] == "已读取 local_tools"
    assert payload["plan"]["items"][0]["step"] == "检查 ActionValidator"
    assert payload["permissions"]["profile"] == "code"


def test_human_message_is_rendered_only_from_model_context(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=tmp_path, backend=_FakeBackend())
    boundary = RuntimeBoundary(cwd=str(tmp_path), project_root=str(tmp_path), allowed_roots=[str(tmp_path)])

    payload_text = runtime._build_human_payload(  # noqa: SLF001
        message="整理会议纪要",
        context={
            "session_id": "s-context",
            "route_state": {"task_checkpoint": {"goal": "route-derived goal"}},
            "agent_state": {"goal": "agent-derived goal"},
            "trace_events": [{"type": "tool.started"}],
            "execution_trace": [{"detail": "raw trace"}],
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
        },
        runtime_boundary=boundary,
    )
    payload = _model_context_payload(payload_text)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "model_context_json:" in payload_text
    assert "runtime_context_json:" not in payload_text
    assert set(payload) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert "route_state" not in encoded
    assert "agent_state" not in encoded
    assert "trace_events" not in encoded
    assert "execution_trace" not in encoded
    assert "route-derived goal" not in encoded
    assert "agent-derived goal" not in encoded


def test_empty_context_manager_falls_back_to_legacy_clean_fields(tmp_path: Path) -> None:
    model_context = build_model_context(
        user_request="继续",
        context={
            "context_manager": {
                "clean_summary": "",
                "clean_turns": [],
                "recent_observations": [],
                "active_files": [],
                "plan": [],
                "context_version": 0,
            },
            "summary": "旧 session 的干净摘要",
            "history_turns": [{"role": "assistant", "text": "上一轮完成了文件定位。"}],
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
        },
        current_task_focus={},
        runtime_boundary_model_view=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)).to_model_view(),
    )
    payload = dump_model(model_context)

    assert payload["memory"]["clean_summary"] == "旧 session 的干净摘要"
    assert payload["conversation"]["recent_turns"][0]["text"] == "上一轮完成了文件定位。"


def test_model_draft_is_excluded_from_clean_context() -> None:
    manager = ContextManager()
    manager.update_after_turn(
        user_request="创建 skill",
        clean_final_answer="We need to create the skill file. Let's try to inspect the folders first.",
        runtime_trace={"tool_events": []},
        plan_updates=None,
    )

    payload = manager.to_session_payload()
    assert classify_assistant_output("We need to create the skill file. Let's try to inspect the folders first.") == "model_draft"
    assert payload["clean_turns"] == [{"role": "user", "text": "创建 skill"}]
    assert "skill file" not in payload["clean_summary"]
    assert payload["recent_observations"] == []


def test_clean_final_answer_is_stored_as_clean_turn() -> None:
    manager = ContextManager()
    manager.update_after_turn(
        user_request="创建 skill",
        clean_final_answer="已完成：我创建了迁移 session 的 skill，并说明了使用方法。",
        runtime_trace={"tool_events": []},
        plan_updates=None,
    )

    assert manager.clean_turns[-1]["role"] == "assistant"
    assert "已完成" in manager.clean_turns[-1]["text"]


def test_context_manager_compacts_clean_history_without_raw_trace() -> None:
    manager = ContextManager()
    for index in range(18):
        manager.update_after_turn(
            user_request=f"用户 {index}",
            clean_final_answer=f"已完成 {index}",
            runtime_trace={
                "tool_events": [
                    {
                        "name": "read_file",
                        "status": "ok",
                        "output_preview": "RAW_OUTPUT_SHOULD_ONLY_BE_SUMMARIZED" * 20,
                        "arguments": {"path": "app/main.py"},
                    }
                ]
            },
            plan_updates=[{"step": "继续", "status": "pending"}],
        )
    before = manager.context_version
    compacted = manager.compact_if_needed(max_clean_turns=16)

    assert compacted is True
    assert manager.context_version > before
    assert manager.clean_summary
    assert len(manager.clean_turns) <= 8
    assert "RAW_OUTPUT_SHOULD_ONLY_BE_SUMMARIZED" not in manager.clean_summary
    assert manager.plan[0].step == "继续"


def test_runtime_trace_only_contributes_summarized_observation() -> None:
    manager = ContextManager()
    manager.update_after_turn(
        user_request="读文件",
        clean_final_answer="已读取文件。",
        runtime_trace={
            "model_draft": "We need to inspect raw files.",
            "tool_events": [
                {
                    "name": "read_file",
                    "status": "ok",
                    "summary": "读取 app/main.py 并找到 runtime 入口。",
                    "output": "RAW FILE CONTENT" * 100,
                    "arguments": {"path": "app/main.py"},
                }
            ],
        },
        plan_updates=None,
    )
    model_context = build_model_context(
        user_request="继续",
        context={"context_manager": manager.to_session_payload()},
        current_task_focus={},
        runtime_boundary_model_view=RuntimeBoundary().to_model_view(),
    )
    encoded = json.dumps(dump_model(model_context), ensure_ascii=False)

    assert "读取 app/main.py" in encoded
    assert "RAW FILE CONTENT" not in encoded
    assert "We need to inspect" not in encoded


def test_render_model_context_outputs_single_model_context_envelope() -> None:
    model_context = build_model_context(
        user_request="hello",
        context={},
        current_task_focus={},
        runtime_boundary_model_view=RuntimeBoundary().to_model_view(),
    )
    rendered = render_model_context(model_context)
    payload = json.loads(rendered.split("model_context_json:\n", 1)[1])

    assert set(payload) == {"model_context"}
    assert set(payload["model_context"]) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
