from __future__ import annotations

from app.llm.types import AIMessage
from app.model_runtime_diagnostics import (
    build_assistant_response_summary_from_message,
    build_model_runtime_analysis,
    build_request_summary,
)


def test_model_runtime_analysis_direct_answer_without_tools() -> None:
    message = AIMessage(
        content="你好！有什么我可以帮你？",
        response_metadata={
            "finish_reason": "stop",
            "response_id": "resp_1",
            "token_usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            "stream_diagnostics": {"provider": "openai_native", "event_count": 3, "text_delta_count": 2},
        },
    )
    analysis = build_model_runtime_analysis(
        request_summary=build_request_summary(
            backend="openai_native",
            provider="openrouter",
            model="demo-model",
            streaming=True,
            api_path="chat_completions",
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "你好"}],
            max_output_tokens=4096,
            temperature=None,
            tools_available_count=31,
            tools_exposed=False,
            tool_choice="none",
            tool_count_exposed=0,
        ),
        runtime_guess={"source": "runtime_guess", "task_type": "standard", "primary_intent": "standard", "output_mode": "direct_answer"},
        high_level_proposal={
            "source": "model",
            "intent": "standard",
            "task_type": "standard",
            "current_goal": "你好",
            "expects_tools": False,
            "response_mode": "direct_answer",
            "summary": "直接回答路径。",
        },
        proposal_diagnostics={"status": "parsed", "checked": True, "schema_validation": {"status": "valid"}},
        runtime_contract={"tools_available": True, "tool_policy": "use_when_needed"},
        explicit_tool_request=False,
        attachment_requires_tooling=False,
        workspace_action_requested=False,
        network_requested=False,
        tools_should_be_exposed=False,
        actual_tools_exposed=False,
        tool_choice="none",
        exposed_tool_names=[],
        assistant_message=message,
    )

    assert analysis["proposal_parse"]["proposal_source"] == "model"
    assert analysis["tool_gating"]["actual_tools_exposed"] is False
    assert analysis["assistant_response_summary"]["assistant_tool_calls_count"] == 0
    assert analysis["final_answer_guard"] == {}
    assert analysis["task_continuity"] == {}
    assert analysis["diagnostic_warnings"] == []


def test_model_runtime_analysis_surfaces_direct_answer_tool_mismatch_and_runtime_fallback() -> None:
    analysis = build_model_runtime_analysis(
        request_summary=build_request_summary(
            backend="openai_native",
            provider="openrouter",
            model="demo-model",
            streaming=True,
            api_path="chat_completions",
            messages=[{"role": "user", "content": "你好"}],
            max_output_tokens=4096,
            temperature=None,
            tools_available_count=31,
            tools_exposed=True,
            tool_choice="auto",
            tool_count_exposed=5,
        ),
        runtime_guess={"source": "runtime_guess", "task_type": "standard", "primary_intent": "standard", "output_mode": "direct_answer"},
        high_level_proposal={
            "source": "runtime_fallback",
            "intent": "standard",
            "task_type": "standard",
            "current_goal": "你好",
            "expects_tools": True,
            "response_mode": "direct_answer",
            "summary": "直接回答路径。",
        },
        proposal_diagnostics={"status": "missing", "checked": False, "schema_validation": {"status": "missing"}},
        runtime_contract={"tools_available": True, "tool_policy": "use_when_needed"},
        explicit_tool_request=False,
        attachment_requires_tooling=False,
        workspace_action_requested=False,
        network_requested=False,
        tools_should_be_exposed=False,
        actual_tools_exposed=True,
        tool_choice="auto",
        exposed_tool_names=["read_file", "list_dir", "search_codebase", "exec_command", "web_search"],
        assistant_response_summary={"assistant_tool_calls_count": 0, "tool_calls": []},
    )

    warning_codes = {item["code"] for item in analysis["diagnostic_warnings"]}
    assert analysis["proposal_parse"]["proposal_block_found"] is False
    assert analysis["proposal_parse"]["proposal_source"] == "runtime_fallback"
    assert analysis["tool_gating"]["reason"] == "BUG: direct_answer predicted but tools were exposed"
    assert "direct_answer_proposal_expects_tools" in warning_codes
    assert "direct_answer_tools_exposed" in warning_codes
    assert "proposal_block_missing_runtime_fallback" in warning_codes


