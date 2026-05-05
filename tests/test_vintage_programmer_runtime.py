from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

import pytest

from app.config import load_config
from app.i18n import translate
from app.models import ChatSettings
from app.vintage_programmer_runtime import VintageProgrammerRuntime


REQUIRED_RUNTIME_ACTIVITY_KEYS = (
    "runtime.activity.summary.japanese_cleanup_requested",
    "runtime.activity.summary.rewrite_requested",
    "runtime.activity.summary.direct_answer_path",
    "runtime.activity.proposal.current_understanding_recorded",
    "runtime.activity.validation.rejected_current_step",
    "runtime.activity.validation.tool_call_queued",
    "runtime.activity.validation.tool_call_queued_named",
    "runtime.activity.validation.direct_answer",
    "runtime.activity.validation.user_input_step",
    "runtime.activity.validation.current_step_accepted",
    "runtime.activity.execution.recorded",
    "runtime.activity.execution.direct_answer_prepared",
    "runtime.activity.execution.tool_output_collected",
    "runtime.activity.execution.tool_result_returned",
    "runtime.activity.execution.requesting_next_model_turn",
    "runtime.activity.execution.processing_tool_calls",
    "runtime.activity.guard.normalized_approved",
    "runtime.activity.guard.accepted",
    "runtime.activity.guard.normalized_continued",
    "runtime.activity.guard.accepted_execution",
    "runtime.activity.guard.rejected",
    "runtime.activity.execution_title.direct_answer",
    "runtime.activity.execution_title.tool_execution",
    "runtime.pending_user_input.summary",
    "runtime.tool.failed",
    "runtime.tool.guard.outside_boundary",
    "runtime.tool.guard.arguments_invalid",
    "runtime.tool.guard.arguments_not_object",
    "runtime.tool.guard.rejected_call",
    "runtime.tool.guard.unknown_tool",
    "runtime.tool.guard.policy_blocked",
    "runtime.tool.guard.schema_invalid",
    "runtime.tool.summary.read_chars",
    "runtime.tool.summary.listed_entries",
    "runtime.tool.summary.file_matches",
    "runtime.tool.summary.search_results",
    "runtime.tool.summary.search_matches",
    "runtime.tool.summary.read_section_chars",
    "runtime.tool.summary.web_status",
    "runtime.tool.summary.web_status_title",
    "runtime.tool.summary.downloaded_file",
    "runtime.tool.summary.image_read",
    "runtime.tool.summary.patch_applied",
    "runtime.tool.summary.exec_command",
    "runtime.tool.summary.plan_updated",
    "runtime.tool.summary.user_input_required",
    "runtime.tool.validation.unavailable",
    "runtime.tool.validation.matched",
    "runtime.tool.validation.tool_unavailable",
    "runtime.budget.same_action_repeat",
    "runtime.budget.no_progress_after_replan",
    "runtime.budget.guard_rejections",
    "runtime.progress.new_error_type",
    "runtime.progress.repeated_error",
    "runtime.progress.new_file_read",
    "runtime.progress.new_directory_entries",
    "runtime.progress.new_glob_matches",
    "runtime.progress.new_search_hits",
    "runtime.progress.new_section_read",
    "runtime.progress.patch_applied",
    "runtime.progress.test_result_changed",
    "runtime.progress.command_result_changed",
    "runtime.progress.plan_updated",
    "runtime.progress.new_web_result",
    "runtime.progress.new_tool_output",
    "runtime.progress.no_new_info",
    "runtime.progress.duplicate_result",
    "runtime.replan.requested",
    "runtime.replan.system_prompt",
    "runtime.replan.known_facts_intro",
    "runtime.replan.failed_actions_intro",
    "runtime.replan.required_next_move",
)


def _proposal_block(**overrides: Any) -> str:
    payload = {
        "intent": "transform",
        "task_type": "rewrite_review",
        "current_goal": "Answer directly from the provided context.",
        "expects_tools": False,
        "response_mode": "direct_answer",
        "user_stage": "Direct answer generation",
        "summary": "Answer directly from the provided context.",
        "next_step_hint": "Prepare the user-facing answer directly.",
        "change_summary_requested": False,
    }
    payload.update(overrides)
    return f"<model_proposal>{json.dumps(payload, ensure_ascii=False)}</model_proposal>"


class _FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        self.content = content
        self.tool_calls = list(tool_calls or [])
        self.kwargs = kwargs


