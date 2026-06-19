from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from app.config import load_config
from app.context_pack import (
    ContextManager,
    apply_compaction_summary_to_state,
    build_compaction_input,
    build_model_context,
    build_structured_compaction_summary,
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


def test_build_model_context_signature_rejects_legacy_inputs(tmp_path: Path) -> None:
    signature = inspect.signature(build_model_context)

    assert "context" not in signature.parameters
    assert "current_task_focus" not in signature.parameters

    with pytest.raises(TypeError):
        build_model_context(
            user_request="继续",
            context_manager=ContextManager(),
            runtime_boundary=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)),
            project_root=tmp_path,
            cwd=tmp_path,
            context={},
        )

    with pytest.raises(TypeError):
        build_model_context(
            user_request="继续",
            context_manager=ContextManager(),
            runtime_boundary=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)),
            project_root=tmp_path,
            cwd=tmp_path,
            current_task_focus={},
        )


def test_model_context_has_six_question_sections(tmp_path: Path) -> None:
    boundary = build_turn_runtime_boundary(
        config=load_config(),
        runtime_contract=RuntimeContract(permission_profile="auto", shell_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )
    manager = ContextManager.from_payload(
        {
            "clean_summary": "已经确认工具入口在 app/local_tools.py。",
            "clean_turns": [{"role": "assistant", "text": "上一轮已经完成工具入口定位。"}],
            "recent_observations": [{"tool": "read_file", "target": "app/local_tools.py", "status": "ok", "summary": "找到了 exec_command。"}],
            "active_files": ["app/local_tools.py"],
            "plan": [{"step": "检查 ActionValidator", "status": "pending"}],
            "context_version": 3,
        }
    )

    model_context = build_model_context(
        user_request="分析当前工具实现",
        context_manager=manager,
        runtime_boundary=boundary,
        project_root=tmp_path,
        cwd=tmp_path,
    )
    payload = dump_model(model_context)

    assert set(payload) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert payload["task"]["user_request"] == "分析当前工具实现"
    assert payload["task"]["goal"] == "分析当前工具实现"
    assert payload["task"]["current_step"] == "找到了 exec_command。"
    assert payload["task"]["next_action"] == "检查 ActionValidator"
    assert payload["workspace"]["project_root"] == str(tmp_path.resolve())
    assert payload["workspace"]["model_visible_paths"] == ["app/local_tools.py"]
    assert payload["memory"]["clean_summary"] == "已经确认工具入口在 app/local_tools.py。"
    assert payload["plan"]["items"][0]["step"] == "检查 ActionValidator"
    assert payload["permissions"]["profile"] == "auto"
    assert payload["permissions"]["label"] == "Auto"
    assert payload["conversation"]["recent_turns"] == [{"role": "assistant", "text": "上一轮已经完成工具入口定位。"}]


def test_model_context_preserves_large_current_request_when_budget_allows(tmp_path: Path) -> None:
    boundary = build_turn_runtime_boundary(
        config=load_config(),
        runtime_contract=RuntimeContract(permission_profile="auto", shell_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )
    long_request = "会议转录：" + ("重要内容" * 1500)

    model_context = build_model_context(
        user_request=long_request,
        context_manager=ContextManager(),
        runtime_boundary=boundary,
        project_root=tmp_path,
        cwd=tmp_path,
        user_request_char_limit=len(long_request),
    )

    assert model_context.task.user_request == long_request


def test_model_context_prefers_task_state_checkpoint_when_present(tmp_path: Path) -> None:
    boundary = build_turn_runtime_boundary(
        config=load_config(),
        runtime_contract=RuntimeContract(permission_profile="auto", shell_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )
    manager = ContextManager.from_payload(
        {
            "recent_observations": [{"tool": "read_file", "summary": "旧观察", "status": "ok"}],
            "plan": [{"step": "旧计划", "status": "pending"}],
            "active_files": ["legacy.py"],
        }
    )

    model_context = build_model_context(
        user_request="继续修 task_state",
        context_manager=manager,
        runtime_boundary=boundary,
        project_root=tmp_path,
        cwd=tmp_path,
        task_state={
            "goal": "修 task_state validator",
            "status": "blocked",
            "plan_items": [
                {"id": "step-1", "step": "Inspect current merge flow", "status": "completed"},
                {"id": "step-2", "step": "Patch validator rules", "status": "in_progress"},
            ],
            "current_step_id": "step-2",
            "next_required_action": "Run focused tests",
            "blocked_reason": "pytest failed",
            "completed_steps": [{"step": "Inspect current merge flow"}],
            "failed_attempts": [{"summary": "pytest failed once"}],
            "validation_warnings": [{"message": "Rejected generic next_required_action"}],
        },
        work_cursor={"active_files": ["app/session_context.py"], "cwd": str(tmp_path), "project_root": str(tmp_path)},
    )
    payload = dump_model(model_context)

    assert payload["task"]["goal"] == "修 task_state validator"
    assert payload["task"]["status"] == "blocked"
    assert payload["task"]["current_step_id"] == "step-2"
    assert payload["task"]["current_step"] == "Patch validator rules"
    assert payload["task"]["next_action"] == "Run focused tests"
    assert payload["task"]["blocked_reason"] == "pytest failed"
    assert payload["task"]["completed_steps"] == ["Inspect current merge flow"]
    assert payload["task"]["failed_attempts"] == ["pytest failed once"]
    assert payload["task"]["validation_warnings"] == ["Rejected generic next_required_action"]
    assert payload["workspace"]["model_visible_paths"] == ["app/session_context.py", "legacy.py"]
    assert payload["plan"]["items"][0]["step"] == "Inspect current merge flow"


def test_context_manager_from_context_payload_reads_only_context_manager() -> None:
    manager = ContextManager.from_context_payload(
        {
            "summary": "legacy summary",
            "thread_memory": {"summary": "legacy thread memory"},
            "history_turns": [{"role": "assistant", "text": "legacy turn"}],
            "current_task_focus": {"active_files": ["app/main.py"]},
            "plan_state": {"items": [{"step": "legacy plan", "status": "pending"}]},
        }
    )

    assert dump_model(manager) == dump_model(ContextManager())


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


def test_structured_compaction_summary_writes_task_and_cursor_state() -> None:
    compaction_input = build_compaction_input(
        old_messages=[{"role": "assistant", "text": "已确认 app/main.py 负责 stream endpoint。"}],
        tool_evidence=[
            {
                "name": "read_file",
                "status": "ok",
                "summary": "读取 app/main.py 并找到 chat_stream。",
                "arguments": {"path": "app/main.py"},
                "output_preview": "RAW_TRACE_SHOULD_NOT_APPEAR",
            },
            {
                "name": "exec_command",
                "status": "error",
                "summary": "pytest 首次运行失败：缺少 fixture。",
                "arguments": {"cmd": "pytest"},
            },
        ],
        task_state={
            "goal": "实现 runtime typed item",
            "status": "blocked",
            "plan_items": [{"step": "补 runtime item", "status": "pending"}],
            "failed_attempts": [{"summary": "旧失败尝试"}],
        },
        work_cursor={"active_files": ["app/main.py"]},
        modified_files=["app/vintage_programmer_runtime.py"],
        current_status="blocked",
    )
    summary = build_structured_compaction_summary(compaction_input)
    manager, task_state, work_cursor = apply_compaction_summary_to_state(
        context_manager=ContextManager(),
        summary=summary,
        task_state={"status": "blocked"},
        work_cursor={},
        generation=2,
    )
    encoded = json.dumps(manager.to_session_payload(), ensure_ascii=False)

    assert set(dump_model(summary)) == {
        "confirmed_facts",
        "files_touched",
        "decisions",
        "failed_attempts",
        "current_state",
        "next_steps",
        "open_questions",
        "do_not_repeat",
    }
    assert "RAW_TRACE_SHOULD_NOT_APPEAR" not in encoded
    assert "app/vintage_programmer_runtime.py" in manager.active_files
    assert task_state["next_required_action"] == "补 runtime item"
    assert task_state["failed_attempts"]
    assert work_cursor["active_files"][0] == "app/vintage_programmer_runtime.py"


def test_runtime_trace_only_contributes_summarized_observation(tmp_path: Path) -> None:
    manager = ContextManager()
    manager.update_after_turn(
        user_request="读文件",
        clean_final_answer="已读取文件。",
        runtime_trace={
            "model_draft": "We need to inspect raw files.",
            "provider_payload": {"raw": "secret"},
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
        context_manager=manager,
        runtime_boundary=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    encoded = json.dumps(dump_model(model_context), ensure_ascii=False)

    assert "读取 app/main.py" in encoded
    assert "RAW FILE CONTENT" not in encoded
    assert "We need to inspect" not in encoded
    assert "provider_payload" not in encoded


def test_render_model_context_outputs_single_model_context_envelope(tmp_path: Path) -> None:
    model_context = build_model_context(
        user_request="hello",
        context_manager=ContextManager(),
        runtime_boundary=RuntimeBoundary(project_root=str(tmp_path), cwd=str(tmp_path)),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    rendered = render_model_context(model_context)
    payload = json.loads(rendered.split("model_context_json:\n", 1)[1])

    assert set(payload) == {"model_context"}
    assert set(payload["model_context"]) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