def test_model_runtime_analysis_does_not_flag_workspace_tool_request_as_direct_answer_bug() -> None:
    analysis = build_model_runtime_analysis(
        request_summary=build_request_summary(
            backend="openai_native",
            provider="openrouter",
            model="demo-model",
            streaming=True,
            api_path="chat_completions",
            messages=[{"role": "user", "content": "请查看当前文件夹下的AGENT.MD文件"}],
            max_output_tokens=4096,
            temperature=None,
            tools_available_count=31,
            tools_exposed=True,
            tool_choice="auto",
            tool_count_exposed=5,
        ),
        runtime_guess={"source": "runtime_guess", "task_type": "standard", "primary_intent": "standard", "output_mode": "tool_assisted_answer"},
        high_level_proposal={
            "source": "runtime_fallback",
            "intent": "standard",
            "task_type": "standard",
            "current_goal": "请查看当前文件夹下的AGENT.MD文件",
            "expects_tools": True,
            "response_mode": "tool_assisted_answer",
            "summary": "需要读取工作区文件。",
        },
        proposal_diagnostics={"status": "missing", "checked": False, "schema_validation": {"status": "missing"}},
        runtime_contract={"tools_available": True, "tool_policy": "use_when_needed"},
        explicit_tool_request=True,
        attachment_requires_tooling=False,
        workspace_action_requested=True,
        network_requested=False,
        tools_should_be_exposed=True,
        actual_tools_exposed=True,
        tool_choice="auto",
        exposed_tool_names=["read_file", "list_dir"],
        assistant_response_summary={"assistant_tool_calls_count": 1, "tool_calls": []},
    )

    warning_codes = {item["code"] for item in analysis["diagnostic_warnings"]}

    assert analysis["tool_gating"]["reason"] == "workspace tool request"
    assert "direct_answer_tools_exposed" not in warning_codes


def test_model_runtime_analysis_can_include_final_answer_guard_and_task_continuity() -> None:
    analysis = build_model_runtime_analysis(
        request_summary=build_request_summary(
            backend="openai_native",
            provider="openrouter",
            model="demo-model",
            streaming=True,
            api_path="chat_completions",
            messages=[{"role": "user", "content": "请先理解图片格式再整理"}],
            max_output_tokens=4096,
            temperature=None,
            tools_available_count=31,
            tools_exposed=True,
            tool_choice="auto",
            tool_count_exposed=2,
        ),
        runtime_guess={"source": "runtime_guess", "task_type": "standard", "primary_intent": "standard", "output_mode": "tool_assisted_answer"},
        high_level_proposal={
            "source": "runtime_fallback",
            "intent": "standard",
            "task_type": "standard",
            "current_goal": "请先理解图片格式再整理",
            "expects_tools": True,
            "response_mode": "tool_assisted_answer",
            "summary": "需要先读取图片并提取格式逻辑，然后继续整理数据。",
        },
        proposal_diagnostics={"status": "missing", "checked": False, "schema_validation": {"status": "missing"}},
        runtime_contract={"tools_available": True, "tool_policy": "use_when_needed"},
        explicit_tool_request=False,
        attachment_requires_tooling=True,
        image_attachment_needs_read=True,
        previous_task_focus_requires_tooling=False,
        workspace_action_requested=False,
        network_requested=False,
        tools_should_be_exposed=True,
        actual_tools_exposed=True,
        tool_choice="auto",
        exposed_tool_names=["image_read", "read_file"],
        assistant_response_summary={"assistant_tool_calls_count": 0, "tool_calls": []},
        final_answer_guard={"checked": True, "accepted": False, "reason": "promise_to_act_without_deliverable"},
        task_continuity={
            "active_goal": "请先理解图片格式再整理",
            "requires_tools": True,
            "attachments_required": True,
            "tools_used": ["image_read"],
            "deliverable_detected": False,
            "should_continue": True,
            "reason": "tool_result_collected_but_deliverable_missing",
        },
    )

    assert analysis["final_answer_guard"]["accepted"] is False
    assert analysis["task_continuity"]["should_continue"] is True


def test_assistant_response_summary_marks_tool_argument_parse_states_and_masks_sensitive_text() -> None:
    message = AIMessage(
        content="Authorization: Bearer sk-live-secret-value",
        tool_calls=[
            {
                "id": "tc-valid",
                "name": "list_dir",
                "args": {"path": "."},
                "raw_args": '{"path":"."}',
                "type": "tool_call",
            },
            {
                "id": "tc-not-object",
                "name": "exec_command",
                "args": {},
                "raw_args": '"pwd"',
                "type": "tool_call",
            },
            {
                "id": "tc-invalid",
                "name": "web_fetch",
                "args": {},
                "raw_args": '{"url":"https://example.com?token=abcdef"',
                "type": "tool_call",
            },
        ],
        response_metadata={
            "finish_reason": "tool_calls",
            "response_id": "resp_2",
            "token_usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4},
            "stream_diagnostics": {"provider": "openai_native", "event_count": 1, "text_delta_count": 0},
        },
    )

    summary = build_assistant_response_summary_from_message(message)

    assert summary["assistant_content_preview"].endswith("***")
    assert summary["tool_calls"][0]["args_parse_status"] == "valid_object"
    assert summary["tool_calls"][1]["args_parse_status"] == "not_object"
    assert summary["tool_calls"][1]["args_type"] == "str"
    assert summary["tool_calls"][2]["args_parse_status"] == "invalid_json"
    assert "***" in str(summary["tool_calls"][2]["raw_args_preview"])