class _FakeTools:
    def __init__(self) -> None:
        self.tool_specs = [
            {"name": "exec_command", "description": "exec command", "parameters": {}},
            {"name": "write_stdin", "description": "write stdin", "parameters": {}},
            {
                "name": "read_file",
                "description": "read one file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {"name": "list_dir", "description": "list one directory", "parameters": {}},
            {"name": "glob_file_search", "description": "find files by glob pattern", "parameters": {}},
            {"name": "search_contents_in_file", "description": "search one file", "parameters": {}},
            {"name": "search_contents_in_file_multi", "description": "search one file with multiple queries", "parameters": {}},
            {"name": "read_section", "description": "read one section by heading", "parameters": {}},
            {"name": "table_extract", "description": "extract document tables", "parameters": {}},
            {"name": "fact_check_file", "description": "fact check one file", "parameters": {}},
            {
                "name": "search_codebase",
                "description": "search codebase",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "web_search",
                "description": "search web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "web_fetch",
                "description": "fetch web",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
            {"name": "web_download", "description": "download remote file", "parameters": {}},
            {"name": "browser_open", "description": "browser open", "parameters": {}},
            {"name": "sessions_list", "description": "list sessions", "parameters": {}},
            {"name": "sessions_history", "description": "session history", "parameters": {}},
            {"name": "image_inspect", "description": "inspect image", "parameters": {}},
            {"name": "image_read", "description": "read image content", "parameters": {}},
            {"name": "archive_extract", "description": "extract archive", "parameters": {}},
            {"name": "mail_extract_attachments", "description": "extract mail attachments", "parameters": {}},
            {"name": "apply_patch", "description": "apply patch", "parameters": {}},
            {"name": "update_plan", "description": "update plan", "parameters": {}},
            {"name": "request_user_input", "description": "request user input", "parameters": {}},
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.runtime_context: dict[str, Any] | None = None
        self.last_runtime_context: dict[str, Any] | None = None

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
    ) -> None:
        payload = {
            "execution_mode": execution_mode,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "cwd": cwd,
            "model": model,
        }
        self.runtime_context = payload
        self.last_runtime_context = dict(payload)

    def clear_runtime_context(self) -> None:
        self.runtime_context = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": True,
            "name": name,
            "project_root": str((self.runtime_context or {}).get("project_root") or ""),
            "cwd": str((self.runtime_context or {}).get("cwd") or ""),
        }


class _FakeToolsWithoutModel(_FakeTools):
    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
    ) -> None:
        payload = {
            "execution_mode": execution_mode,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "cwd": cwd,
        }
        self.runtime_context = payload
        self.last_runtime_context = dict(payload)


class _FakeBackend:
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        self.tools = _FakeTools()
        self._scripted_messages = list(scripted_messages)
        self.invocations: list[dict[str, Any]] = []
        self._SystemMessage = _FakeMessage
        self._HumanMessage = _FakeMessage
        self._ToolMessage = _FakeMessage

    def _next(self) -> _FakeMessage:
        if self._scripted_messages:
            return self._scripted_messages.pop(0)
        return _FakeMessage(content="fallback")

    def _empty_usage(self) -> dict[str, int]:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}

    def _merge_usage(self, left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        merged = dict(left)
        for key, value in right.items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
        return merged

    def _extract_usage_from_message(self, _message: Any) -> dict[str, int]:
        return self._empty_usage()

    def _content_to_text(self, content: Any) -> str:
        return str(content or "")

    def _shorten(self, value: Any, limit: int) -> str:
        return str(value or "")[: max(0, int(limit))]

    def _invoke_chat_with_runner(
        self,
        *,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = (max_output_tokens, enable_tools, tool_names)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "initial"})
        return self._next(), object(), model, []

    def _invoke_with_runner_recovery(
        self,
        *,
        runner: Any,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = (runner, max_output_tokens, enable_tools, tool_names)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "followup"})
        return self._next(), object(), model, []


