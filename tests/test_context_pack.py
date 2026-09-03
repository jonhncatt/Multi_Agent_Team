from __future__ import annotations

import json

from app.context_pack import (
    ContextManager,
    build_compaction_input,
    build_structured_compaction_summary,
    classify_assistant_output,
)
from app.serialization import dump_model


def test_legacy_context_manager_still_loads_for_session_migration() -> None:
    manager = ContextManager.from_payload(
        {
            "clean_summary": "旧摘要",
            "clean_turns": [{"role": "assistant", "text": "旧回答"}],
            "recent_observations": [{"tool": "read_file", "status": "ok", "summary": "读过文件"}],
            "active_files": ["app/main.py"],
        }
    )

    assert manager.working_summary == "旧摘要"
    assert manager.recent_turns == [{"role": "assistant", "text": "旧回答"}]
    assert manager.recent_tool_results[0].summary == "读过文件"
    assert manager.relevant_files == ["app/main.py"]


def test_model_draft_classification_remains_available_for_legacy_data() -> None:
    assert classify_assistant_output("We need to inspect files first.") == "model_draft"
    assert classify_assistant_output("已完成实现并通过测试。") == "final_answer"


def test_structured_compaction_summary_omits_raw_trace() -> None:
    compaction_input = build_compaction_input(
        old_messages=[
            {"role": "user", "text": "只修改目标 cpp 文件。"},
            {"role": "assistant", "text": "未经验证：所有测试已经通过。"},
            {"role": "tool", "text": "编译器返回 0", "tool": "exec_command"},
        ],
        tool_evidence=[
            {
                "name": "read_file",
                "status": "ok",
                "summary": "读取 app/main.py。",
                "output_preview": "RAW_TRACE_SHOULD_NOT_APPEAR" * 20,
            }
        ],
        task_state={"goal": "实现 transcript", "status": "in_progress"},
        work_cursor={"active_files": ["app/main.py"]},
        modified_files=["app/vintage_programmer_runtime.py"],
    )
    summary = build_structured_compaction_summary(compaction_input)
    encoded = json.dumps(dump_model(summary), ensure_ascii=False)

    assert "RAW_TRACE_SHOULD_NOT_APPEAR" not in encoded
    assert "只修改目标 cpp 文件。" in summary.user_requirements
    assert "未经验证" not in " ".join(summary.confirmed_facts)


def test_compaction_input_keeps_early_user_constraints_and_failures_when_bounded() -> None:
    old_messages = [
        {"role": "user", "text": "You must preserve the earliest constraint ORION-742."},
        *[
            {"role": "assistant", "text": f"intermediate assistant observation {index}"}
            for index in range(140)
        ],
    ]
    tool_evidence = [
        {"name": "read_file", "status": "ok", "summary": f"successful observation {index}"}
        for index in range(120)
    ]
    tool_evidence.insert(
        60,
        {"name": "exec_command", "status": "failed", "summary": "critical failure NEBULA-19"},
    )

    compaction_input = build_compaction_input(
        old_messages=old_messages,
        tool_evidence=tool_evidence,
    )

    assert any(
        "ORION-742" in str(item.get("text") or "")
        for item in compaction_input["old_messages"]
    )
    assert any(
        "NEBULA-19" in str(item.get("summary") or "")
        for item in compaction_input["tool_evidence"]
    )
    assert len(compaction_input["old_messages"]) <= 96
    assert len(compaction_input["tool_evidence"]) <= 96


def test_context_manager_does_not_read_unscoped_legacy_fields() -> None:
    manager = ContextManager.from_context_payload(
        {
            "summary": "unscoped summary",
            "history_turns": [{"role": "assistant", "text": "unscoped turn"}],
        }
    )

    assert dump_model(manager) == dump_model(ContextManager())