class _FakeBackendWithoutModelContext(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        super().__init__(scripted_messages)
        self.tools = _FakeToolsWithoutModel()


class _StreamingBackend(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], *, deltas: list[str]) -> None:
        super().__init__(scripted_messages)
        self._deltas = list(deltas)

    def _invoke_chat_with_runner(
        self,
        *,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb=None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = (max_output_tokens, enable_tools, tool_names)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "initial"})
        if event_cb is not None:
            for delta in self._deltas:
                event_cb({"type": "response.output_text.delta", "delta": delta, "timestamp": 1.0})
            event_cb(
                {
                    "type": "response.completed",
                    "timestamp": 2.0,
                    "diagnostics": {
                        "provider": "codex_auth",
                        "event_count": len(self._deltas) + 1,
                        "text_delta_count": len(self._deltas),
                        "text_chars": sum(len(item) for item in self._deltas),
                        "completed_at": 2.0,
                    },
                }
            )
        return self._next(), object(), model, []

    def _invoke_with_runner_recovery(
        self,
        *,
        runner: Any,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb=None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = runner
        return self._invoke_chat_with_runner(
            messages=messages,
            model=model,
            max_output_tokens=max_output_tokens,
            enable_tools=enable_tools,
            tool_names=tool_names,
            event_cb=event_cb,
        )


class _CancellingTools(_FakeTools):
    def __init__(self, cancel_event: threading.Event, *, cancel_after_calls: int = 1) -> None:
        super().__init__()
        self._cancel_event = cancel_event
        self._cancel_after_calls = max(1, int(cancel_after_calls))

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().execute(name, arguments)
        if len(self.calls) >= self._cancel_after_calls:
            self._cancel_event.set()
        return result


class _FakeImageReadTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "image_read":
            self.calls.append((name, dict(arguments)))
            path = str(arguments.get("path") or "")
            return {
                "ok": True,
                "path": path,
                "mime": "image/png",
                "width": 494,
                "height": 102,
                "visible_text": "Vintage\nVP\nnew_validation_agent",
                "analysis": "Extracted visible text from the image using local OCR.",
                "summary": "image_read · ocr_only · rapidocr",
                "diagnostics": {
                    "engines_tried": ["rapidocr"],
                    "ocr_available": True,
                    "ocr_engine": "rapidocr",
                    "fallback_reason": "no_runtime_image_reader",
                    "read_strategy": "ocr_only",
                    "visible_text_preview": "Vintage / VP / new_validation_agent",
                },
            }
        return super().execute(name, arguments)


class _FakeBackendWithTools(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], tools: _FakeTools) -> None:
        super().__init__(scripted_messages)
        self.tools = tools


def _write_specs(agent_dir: Path, *, include_soul: bool = True, include_tools: bool = True) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    if include_soul:
        (agent_dir / "soul.md").write_text("soul rules", encoding="utf-8")
    (agent_dir / "identity.md").write_text(
        "# Identity\n\n角色定义：\n- primary agent\n",
        encoding="utf-8",
    )
    (agent_dir / "agent.md").write_text(
        "---\n"
        "id: vintage_programmer\n"
        "title: Vintage Programmer\n"
        "default_model: gpt-test\n"
        "tool_policy: read_only\n"
        "network_mode: explicit_tools\n"
        "approval_policy: on_failure_or_high_impact\n"
        "evidence_policy: required_for_external_or_runtime_facts\n"
        "collaboration_modes:\n"
        "  - default\n"
        "  - plan\n"
        "  - execute\n"
        "max_tool_rounds: 4\n"
        "---\n"
        "\n"
        "agent workflow\n",
        encoding="utf-8",
    )
    if include_tools:
        (agent_dir / "tools.md").write_text("tool rules", encoding="utf-8")


def _isolated_config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_runtime_requires_soul_and_agent_specs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir, include_soul=False)

    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    with pytest.raises(RuntimeError, match="Missing required agent spec file"):
        runtime.descriptor()

    agent_dir = tmp_path / "agents" / "missing_identity"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "soul.md").write_text("soul", encoding="utf-8")
    (agent_dir / "agent.md").write_text("---\nid: vintage_programmer\n---\nagent\n", encoding="utf-8")
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    with pytest.raises(RuntimeError, match="Missing required agent spec file"):
        runtime.descriptor()


def test_runtime_parses_frontmatter_and_prompt_order(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )

    descriptor = runtime.descriptor()
    spec = runtime._load_spec()
    prompt = runtime._render_system_prompt(ChatSettings(model="gpt-test"), spec=spec, loaded_skills=[])

    assert descriptor["agent_id"] == "vintage_programmer"
    assert descriptor["tool_policy"] == "read_only"
    assert descriptor["network"]["mode"] == "explicit_tools"
    assert descriptor["network"]["web_tool_contract"] == ["web_search", "web_fetch", "web_download"]
    assert descriptor["workflow"]["modes"] == ["default", "plan", "execute"]
    assert "max_tool_rounds" not in descriptor
    assert descriptor["loop_safeguards"]["max_total_tool_calls_per_turn"] > 0
    assert prompt.index("[soul.md]") < prompt.index("[identity.md]") < prompt.index("[agent.md]") < prompt.index("[tools.md]")
    assert "Use tools when needed." in prompt
    assert "Execution must happen through tool calls." not in prompt


def test_runtime_activity_copy_has_locale_parity() -> None:
    for locale in ("zh-CN", "ja-JP", "en"):
        for key in REQUIRED_RUNTIME_ACTIVITY_KEYS:
            assert translate(locale, key) != key, f"{locale} missing {key}"


def test_runtime_activity_helpers_use_requested_locale() -> None:
    assert VintageProgrammerRuntime._validation_activity_detail(
        "zh-CN",
        {"accepted": True, "action_type": "direct_answer"},
    ) == translate("zh-CN", "runtime.activity.validation.direct_answer")
    assert VintageProgrammerRuntime._execution_activity_detail("ja-JP", {}) == translate(
        "ja-JP",
        "runtime.activity.execution.recorded",
    )
    assert VintageProgrammerRuntime._tool_guard_activity_detail(
        "en",
        {"status": "accepted", "tool_name": "read_file"},
    ) == translate("en", "runtime.activity.guard.accepted_execution", tool="read_file")


def test_runtime_answers_self_contained_text_tasks_without_forcing_tools(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="SSE 是 Server-Sent Events。")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="解释一下 SSE 是什么",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-direct-answer",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "SSE 是 Server-Sent Events。"
    assert backend.tools.calls == []
    assert result["activity"]["trace_events"]


def test_runtime_emits_streamed_answer_deltas_and_activity_for_direct_answers(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _StreamingBackend(
        [_FakeMessage(content=f"{_proposal_block(summary='Polish the sentence directly.')}streamed answer")],
        deltas=[
            _proposal_block(summary="Polish the sentence directly."),
            "streamed ",
            "answer",
        ],
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="把这句日语润色一下",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-streaming",
            "run_id": "run-streaming",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    delta_events = [item for item in progress_events if str(item.get("event") or "") == "item/agentMessage/delta"]
    trace_payloads = [dict(item.get("trace") or {}) for item in progress_events if str(item.get("event") or "") == "trace_event"]
    trace_types = [str(item.get("type") or "") for item in trace_payloads]
    answer_delta_traces = [item for item in trace_payloads if str(item.get("type") or "") == "answer.delta"]

    assert [item["delta"] for item in delta_events] == ["streamed ", "answer"]
    assert result["text"] == "streamed answer"
    assert result["answer_stream"]["streamed"] is True
    assert result["answer_stream"]["upstream_progressive"] is True
    assert "activity.started" in trace_types
    assert "activity.done" in trace_types
    assert "answer.started" in trace_types
    assert len(answer_delta_traces) == 2
    assert all(item.get("visible") is True for item in answer_delta_traces)
    assert "answer.done" in trace_types


def test_runtime_emits_non_tool_activity_details_and_revision_summary(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _StreamingBackend(
        [
            _FakeMessage(
                content=(
                    _proposal_block(
                        intent="transform",
                        task_type="japanese_grammar_review",
                        current_goal="Polish the Japanese sentence and produce the revised version.",
                        expects_tools=False,
                        response_mode="revision_with_change_summary",
                        user_stage="Japanese grammar cleanup",
                        summary="Polish the Japanese sentence directly and include a short change summary.",
                        next_step_hint="Return the revised sentence directly.",
                        change_summary_requested=True,
                    )
                    + "今日は駅へ行きます。"
                )
            )
        ],
        deltas=[_proposal_block(summary="Polish the Japanese sentence directly and include a short change summary."), "今日は駅へ", "行きます。"],
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="请把这句日语润色一下：今日は駅に行きます。",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-jp-revision",
            "run_id": "run-jp-revision",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
            "route_state": {
                "task_type": "followup_transform",
                "primary_intent": "transform",
                "execution_policy": "grounded_generation_pipeline",
                "use_revision": True,
            },
        },
        progress_cb=progress_events.append,
    )

    trace_payloads = [dict(item.get("trace") or {}) for item in progress_events if str(item.get("event") or "") == "trace_event"]
    proposal_done = next(
        item
        for item in trace_payloads
        if str(item.get("type") or "") == "activity.done"
        and str(((item.get("payload") or {}).get("activity") or {}).get("stage") or "") == "high_level_proposal"
    )
    step_validation_done = next(
        item
        for item in trace_payloads
        if str(item.get("type") or "") == "activity.done"
        and str(((item.get("payload") or {}).get("activity") or {}).get("stage") or "") == "step_validation"
    )
    execution_done = next(
        item
        for item in trace_payloads
        if str(item.get("type") or "") in {"activity.done", "activity.delta"}
        and str(((item.get("payload") or {}).get("activity") or {}).get("stage") or "") == "execution"
    )
    answer_done = next(item for item in trace_payloads if str(item.get("type") or "") == "answer.done")
    revision_summary = dict((answer_done.get("payload") or {}).get("revision_summary") or {})
    summary_items = list(revision_summary.get("items") or [])
    proposal_payload = dict((proposal_done.get("payload") or {}).get("high_level_proposal") or {})
    validated_payload = dict((step_validation_done.get("payload") or {}).get("validated_next_step") or {})
    execution_payload = dict((execution_done.get("payload") or {}).get("execution_trace_entry") or {})

    assert proposal_payload["task_type"] == "japanese_grammar_review"
    assert proposal_payload["response_mode"] == "revision_with_change_summary"
    assert validated_payload["action_type"] == "direct_answer"
    assert validated_payload["accepted"] is True
    assert revision_summary["task_type"] == "japanese_grammar_review"
    assert summary_items
    assert summary_items[0]["original_excerpt"] == "今日は駅に行きます。"
    assert "今日は駅へ行きます。" in summary_items[0]["result_excerpt"]
    assert execution_payload["action_type"] == "direct_answer"
    assert result["high_level_proposal"]["task_type"] == "japanese_grammar_review"
    assert result["validated_next_step"]["action_type"] == "direct_answer"
    assert result["execution_trace"]
    assert result["execution_trace"][-1]["action_type"] == "direct_answer"


def test_runtime_runs_single_agent_tool_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content=_proposal_block(
                    intent="research",
                    task_type="web_research",
                    current_goal="Use web search to gather the latest evidence before answering.",
                    expects_tools=True,
                    response_mode="direct_answer",
                    user_stage="Gather evidence with web tools",
                    summary="Use web search before answering.",
                    next_step_hint="Run web search and revise the next proposal from the result.",
                ),
                tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}],
            ),
            _FakeMessage(content="final answer"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="帮我查一下最新情况",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-1",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["text"] == "final answer"
    assert result["agent_id"] == "vintage_programmer"
    assert len(result["tool_events"]) == 1
    assert backend.tools.calls[0][0] == "web_search"
    assert backend.tools.last_runtime_context["project_id"] == "project_demo"
    assert backend.tools.last_runtime_context["model"] == "gpt-test"
    assert result["inspector"]["agent"]["tool_policy"] == "read_only"
    assert result["inspector"]["run_state"]["collaboration_mode"] == "default"
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert result["inspector"]["session"]["project_root"] == str(tmp_path)
    assert result["tool_events"][0]["project_root"] == str(tmp_path)
    assert result["high_level_proposal"]["task_type"] == "web_research"
    assert result["validated_next_step"]["action_type"] == "direct_answer"
    assert result["validated_next_step"]["accepted"] is True
    assert result["execution_trace"]
    assert result["execution_trace"][0]["action_type"] == "tool_call"
    assert result["execution_trace"][-1]["action_type"] == "direct_answer"
    assert result["tool_events"][0]["arguments_preview"] == "query=latest"
    assert result["tool_events"][0]["schema_validation"]["status"] == "valid"
    assert result["tool_events"][0]["guard_result"]["status"] == "accepted"
    tool_progress = next(item for item in progress_events if str(item.get("event") or "") == "tool")
    assert tool_progress["item"]["raw_arguments"]["query"] == "latest"
    assert tool_progress["item"]["normalized_arguments"]["query"] == "latest"
    assert tool_progress["item"]["arguments_preview"] == "query=latest"
    assert tool_progress["item"]["schema_validation"]["status"] == "valid"
    trace_types = [item["type"] for item in result["activity"]["trace_events"]]
    assert "run.started" in trace_types
    assert "runtime_contract.selected" in trace_types
    assert "activity.started" in trace_types
    assert "activity.delta" in trace_types
    assert "tool.started" in trace_types
    assert "tool.finished" in trace_types
    assert "run.finished" in trace_types
    assert result["model_proposal"]["task_type"] == result["high_level_proposal"]["task_type"]
    assert result["validated_plan"]["action_type"] == result["validated_next_step"]["action_type"]


def test_runtime_guard_normalizes_alias_arguments_and_executes_tool(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"q": "PLAN.md"}}]),
            _FakeMessage(content="normalized tool loop done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 PLAN.md",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-normalized-tool-guard",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "normalized tool loop done"
    assert backend.tools.calls == [("web_search", {"query": "PLAN.md"})]
    assert result["tool_events"][0]["raw_tool_call"]["name"] == "web_search"
    assert result["tool_events"][0]["raw_arguments"]["q"] == "PLAN.md"
    assert result["tool_events"][0]["normalized_arguments"]["query"] == "PLAN.md"
    assert result["tool_events"][0]["guard_result"]["status"] == "normalized"
    assert "q->query" in result["tool_events"][0]["guard_result"]["normalization_notes"]


def test_runtime_guard_rejects_removed_legacy_tool_name_and_returns_tool_error_to_model(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read", "args": {"path": "README.md"}}]),
            _FakeMessage(content="I revised the tool choice after the guard rejection."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="读取 README.md",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-tool-guard-rejected",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "I revised the tool choice after the guard rejection."
    assert backend.tools.calls == []
    assert result["tool_events"][0]["guard_result"]["status"] == "rejected"
    assert result["tool_events"][0]["status"] == "error"
    assert result["tool_events"][0]["raw_tool_call"]["name"] == "read"
    assert len(backend.invocations) == 2
    followup_messages = backend.invocations[1]["messages"]
    tool_message = next(item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc1")
    assert "\"kind\": \"tool_call_rejected\"" in str(tool_message.content)
    assert "\"tool\": \"read\"" in str(tool_message.content)


def test_runtime_guard_rejects_schema_mismatch_then_model_retries_with_valid_tool(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": {"text": "PLAN.md"}}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "web_search", "args": {"query": "PLAN.md"}}]),
            _FakeMessage(content="retry succeeded"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 PLAN.md",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-tool-guard-schema-retry",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "retry succeeded"
    assert backend.tools.calls == [("web_search", {"query": "PLAN.md"})]
    assert len(result["tool_events"]) == 2
    assert result["tool_events"][0]["guard_result"]["status"] == "rejected"
    assert result["tool_events"][0]["schema_validation"]["status"] == "invalid"
    assert result["tool_events"][1]["guard_result"]["status"] == "accepted"


def test_runtime_loads_project_contract_from_agents_md(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    (tmp_path / "AGENTS.md").write_text("Project contract: model-led turn planning only.", encoding="utf-8")
    backend = _FakeBackend([_FakeMessage(content=f"{_proposal_block()}done")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    runtime.run(
        message="直接回答",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-agents",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    system_prompt = str(backend.invocations[0]["messages"][0].content or "")
    assert "[AGENTS.md]" in system_prompt
    assert "Project contract: model-led turn planning only." in system_prompt


def test_invalid_final_guard_steers_authorized_write_into_tool_call(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_policy: read_only", "tool_policy: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="如果你确认要我修改，我可以给你补丁。请回一句补。"),
            _FakeMessage(content="", tool_calls=[{"id": "tc-patch", "name": "apply_patch", "args": {"patch": "*** Begin Patch\n*** End Patch\n"}}]),
            _FakeMessage(content="已经补齐。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="我有版本控制，你大胆修改，缺少的直接补全。",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-guard",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [],
        },
    )

    assert backend.tools.calls and backend.tools.calls[0][0] == "apply_patch"
    assert result["invalid_final_guard"]["triggered"] is True
    assert "invalid_final_guard_steer" in result["inspector"]["notes"]
    assert result["turn_status"] == "completed"


def test_invalid_final_guard_blocks_repeated_confirmation_after_authorization(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_policy: read_only", "tool_policy: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="请确认，我再 apply_patch。"),
            _FakeMessage(content="需要你再回一句补，我才能修改。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="直接补全缺少功能，大胆修改。",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-guard-block",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [],
        },
    )

    assert backend.tools.calls == []
    assert result["turn_status"] == "blocked"
    assert result["blocked_reason"] == "model_refused_to_act_after_authorization"
    assert result["invalid_final_guard"]["attempts"] == 2


def test_runtime_injects_attachment_evidence_pack_into_model_context(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="根据资料补齐完成")])
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查看资料，缺的直接补全。",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-evidence",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [],
            "attachment_evidence_pack": [
                {
                    "id": "a1",
                    "name": "requirements.pdf",
                    "kind": "document",
                    "summary": "missing export button",
                    "read_hint": {"tool": "read_file", "path": "/tmp/requirements.pdf"},
                }
            ],
        },
    )

    first_messages = backend.invocations[0]["messages"]
    human_payload = str(first_messages[-1].content)
    assert "attachment_evidence_pack" in human_payload
    assert "missing export button" in human_payload
    assert result["attachment_evidence_pack_preview"][0]["name"] == "requirements.pdf"


def test_runtime_can_continue_past_legacy_max_tool_rounds_with_internal_budget(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "one"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "search_codebase", "args": {"query": "needle"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "web_fetch", "args": {"url": "https://example.com"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "sessions_list", "args": {"limit": 5}}]),
            _FakeMessage(content="long loop done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="继续工作直到完成",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-long-loop",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "long loop done"
    assert len(result["tool_events"]) == 5
    assert [item["name"] for item in result["tool_events"]] == [
        "web_search",
        "read_file",
        "search_codebase",
        "web_fetch",
        "sessions_list",
    ]
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert "tool_round_limit" not in result["inspector"]["run_state"]
    assert result["inspector"]["run_state"]["loop_safeguards"]["max_total_tool_calls_per_turn"] > 0


def test_runtime_blocks_when_same_action_repeats_after_replan(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc6", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="should not reach"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="持续搜索直到有结果",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-repeat-budget",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "blocked"
    assert any(
        note in {"replan_requested:no_progress", "replan_requested:same_action_repeat"}
        for note in result["inspector"]["notes"]
    )
    assert "turn_budget_same_action_repeats_exceeded" in result["inspector"]["notes"]
    assert result["inspector"]["run_state"]["replan_history"][0]["trigger"] in {"no_progress", "same_action_repeat"}
    assert "should not reach" not in result["text"]


def test_runtime_different_read_file_paths_do_not_count_as_same_action_repeat(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "a.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read_file", "args": {"path": "b.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "read_file", "args": {"path": "c.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "read_file", "args": {"path": "d.py"}}]),
            _FakeMessage(content="done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="依次读取几个不同文件再结束",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-different-read-paths",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert [item["name"] for item in result["tool_events"]] == ["read_file", "read_file", "read_file", "read_file"]
    assert "turn_budget_same_action_repeats_exceeded" not in result["inspector"]["notes"]
    assert any(
        signal["kind"] == "new_file_read" and signal["has_progress"]
        for signal in result["inspector"]["run_state"]["progress_signals"]
    )


def test_runtime_replans_after_repeated_no_progress_searches(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="replanned answer"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="先搜索，没有结果时换思路",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-replan-no-progress",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "replanned answer"
    assert "replan_requested:no_progress" in result["inspector"]["notes"]
    assert result["inspector"]["run_state"]["replan_history"][0]["trigger"] == "no_progress"
    assert any(
        signal["kind"] == "no_new_info"
        for signal in result["inspector"]["run_state"]["progress_signals"]
    )


def test_runtime_cancels_turn_when_cancel_event_is_set(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    cancel_event = threading.Event()
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}]),
            _FakeMessage(content="should not reach"),
        ],
        _CancellingTools(cancel_event, cancel_after_calls=1),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="先开始，再取消",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-cancelled",
            "cancel_event": cancel_event,
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "cancelled"
    assert result["text"] == translate(ChatSettings().locale, "runtime.cancelled.text")
    assert len(result["tool_events"]) == 1
    assert "run_cancelled_by_user" in result["inspector"]["notes"]


def test_runtime_steers_image_attachment_requests_into_image_read(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
            _FakeMessage(content="", tool_calls=[{"id": "tc-image", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="图片里写着 hello world"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我看看这张图里写了什么",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里写着 hello world"
    assert result["inspector"]["run_state"]["requires_tools"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert "attachment_tooling_expected" in result["inspector"]["notes"]
    assert "image_attachment_context" in result["inspector"]["notes"]


def test_runtime_rewrites_image_tool_arguments_from_attachment_refs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_read", "args": {"image_path": "img-1"}}],
            ),
            _FakeMessage(content="done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我读图",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-ref",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "done"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}


def test_runtime_aliases_image_analysis_tool_name_and_attachment_ref(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_analysis", "args": {"image_path": "img-1"}}],
            ),
            _FakeMessage(content="图片里是登录报错截图"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="解释图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-alias",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里是登录报错截图"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}
    assert "tool_alias:image_analysis->image_read" in result["inspector"]["notes"]


def test_runtime_aliases_image_tool_name_and_uses_single_attached_image(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_tool", "args": {}}],
            ),
            _FakeMessage(content="图片里是一个登录页截图"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-tool-alias",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里是一个登录页截图"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}
    assert "tool_alias:image_tool->image_read" in result["inspector"]["notes"]


def test_runtime_auto_rescues_missing_context_reply_for_image_attachments(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="我需要更多上下文后才能操作这张图片。"),
            _FakeMessage(content="我理解你希望我进行操作，但是你没有提供任何任务或上下文。"),
            _FakeMessage(content="图片里显示的是 Vintage Programmer 的首页。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-auto-rescue",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里显示的是 Vintage Programmer 的首页。"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert "strict_agentic_act_now_steer" in result["inspector"]["notes"]
    assert "auto_image_read_rescue" in result["inspector"]["notes"]


def test_runtime_finishes_with_image_read_fallback_after_repeat_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "image_read", "args": {"path": str(image_path)}}]),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-repeat-fallback",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["turn_status"] == "completed"
    assert "Vintage" in result["text"]
    assert "new_validation_agent" in result["text"]
    assert len(result["tool_events"]) == 5
    assert any(
        note in {"image_read_repeat_fallback_answer", "image_read_result_forced_summary"}
        for note in result["inspector"]["notes"]
    )


def test_runtime_forces_tool_based_summary_for_generic_image_read_requests(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="产品名称是 MetaPixel，Logo 也是 MetaPixel。"),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-forced-summary",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert "MetaPixel" not in result["text"]
    assert "Vintage" in result["text"]
    assert "new_validation_agent" in result["text"]
    assert "image_read_result_forced_summary" in result["inspector"]["notes"]
    assert result["tool_events"][0]["diagnostics"]["ocr_engine"] == "rapidocr"
    assert "Vintage" in result["tool_events"][0]["diagnostics"]["visible_text_preview"]


def test_runtime_restores_task_checkpoint_for_followup_turn(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="继续沿用当前任务上下文处理")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="让其修改",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-followup-task",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "route_state": {
                "task_checkpoint": {
                    "task_id": "task-1",
                    "goal": "Inspect the current code and patch it",
                    "project_root": str(tmp_path),
                    "cwd": str(tmp_path),
                    "active_files": [str(tmp_path / "app.py")],
                    "active_attachments": [],
                    "last_completed_step": "read_file: app.py",
                    "next_action": "modify app.py",
                }
            },
        },
    )

    assert result["inspector"]["run_state"]["goal"] == "Inspect the current code and patch it"
    assert result["inspector"]["run_state"]["task_checkpoint"]["task_id"] == "task-1"
    assert result["route_state"]["task_checkpoint"]["active_files"] == [str(tmp_path / "app.py")]
    assert "task_checkpoint_restored" in result["inspector"]["notes"]


def test_runtime_updates_task_checkpoint_from_successful_tool(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="图片里是 Vintage Programmer 的首页"),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-task-checkpoint",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    checkpoint = result["route_state"]["task_checkpoint"]
    assert checkpoint["cwd"] == str(tmp_path)
    assert checkpoint["active_files"] == [str(image_path)]
    assert checkpoint["active_attachments"][0]["id"] == "img-1"
    assert checkpoint["last_completed_step"].startswith("image_read:")


def test_runtime_handles_runtime_context_setters_without_model_kwarg(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackendWithoutModelContext(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}]),
            _FakeMessage(content="ok"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我查一下最新情况",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-no-model-kw",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
        },
    )

    assert result["text"] == "ok"
    assert backend.tools.calls == [("web_search", {"query": "latest"})]
    assert backend.tools.last_runtime_context == {
        "execution_mode": None,
        "session_id": "s-no-model-kw",
        "project_id": "",
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
    }


def test_runtime_auto_rescues_image_attachment_turn_when_model_refuses_to_use_tools(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
            _FakeMessage(content="我还是无法直接对图像执行 OCR。"),
            _FakeMessage(content="我已经根据工具结果读取了这张截图。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我读一下这张截图",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-blocked",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert [item["name"] for item in result["tool_events"]] == ["image_read"]
    assert result["inspector"]["run_state"]["requires_tools"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert "strict_agentic_act_now_steer" in result["inspector"]["notes"]
    assert "auto_image_read_rescue" in result["inspector"]["notes"]


def test_runtime_loads_enabled_skills_and_skips_workspace_nudge_for_inline_code(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "workspace" / "skills" / "inline_helper"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: inline_helper\n"
        "title: Inline Helper\n"
        "enabled: true\n"
        "bind_to:\n"
        "  - vintage_programmer\n"
        "summary: Helps with inline pasted code.\n"
        "---\n\n"
        "# Inline Helper\n\n"
        "When the user pastes code directly, analyze it in place.\n",
        encoding="utf-8",
    )
    backend = _FakeBackend([_FakeMessage(content="inline analysis complete")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="请直接分析这段代码，不要去 workspace 里再找：\n```python\nclass A:\n    def run(self):\n        return 1\n```\n这里哪里有问题？",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-inline", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert result["text"] == "inline analysis complete"
    assert result["inspector"]["run_state"]["inline_document"] is True
    assert result["inspector"]["run_state"]["requires_tools"] is False
    assert result["inspector"]["loaded_skills"][0]["id"] == "inline_helper"


def test_runtime_treats_short_pasted_code_as_direct_context_even_with_fix_language(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="直接分析短代码")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我修一下这段代码：\ndef f(x):\n    return x +\n报错在哪里？",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-short-inline", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert result["text"] == "直接分析短代码"
    assert result["inspector"]["run_state"]["requires_tools"] is False
