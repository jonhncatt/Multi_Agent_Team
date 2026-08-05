from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from app.config import load_config
from app.context_meter import build_context_window_status
from app.i18n import translate
from app.models import ChatSettings, ToolEvent
from app.runtime_boundary import RuntimeBoundary
from app.answer_stream_state import new_answer_stream_state
from app import vintage_programmer_runtime as runtime_module
from app.vintage_programmer_runtime import VintageProgrammerRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RUNTIME_ACTIVITY_KEYS = (
    "runtime.activity.summary.japanese_cleanup_requested",
    "runtime.activity.summary.rewrite_requested",
    "runtime.activity.summary.direct_answer_path",
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
    "runtime.budget.detail.title",
    "runtime.budget.detail.reason",
    "runtime.budget.detail.suggestion",
    "runtime.budget.detail.model_action_empty",
    "runtime.budget.detail.unknown",
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
)


def test_stream_transaction_id_is_unique_when_provider_reuses_call_id() -> None:
    first = VintageProgrammerRuntime._typed_tool_item_id(
        run_id="run-1",
        raw_tool_call={"id": "duplicate-call"},
        tool_name="read_file",
        round_idx=1,
        call_idx=1,
    )
    second = VintageProgrammerRuntime._typed_tool_item_id(
        run_id="run-1",
        raw_tool_call={"id": "duplicate-call"},
        tool_name="read_file",
        round_idx=2,
        call_idx=1,
    )

    assert first != second
    assert first.endswith(":duplicate-call")
    assert second.endswith(":duplicate-call")


class _FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        self.content = content
        self.tool_calls = list(tool_calls or [])
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeSystemMessage(_FakeMessage):
    pass


class _FakeHumanMessage(_FakeMessage):
    pass


class _FakeAIMessage(_FakeMessage):
    pass


class _FakeToolMessage(_FakeMessage):
    pass


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
                    "properties": {
                        "query": {"type": "string"},
                        "root": {"type": "string", "default": "."},
                    },
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
            {
                "name": "spawn_subagent",
                "description": "delegate a bounded read-heavy task",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "role": {"type": "string", "default": "explorer"},
                        "label": {"type": "string", "default": ""},
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "wait_subagents",
                "description": "wait for subagents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subagent_ids": {"type": "array", "items": {"type": "string"}},
                        "timeout_seconds": {"type": "number", "default": 30},
                    },
                    "additionalProperties": False,
                },
            },
            {"name": "request_user_input", "description": "request user input", "parameters": {}},
            {
                "name": "save_skill",
                "description": "save workspace skill",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "body": {"type": "string"},
                        "enabled": {"type": "boolean"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["name", "description", "body"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_tasks",
                "description": "search durable task snapshots",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "status": {"type": "string"},
                        "project_scope": {"type": "string"},
                        "include_archived": {"type": "boolean"},
                        "detail_level": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "save_task",
                "description": "save durable task snapshot",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "title": {"type": "string"},
                        "goal": {"type": "string"},
                        "summary": {"type": "string"},
                        "progress": {"type": "array", "items": {"type": "string"}},
                        "next_steps": {"type": "array", "items": {"type": "string"}},
                        "decisions": {"type": "array", "items": {"type": "string"}},
                        "blockers": {"type": "array", "items": {"type": "string"}},
                        "artifacts": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                        "approval_token": {"type": "string"},
                    },
                    "required": ["title", "goal", "summary"],
                    "additionalProperties": False,
                },
            },
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.runtime_context: dict[str, Any] | None = None
        self.last_runtime_context: dict[str, Any] | None = None
        self.skill_writer: Any | None = None
        self.task_lister: Any | None = None
        self.task_writer: Any | None = None
        self.subagent_runner: Any | None = None
        self.subagent_waiter: Any | None = None

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        skill_writer: Any | None = None,
        task_lister: Any | None = None,
        task_writer: Any | None = None,
        subagent_runner: Any | None = None,
        subagent_waiter: Any | None = None,
    ) -> None:
        self.skill_writer = skill_writer
        self.task_lister = task_lister
        self.task_writer = task_writer
        self.subagent_runner = subagent_runner
        self.subagent_waiter = subagent_waiter
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
        self.task_lister = None
        self.task_writer = None
        self.subagent_runner = None
        self.subagent_waiter = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if name == "save_skill" and callable(self.skill_writer):
            return self.skill_writer(**arguments)
        if name == "list_tasks" and callable(self.task_lister):
            project_scope = str(arguments.get("project_scope") or "current_project")
            rows = self.task_lister(
                project_id=(
                    None
                    if project_scope == "all_projects"
                    else str((self.runtime_context or {}).get("project_id") or "")
                ),
                include_archived=bool(arguments.get("include_archived")),
                limit=int(arguments.get("limit") or 20),
            )
            return {"ok": True, "tasks": list(rows or [])}
        if name == "save_task" and callable(self.task_writer):
            return self.task_writer(**arguments)
        if name == "spawn_subagent" and callable(self.subagent_runner):
            return self.subagent_runner(**arguments)
        if name == "wait_subagents" and callable(self.subagent_waiter):
            return self.subagent_waiter(**arguments)
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


class _BoundaryCapturingTools(_FakeTools):
    def __init__(self) -> None:
        super().__init__()
        self.runtime_boundaries: list[dict[str, Any]] = []
        self.runtime_contexts: list[dict[str, Any]] = []

    def set_runtime_context(self, **kwargs: Any) -> None:
        self.runtime_contexts.append(dict(kwargs))
        self.runtime_boundaries.append(dict(kwargs.get("runtime_boundary") or {}))
        super().set_runtime_context(
            execution_mode=kwargs.get("execution_mode"),
            session_id=kwargs.get("session_id"),
            project_id=kwargs.get("project_id"),
            project_root=kwargs.get("project_root"),
            cwd=kwargs.get("cwd"),
            model=kwargs.get("model"),
            skill_writer=kwargs.get("skill_writer"),
        )


class _FailingTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        raise RuntimeError("boom")


class _ScriptedTools(_FakeTools):
    def __init__(self, scripted_results: list[dict[str, Any]]) -> None:
        super().__init__()
        self._scripted_results = [dict(item) for item in scripted_results]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if not self._scripted_results:
            return {
                "ok": True,
                "name": name,
                "project_root": str((self.runtime_context or {}).get("project_root") or ""),
                "cwd": str((self.runtime_context or {}).get("cwd") or ""),
            }
        result = dict(self._scripted_results.pop(0))
        result.setdefault("name", name)
        result.setdefault("project_root", str((self.runtime_context or {}).get("project_root") or ""))
        result.setdefault("cwd", str((self.runtime_context or {}).get("cwd") or ""))
        return result


class _ApprovalRequiredTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": False,
            "command": str(arguments.get("cmd") or ""),
            "cwd": str(arguments.get("cwd") or ""),
            "returncode": 126,
            "error": "Command execution requires approval.",
            "error_kind": "command_execution_approval_required",
            "approval_required": True,
            "approval_request": {
                "type": "command_execution",
                "approval_token": "approval-token-1",
                "command": str(arguments.get("cmd") or ""),
                "cwd": str(arguments.get("cwd") or ""),
                "risks": [
                    {
                        "kind": "supply_chain_command",
                        "category": "supply_chain",
                        "message": "Command can execute network-origin package code.",
                        "base_command": "python",
                        "blocked_argument": "-c",
                    }
                ],
                "files": [],
                "single_use": True,
                "default_action": "cancel",
            },
            "summary": "Command execution requires explicit approval.",
        }


class _ApprovedCommandTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": True,
            "session_id": 7,
            "status": "completed",
            "running": False,
            "returncode": 0,
            "output": "approved command output\n",
            "command": str(arguments.get("cmd") or ""),
            "cwd": str(arguments.get("cwd") or ""),
            "command_execution_approved": {
                "approved": True,
                "approval_source": "user",
                "approval_scope": str(arguments.get("approval_scope") or "once"),
                "approval_token": str(arguments.get("approval_token") or ""),
                "command": str(arguments.get("cmd") or ""),
                "cwd": str(arguments.get("cwd") or ""),
                "risks": [],
                "files": [],
                **(
                    {
                        "thread_rule": {
                            "rule_id": "thread-rule-1",
                            "scope": "thread",
                            "kind": "python_inline",
                            "created": True,
                        }
                    }
                    if str(arguments.get("approval_scope") or "") == "thread"
                    else {}
                ),
            },
            "summary": "command exited with 0",
        }


class _TaskApprovalRequiredTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        current_task = {
            "task_id": str(arguments.get("task_id") or ""),
            "title": "Current Task",
            "goal": "Verify the issue",
            "summary": "Current summary",
            "progress": ["Collected logs"],
            "next_steps": ["Inspect runtime"],
            "decisions": [],
            "blockers": [],
            "artifacts": [],
            "status": "active",
        }
        proposed_task = {**current_task, **dict(arguments)}
        return {
            "ok": False,
            "error_kind": "task_update_approval_required",
            "approval_required": True,
            "approval_request": {
                "type": "task_update",
                "approval_token": "task-approval-token-1",
                "task_id": str(arguments.get("task_id") or ""),
                "current_task": current_task,
                "proposed_task": proposed_task,
                "changed_fields": ["summary", "progress", "next_steps"],
                "single_use": True,
                "default_action": "cancel",
            },
            "summary": "Task update requires explicit approval.",
        }


class _ApprovedTaskTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": True,
            "task_id": str(arguments.get("task_id") or ""),
            "task_update_approved": True,
            "summary": "Task updated after approval.",
        }


class _FakeBackend:
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        self.tools = _FakeTools()
        self._scripted_messages = list(scripted_messages)
        self.invocations: list[dict[str, Any]] = []
        self._SystemMessage = _FakeSystemMessage
        self._HumanMessage = _FakeHumanMessage
        self._ToolMessage = _FakeToolMessage

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


class _FakeBackendWithoutModelKwarg(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        super().__init__(scripted_messages)
        self.tools = _FakeToolsWithoutModel()


class _InitialModelDowngradeBackend(_FakeBackend):
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
        return self._next(), object(), "mixtral-8x7b-32768", ["model_fallback"]


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
                        "provider": "api_key",
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


class _FailingFollowupBackend(_FakeBackend):
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
        raise RuntimeError("azure rejected broken history")


class _FlakyNoneTypeFollowupBackend(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], *, fail_times: int) -> None:
        super().__init__(scripted_messages)
        self._fail_times = max(0, int(fail_times))

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
        _ = (runner, max_output_tokens, enable_tools, tool_names, event_cb)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "followup"})
        if self._fail_times > 0:
            self._fail_times -= 1
            raise AttributeError("'NoneType' object has no attribute 'model_dump'")
        return self._next(), object(), model, []


class _RequestTooLargeInitialBackend(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], *, fail_times: int) -> None:
        super().__init__(scripted_messages)
        self._fail_times = max(0, int(fail_times))

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
        _ = (max_output_tokens, enable_tools, tool_names, event_cb)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "initial"})
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError(
                "<html><head><title>413 Request Entity Too Large</title></head>"
                "<body><h1>413 Request Entity Too Large</h1><p>nginx/1.30.1</p></body></html>"
            )
        return self._next(), object(), model, []


class _RequestTooLargeFollowupBackend(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], *, fail_times: int) -> None:
        super().__init__(scripted_messages)
        self._fail_times = max(0, int(fail_times))

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
        _ = (runner, max_output_tokens, enable_tools, tool_names, event_cb)
        self.invocations.append({"messages": list(messages), "model": model, "kind": "followup"})
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("413 Request Entity Too Large")
        return self._next(), object(), model, []


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
        "tool_scope: read_only\n"
        "network_mode: explicit_tools\n"
        "approval_policy: on_failure_or_high_impact\n"
        "evidence_policy: required_for_external_or_runtime_facts\n"
        "max_tool_rounds: 4\n"
        "---\n"
        "\n"
        "agent workflow\n",
        encoding="utf-8",
    )
    if include_tools:
        (agent_dir / "tools.md").write_text("tool rules", encoding="utf-8")


def _write_builtin_subagent_spec(agents_dir: Path, name: str = "explorer") -> None:
    builtin_dir = agents_dir / "builtin"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    (builtin_dir / f"{name}.toml").write_text(
        f'name = "{name}"\n'
        f'description = "Read-only {name} test role."\n'
        'tool_scope = "read_only"\n'
        'allowed_tools = ["read_file", "search_codebase"]\n'
        'developer_instructions = "Inspect evidence and return concise findings."\n',
        encoding="utf-8",
    )


def _isolated_config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_model_request_estimate_includes_full_messages_and_selected_tool_schemas(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    messages = [
        _FakeSystemMessage(content="system " + "S" * 8_000),
        _FakeHumanMessage(content="attachment " + "A" * 12_000),
    ]

    without_tools = runtime._estimate_model_request_tokens(messages, model="gpt-5.4", tool_names=[])
    with_tools = runtime._estimate_model_request_tokens(
        messages,
        model="gpt-5.4",
        tool_names=["read_file", "search_codebase"],
    )

    assert without_tools > 2_000
    assert with_tools > without_tools


def test_runtime_does_not_create_a_second_semantic_task_completion_state(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    result = runtime.run(
        message="say ok",
        settings=ChatSettings(model="gpt-test", enable_tools=False, response_style="short"),
        context={"session_id": "thread-1", "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)}},
    )

    assert result["turn_status"] == "completed"
    assert result["final_answer"] == "ok"
    assert "task_completion" not in result
    assert "task_completion" not in result["inspector"]["run_state"]


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
    prompt = runtime._render_system_prompt(ChatSettings(model="gpt-test"), spec=spec, available_skills=[])

    assert descriptor["agent_id"] == "vintage_programmer"
    assert descriptor["tool_scope"] == "read_only"
    assert descriptor["tool_policy"] == "read_only"
    assert descriptor["network"]["mode"] == "explicit_tools"
    assert descriptor["network"]["web_tool_contract"] == ["web_search", "web_fetch", "web_download"]
    assert "modes" not in descriptor["workflow"]
    assert "max_tool_rounds" not in descriptor
    assert "emergency_max_tool_calls_per_turn" not in descriptor["loop_safeguards"]
    assert descriptor["loop_safeguards"]["continuation_policy"] == "model_led"
    assert "max_turn_seconds" not in descriptor["loop_safeguards"]
    assert "max_total_failures" not in descriptor["loop_safeguards"]
    assert prompt.index("[soul.md]") < prompt.index("[identity.md]") < prompt.index("[agent.md]") < prompt.index("[tools.md]")
    assert "[runtime_protocol]" in prompt
    assert "[context_authority]" in prompt
    assert "[evidence_reliability]" in prompt
    assert "[conflict_resolution]" in prompt
    assert "The final user message is the current request." in prompt
    assert "[runtime_contract]" not in prompt
    assert "[anti_permission_gate]" not in prompt
    assert "[model_led_action_protocol]" not in prompt
    assert "[full_auto_tool_policy]" not in prompt
    assert "task_state_delta" not in prompt


def test_runtime_accepts_legacy_tool_policy_frontmatter(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_policy: read_only"),
        encoding="utf-8",
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )

    descriptor = runtime.descriptor()

    assert descriptor["tool_scope"] == "read_only"
    assert descriptor["tool_policy"] == "read_only"


def test_descriptor_uses_cache_until_explicit_invalidation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )

    load_calls = {"spec": 0, "skills": 0}
    original_load_spec = runtime._load_spec
    original_enabled_skills = runtime._enabled_skills

    def counting_load_spec(*args: Any, **kwargs: Any):
        load_calls["spec"] += 1
        return original_load_spec(*args, **kwargs)

    def counting_enabled_skills(agent_id: str):
        load_calls["skills"] += 1
        return original_enabled_skills(agent_id)

    monkeypatch.setattr(runtime, "_load_spec", counting_load_spec)
    monkeypatch.setattr(runtime, "_enabled_skills", counting_enabled_skills)

    first = runtime.descriptor()
    second = runtime.descriptor()

    assert first == second
    assert load_calls == {"spec": 1, "skills": 1}

    runtime.invalidate_descriptor_cache()
    third = runtime.descriptor()

    assert third == first
    assert load_calls == {"spec": 2, "skills": 2}


def test_build_human_payload_contains_only_current_user_request(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )

    payload_text = runtime._build_human_payload(
        message="题目",
        context={
            "session_id": "s-1",
            "project": {"project_root": str(tmp_path)},
            "context_manager": {
                "clean_turns": [{"role": "user", "text": f"turn-{index}"} for index in range(20)],
                "context_version": 2,
            },
            "route_state": {"task_checkpoint": {"task_id": "task-old", "goal": "帮我写个请假邮件"}},
            "current_task_focus": {"task_id": "task-old", "goal": "帮我写个请假邮件"},
            "active_task_focus": {"task_id": "task-old", "goal": "帮我写个请假邮件"},
            "current_turn": {
                "user_message": "题目",
                "goal": "Provide only a subject/title for the previous email or draft.",
                "is_followup": True,
                "followup_type": "subject_request",
                "source": "followup_classifier",
            },
            "recent_user_messages": ["帮我写个请假邮件"],
            "history_turns": [{"role": "user", "text": f"turn-{index}"} for index in range(20)],
        },
    )

    assert payload_text == "题目"
    assert "task-old" not in payload_text
    assert "followup_classifier" not in payload_text


def test_thread_messages_replay_history_without_task_relation_classifier(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="unused")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    summary, messages = runtime._thread_messages(
        {
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"id": "u1", "role": "user", "content": "帮我写请假邮件"},
                    {"id": "a1", "role": "assistant", "content": "邮件正文已经写好。"},
                ],
            },
            "task_state": {"task_id": "task-mail", "goal": "写请假邮件"},
            "context_manager": {"working_summary": "不应进入模型"},
        }
    )

    assert summary == ""
    assert [message.content for message in messages] == ["帮我写请假邮件", "邮件正文已经写好。"]
    assert backend.invocations == []


def test_thread_messages_apply_compaction_summary(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    summary, messages = runtime._thread_messages(
        {
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"id": "u1", "turn_id": "u1", "role": "user", "content": "old"},
                    {"id": "a1", "turn_id": "a1", "role": "assistant", "content": "old answer"},
                    {"id": "u2", "turn_id": "u2", "role": "user", "content": "new"},
                ],
            },
            "compaction_status": {
                "compacted_history": "old exchange summary",
                "compacted_until_turn_id": "a1",
            },
        }
    )

    assert summary == "old exchange summary"
    assert [message.content for message in messages] == ["new"]


def test_thread_messages_replay_assistant_tool_pairs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="unused")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    summary, messages = runtime._thread_messages(
        {
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"role": "user", "content": "读取文件"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "c1", "name": "read_file", "args": {"path": "README.md"}}],
                    },
                    {"role": "tool", "content": "ok", "tool_call_id": "c1", "name": "read_file"},
                ],
            },
        }
    )

    assert summary == ""
    assert messages[1].tool_calls[0]["id"] == "c1"
    assert messages[2].tool_call_id == "c1"


def test_runtime_has_no_turn_relation_classifier(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    assert not hasattr(runtime, "_build_model_context")
    assert not hasattr(runtime, "_resolve_turn_relation")
    assert not hasattr(runtime_module, "_TURN_RELATION_CLASSIFIER_TIMEOUT_SECONDS")


def test_apply_patch_tool_event_exposes_changed_files_as_source_refs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([]),
    )
    changed_path = str(tmp_path / "app" / "changed.py")

    event = runtime._build_tool_event(
        name="apply_patch",
        arguments={"patch": "*** Begin Patch", "cwd": str(tmp_path)},
        result={"ok": True, "cwd": str(tmp_path), "files": [changed_path], "summary": "patch applied"},
        locale="zh-CN",
    )

    assert event.source_refs == [changed_path]


def test_turn_changes_keep_file_updates_separate_from_tool_failures_and_latest_verification() -> None:
    events = [
        ToolEvent(
            name="apply_patch",
            normalized_arguments={"patch": "*** Begin Patch"},
            output_preview="patched",
            status="ok",
            source_refs=["app/runtime.py", "tests/test_runtime.py"],
        ),
        ToolEvent(
            name="exec_command",
            normalized_arguments={"cmd": "pytest tests/test_runtime.py"},
            output_preview="failed",
            status="error",
            summary="1 failed",
        ),
        ToolEvent(
            name="exec_command",
            normalized_arguments={"cmd": "pytest tests/test_runtime.py"},
            output_preview="passed",
            status="ok",
            summary="1 passed",
        ),
    ]

    changes = VintageProgrammerRuntime._build_turn_changes(events, turn_status="failed")

    assert changes["count"] == 2
    assert [item["path"] for item in changes["files"]] == ["app/runtime.py", "tests/test_runtime.py"]
    assert changes["retained"] is True
    assert changes["verification"]["status"] == "passed"
    assert "failure_count" not in changes


def test_turn_changes_do_not_claim_failed_or_skipped_patch_writes() -> None:
    events = [
        ToolEvent(
            name="apply_patch",
            normalized_arguments={"patch": "*** Begin Patch"},
            output_preview="failed",
            status="error",
            source_refs=["app/uncertain.py"],
        ),
        ToolEvent(
            name="exec_command",
            normalized_arguments={"cmd": "python scripts/update_generated.py"},
            output_preview="cancelled",
            status="cancelled",
        ),
    ]

    changes = VintageProgrammerRuntime._build_turn_changes(events, turn_status="cancelled")

    assert changes["files"] == []
    assert changes["count"] == 0
    assert changes["possible_untracked_changes"] is True
    assert changes["retained"] is True


def test_runtime_activity_copy_has_locale_parity() -> None:
    for locale in ("zh-CN", "ja-JP", "en"):
        for key in REQUIRED_RUNTIME_ACTIVITY_KEYS:
            assert translate(locale, key) != key, f"{locale} missing {key}"


def test_agent_specs_define_v2_contract_and_tool_guidance() -> None:
    zh_spec_dir = REPO_ROOT / "agents" / "vintage_programmer" / "locales" / "zh-CN"
    agent_doc = (zh_spec_dir / "agent.md").read_text(encoding="utf-8")
    tools_doc = (zh_spec_dir / "tools.md").read_text(encoding="utf-8")

    assert "spec_version: 2" in agent_doc
    assert "api_surface: chat_completions" in agent_doc
    assert "tool_scope options: all | read_only | none" in agent_doc
    assert "tool_scope: all" in agent_doc
    assert "tool_policy:" not in agent_doc
    assert "allowed_tools:" not in agent_doc
    assert "model_family:" not in agent_doc
    assert "default_model:" not in agent_doc
    assert "outcome_first" in agent_doc
    assert "以用户目标为主线" in agent_doc
    assert "当前输入优先" in agent_doc
    assert "本地 skills 只是覆盖层" in agent_doc
    assert "不要为每个请求都创建计划" in agent_doc
    assert "多步骤、多文件、代码修改、调试、测试" in agent_doc
    assert "简单问答、单步检查或琐碎命令" in agent_doc
    assert "唯一 checklist 协议" in agent_doc
    assert "task_state_delta" not in agent_doc
    assert "./.venv/bin/python" in tools_doc
    assert ".venv\\Scripts\\python.exe" in tools_doc
    assert "不要假定 `python3`" in tools_doc
    assert "update_plan" in agent_doc
    assert "网络信息先用 `web_search` 找来源，再按需用 `web_fetch` 读取正文" in tools_doc
    assert "优先一次 `web_search`，最多再读取一个权威来源" in tools_doc
    assert "## 状态和用户输入工具" in tools_doc
    assert "`update_plan` 只在需要维护多步任务状态时使用" in tools_doc
    assert "具体计划规则以 `agent.md` 为准" in tools_doc
    assert "只在任务需要取证、执行或验证时调用工具" in tools_doc


def test_rendered_prompt_has_single_policy_owners() -> None:
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=REPO_ROOT / "agents" / "vintage_programmer",
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    prompt = runtime._render_system_prompt(
        ChatSettings(model="gpt-5.4", locale="zh-CN"),
        spec=runtime._load_spec(locale="zh-CN"),
        available_skills=[],
        runtime_context_text='[current_runtime_context]\n{"cwd":"/workspace"}',
    )
    meaningful_lines = [line.strip() for line in prompt.splitlines() if line.strip()]

    assert len(meaningful_lines) == len(set(meaningful_lines))
    assert prompt.count("不要为每个请求都创建计划") == 1
    assert prompt.count("不要假定 `python3`") == 1
    assert "task_state_delta" not in prompt
    assert "[current_runtime_context]" in prompt
    assert "[runtime_contract]" not in prompt
    assert "[full_auto_tool_policy]" not in prompt


def test_runtime_activity_helpers_use_requested_locale() -> None:
    assert VintageProgrammerRuntime._validation_activity_detail(
        "zh-CN",
        {"allowed": True, "tool_name": "read_file"},
    ) == translate("zh-CN", "runtime.activity.guard.normalized_continued", tool="read_file", suffix="")
    assert VintageProgrammerRuntime._execution_activity_detail("ja-JP", {}) == translate(
        "ja-JP",
        "runtime.activity.execution.recorded",
    )
    assert VintageProgrammerRuntime._validation_activity_detail(
        "en",
        {"allowed": False, "tool_name": "read_file", "message": "blocked"},
    ) == "blocked"


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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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


def test_runtime_answers_simple_greeting_without_tool_calls(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="你好，有什么我可以帮你？")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="你好",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-greeting",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "你好，有什么我可以帮你？"
    assert backend.tools.calls == []
    assert result["tool_events"] == []


def test_runtime_replays_typed_thread_before_current_user_message(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="件名：休暇申請")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="题目呢",
        settings=ChatSettings(model="gpt-test", enable_tools=False, response_style="short"),
        context={
            "session_id": "s-thread-replay",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"id": "u1", "role": "user", "content": "帮我写一封日语请假邮件"},
                    {"id": "a1", "role": "assistant", "content": "邮件正文已经写好。"},
                ],
            },
            "context_manager": {"working_summary": "THIS_MUST_NOT_BE_SENT"},
            "task_state": {"goal": "THIS_MUST_NOT_BE_SENT_EITHER"},
            "attachments": [],
        },
    )

    sent = result["activity"]["llm_exchanges"][0]["sent_messages_exact"]
    conversation = [(item["role"], item["content"]) for item in sent if item["role"] in {"user", "assistant"}]
    encoded = json.dumps(sent, ensure_ascii=False)
    assert conversation == [
        ("user", "帮我写一封日语请假邮件"),
        ("assistant", "邮件正文已经写好。"),
        ("user", "题目呢"),
    ]
    assert "THIS_MUST_NOT_BE_SENT" not in encoded
    assert result["text"] == "件名：休暇申請"


def test_runtime_emits_streamed_answer_deltas_and_activity_for_direct_answers(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _StreamingBackend(
        [_FakeMessage(content="streamed answer")],
        deltas=["streamed ", "answer"],
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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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


def test_runtime_records_phase_timings_for_direct_answer(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _StreamingBackend([_FakeMessage(content="streamed answer")], deltas=["streamed ", "answer"])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="把这句日语润色一下",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-timing",
            "run_id": "run-timing",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert "phase_timings" not in dict(result.get("activity") or {})
    phase_timings = dict(dict((result.get("inspector") or {}).get("run_state") or {}).get("phase_timings") or {})
    assert phase_timings["agent_spec_load_ms"] >= 0
    assert phase_timings["skills_load_ms"] >= 0
    for key in (
        "runtime_contract_ms",
        "runtime_boundary_ms",
        "runtime_project_contract_ms",
        "runtime_thread_replay_ms",
        "runtime_user_request_limit_ms",
        "runtime_render_messages_ms",
        "runtime_initial_trace_ms",
        "runtime_tools_context_ms",
        "runtime_pre_model_ms",
        "model_initial_response_ms",
        "model_last_response_ms",
    ):
        assert phase_timings[key] >= 0
    assert phase_timings["model_request_start_ms"] >= 0
    assert phase_timings["model_request_start_ms"] >= phase_timings["runtime_pre_model_ms"]
    assert phase_timings["model_first_event_ms"] >= phase_timings["model_request_start_ms"]
    assert phase_timings["model_first_text_delta_ms"] >= phase_timings["model_first_event_ms"]
    assert phase_timings["answer_ready_ms"] >= phase_timings["model_first_text_delta_ms"]
    assert phase_timings["runtime_total_ms"] >= phase_timings["answer_ready_ms"]


def test_runtime_short_input_skips_exact_tokenizer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="你好，有什么我可以帮你？")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    def fail_count_tokens(_text: str, _model: str | None = None) -> int:
        raise AssertionError("short user requests should not require exact tokenizer")

    monkeypatch.setattr(runtime_module, "count_tokens", fail_count_tokens)

    result = runtime.run(
        message="你好",
        settings=ChatSettings(model="gpt-test", enable_tools=False, response_style="short"),
        context={
            "session_id": "s-short-tokenizer",
            "run_id": "run-short-tokenizer",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "context_manager": {
                "clean_turns": [{"role": "user", "text": f"old-{index}"} for index in range(5000)]
            },
            "attachments": [],
        },
    )

    assert result["text"] == "你好，有什么我可以帮你？"
    phase_timings = dict(dict((result.get("inspector") or {}).get("run_state") or {}).get("phase_timings") or {})
    assert phase_timings["runtime_user_request_limit_ms"] >= 0


def test_runtime_emits_non_tool_activity_without_route_semantic_inference(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _StreamingBackend(
        [_FakeMessage(content="今日は駅へ行きます。")],
        deltas=["今日は駅へ", "行きます。"],
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
    model_action_done = next(
        item
        for item in trace_payloads
        if str(item.get("type") or "") == "activity.done"
        and str(((item.get("payload") or {}).get("activity") or {}).get("stage") or "") == "model_action"
    )
    execution_done = next(
        item
        for item in trace_payloads
        if str(item.get("type") or "") in {"activity.done", "activity.delta"}
        and str(((item.get("payload") or {}).get("activity") or {}).get("stage") or "") == "execution"
    )
    answer_done = next(item for item in trace_payloads if str(item.get("type") or "") == "answer.done")
    revision_summary = dict((answer_done.get("payload") or {}).get("revision_summary") or {})
    model_action_payload = dict((model_action_done.get("payload") or {}).get("model_action") or {})
    execution_payload = dict((execution_done.get("payload") or {}).get("execution_trace_entry") or {})

    assert model_action_payload["action_type"] == "final_answer"
    assert model_action_payload["accepted"] is True
    assert revision_summary == {}
    assert execution_payload["action_type"] == "final_answer"
    assert result["model_action"]["action_type"] == "final_answer"
    assert result["execution_trace"]
    assert result["execution_trace"][-1]["action_type"] == "final_answer"


def test_runtime_runs_single_agent_tool_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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
    assert result["inspector"]["agent"]["tool_scope"] == "read_only"
    assert result["inspector"]["agent"]["tool_policy"] == "read_only"
    assert result["inspector"]["run_state"]["permission_profile"] == "full_access"
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert result["inspector"]["session"]["project_root"] == str(tmp_path)
    assert result["tool_events"][0]["project_root"] == str(tmp_path)
    assert result["model_action"]["action_type"] == "final_answer"
    assert result["model_action"]["accepted"] is True
    assert result["execution_trace"]
    assert result["execution_trace"][0]["action_type"] == "tool_call"
    assert result["execution_trace"][-1]["action_type"] == "final_answer"
    assert [item["role"] for item in result["transcript_delta"]] == ["assistant", "tool"]
    assert result["transcript_delta"][0]["tool_calls"][0]["id"] == "tc1"
    assert result["transcript_delta"][1]["tool_call_id"] == "tc1"
    assert result["tool_events"][0]["arguments_preview"] == "query=latest"
    assert result["tool_events"][0]["schema_validation"]["status"] == "valid"
    assert result["tool_events"][0]["validation_result"]["allowed"] is True
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
    assert result["inspector"]["run_state"]["model_action"]["action_type"] == result["model_action"]["action_type"]


def test_runtime_accepts_queued_guidance_before_finalizing_turn(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeAIMessage(content="I can finish now."),
            _FakeAIMessage(content="The tests pass; I will check the documentation."),
            _FakeMessage(content="Tests passed; here is the verified result."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    pending = [
        {
            "id": "steer-1",
            "message": "Run the tests before answering.",
            "queued_at": 10.0,
            "accepted_at": 11.0,
        },
        {
            "id": "steer-2",
            "message": "Then check the documentation.",
            "queued_at": 12.0,
            "accepted_at": 13.0,
        },
    ]

    def drain_pending_steers(*, final: bool = False) -> list[dict[str, Any]]:
        _ = final
        drained = pending[:1]
        del pending[:1]
        return drained

    progress_events: list[dict[str, Any]] = []
    result = runtime.run(
        message="Finish this change.",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-steer",
            "run_id": "run-steer",
            "drain_pending_steers": drain_pending_steers,
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["text"] == "Tests passed; here is the verified result."
    assert [item["id"] for item in result["steered_user_messages"]] == ["steer-1", "steer-2"]
    assert [item["role"] for item in result["intermediate_turns"]] == [
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert result["intermediate_turns"][0]["text"] == "I can finish now."
    assert result["intermediate_turns"][1]["text"] == "Run the tests before answering."
    assert result["intermediate_turns"][2]["text"] == "The tests pass; I will check the documentation."
    assert result["intermediate_turns"][3]["text"] == "Then check the documentation."
    assert [item["role"] for item in result["transcript_delta"]] == [
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert result["transcript_delta"][1]["content"] == "Run the tests before answering."
    assert result["transcript_delta"][3]["content"] == "Then check the documentation."
    assert len(backend.invocations) == 3
    followup_messages = backend.invocations[1]["messages"]
    assert followup_messages[-2].content == "I can finish now."
    assert followup_messages[-1].content == "Run the tests before answering."
    final_messages = backend.invocations[2]["messages"]
    assert final_messages[-2].content == "The tests pass; I will check the documentation."
    assert final_messages[-1].content == "Then check the documentation."
    assert any(item.get("event") == "turn/segment/completed" for item in progress_events)
    assert any(item.get("event") == "turn/steer/accepted" for item in progress_events)
    accepted_event = next(item for item in progress_events if item.get("event") == "turn/steer/accepted")
    assert accepted_event["starts_next_response"] is True
    assert str(accepted_event["next_segment_id"]).startswith("run-steer:agent_message:")


def test_runtime_accepts_steer_after_tool_batch_before_next_model_request(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-first-redmine",
                        "name": "read_file",
                        "args": {"path": str(tmp_path / "redmine-101.md")},
                    }
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-second-redmine",
                        "name": "read_file",
                        "args": {"path": str(tmp_path / "redmine-202.md")},
                    }
                ],
            ),
            _FakeMessage(content="第二个 Redmine 的读取结果。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    pending = [
        {
            "id": "steer-redmine-2",
            "message": "再读取 https://redmine.example/issues/202",
            "queued_at": 12.0,
            "accepted_at": 13.0,
        }
    ]
    drain_calls: list[bool] = []

    def drain_pending_steers(*, final: bool = False) -> list[dict[str, Any]]:
        drain_calls.append(bool(final))
        if not pending:
            return []
        drained = list(pending)
        pending.clear()
        return drained

    progress_events: list[dict[str, Any]] = []
    result = runtime.run(
        message="读取 https://redmine.example/issues/101",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-redmine-steer",
            "run_id": "run-redmine-steer",
            "drain_pending_steers": drain_pending_steers,
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["text"] == "第二个 Redmine 的读取结果。"
    assert [(item["role"], item["text"]) for item in result["intermediate_turns"]] == [
        ("user", "再读取 https://redmine.example/issues/202"),
    ]
    assert [call[0] for call in backend.tools.calls] == ["read_file", "read_file"]
    assert len(backend.invocations) == 3
    assert drain_calls[0] is False
    assert str(backend.invocations[1]["messages"][-2].content).startswith(
        '{"ok": true'
    )
    assert backend.invocations[1]["messages"][-1].content == "再读取 https://redmine.example/issues/202"
    accepted_event = next(
        item
        for item in progress_events
        if item.get("event") == "turn/steer/accepted"
    )
    assert accepted_event["boundary"] == "after_tool"
    assert accepted_event["starts_next_response"] is False
    assert not any(item.get("event") == "turn/segment/completed" for item in progress_events)
    accepted_index = progress_events.index(accepted_event)
    next_model_index = next(
        index
        for index, item in enumerate(progress_events[accepted_index + 1 :], start=accepted_index + 1)
        if item.get("event") == "trace_event"
        and str((item.get("trace") or {}).get("type") or "") == "llm.started"
    )
    assert accepted_index < next_model_index


def test_runtime_subagent_uses_isolated_read_only_context_and_returns_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    _write_builtin_subagent_spec(agent_dir.parent)
    child_tools = _BoundaryCapturingTools()
    child_summary = "Found the entry point in app/main.py.\n" + ("detail " * 2500) + "TAIL_MARKER"
    child_backend = _FakeBackendWithTools(
        [_FakeMessage(content=child_summary)],
        child_tools,
    )
    monkeypatch.setattr(runtime_module, "create_vp_runtime_backend", lambda _config: child_backend)
    parent_backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-subagent",
                        "name": "spawn_subagent",
                        "args": {
                            "task": "Locate the request entry point and report the relevant file.",
                            "role": "explorer",
                            "label": "Find request entry point",
                        },
                    }
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-wait-subagent",
                        "name": "wait_subagents",
                        "args": {"timeout_seconds": 30},
                    }
                ],
            ),
            _FakeMessage(content="The subagent found the request entry point."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=parent_backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="Use a subagent to locate the request entry point.",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-subagent",
            "run_id": "run-subagent",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["text"] == "The subagent found the request entry point."
    assert [item[0] for item in parent_backend.tools.calls[:2]] == [
        "spawn_subagent",
        "wait_subagents",
    ]
    subagent_event = next(item for item in result["tool_events"] if item["name"] == "spawn_subagent")
    assert "running" in str(subagent_event["result_preview"])
    wait_event = next(item for item in result["tool_events"] if item["name"] == "wait_subagents")
    assert "app/main.py" in str(wait_event["result_preview"])
    wait_tool_message = parent_backend.invocations[2]["messages"][-1]
    assert "TAIL_MARKER" in str(wait_tool_message.content)
    subagent_items = [item for item in result["activity"]["live_items"] if item.get("type") == "subagent"]
    assert len(subagent_items) == 1
    assert subagent_items[0]["status"] == "completed"
    assert "app/main.py" in subagent_items[0]["summary"]
    assert subagent_items[0]["summary_truncated"] is True
    assert subagent_items[0]["summary_total_chars"] == len(child_summary)
    assert child_tools.runtime_boundaries
    assert child_tools.runtime_boundaries[-1]["workspace_write_allowed"] is False
    assert child_tools.runtime_boundaries[-1]["writable_roots"] == []
    assert child_tools.runtime_contexts[-1]["subagent_read_only"] is True
    assert isinstance(child_tools.runtime_contexts[-1]["cancel_event"], threading.Event)
    stream_events = [
        item for item in progress_events
        if item.get("event") in {"item/started", "item/completed"}
        and str((item.get("item") or {}).get("type") or "") == "subagent"
    ]
    assert [item["event"] for item in stream_events] == ["item/started", "item/completed"]


def test_runtime_runs_independent_subagents_in_parallel_and_waits_for_both(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    _write_builtin_subagent_spec(agent_dir.parent, "explorer")
    _write_builtin_subagent_spec(agent_dir.parent, "analyst")
    barrier = threading.Barrier(2)
    active_lock = threading.Lock()
    activity = {"active": 0, "peak": 0, "created": 0}

    class _ConcurrentChildBackend(_FakeBackend):
        def _invoke_chat_with_runner(self, **kwargs: Any):
            with active_lock:
                activity["active"] += 1
                activity["peak"] = max(activity["peak"], activity["active"])
            try:
                barrier.wait(timeout=5)
                return super()._invoke_chat_with_runner(**kwargs)
            finally:
                with active_lock:
                    activity["active"] -= 1

    def create_child_backend(_config):
        with active_lock:
            activity["created"] += 1
            index = activity["created"]
        return _ConcurrentChildBackend([_FakeMessage(content=f"Child result {index}.")])

    monkeypatch.setattr(runtime_module, "create_vp_runtime_backend", create_child_backend)
    parent_backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-subagent-a",
                        "name": "spawn_subagent",
                        "args": {"task": "Explore parser paths.", "role": "explorer", "label": "Paths"},
                    },
                    {
                        "id": "tc-subagent-b",
                        "name": "spawn_subagent",
                        "args": {"task": "Analyze protocol risks.", "role": "analyst", "label": "Risks"},
                    },
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-wait-all",
                        "name": "wait_subagents",
                        "args": {"timeout_seconds": 30},
                    }
                ],
            ),
            _FakeMessage(content="Combined both independent findings."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=parent_backend,
    )

    result = runtime.run(
        message="Delegate two independent investigations and combine them.",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-parallel-subagents",
            "run_id": "run-parallel-subagents",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "Combined both independent findings."
    assert activity["created"] == 2
    assert activity["peak"] == 2
    assert [item[0] for item in parent_backend.tools.calls] == [
        "spawn_subagent",
        "spawn_subagent",
        "wait_subagents",
    ]
    wait_event = next(item for item in result["tool_events"] if item["name"] == "wait_subagents")
    assert "Child result 1" in str(wait_event["result_preview"])
    assert "Child result 2" in str(wait_event["result_preview"])
    subagent_items = [item for item in result["activity"]["live_items"] if item.get("type") == "subagent"]
    assert len(subagent_items) == 2
    assert all(item.get("status") == "completed" for item in subagent_items)


def test_runtime_empty_parent_response_cancels_active_subagent_without_waiting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    _write_builtin_subagent_spec(agent_dir.parent, "explorer")
    child_started = threading.Event()
    release_child = threading.Event()
    child_command_cancelled = threading.Event()

    class _CancellableChildTools(_FakeTools):
        def _cancel_command_sessions(self, *, run_id: str = "") -> int:
            assert ":subagent:" in run_id
            child_command_cancelled.set()
            return 1

    class _BlockingChildBackend(_FakeBackend):
        def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
            super().__init__(scripted_messages)
            self.tools = _CancellableChildTools()

        def _invoke_chat_with_runner(self, **kwargs: Any):
            child_started.set()
            release_child.wait(timeout=5)
            return super()._invoke_chat_with_runner(**kwargs)

    class _EmptyFailingParentBackend(_FlakyNoneTypeFollowupBackend):
        def _invoke_with_runner_recovery(self, **kwargs: Any):
            assert child_started.wait(timeout=2), "subagent did not start before the parent follow-up"
            return super()._invoke_with_runner_recovery(**kwargs)

    monkeypatch.setattr(
        runtime_module,
        "create_vp_runtime_backend",
        lambda _config: _BlockingChildBackend([_FakeMessage(content="late child result")]),
    )
    parent_backend = _EmptyFailingParentBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-subagent-before-empty",
                        "name": "spawn_subagent",
                        "args": {
                            "task": "Run the slow verification.",
                            "role": "explorer",
                            "label": "Slow verification",
                        },
                    }
                ],
            ),
        ],
        fail_times=2,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=parent_backend,
    )
    progress_events: list[dict[str, Any]] = []

    started_at = time.monotonic()
    try:
        result = runtime.run(
            message="Delegate the verification and report back.",
            settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
            context={
                "session_id": "s-empty-with-active-subagent",
                "run_id": "run-empty-with-active-subagent",
                "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
                "history_turns": [],
                "attachments": [],
            },
            progress_cb=progress_events.append,
        )
    finally:
        release_child.set()
    elapsed = time.monotonic() - started_at

    assert result["turn_status"] == "failed"
    assert result["runtime_error"]["kind"] == "llm_empty_response"
    assert elapsed < 1.5
    assert child_command_cancelled.is_set()
    subagent_items = [item for item in result["activity"]["live_items"] if item.get("type") == "subagent"]
    assert len(subagent_items) == 1
    assert subagent_items[0]["status"] == "cancelled"
    completed_items = [
        item.get("item") or {}
        for item in progress_events
        if item.get("event") == "item/completed" and str((item.get("item") or {}).get("type") or "") == "subagent"
    ]
    assert completed_items[-1]["status"] == "cancelled"
    trace_types = [
        str((item.get("trace") or {}).get("type") or "")
        for item in progress_events
        if item.get("event") == "trace_event"
    ]
    assert "llm.failed" in trace_types
    assert "run.failed" in trace_types


def test_runtime_surfaces_command_execution_pending_approval(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    command = "python -c \"from pathlib import Path; print(Path('.').resolve())\""
    tools = _ApprovalRequiredTools()
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-approval",
                        "name": "exec_command",
                        "args": {
                            "cmd": command,
                            "purpose": "Verify the active Python interpreter before continuing.",
                            "cwd": str(tmp_path),
                        },
                    }
                ],
            )
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="run risky command",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-command-approval",
            "logical_turn_started_at": 1_700_000_000.25,
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["turn_status"] == "needs_user_input"
    assert result["pending_approval"]["type"] == "command_execution"
    assert result["pending_approval"]["purpose"] == "Verify the active Python interpreter before continuing."
    assert result["pending_approval"]["approval_token"] == "approval-token-1"
    assert result["pending_user_input"]["approval_request"]["type"] == "command_execution"
    assert result["pending_turn"]["tool_call_id"] == "tc-approval"
    assert result["pending_turn"]["turn_started_at"] == 1_700_000_000.25
    assert result["activity"]["turn_started_at"] == 1_700_000_000.25
    assert [item["role"] for item in result["transcript_delta"]] == ["assistant"]
    assert result["inspector"]["run_state"]["pending_approval"]["command"] == command
    request_event = next(item for item in progress_events if str(item.get("event") or "") == "request_user_input")
    assert request_event["pending_approval"]["type"] == "command_execution"
    assert request_event["run_snapshot"]["pending_approval"]["approval_token"] == "approval-token-1"


def test_runtime_surfaces_complete_task_update_pending_approval(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _TaskApprovalRequiredTools()
    proposed = {
        "task_id": "task-approval-1",
        "title": "Current Task",
        "goal": "Verify the issue",
        "summary": "Runtime inspection is complete.",
        "progress": ["Collected logs", "Inspected runtime"],
        "next_steps": ["Verify the fix"],
        "decisions": [],
        "blockers": [],
        "artifacts": ["runtime-report.md"],
        "status": "active",
    }
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-task-approval",
                        "name": "save_task",
                        "args": proposed,
                    }
                ],
            )
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="更新当前 Task",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-task-update-approval",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["turn_status"] == "needs_user_input"
    assert result["pending_approval"]["type"] == "task_update"
    assert result["pending_approval"]["current_task"]["summary"] == "Current summary"
    assert result["pending_approval"]["proposed_task"]["summary"] == proposed["summary"]
    assert result["pending_turn"]["type"] == "task_update"
    assert result["pending_turn"]["tool_call_id"] == "tc-task-approval"
    assert [item["role"] for item in result["transcript_delta"]] == ["assistant"]
    request_event = next(item for item in progress_events if item.get("event") == "request_user_input")
    assert request_event["pending_approval"]["approval_token"] == "task-approval-token-1"


def test_runtime_approved_task_update_resumes_exact_save_task_call(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ApprovedTaskTools()
    backend = _FakeBackendWithTools([_FakeMessage(content="Task update completed.")], tools)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    proposed = {
        "task_id": "task-approval-1",
        "title": "Current Task",
        "goal": "Verify the issue",
        "summary": "Runtime inspection is complete.",
        "progress": ["Collected logs", "Inspected runtime"],
        "next_steps": ["Verify the fix"],
        "decisions": [],
        "blockers": [],
        "artifacts": ["runtime-report.md"],
        "status": "active",
    }

    result = runtime.run(
        message="更新当前 Task",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-task-update-approval",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"role": "user", "content": "更新当前 Task"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tc-task-approval",
                                "name": "save_task",
                                "args": proposed,
                            }
                        ],
                    },
                ],
            },
            "pending_turn": {
                "schema_version": 1,
                "type": "task_update",
                "turn_id": "turn-task-update",
                "request_message": "更新当前 Task",
                "tool_call_id": "tc-task-approval",
                "tool_call": {
                    "id": "tc-task-approval",
                    "name": "save_task",
                    "args": proposed,
                },
                "task_id": "task-approval-1",
            },
            "user_input_response": {
                "type": "task_update",
                "action": "approve_once",
                "approval_token": "task-approval-token-1",
                "tool_call_id": "tc-task-approval",
                "task_id": "task-approval-1",
            },
            "attachments": [],
        },
    )

    assert tools.calls[0] == (
        "save_task",
        {**proposed, "approval_token": "task-approval-token-1"},
    )
    assert result["text"].startswith("Task update completed.")
    assert result["tool_events"][0]["name"] == "save_task"
    assert result["tool_events"][0]["status"] == "ok"
    assert result["pending_approval"] == {}
    sent_messages = backend.invocations[0]["messages"]
    approval_results = [item for item in sent_messages if isinstance(item, _FakeToolMessage)]
    assert approval_results[-1].tool_call_id == "tc-task-approval"


def test_runtime_approve_once_executes_original_command_with_token(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    tools = _ApprovedCommandTools()
    backend = _FakeBackendWithTools([_FakeMessage(content="approved summary")], tools)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="Approve once",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-command-approval-resume",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"role": "user", "content": "run risky command"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tc-approval",
                                "name": "exec_command",
                                "args": {"cmd": "python -c \"print('x')\"", "cwd": str(tmp_path)},
                            }
                        ],
                    },
                ],
            },
            "pending_turn": {
                "schema_version": 1,
                "type": "command_execution",
                "turn_id": "turn-original",
                "request_message": "run risky command",
                "tool_call_id": "tc-approval",
                "tool_call": {
                    "id": "tc-approval",
                    "name": "exec_command",
                    "args": {"cmd": "python -c \"print('x')\"", "cwd": str(tmp_path)},
                },
                "plan": [{"step": "Run the requested check", "status": "in_progress"}],
            },
            "user_input_response": {
                "type": "command_execution",
                "action": "approve_once",
                "approval_token": "approval-token-1",
                "command": "python -c \"print('x')\"",
                "cwd": str(tmp_path),
            },
        },
    )

    assert tools.calls[0] == (
        "exec_command",
        {
            "cmd": "python -c \"print('x')\"",
            "cwd": str(tmp_path),
            "approval_token": "approval-token-1",
            "tainted_approval_token": "approval-token-1",
        },
    )
    assert result["text"].startswith("approved summary")
    assert result["tool_events"][0]["name"] == "exec_command"
    assert result["tool_events"][0]["status"] == "ok"
    assert result["inspector"]["run_state"]["pending_approval"] == {}
    assert any(item["type"] == "approval.approved" for item in result["inspector"]["trace_events"])
    assert len(
        [item for item in backend.invocations[0]["messages"] if isinstance(item, _FakeSystemMessage)]
    ) == 1
    sent_messages = backend.invocations[0]["messages"]
    assert not any(
        "[approved_command_execution_result]" in str(item.content or "")
        for item in sent_messages
        if isinstance(item, _FakeHumanMessage)
    )
    approval_results = [item for item in sent_messages if isinstance(item, _FakeToolMessage)]
    assert approval_results[-1].tool_call_id == "tc-approval"
    assert result["plan"] == [{"step": "Run the requested check", "status": "in_progress"}]


def test_runtime_approve_thread_creates_narrow_command_rule(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ApprovedCommandTools()
    backend = _FakeBackendWithTools([_FakeMessage(content="thread approval saved")], tools)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    command = "python -c \"print('x')\""

    result = runtime.run(
        message="Always allow this command in the Thread",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-command-thread-approval",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"role": "user", "content": "run risky command"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tc-thread-approval",
                                "name": "exec_command",
                                "args": {"cmd": command, "cwd": str(tmp_path)},
                            }
                        ],
                    },
                ],
            },
            "pending_turn": {
                "schema_version": 1,
                "type": "command_execution",
                "turn_id": "turn-thread-rule",
                "request_message": "run risky command",
                "tool_call_id": "tc-thread-approval",
                "tool_call": {
                    "id": "tc-thread-approval",
                    "name": "exec_command",
                    "args": {"cmd": command, "cwd": str(tmp_path)},
                },
            },
            "user_input_response": {
                "type": "command_execution",
                "action": "approve_thread",
                "approval_token": "approval-token-thread",
                "command": command,
                "cwd": str(tmp_path),
            },
        },
    )

    assert tools.calls[0] == (
        "exec_command",
        {
            "cmd": command,
            "cwd": str(tmp_path),
            "approval_token": "approval-token-thread",
            "tainted_approval_token": "approval-token-thread",
            "approval_scope": "thread",
        },
    )
    assert result["text"].startswith("thread approval saved")
    approved_trace = next(
        item for item in result["inspector"]["trace_events"] if item["type"] == "approval.approved"
    )
    assert approved_trace["payload"]["approval_scope"] == "thread"
    assert approved_trace["payload"]["thread_rule"]["rule_id"] == "thread-rule-1"
    assert result["pending_approval"] == {}


def test_runtime_declined_command_resumes_with_one_tool_result_and_no_human_message(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ApprovedCommandTools()
    backend = _FakeBackendWithTools([_FakeMessage(content="I will continue without that command.")], tools)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    context = {
        "session_id": "s-command-declined",
        "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
        "thread_transcript": {
            "schema_version": 1,
            "items": [
                {"role": "user", "content": "run risky command"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc-declined",
                            "name": "exec_command",
                            "args": {"cmd": "python -c \"print('x')\"", "cwd": str(tmp_path)},
                        }
                    ],
                },
            ],
        },
        "pending_turn": {
            "schema_version": 1,
            "type": "command_execution",
            "turn_id": "turn-original",
            "request_message": "run risky command",
            "tool_call_id": "tc-declined",
            "tool_call": {
                "id": "tc-declined",
                "name": "exec_command",
                "args": {"cmd": "python -c \"print('x')\"", "cwd": str(tmp_path)},
            },
        },
        "user_input_response": {
            "type": "command_execution",
            "action": "cancel",
            "tool_call_id": "tc-declined",
        },
        "attachments": [],
    }

    result = runtime.run(
        message="run risky command",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context=context,
    )

    assert tools.calls == []
    sent_messages = backend.invocations[0]["messages"]
    human_messages = [item for item in sent_messages if isinstance(item, _FakeHumanMessage)]
    assert len(human_messages) == 1
    assert human_messages[0].content == "run risky command"
    tool_results = [item for item in sent_messages if isinstance(item, _FakeToolMessage)]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "tc-declined"
    assert "user_declined" in str(tool_results[0].content)
    assert [item["role"] for item in result["transcript_delta"]] == ["tool"]
    assert result["pending_turn"] == {}


def test_runtime_request_user_input_pauses_and_resumes_the_same_turn(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    first_tools = _ScriptedTools(
        [
            {
                "ok": True,
                "pending": True,
                "summary": "Choose the target format.",
                "questions": [
                    {
                        "id": "format",
                        "header": "Format",
                        "question": "Which format?",
                        "options": [{"label": "Markdown"}, {"label": "JSON"}],
                    }
                ],
            }
        ]
    )
    first_backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-input", "name": "request_user_input", "args": {}}],
            )
        ],
        first_tools,
    )
    first_runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=first_backend,
    )

    first = first_runtime.run(
        message="Prepare the report.",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-user-input-resume",
            "run_id": "run-first",
            "logical_turn_id": "turn-original",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "attachments": [],
        },
    )

    assert first["turn_status"] == "needs_user_input"
    assert first["pending_user_input"]["type"] == "request_user_input"
    assert first["pending_turn"]["turn_id"] == "turn-original"
    assert [item["role"] for item in first["transcript_delta"]] == ["assistant"]

    second_tools = _ApprovedCommandTools()
    second_backend = _FakeBackendWithTools(
        [_FakeMessage(content="I will deliver the report as Markdown.")],
        second_tools,
    )
    second_runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=second_backend,
    )
    second = second_runtime.run(
        message="Prepare the report.",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-user-input-resume",
            "run_id": "run-resume",
            "logical_turn_id": "turn-original",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"role": "user", "content": "Prepare the report."},
                    *first["transcript_delta"],
                ],
            },
            "pending_turn": first["pending_turn"],
            "user_input_response": {
                "type": "request_user_input",
                "tool_call_id": "tc-input",
                "response": "Markdown",
            },
            "attachments": [],
        },
    )

    sent_messages = second_backend.invocations[0]["messages"]
    human_messages = [item for item in sent_messages if isinstance(item, _FakeHumanMessage)]
    assert len(human_messages) == 1
    assert human_messages[0].content == "Prepare the report."
    input_results = [item for item in sent_messages if isinstance(item, _FakeToolMessage)]
    assert len(input_results) == 1
    assert input_results[0].tool_call_id == "tc-input"
    assert "Markdown" in str(input_results[0].content)
    assert second["turn_status"] == "completed"
    assert second["pending_turn"] == {}


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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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
    assert result["tool_events"][0]["validation_result"]["allowed"] is True
    assert "q->query" in result["tool_events"][0]["validation_result"]["normalization_notes"]


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
    assert result["tool_events"][0]["validation_result"]["allowed"] is False
    assert result["tool_events"][0]["status"] == "rejected"
    assert result["tool_events"][0]["raw_tool_call"]["name"] == "read"
    assert len(backend.invocations) == 2
    followup_messages = backend.invocations[1]["messages"]
    tool_message = next(item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc1")
    assert "\"type\": \"validation_error\"" in str(tool_message.content) or "\"type\": \"boundary_denied\"" in str(tool_message.content)
    assert "\"tool\": \"read\"" in str(tool_message.content)
    assert runtime._messages_at_tool_boundary(followup_messages)
    assert len([item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc1"]) == 1


def test_runtime_drains_all_model_tool_calls_without_cap(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    tool_calls = [
        {"id": f"tc{index}", "name": "web_search", "args": {"query": f"query-{index}"}}
        for index in range(12)
    ]
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=tool_calls),
            _FakeMessage(content="final after all tools"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="分析当前文件夹里的工具实现",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-drain-all-tools",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "final after all tools"
    assert len(backend.tools.calls) == 12
    assert len(result["tool_events"]) == 12
    followup_messages = backend.invocations[1]["messages"]
    tool_messages = [
        item
        for item in followup_messages
        if str(item.kwargs.get("tool_call_id") or "").startswith("tc")
    ]
    assert len(tool_messages) == 12
    assert {item.kwargs["tool_call_id"] for item in tool_messages} == {f"tc{index}" for index in range(12)}
    assert runtime._messages_at_tool_boundary(followup_messages)


def test_runtime_tool_failure_still_closes_call_id(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    tools = _FailingTools()
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc-fail", "name": "web_search", "args": {"query": "x"}}]),
            _FakeMessage(content="recovered"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-tool-failure-closes-id",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "recovered"
    followup_messages = backend.invocations[1]["messages"]
    tool_message = next(item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc-fail")
    assert '"ok": false' in str(tool_message.content)
    assert "tool_execution_error" in str(tool_message.content)
    assert "boom" in str(tool_message.content)
    assert runtime._messages_at_tool_boundary(followup_messages)


def test_runtime_records_completed_initial_llm_exchange(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="Done.")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="直接回答",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-llm-exchange-initial",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 1
    exchange = exchanges[0]
    assert exchange["phase"] == "initial"
    assert exchange["status"] == "completed"
    assert exchange["sent_messages_exact"][0]["role"] == "system"
    assert exchange["sent_messages_exact"][-1]["role"] == "user"
    assert exchange["model_returned_exact"]["content"] == "Done."
    assert exchange["harness_interpretation"]["decision"] == "final_answer"
    assert exchange["harness_interpretation"]["final_answer_allowed"] is True
    assert result["inspector"]["run_state"]["llm_exchanges"] == exchanges
    assert all("llm_exchanges" not in dict(item.get("payload") or {}) for item in result["activity"]["trace_events"])


def test_runtime_sends_current_attachments_to_model_messages(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    attachment_path = str(tmp_path / "report.md")
    backend = _FakeBackend([_FakeMessage(content="收到附件。")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我看一下这个附件",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-current-attachments",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "att-1",
                    "name": "report.md",
                    "mime": "text/markdown",
                    "kind": "document",
                    "path": attachment_path,
                }
            ],
        },
    )

    sent = json.dumps(result["activity"]["llm_exchanges"][0]["sent_messages_exact"], ensure_ascii=False)

    assert "current_attachments" in sent
    assert "report.md" in sent
    assert "text/markdown" in sent
    assert "document" in sent
    assert attachment_path in sent
    assert backend.invocations[0]["messages"][-1].content == "帮我看一下这个附件"
    assert len(
        [item for item in backend.invocations[0]["messages"] if isinstance(item, _FakeSystemMessage)]
    ) == 1
    assert any(
        '"current_attachments"' in str(item.content or "")
        for item in backend.invocations[0]["messages"]
        if isinstance(item, _FakeHumanMessage)
    )
    assert any(
        attachment_path in str(item.content or "")
        for item in backend.invocations[0]["messages"]
        if isinstance(item, _FakeHumanMessage)
    )


def test_runtime_records_tool_and_followup_llm_exchanges(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="I will inspect the folder.", tool_calls=[{"id": "tc-llm-tool", "name": "web_search", "args": {"query": "x"}}]),
            _FakeMessage(content="final after tool"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-llm-exchange-followup",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 2
    initial_exchange, followup_exchange = exchanges
    assert initial_exchange["model_returned_exact"]["tool_calls"][0]["id"] == "tc-llm-tool"
    assert initial_exchange["model_returned_exact"]["tool_calls"][0]["name"] == "web_search"
    assert initial_exchange["harness_interpretation"]["has_tool_calls"] is True
    assert initial_exchange["harness_interpretation"]["decision"] == "tool_call"
    tool_messages = [item for item in followup_exchange["sent_messages_exact"] if item["role"] == "tool"]
    assert tool_messages
    assert tool_messages[0]["tool_call_id"] == "tc-llm-tool"
    assert followup_exchange["model_returned_exact"]["content"] == "final after tool"
    assert followup_exchange["harness_interpretation"]["decision"] == "final_answer"


def test_runtime_blocks_when_followup_model_action_is_empty_after_successful_local_file_tool(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    (tmp_path / "notes.txt").write_text("local context", encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc-empty-followup", "name": "read_file", "args": {"path": "notes.txt"}}]),
            _FakeMessage(content=""),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="读取 notes.txt 后继续处理",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", locale="zh-CN"),
        context={
            "session_id": "s-empty-followup-after-tool",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "blocked"
    assert result["final_answer"] == ""
    assert result["runtime_error"] == {}
    assert result["blocked_reason"] == "model_action_empty"
    assert "模型没有给出可执行的下一步" in result["text"]
    assert backend.tools.calls == [("read_file", {"path": "notes.txt"})]
    assert result["tool_events"][0]["status"] == "ok"
    assert result["blocked_stop_diagnostics"]["blocked_reason"] == "model_action_empty"

    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 2
    initial_exchange, followup_exchange = exchanges
    assert initial_exchange["harness_interpretation"]["decision"] == "tool_call"
    assert followup_exchange["phase"] == "post_tool_response"
    assert followup_exchange["status"] == "completed"
    assert followup_exchange["model_returned_exact"]["content"] == ""
    assert followup_exchange["harness_interpretation"]["decision"] == "empty"
    assert followup_exchange["harness_interpretation"]["turn_status_after_round"] == "blocked"
    assert result["model_action"]["action_type"] == "empty"
    assert result["model_action"]["accepted"] is False
    assert result["execution_trace"][-1]["payload"]["response_kind"] == "empty_response"


def test_runtime_recovers_once_from_invalid_tool_call(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    (tmp_path / "notes.txt").write_text("local context", encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                invalid_tool_calls=[
                    {
                        "id": "bad-call",
                        "name": "apply_patch",
                        "args": '{"patch":',
                        "error": "Function apply_patch arguments are not valid JSON.",
                    }
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-recovered", "name": "read_file", "args": {"path": "notes.txt"}}],
            ),
            _FakeMessage(content="recovered after correcting the native tool call"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="读取 notes.txt 后给出结论",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", locale="zh-CN"),
        context={
            "session_id": "s-invalid-tool-call-recovery",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "recovered after correcting the native tool call"
    assert backend.tools.calls == [("read_file", {"path": "notes.txt"})]
    assert result["replan_history"][0]["trigger"] == "invalid_tool_call"
    exchanges = result["activity"]["llm_exchanges"]
    assert exchanges[0]["harness_interpretation"]["decision"] == "invalid_tool_call"
    assert exchanges[0]["harness_interpretation"]["has_invalid_tool_calls"] is True
    assert exchanges[1]["phase"] == "model_action_recovery:invalid_tool_call"
    assert exchanges[1]["harness_interpretation"]["decision"] == "tool_call"
    assert result["model_action"]["action_type"] == "final_answer"
    assert "args" not in result["replan_history"][0]["structured_failures"][0]


def test_runtime_keeps_requesting_protocol_repair_for_invalid_tool_calls(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    invalid = {
        "id": "bad-call",
        "name": "apply_patch",
        "args": '{"patch":',
        "error": "Function apply_patch arguments are not valid JSON.",
    }
    backend = _FakeBackend(
        [
            _FakeMessage(content="", invalid_tool_calls=[invalid]),
            _FakeMessage(content="", invalid_tool_calls=[{**invalid, "id": "bad-call-again"}]),
            _FakeMessage(content="must not be reached"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="修改现有文件",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", locale="zh-CN"),
        context={
            "session_id": "s-invalid-tool-call-repeated",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert result["text"] == "must not be reached"
    assert backend.tools.calls == []
    assert len(backend.invocations) == 3
    assert [item["trigger"] for item in result["replan_history"]] == [
        "invalid_tool_call",
        "invalid_tool_call",
    ]
    exchanges = result["activity"]["llm_exchanges"]
    assert exchanges[1]["harness_interpretation"]["decision"] == "invalid_tool_call"
    assert exchanges[-1]["harness_interpretation"]["decision"] == "final_answer"
    assert exchanges[-1]["harness_interpretation"]["turn_status_after_round"] == "completed"


def test_runtime_does_not_invent_recovery_when_model_goes_empty_after_tool_failure(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ScriptedTools(
        [
            {
                "ok": False,
                "error": {
                    "kind": "file_already_exists",
                    "operation": "add",
                    "message": "Cannot add file because it already exists: SKILL.md",
                    "recovery": "Retry with *** Update File: SKILL.md.",
                },
            },
            {"ok": True, "files": [str(tmp_path / "SKILL.md")]},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-add-existing",
                        "name": "apply_patch",
                        "args": {"patch": "*** Begin Patch\n*** Add File: SKILL.md\n+new\n*** End Patch"},
                    }
                ],
            ),
            _FakeMessage(content=""),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-update-existing",
                        "name": "apply_patch",
                        "args": {
                            "patch": "*** Begin Patch\n*** Update File: SKILL.md\n@@\n-old\n+new\n*** End Patch"
                        },
                    }
                ],
            ),
            _FakeMessage(content="updated the existing skill"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="更新现有的 SKILL.md",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", locale="zh-CN"),
        context={
            "session_id": "s-empty-after-file-exists",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "blocked"
    assert result["blocked_reason"] == "model_action_empty"
    assert [name for name, _ in tools.calls] == ["apply_patch"]
    assert result["failure_recovery"]["records"][0]["error_kind"] == "file_already_exists"
    assert result["replan_history"] == []
    assert len(backend.invocations) == 2


def test_runtime_reports_generic_empty_action_after_failure(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    tools = _ScriptedTools(
        [
            {
                "ok": False,
                "error": {
                    "kind": "file_already_exists",
                    "message": "Cannot add file because it already exists: SKILL.md",
                },
            }
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "SKILL.md"}}],
            ),
            _FakeMessage(content=""),
            _FakeMessage(content=""),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="继续处理现有 SKILL.md",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", locale="zh-CN"),
        context={
            "session_id": "s-empty-after-failure-recovery-empty",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "blocked"
    assert result["blocked_reason"] == "model_action_empty"
    assert len(backend.invocations) == 2
    assert result["replan_history"] == []


def test_runtime_llm_followup_failure_preserves_debug_context(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FailingFollowupBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc-debug", "name": "web_search", "args": {"query": "x"}}]),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-followup-failure-debug",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "failed"
    assert result["final_answer"] == ""
    assert result["runtime_error"]["kind"] == "llm_request_error"
    assert result["runtime_error"]["phase"] == "before_followup_llm"
    assert result["runtime_error"]["message"] == "azure rejected broken history"
    assert "azure rejected broken history" not in result["text"]
    assert len(result["tool_events"]) == 1
    failed = next(item for item in result["activity"]["trace_events"] if item.get("type") == "llm.failed")
    payload = failed["payload"]
    assert payload["exception_type"] == "RuntimeError"
    assert payload["exception_module"] == "builtins"
    assert "traceback_tail" in payload
    assert payload["tool_boundary_clean"] is True
    assert payload["message_count"] == len(backend.invocations[1]["messages"])
    assert payload["phase"] == "before_followup_llm"
    assert payload["last_successful_round"] == 0
    assert payload["failed_round"] == 1
    assert payload["last_message_roles"][-1] == "tool"
    assert runtime._messages_at_tool_boundary(backend.invocations[1]["messages"])
    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 2
    failed_exchange = exchanges[-1]
    assert failed_exchange["phase"] == "post_tool_response"
    assert failed_exchange["status"] == "failed"
    assert failed_exchange["model_returned_exact"] is None
    assert failed_exchange["error"]["kind"] == "llm_request_error"
    assert failed_exchange["error"]["message"] == "azure rejected broken history"
    assert any(item["tool_call_id"] == "tc-debug" for item in failed_exchange["sent_messages_exact"] if item["role"] == "tool")
    assert failed_exchange["harness_interpretation"]["decision"] == "runtime_error"
    assert failed_exchange["harness_interpretation"]["turn_status_after_round"] == "failed"


def _oversized_thread_transcript() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index in range(8):
        items.extend(
            [
                {
                    "id": f"old-user-{index}",
                    "turn_id": f"old-turn-{index}",
                    "role": "user",
                    "content": f"old request {index} " + ("attachment evidence " * 3000),
                },
                {
                    "id": f"old-assistant-{index}",
                    "turn_id": f"old-turn-{index}",
                    "role": "assistant",
                    "content": f"old answer {index} " + ("investigation result " * 3000),
                },
            ]
        )
    return {"schema_version": 1, "items": items}


def test_runtime_compacts_locally_and_retries_one_413_request(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _RequestTooLargeInitialBackend(
        [_FakeMessage(content="Recovered after local compaction.")],
        fail_times=1,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    progress_events: list[dict[str, Any]] = []

    result = runtime.run(
        message="继续调查，但不要重新读取大附件",
        settings=ChatSettings(
            model="gpt-test",
            enable_tools=True,
            permission_profile="full_dev",
            locale="zh-CN",
        ),
        context={
            "session_id": "s-request-too-large-recovers",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": _oversized_thread_transcript(),
            "attachments": [],
        },
        progress_cb=progress_events.append,
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "Recovered after local compaction."
    assert result["runtime_error"] == {}
    assert len(backend.invocations) == 2
    first_chars = sum(len(str(message.content)) for message in backend.invocations[0]["messages"])
    retry_chars = sum(len(str(message.content)) for message in backend.invocations[1]["messages"])
    assert retry_chars < first_chars
    recovery = result["request_too_large_recovery"]
    assert recovery["attempted"] is True
    assert recovery["compacted"] is True
    assert recovery["retried"] is True
    assert recovery["recovered"] is True
    assert recovery["after_bytes"] < recovery["before_bytes"]

    exchanges = result["activity"]["llm_exchanges"]
    assert [item["phase"] for item in exchanges] == [
        "initial",
        "initial_request_too_large_retry",
    ]
    assert [item["status"] for item in exchanges] == ["failed", "completed"]
    assert exchanges[0]["error"]["kind"] == "request_too_large"
    assert "nginx/1.30.1" in exchanges[0]["error"]["raw_message"]
    assert "nginx/1.30.1" not in exchanges[0]["error"]["message"]
    trace_types = [item.get("type") for item in result["activity"]["trace_events"]]
    assert "llm.request_too_large.compacting" in trace_types
    assert "llm.request_too_large.retry_succeeded" in trace_types
    assert "llm.failed" not in trace_types
    compaction_items = [
        event["item"]
        for event in progress_events
        if event.get("event") == "item/completed"
        and str((event.get("item") or {}).get("type") or "") == "contextCompaction"
    ]
    assert len(compaction_items) == 1
    assert compaction_items[0]["reason"] == "request_too_large"
    assert "正在进行唯一一次重试" in compaction_items[0]["summary"]


def test_runtime_does_not_resend_413_when_no_old_context_can_be_compacted(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _RequestTooLargeInitialBackend([], fail_times=2)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="读取当前这个很大的附件",
        settings=ChatSettings(
            model="gpt-test",
            enable_tools=True,
            permission_profile="full_dev",
            locale="zh-CN",
        ),
        context={
            "session_id": "s-request-too-large-current-attachment",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {"schema_version": 1, "items": []},
            "attachments": [],
        },
    )

    assert len(backend.invocations) == 1
    assert result["turn_status"] == "failed"
    assert result["runtime_error"]["kind"] == "request_too_large"
    assert result["runtime_error"]["status_code"] == 413
    assert "nginx/1.30.1" in result["runtime_error"]["raw_message"]
    assert "nginx/1.30.1" not in result["text"]
    assert "移除或缩小" in result["text"]
    recovery = result["request_too_large_recovery"]
    assert recovery["attempted"] is True
    assert recovery["compacted"] is False
    assert recovery["retried"] is False


def test_runtime_stops_after_single_compacted_413_retry(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _RequestTooLargeInitialBackend([], fail_times=3)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="继续调查",
        settings=ChatSettings(
            model="gpt-test",
            enable_tools=True,
            permission_profile="full_dev",
            locale="zh-CN",
        ),
        context={
            "session_id": "s-request-too-large-retry-once",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": _oversized_thread_transcript(),
            "attachments": [],
        },
    )

    assert len(backend.invocations) == 2
    assert result["turn_status"] == "failed"
    assert result["runtime_error"]["kind"] == "request_too_large"
    assert result["runtime_error"]["retry_attempt"] == 1
    assert result["runtime_error"]["phase"] == "initial_request_too_large_retry"
    recovery = result["request_too_large_recovery"]
    assert recovery["compacted"] is True
    assert recovery["retried"] is True
    assert recovery["recovered"] is False


def test_runtime_compacts_and_retries_one_followup_413_request(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _RequestTooLargeFollowupBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-413-followup",
                        "name": "web_search",
                        "args": {"query": "latest evidence"},
                    }
                ],
            ),
            _FakeMessage(content="Recovered follow-up response."),
        ],
        fail_times=1,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="搜索后继续总结",
        settings=ChatSettings(
            model="gpt-test",
            enable_tools=True,
            permission_profile="full_dev",
            locale="zh-CN",
        ),
        context={
            "session_id": "s-request-too-large-followup",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": _oversized_thread_transcript(),
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "Recovered follow-up response."
    assert [item["kind"] for item in backend.invocations] == [
        "initial",
        "followup",
        "followup",
    ]
    assert result["request_too_large_recovery"]["recovered"] is True
    exchanges = result["activity"]["llm_exchanges"]
    assert [item["phase"] for item in exchanges] == [
        "initial",
        "post_tool_response",
        "post_tool_response_request_too_large_retry",
    ]
    assert [item["status"] for item in exchanges] == [
        "completed",
        "failed",
        "completed",
    ]
    assert runtime._messages_at_tool_boundary(backend.invocations[-1]["messages"])


def test_runtime_retries_clean_boundary_nonetype_model_dump_failure(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FlakyNoneTypeFollowupBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc-retry", "name": "web_search", "args": {"query": "x"}}]),
            _FakeMessage(content="retry recovered"),
        ],
        fail_times=1,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-followup-retry-debug",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "retry recovered"
    assert result["turn_status"] == "completed"
    trace_types = [item.get("type") for item in result["activity"]["trace_events"]]
    assert "llm.retrying" in trace_types
    assert "llm.retry_succeeded" in trace_types
    assert "llm.failed" not in trace_types
    retrying = next(item for item in result["activity"]["trace_events"] if item.get("type") == "llm.retrying")
    assert retrying["payload"]["tool_boundary_clean"] is True
    assert retrying["payload"]["exception_type"] == "AttributeError"
    assert runtime._messages_at_tool_boundary(backend.invocations[1]["messages"])
    assert runtime._messages_at_tool_boundary(backend.invocations[2]["messages"])
    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 3
    assert [item["phase"] for item in exchanges] == ["initial", "post_tool_response", "post_tool_response_retry"]
    assert [item["status"] for item in exchanges] == ["completed", "failed", "completed"]
    assert exchanges[1]["error"]["kind"] == "llm_empty_response"
    assert exchanges[2]["model_returned_exact"]["content"] == "retry recovered"


def test_runtime_retry_failure_reports_rich_llm_diagnostics(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FlakyNoneTypeFollowupBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc-retry-fails", "name": "web_search", "args": {"query": "x"}}]),
        ],
        fail_times=2,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-followup-retry-fails",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "failed"
    assert result["final_answer"] == ""
    assert result["runtime_error"]["kind"] == "llm_empty_response"
    assert result["runtime_error"]["phase"] == "before_followup_llm_retry"
    trace_events = result["activity"]["trace_events"]
    trace_types = [item.get("type") for item in trace_events]
    assert "llm.retrying" in trace_types
    assert "llm.retry_failed" in trace_types
    failed = next(item for item in trace_events if item.get("type") == "llm.failed")
    assert failed["payload"]["exception_type"] == "AttributeError"
    assert failed["payload"]["kind"] == "llm_empty_response"
    assert failed["payload"]["tool_boundary_clean"] is True
    assert failed["payload"]["retry_attempt"] == 1
    assert failed["payload"]["failed_round"] == 1
    assert "traceback_tail" in failed["payload"]
    exchanges = result["activity"]["llm_exchanges"]
    assert len(exchanges) == 3
    assert [item["status"] for item in exchanges] == ["completed", "failed", "failed"]
    assert exchanges[-1]["phase"] == "post_tool_response_retry"
    assert exchanges[-1]["error"]["kind"] == "llm_empty_response"
    assert exchanges[-1]["harness_interpretation"]["decision"] == "runtime_error"


def test_runtime_tool_call_content_uses_model_draft_until_completed(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="I will inspect the folder.", tool_calls=[{"id": "tc-draft", "name": "web_search", "args": {"query": "x"}}]),
            _FakeMessage(content="Done."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-model-draft",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["final_answer"] == "Done."
    assert result["model_draft"] == "I will inspect the folder."
    assert result["runtime_error"] == {}
    assert result["text"] == "Done."


def test_runtime_failed_followup_preserves_model_draft_in_activity(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FlakyNoneTypeFollowupBackend(
        [
            _FakeMessage(
                content="I will inspect the folder first.",
                tool_calls=[{"id": "tc-draft-fail", "name": "web_search", "args": {"query": "x"}}],
            ),
        ],
        fail_times=2,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查一下 x",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-model-draft-fail",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "failed"
    assert result["final_answer"] == ""
    assert result["model_draft"] == "I will inspect the folder first."
    assert result["runtime_error"]["kind"] == "llm_empty_response"
    assert result["activity"]["model_draft"] == "I will inspect the folder first."


def test_runtime_model_stream_observer_ignores_none_event(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    trace_events: list[dict[str, Any]] = []
    observer = runtime._make_model_stream_observer(
        progress_cb=None,
        run_id="run-stream-none",
        thread_id="thread-stream-none",
        locale="zh-CN",
        trace_events=trace_events,
        answer_stream_state=new_answer_stream_state(run_id="run-stream-none", thread_id="thread-stream-none"),
        stage="post_tool_response",
        model="gpt-test",
        tool_round=1,
    )

    observer(None)

    assert any(item.get("type") == "llm.stream_event.none" for item in trace_events)


def test_runtime_rejects_redaction_placeholder_as_glob_pattern(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-redacted-glob", "name": "glob_file_search", "args": {"pattern": "***", "path": "."}}],
            ),
            _FakeMessage(content="recovered"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="找一下文件",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-redacted-glob",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "recovered"
    assert backend.tools.calls == []
    followup_messages = backend.invocations[1]["messages"]
    tool_message = next(item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc-redacted-glob")
    assert "redaction_placeholder_used" in str(tool_message.content)
    assert "*** is a UI redaction placeholder" in str(tool_message.content)
    assert runtime._messages_at_tool_boundary(followup_messages)


def test_runtime_rejects_redaction_placeholder_as_search_query(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-redacted-search", "name": "search_codebase", "args": {"query": "***"}}],
            ),
            _FakeMessage(content="recovered"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="搜一下代码",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-redacted-search",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "recovered"
    assert backend.tools.calls == []
    followup_messages = backend.invocations[1]["messages"]
    tool_message = next(item for item in followup_messages if item.kwargs.get("tool_call_id") == "tc-redacted-search")
    assert "redaction_placeholder_used" in str(tool_message.content)
    assert runtime._messages_at_tool_boundary(followup_messages)


def test_tool_message_compaction_keeps_actionable_paths() -> None:
    long_asset_path = "dist/assets/index-0123456789abcdef0123456789abcdef.js"
    result = {
        "ok": True,
        "tool_name": "glob_file_search",
        "path": "dist/assets",
        "root_ref": "project_root",
        "resolved_path": "/tmp/project/dist/assets",
        "matches": [long_asset_path],
    }

    compact = VintageProgrammerRuntime._compact_tool_result_for_model(result, tool_name="glob_file_search")

    assert compact["matches"] == [long_asset_path]
    assert "***" not in json.dumps(compact, ensure_ascii=False)
    assert "resolved_path" not in compact


def test_runtime_cancel_during_tool_drain_closes_remaining_call_ids(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    cancel_event = threading.Event()
    tools = _CancellingTools(cancel_event, cancel_after_calls=1)
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {"id": "tc1", "name": "web_search", "args": {"query": "one"}},
                    {"id": "tc2", "name": "web_search", "args": {"query": "two"}},
                    {"id": "tc3", "name": "web_search", "args": {"query": "three"}},
                ],
            ),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查三个东西",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev"),
        context={
            "session_id": "s-cancel-drain",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
            "cancel_event": cancel_event,
        },
    )

    assert result["turn_status"] == "cancelled"
    assert len(result["tool_events"]) == 3
    assert {item["raw_tool_call"]["id"] for item in result["tool_events"]} == {"tc1", "tc2", "tc3"}
    assert any("tool_cancelled" in str(item["output_preview"]) for item in result["tool_events"])


def test_tool_call_preview_preserves_uuid_identity_but_masks_arguments() -> None:
    call_id = "call-0a039f75-e4e2-445f-bdda-0bc6ebc35946"
    opaque_token = "s" * 40

    preview = VintageProgrammerRuntime._safe_tool_call_preview(
        {
            "id": call_id,
            "name": "web_search",
            "arguments": {"token": opaque_token},
        }
    )

    assert preview["id"] == call_id
    assert preview["name"] == "web_search"
    assert opaque_token not in json.dumps(preview, ensure_ascii=False)


def test_runtime_messages_at_tool_boundary_detects_missing_tool_output(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="ok")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    ai = backend._AIMessage(
        content="",
        tool_calls=[
            {"id": "tc1", "name": "web_search", "args": {"query": "one"}},
            {"id": "tc2", "name": "web_search", "args": {"query": "two"}},
        ],
    ) if hasattr(backend, "_AIMessage") else _FakeMessage(
        content="",
        tool_calls=[
            {"id": "tc1", "name": "web_search", "args": {"query": "one"}},
            {"id": "tc2", "name": "web_search", "args": {"query": "two"}},
        ],
    )
    tool1 = backend._ToolMessage(content="{}", tool_call_id="tc1", name="web_search")

    assert runtime._messages_at_tool_boundary([ai, tool1]) is False

    tool2 = backend._ToolMessage(content="{}", tool_call_id="tc2", name="web_search")
    assert runtime._messages_at_tool_boundary([ai, tool1, tool2]) is True


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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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
    assert result["tool_events"][0]["validation_result"]["allowed"] is False
    assert result["tool_events"][0]["schema_validation"]["status"] == "invalid"
    assert result["tool_events"][1]["validation_result"]["allowed"] is True


def test_runtime_loads_only_explicitly_bound_project_profile_instructions(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    (tmp_path / "AGENTS.md").write_text("Repository AGENTS.md must not load implicitly.", encoding="utf-8")
    backend = _FakeBackend([_FakeMessage(content="done")])
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
            "project": {
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
                "profile_key": "team:pcbasher",
                "project_instructions": "Project contract: model-led turn planning only.",
            },
            "history_turns": [],
            "attachments": [],
        },
    )

    messages = backend.invocations[0]["messages"]
    system_messages = [item for item in messages if isinstance(item, _FakeSystemMessage)]
    assert len(system_messages) == 1
    assert "Project contract: model-led turn planning only." not in str(system_messages[0].content or "")
    assert any(
        "[project_instructions]" in str(item.content or "")
        and "Project contract: model-led turn planning only." in str(item.content or "")
        and "Repository AGENTS.md must not load implicitly." not in str(item.content or "")
        for item in messages
        if isinstance(item, _FakeHumanMessage)
    )
    assert messages[-1].content == "直接回答"


def test_runtime_does_not_load_project_instructions_without_profile_binding(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    (tmp_path / "AGENTS.md").write_text("Repository AGENTS.md must not load implicitly.", encoding="utf-8")
    backend = _FakeBackend([_FakeMessage(content="done")])
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
            "session_id": "s-no-project-profile",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path), "profile_key": ""},
            "history_turns": [],
            "attachments": [],
        },
    )

    messages = backend.invocations[0]["messages"]
    assert not any(
        "[project_instructions]" in str(item.content or "")
        or "Repository AGENTS.md must not load implicitly." in str(item.content or "")
        for item in messages
    )


def test_runtime_message_layers_keep_context_below_single_system_message(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    attachment_path = tmp_path / "spec.md"
    attachment_path.write_text("spec", encoding="utf-8")
    backend = _FakeBackend([_FakeMessage(content="done")])
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    runtime.run(
        message="current request",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-message-layers",
            "project": {
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
                "profile_key": "builtin:vintage-programmer",
                "project_instructions": "Repository rule",
            },
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"id": "u1", "turn_id": "u1", "role": "user", "content": "old"},
                    {"id": "a1", "turn_id": "a1", "role": "assistant", "content": "old answer"},
                    {"id": "u2", "turn_id": "u2", "role": "user", "content": "recent"},
                ],
            },
            "compaction_status": {
                "compacted_history": "older summary",
                "compacted_until_turn_id": "a1",
            },
            "attachments": [
                {
                    "id": "att-1",
                    "name": "spec.md",
                    "mime": "text/markdown",
                    "kind": "document",
                    "path": str(attachment_path),
                }
            ],
        },
    )

    messages = backend.invocations[0]["messages"]
    assert [type(item) for item in messages] == [
        _FakeSystemMessage,
        _FakeHumanMessage,
        _FakeHumanMessage,
        _FakeHumanMessage,
        _FakeHumanMessage,
        _FakeHumanMessage,
    ]
    assert "[current_runtime_context]" in messages[0].content
    assert "[project_instructions]" in messages[1].content
    assert "[thread_compaction_summary]" in messages[2].content
    assert messages[3].content == "recent"
    assert "[current_attachment_context]" in messages[4].content
    assert messages[5].content == "current request"


def test_runtime_replays_persisted_compaction_summary_when_status_only_has_metadata(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="done")])
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    runtime.run(
        message="current request",
        settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={
            "session_id": "s-compaction-summary-wire",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {
                "schema_version": 1,
                "items": [
                    {"id": "u1", "turn_id": "u1", "role": "user", "content": "old"},
                    {"id": "a1", "turn_id": "a1", "role": "assistant", "content": "old answer"},
                    {"id": "u2", "turn_id": "u2", "role": "user", "content": "recent"},
                ],
            },
            "summary": "persisted replacement summary",
            "compaction_status": {
                "compacted_history_present": True,
                "compacted_history_chars": 29,
                "compacted_until_turn_id": "a1",
            },
            "attachments": [],
        },
    )

    messages = backend.invocations[0]["messages"]
    assert any(
        "[thread_compaction_summary]" in str(item.content or "")
        and "persisted replacement summary" in str(item.content or "")
        for item in messages
        if isinstance(item, _FakeHumanMessage)
    )
    assert not any(str(item.content or "") == "old" for item in messages)
    assert any(str(item.content or "") == "recent" for item in messages)


def test_authorized_write_final_answer_is_not_runtime_steered(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="如果你确认要我修改，我可以给你补丁。请回一句补。"),
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

    assert backend.tools.calls == []
    assert result["text"] == "如果你确认要我修改，我可以给你补丁。请回一句补。"
    assert "invalid_final_guard" not in result
    assert "invalid_final_guard_steer" not in result["inspector"]["notes"]
    assert result["turn_status"] == "completed"


def test_repeated_confirmation_text_is_model_final_answer_not_runtime_block(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="请确认，我再 apply_patch。"),
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
    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert "invalid_final_guard" not in result


def test_runtime_sends_attachment_evidence_pack_to_model_messages(tmp_path: Path) -> None:
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
                    "text_preview": "hello attachment",
                    "read_hint": {"tool": "read_file", "path": "/tmp/requirements.pdf"},
                }
            ],
        },
    )

    first_messages = backend.invocations[0]["messages"]
    sent = json.dumps(result["activity"]["llm_exchanges"][0]["sent_messages_exact"], ensure_ascii=False)

    assert first_messages[-1].content == "查看资料，缺的直接补全。"
    assert "attachment_evidence" in sent
    assert "missing export button" in sent
    assert "hello attachment" in sent
    assert any(
        '"attachment_evidence"' in str(item.content or "")
        for item in first_messages
        if isinstance(item, _FakeHumanMessage)
    )
    assert result["attachment_evidence_pack_preview"][0]["name"] == "requirements.pdf"


def test_runtime_user_request_uses_openai_large_context_budget(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    long_request = "会议转录：" + ("重要内容" * 2000)

    visible_request, truncated = runtime._user_request_for_model(
        long_request,
        model="gpt-5.4",
        max_output_tokens=8192,
    )

    assert visible_request == long_request
    assert truncated is False


def test_human_payload_applies_user_request_limit_after_context_separation(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    config = _isolated_config(tmp_path)
    config.max_user_request_chars = 4000
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    long_request = "A" * 6000

    rendered = runtime._build_human_payload(
        message=long_request,
        context={"project": {"project_root": str(tmp_path), "cwd": str(tmp_path)}},
    )

    assert rendered == "A" * 4000
    assert "A" * 4001 not in rendered


def test_runtime_attachment_evidence_preview_uses_large_context_budget(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    config = _isolated_config(tmp_path)
    config.max_attachment_chars = 80_000
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    preview = "A" * 20_000

    packed = runtime._attachment_evidence_pack_for_model(
        [{"id": "a1", "name": "meeting.txt", "preview": preview}],
        preview_limit=runtime._attachment_preview_char_limit_for_model(model="gpt-5.4", max_output_tokens=8192),
    )

    assert len(packed[0]["preview"]) > 10_000


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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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
    assert "emergency_max_tool_calls_per_turn" not in result["inspector"]["run_state"]["loop_safeguards"]
    assert "max_total_tool_calls_per_turn" not in result["inspector"]["run_state"]["loop_safeguards"]


def test_runtime_can_continue_past_old_24_tool_calls_when_progress_continues(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend_messages = [
        _FakeMessage(
            content="",
            tool_calls=[{"id": f"tc{index}", "name": "read_file", "args": {"path": f"file_{index}.py"}}],
        )
        for index in range(1, 26)
    ]
    backend_messages.append(_FakeMessage(content="long productive loop done"))
    backend = _FakeBackend(backend_messages)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="持续检查不同文件直到完成",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-tool-budget-progress",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "long productive loop done"
    assert len(result["tool_events"]) == 25
    assert "turn_budget_emergency_tool_calls_exceeded" not in result["inspector"]["notes"]


def test_runtime_ignores_legacy_emergency_tool_call_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import app.vintage_programmer_runtime as runtime_module

    base_safeguards = runtime_module.default_loop_safeguards()
    monkeypatch.setattr(
        runtime_module,
        "default_loop_safeguards",
        lambda: {
            **base_safeguards,
            "emergency_max_tool_calls_per_turn": 2,
        },
    )

    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "a.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read_file", "args": {"path": "b.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "read_file", "args": {"path": "c.py"}}]),
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
        message="持续读取文件直到结束",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-emergency-tool-cap",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert result["text"] == "should not reach"
    assert len(result["tool_events"]) == 3
    assert "turn_budget_emergency_tool_calls_exceeded" not in result["inspector"]["notes"]


def test_runtime_leaves_repeated_actions_to_the_model(tmp_path: Path) -> None:
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

    assert result["turn_status"] == "completed"
    assert result["text"] == "should not reach"
    assert len(result["tool_events"]) == 6
    assert result["inspector"]["run_state"]["replan_history"] == []
    assert "turn_budget_same_action_repeats_exceeded" not in result["inspector"]["notes"]


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


def test_runtime_does_not_guess_whether_repeated_searches_make_progress(tmp_path: Path) -> None:
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
    assert "replan_requested:no_progress" not in result["inspector"]["notes"]
    assert result["inspector"]["run_state"]["replan_history"] == []
    assert all(
        len([item for item in invocation["messages"] if isinstance(item, _FakeSystemMessage)]) == 1
        for invocation in backend.invocations
    )
    assert not any(
        "[checkpoint_replan]" in str(item.content or "")
        for item in backend.invocations[-1]["messages"]
        if isinstance(item, _FakeHumanMessage)
    )
    assert any(
        signal["kind"] == "no_new_info"
        for signal in result["inspector"]["run_state"]["progress_signals"]
    )


def test_runtime_distinguishes_same_failure_class_with_different_targets(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ScriptedTools(
        [
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126},
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126},
            {"ok": True, "content": "alternative evidence"},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "exec_command", "args": {"cmd": "python missing_one.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "exec_command", "args": {"cmd": "python missing_two.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "read_file", "args": {"path": "README.md"}}]),
            _FakeMessage(content="recovered with a different strategy"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="检查两个候选命令，如果路径策略失败就换成读取已有文件",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-recover-same-failure-class",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "recovered with a different strategy"
    assert [call[0] for call in tools.calls] == ["exec_command", "exec_command", "read_file"]
    assert result["inspector"]["run_state"]["replan_history"] == []
    recovery = result["failure_recovery"]
    assert recovery["failure_count"] == 2
    assert recovery["repeated_failure_count"] == 0
    assert recovery["records"][0]["target_fingerprint"] != recovery["records"][1]["target_fingerprint"]
    assert all(item["consecutive_occurrence"] == 1 for item in recovery["records"])
    assert recovery["recoveries"][-1]["recovered_by_tool"] == "read_file"
    tool_messages = [
        str(message.content or "")
        for invocation in backend.invocations
        for message in invocation["messages"]
        if isinstance(message, _FakeToolMessage)
    ]
    assert any("runtime_failure" in message and "command_path_outside_allowed_roots" in message for message in tool_messages)


def test_runtime_returns_environment_failures_to_the_model_without_stopping(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    tools = _ScriptedTools(
        [
            {"ok": False, "error_kind": "tool_unavailable"},
            {"ok": False, "error_kind": "tool_unavailable"},
            {"ok": False, "error_kind": "tool_unavailable"},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "one.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read_file", "args": {"path": "two.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "read_file", "args": {"path": "three.md"}}]),
            _FakeMessage(content="should not claim completion"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="读取可用文件；如果工具环境不可用则明确停止",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-environment-block",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert result["text"] == "should not claim completion"
    assert len(tools.calls) == 3
    assert result["failure_recovery"]["failure_categories"] == {"environment_blocked": 3}
    assert result["failure_recovery"]["records"][-1]["retryability"] == "blocked"
    assert result["replan_history"] == []


def test_runtime_leaves_repeated_tool_failures_to_the_model(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ScriptedTools(
        [
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126},
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126},
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "exec_command", "args": {"cmd": "python one.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "exec_command", "args": {"cmd": "python one.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "exec_command", "args": {"cmd": "python one.py"}}]),
            _FakeMessage(content="should not claim completion"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="检查命令路径；同类边界错误重复时必须换方案或停止",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-repeated-tool-call-failure",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert len(tools.calls) == 3
    assert result["failure_recovery"]["failure_categories"] == {"tool_call_failure": 3}
    assert result["failure_recovery"]["repeated_failure_count"] == 2
    assert result["text"] == "should not claim completion"
    assert result["replan_history"] == []


def test_runtime_executes_all_calls_and_allows_new_strategy_after_failures(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    bad_root = "RunningTP_MT/Script/PLP_10.cpp"
    bad_root_path = tmp_path / bad_root
    bad_root_path.parent.mkdir(parents=True, exist_ok=True)
    bad_root_path.write_text("PLP", encoding="utf-8")
    tools = _ScriptedTools(
        [
            {"ok": False, "error": f"Not a directory: {bad_root}"},
            {"ok": False, "error": f"Not a directory: {bad_root}"},
            {"ok": False, "error": f"Not a directory: {bad_root}"},
            {"ok": True, "command": f"rg -n PLP {bad_root}", "returncode": 0, "output": "PLP_10.cpp:1:match"},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "search_codebase", "args": {"query": "PLP", "root": bad_root}}],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {"id": "tc2", "name": "search_codebase", "args": {"query": "PLP", "root": bad_root}},
                    {"id": "tc3", "name": "search_codebase", "args": {"query": "PLP", "root": bad_root}},
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc4",
                        "name": "exec_command",
                        "args": {"cmd": f"select-string -Pattern PLP {bad_root}"},
                    }
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc5", "name": "exec_command", "args": {"cmd": f"rg -n PLP {bad_root}"}}],
            ),
            _FakeMessage(content="recovered with rg"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="查找 PLP；同一搜索失败时重新规划，并改用允许的命令",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-new-strategy-after-replan",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "recovered with rg"
    assert [call[0] for call in tools.calls] == [
        "search_codebase",
        "search_codebase",
        "search_codebase",
        "exec_command",
    ]
    assert [item["status"] for item in result["tool_events"]] == ["error", "error", "error", "rejected", "ok"]
    recovery = result["failure_recovery"]
    assert recovery["failure_count"] == 4
    assert recovery["failure_outcomes"] == {"failed": 3, "rejected": 1}
    assert [item["error_kind"] for item in recovery["records"]] == [
        "not_a_directory",
        "not_a_directory",
        "not_a_directory",
        "command_not_allowed",
    ]
    assert recovery["records"][1]["repeated"] is True
    assert recovery["records"][3]["outcome"] == "rejected"
    assert recovery["records"][3]["failure_phase"] == "policy"
    assert result["replan_history"] == []
    assert result["blocked_reason"] == ""


def test_runtime_has_no_total_distinct_failure_budget(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ScriptedTools(
        [
            {"ok": False, "error_kind": "command_path_outside_allowed_roots", "returncode": 126}
            for _ in range(5)
        ]
    )
    backend = _FakeBackendWithTools(
        [
            *[
                _FakeMessage(
                    content="",
                    tool_calls=[
                        {"id": f"tc{index}", "name": "exec_command", "args": {"cmd": f"python target_{index}.py"}}
                    ],
                )
                for index in range(1, 6)
            ],
            _FakeMessage(content="should not reach"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="尝试不同目标，但总失败次数必须有上限",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-total-failure-budget",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert len(tools.calls) == 5
    assert result["failure_recovery"]["failure_count"] == 5
    assert len({item["target_fingerprint"] for item in result["failure_recovery"]["records"]}) == 5
    assert result["replan_history"] == []
    assert result["text"] == "should not reach"


def test_runtime_allows_model_to_recover_when_verification_precedes_target_mutation(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(
        agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"),
        encoding="utf-8",
    )
    tools = _ScriptedTools(
        [
            {"ok": False, "command": "python run_checks.py", "returncode": 1},
            {"ok": True, "files": [str(tmp_path / "REPORT.md")]},
            {"ok": True, "command": "python run_checks.py", "returncode": 0},
        ]
    )
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "exec_command", "args": {"cmd": "python run_checks.py"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "apply_patch", "args": {"patch": "*** Begin Patch\n*** Add File: REPORT.md\n+done\n*** End Patch"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "exec_command", "args": {"cmd": "python run_checks.py"}}]),
            _FakeMessage(content="implemented and verified"),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=_isolated_config(tmp_path),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="请修改 REPORT.md，完成后运行 run_checks.py 验证",
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
        context={
            "session_id": "s-verify-before-mutation",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "implemented and verified"
    first_failure = result["failure_recovery"]["records"][0]
    assert first_failure["category"] == "verification_failure"
    assert "precondition" not in first_failure
    assert result["replan_history"] == []
    assert "task_completion" not in result


def test_runtime_ignores_legacy_no_progress_safeguard_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.vintage_programmer_runtime as runtime_module

    base_safeguards = runtime_module.default_loop_safeguards()
    monkeypatch.setattr(
        runtime_module,
        "default_loop_safeguards",
        lambda: {
            **base_safeguards,
            "max_same_action_repeats": 100,
            "no_progress_threshold_before_replan": 2,
            "no_progress_threshold_after_replan": 1,
        },
    )
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "search_contents_in_file", "args": {"path": "app.js", "query": "missing"}}]),
            _FakeMessage(content="model chose to stop searching"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="先搜索，没有结果时继续尝试直到阻塞",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short", locale="zh-CN"),
        context={
            "session_id": "s-blocked-no-progress-detail",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert result["text"] == "model chose to stop searching"
    assert len(result["tool_events"]) == 4
    assert result["replan_history"] == []


def test_runtime_returns_repeated_guard_rejections_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.vintage_programmer_runtime as runtime_module

    base_safeguards = runtime_module.default_loop_safeguards()
    monkeypatch.setattr(
        runtime_module,
        "default_loop_safeguards",
        lambda: {
            **base_safeguards,
            "max_guard_rejections": 1,
            "automatic_replan": False,
        },
    )
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "read", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read", "args": {"path": "README.md"}}]),
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
        message="连续触发 guard 拒绝直到阻塞",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short", locale="zh-CN"),
        context={
            "session_id": "s-guard-blocked-detail",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["blocked_reason"] == ""
    assert result["text"] == "should not reach"
    assert [item["status"] for item in result["tool_events"]] == ["rejected", "rejected"]
    assert result["replan_history"] == []


def test_runtime_guard_safe_downgrades_command_substitution_before_counting_rejection(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "exec_command",
                        "args": {"cmd": 'output=$(python hello.py) && if [ "$output" = "Hello, World!" ]; then echo Match; fi'},
                    }
                ],
            ),
            _FakeMessage(content="done"),
        ],
        _FakeTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="先跑命令，再继续",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short", locale="zh-CN"),
        context={
            "session_id": "s-guard-safe-downgrade",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "done"
    assert backend.tools.calls
    assert backend.tools.calls[0][0] == "exec_command"
    assert backend.tools.calls[0][1]["cmd"] == "python hello.py"
    assert "tool_validation_rejection_replan_requested" not in result["inspector"]["notes"]
    assert any("guard_safe_downgrade" in note for note in result["inspector"]["notes"])


def test_runtime_returns_compound_shell_rejection_without_forcing_replan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.vintage_programmer_runtime as runtime_module

    base_safeguards = runtime_module.default_loop_safeguards()
    monkeypatch.setattr(
        runtime_module,
        "default_loop_safeguards",
        lambda: {
            **base_safeguards,
            "max_guard_rejections": 0,
            "automatic_replan": True,
        },
    )
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "exec_command", "args": {"cmd": "for file in *.py; do python \"$file\"; done"}}]),
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
        message="遇到 guard 拒绝后换一种更安全的命令方式",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short", locale="zh-CN"),
        context={
            "session_id": "s-guard-replan-hint",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "completed"
    assert result["text"] == "replanned answer"
    assert result["inspector"]["run_state"]["replan_history"] == []
    assert result["tool_events"][0]["status"] == "rejected"


def test_empty_model_action_message_preserves_recent_observability_without_replan_claim(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="done")]),
    )

    text = runtime._build_blocked_stop_message(
        locale="zh-CN",
        blocked_reason="model_action_empty",
        progress_signals=[
            {"has_progress": True, "kind": "command_result_changed", "summary": "命令结果发生了变化：python hello.py", "tool_name": "exec_command"},
            {"has_progress": True, "kind": "plan_updated", "summary": "检查清单新增完成项：1 项", "tool_name": "update_plan"},
        ],
        replan_history=[{"trigger": "validation_rejection_limit", "detail": "$.max_chars must be >= 128"}],
        tool_events=[
            ToolEvent(
                name="exec_command",
                arguments_preview='output=$(python hello.py) && if ...',
                output_preview="",
                summary="Compound command contains current unsupported shell structure: command substitution.",
                status="blocked",
                validation_result={"allowed": False, "code": "invalid_arguments"},
                schema_validation={"status": "invalid"},
            )
        ],
    )

    assert "最近被拒绝的动作" in text
    assert "最近有效进展" in text
    assert "最近 plan 更新" in text
    assert "output=$(python hello.py) && if ..." in text
    assert "命令结果发生了变化：python hello.py" in text
    assert "检查清单新增完成项：1 项" in text
    assert "复盘触发原因" not in text
    assert "validation_rejection_limit" not in text


@pytest.mark.parametrize("tool_count", [8, 12, 20])
def test_mid_turn_compaction_does_not_trigger_from_tool_count_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool_count: int,
) -> None:
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_FakeBackend([]),
    )
    messages = [_FakeSystemMessage(content="system"), *[_FakeHumanMessage(content=f"m-{idx}") for idx in range(14)]]
    tool_events = [
        ToolEvent(name="read_file", output_preview="ok", status="ok", summary=f"event-{idx}")
        for idx in range(tool_count)
    ]
    monkeypatch.setattr(runtime, "_estimate_model_request_tokens", lambda *args, **kwargs: 100)
    context_status = build_context_window_status(
        model="gpt-5.6-sol",
        current_tokens=0,
        auto_compact_token_limit=1000,
    )

    compacted_messages, compacted_until, compacted, status = runtime._maybe_compact_live_messages(
        messages=messages,
        base_message_count=1,
        tool_events=tool_events,
        compacted_until=0,
        model="gpt-5.6-sol",
        tool_names=["read_file"],
        max_output_tokens=1000,
        progress_cb=None,
        run_id="run-one",
        locale="en",
        trace_events=[],
        context_window_status=context_status,
    )

    assert compacted_messages is messages
    assert compacted_until == 0
    assert compacted is False
    assert status.estimated_context_tokens == 100


def test_mid_turn_compaction_runs_once_when_token_threshold_is_crossed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_FakeBackend([]),
    )
    messages = [_FakeSystemMessage(content="system"), *[_FakeHumanMessage(content=f"m-{idx}") for idx in range(14)]]
    tool_events = [
        ToolEvent(name="read_file", output_preview="ok", status="ok", summary=f"event-{idx}")
        for idx in range(20)
    ]
    calls = {"count": 0}

    monkeypatch.setattr(runtime, "_estimate_model_request_tokens", lambda *args, **kwargs: 1000)
    context_status = build_context_window_status(
        model="gpt-5.6-sol",
        current_tokens=0,
        auto_compact_token_limit=1000,
    )

    def compact_summary(**_kwargs: Any) -> str:
        calls["count"] += 1
        return "structured continuation memory"

    monkeypatch.setattr(runtime, "_build_live_compaction_summary", compact_summary)
    compacted_messages, compacted_until, compacted, status = runtime._maybe_compact_live_messages(
        messages=messages,
        base_message_count=1,
        tool_events=tool_events,
        compacted_until=0,
        model="gpt-5.6-sol",
        tool_names=["read_file"],
        max_output_tokens=1000,
        progress_cb=None,
        run_id="run-one",
        locale="en",
        trace_events=[],
        context_window_status=context_status,
        retained_context_tokens=1,
    )

    assert compacted is True
    assert compacted_until == 20
    assert status.estimated_context_tokens == 1000
    assert calls["count"] == 1
    assert len(compacted_messages) < len(messages)

    repeated_messages, repeated_until, repeated, _ = runtime._maybe_compact_live_messages(
        messages=compacted_messages,
        base_message_count=1,
        tool_events=tool_events,
        compacted_until=compacted_until,
        model="gpt-5.6-sol",
        tool_names=["read_file"],
        max_output_tokens=1000,
        progress_cb=None,
        run_id="run-one",
        locale="en",
        trace_events=[],
        context_window_status=status,
        retained_context_tokens=1,
    )
    assert repeated_messages is compacted_messages
    assert repeated_until == compacted_until
    assert repeated is False
    assert calls["count"] == 1


def test_live_tail_retention_keeps_tool_transactions_atomic(tmp_path: Path) -> None:
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_FakeBackend([]),
    )
    old_call = _FakeAIMessage(content="", tool_calls=[{"id": "old", "name": "read_file", "args": {}}])
    old_result = _FakeToolMessage(content="old", tool_call_id="old", name="read_file")
    newest_call = _FakeAIMessage(
        content="",
        tool_calls=[
            {"id": "new-a", "name": "read_file", "args": {}},
            {"id": "new-b", "name": "read_file", "args": {}},
        ],
    )
    newest_result_a = _FakeToolMessage(content="a", tool_call_id="new-a", name="read_file")
    newest_result_b = _FakeToolMessage(content="b", tool_call_id="new-b", name="read_file")

    retained = runtime._retained_live_tail(
        [old_call, old_result, newest_call, newest_result_a, newest_result_b],
        model="gpt-5.6-sol",
        token_budget=1,
    )

    assert retained == [newest_call, newest_result_a, newest_result_b]
    assert runtime._messages_at_tool_boundary(retained) is True


def test_mid_turn_compaction_recalculates_after_model_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = load_config()
    config.context_window_tokens = 0
    config.model_max_context_window_tokens = 0
    config.context_auto_compact_token_limit = 0
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_FakeBackend([]),
    )
    messages: list[Any] = [_FakeSystemMessage(content="system")]
    tool_events: list[ToolEvent] = []
    for index in range(3):
        call_id = f"call-{index}"
        messages.extend(
            [
                _FakeAIMessage(content="", tool_calls=[{"id": call_id, "name": "read_file", "args": {}}]),
                _FakeToolMessage(content=f"result-{index}", tool_call_id=call_id, name="read_file"),
            ]
        )
        tool_events.append(ToolEvent(name="read_file", output_preview="ok", status="ok", summary=call_id))
    previous_status = build_context_window_status(
        model="gpt-5.6-sol",
        current_tokens=20_000,
    )
    monkeypatch.setattr(runtime, "_estimate_model_request_tokens", lambda *args, **kwargs: 30_000)
    monkeypatch.setattr(runtime, "_build_live_compaction_summary", lambda **kwargs: "continuation memory")

    compacted_messages, compacted_until, compacted, status = runtime._maybe_compact_live_messages(
        messages=messages,
        base_message_count=1,
        tool_events=tool_events,
        compacted_until=0,
        model="mixtral-8x7b-32768",
        tool_names=["read_file"],
        max_output_tokens=1000,
        progress_cb=None,
        run_id="run-downgrade",
        locale="en",
        trace_events=[],
        context_window_status=previous_status,
        retained_context_tokens=1,
    )

    assert compacted is True
    assert compacted_until == 2
    assert status.model == "mixtral-8x7b-32768"
    assert status.operational_context_window == 32 * 1024
    assert status.auto_compact_token_limit == int(32 * 1024 * 0.9)
    assert status.model_downgraded is True
    assert status.previous_model == "gpt-5.6-sol"
    assert runtime._messages_at_tool_boundary(compacted_messages) is True
    assert len(compacted_messages) < len(messages)


def test_model_downgrade_compacts_large_base_before_the_next_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = load_config()
    config.context_window_tokens = 0
    config.model_max_context_window_tokens = 0
    config.context_auto_compact_token_limit = 0
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_FakeBackend([]),
    )
    messages = [
        _FakeSystemMessage(content="system contract"),
        _FakeHumanMessage(content="old replay one"),
        _FakeAIMessage(content="old replay answer"),
        _FakeHumanMessage(content="current request"),
    ]
    large_model_status = build_context_window_status(
        model="gpt-5.6-sol",
        current_tokens=30_000,
    )
    downgraded_status = build_context_window_status(
        model="mixtral-8x7b-32768",
        current_tokens=30_000,
        previous_status=large_model_status,
    )
    captured: dict[str, Any] = {}

    def summary(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "compressed replay memory"

    monkeypatch.setattr(runtime, "_build_live_compaction_summary", summary)
    monkeypatch.setattr(runtime, "_estimate_model_request_tokens", lambda *args, **kwargs: 1000)

    compacted_messages, compacted, after_status = runtime._compact_messages_after_model_downgrade(
        messages=messages,
        model="mixtral-8x7b-32768",
        tool_names=["read_file"],
        max_output_tokens=1000,
        context_window_status=downgraded_status,
        progress_cb=None,
        run_id="run-base-downgrade",
        locale="en",
        trace_events=[],
        retained_context_tokens=1,
    )

    assert compacted is True
    assert compacted_messages[0] is messages[0]
    assert compacted_messages[-1] is messages[-1]
    assert len(compacted_messages) == 3
    assert captured["allow_llm"] is False
    assert len(captured["old_messages"]) == 2
    assert after_status.estimated_context_tokens == 1000
    assert after_status.model_downgraded is True
    assert after_status.previous_model == "gpt-5.6-sol"


def test_runtime_compacts_initial_replay_after_effective_model_downgrade(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    config = _isolated_config(tmp_path)
    config.context_window_tokens = 0
    config.model_max_context_window_tokens = 0
    config.context_auto_compact_token_limit = 0
    backend = _InitialModelDowngradeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "read-one", "name": "read_file", "args": {"path": "README.md"}}],
            ),
            _FakeMessage(content="finished after downgrade"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    pre_turn_status = build_context_window_status(
        model="gpt-5.6-sol",
        current_tokens=40_000,
    )
    transcript_items = [
        {
            "id": f"history-{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"history-{index}:" + ("A" * 10_000),
        }
        for index in range(36)
    ]

    result = runtime.run(
        message="read the file and finish",
        settings=ChatSettings(
            model="gpt-5.6-sol",
            enable_tools=True,
            permission_profile="full_dev",
            response_style="short",
        ),
        context={
            "session_id": "s-model-downgrade",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "thread_transcript": {"items": transcript_items},
            "attachments": [],
            "compaction_status": {
                **pre_turn_status.to_dict(),
                "context_window_status": pre_turn_status.to_dict(),
            },
        },
    )

    assert result["turn_status"] == "completed"
    assert "context_compacted_for_model_downgrade" in result["inspector"]["notes"]
    assert result["inspector"]["run_state"]["compaction_status"]["model_downgraded"] is True
    assert len(backend.invocations) == 2
    assert backend.invocations[1]["model"] == "mixtral-8x7b-32768"
    assert len(backend.invocations[1]["messages"]) < len(backend.invocations[0]["messages"])


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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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


def test_runtime_accepts_image_attachment_final_answer_without_auto_tool_steer(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
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

    assert result["text"] == "由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"
    assert result["inspector"]["run_state"]["tools_available"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert backend.tools.calls == []
    assert result["tool_events"] == []
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


def test_runtime_uses_canonical_image_read_name_with_attachment_ref(tmp_path: Path) -> None:
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


def test_runtime_uses_single_attached_image_for_canonical_image_read(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_read", "args": {}}],
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


def test_runtime_does_not_auto_rescue_missing_context_reply_for_image_attachments(tmp_path: Path) -> None:
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

    assert result["text"] == "我需要更多上下文后才能操作这张图片。"
    assert backend.tools.calls == []
    assert result["tool_events"] == []
    assert result["turn_status"] == "completed"
    assert "auto_image_read_rescue" not in result["inspector"]["notes"]


def test_runtime_leaves_repeated_image_reads_to_the_model(tmp_path: Path) -> None:
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
            _FakeMessage(content="finished after repeated inspection"),
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
    assert result["text"] == "finished after repeated inspection"
    assert len(result["tool_events"]) == 5
    assert "image_read_repeat_fallback_answer" not in result["inspector"]["notes"]
    assert "image_read_result_forced_summary" not in result["inspector"]["notes"]


def test_runtime_does_not_override_model_answer_after_image_read(tmp_path: Path) -> None:
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

    assert result["text"] == "产品名称是 MetaPixel，Logo 也是 MetaPixel。"
    assert "image_read_result_forced_summary" not in result["inspector"]["notes"]
    assert result["tool_events"][0]["diagnostics"]["ocr_engine"] == "rapidocr"
    assert "Vintage" in result["tool_events"][0]["diagnostics"]["visible_text_preview"]


def test_runtime_ignores_legacy_task_checkpoint_for_followup_turn(tmp_path: Path) -> None:
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

    assert result["inspector"]["run_state"]["goal"] == "让其修改"
    assert "task_checkpoint" not in result["inspector"]["run_state"]
    assert "route_state" not in result
    assert "task_checkpoint_restored" not in result["inspector"]["notes"]


def test_runtime_keeps_successful_tool_evidence_without_task_checkpoint(tmp_path: Path) -> None:
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

    assert "route_state" not in result
    assert "task_state" not in result
    assert result["tool_events"][0]["name"] == "image_read"
    assert result["tool_events"][0]["status"] == "ok"


def test_runtime_does_not_interpret_task_state_delta_markup(tmp_path: Path) -> None:
    class _PatchTools(_FakeTools):
        def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((name, dict(arguments)))
            if name == "apply_patch":
                path = str(arguments.get("path") or "app/session_context.py")
                return {
                    "ok": True,
                    "name": name,
                    "summary": f"Patched {path}",
                    "files": [path],
                    "path": path,
                    "project_root": str((self.runtime_context or {}).get("project_root") or ""),
                    "cwd": str((self.runtime_context or {}).get("cwd") or ""),
                }
            return super().execute(name, arguments)

    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    tools = _PatchTools()
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "apply_patch", "args": {"path": "app/session_context.py"}}]),
            _FakeMessage(
                content=(
                    "Patched the task_state merge path.\n"
                    "<task_state_delta>{\"progress_basis\":[\"apply_patch: app/session_context.py\"],"
                    "\"next_required_action\":\"Run focused tests\"}</task_state_delta>"
                )
            ),
        ],
        tools,
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="继续修 task_state",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-task-delta-runtime",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "task_state": {
                "task_id": "task-runtime-delta",
                "goal": "修 task_state validator",
                "status": "in_progress",
                "plan_items": [{"id": "step-123", "step": "Patch task_state merge path", "status": "in_progress"}],
            },
            "work_cursor": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
        },
    )

    assert result["text"].startswith("Patched the task_state merge path.")
    assert "task_completion" not in result
    assert "<task_state_delta>" in result["text"]
    assert "task_state_delta" not in result
    assert "task_state" not in result
    assert "task_state_validation" not in result["inspector"]["run_state"]


def test_runtime_handles_runtime_context_setters_without_model_kwarg(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackendWithoutModelKwarg(
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
        settings=ChatSettings(model="gpt-test", enable_tools=True, permission_profile="full_dev", response_style="short"),
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


def test_runtime_does_not_auto_rescue_image_attachment_turn_when_model_refuses_to_use_tools(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
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

    assert result["text"] == "由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"
    assert result["tool_events"] == []
    assert result["inspector"]["run_state"]["tools_available"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "not_needed"


def test_runtime_loads_enabled_team_skills_for_inline_code(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "inline_helper"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: inline_helper\n"
        "description: Helps with inline pasted code.\n"
        "enabled: true\n"
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
        message="$inline_helper 请直接分析这段代码，不要去 workspace 里再找：\n```python\nclass A:\n    def run(self):\n        return 1\n```\n这里哪里有问题？",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-inline", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert result["text"] == "inline analysis complete"
    assert result["inspector"]["run_state"]["inline_document"] is True
    assert result["tool_events"] == []
    assert result["inspector"]["available_skills"][0]["key"] == "team:inline_helper"
    assert result["inspector"]["loaded_skills"] == []


def test_runtime_initial_prompt_lists_skills_without_full_skill_body(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "repo_triage"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: repo_triage\n"
        "description: Use for repository triage.\n"
        "enabled: true\n"
        "---\n\n"
        "# Repo Triage\n\n"
        "Full secret instruction body.\n",
        encoding="utf-8",
    )
    backend = _FakeBackend([_FakeMessage(content="done")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    runtime.run(
        message="帮我看一下仓库状态",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-skills-light", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    system_prompt = str(backend.invocations[0]["messages"][0].content)
    assert "[available_skills]" in system_prompt
    assert "team:repo_triage" in system_prompt
    assert "Use for repository triage." in system_prompt
    assert "Full secret instruction body." not in system_prompt
    available_section = system_prompt.split("[available_skills]", 1)[1].split("\n\n", 1)[0]
    skill_metadata = [
        json.loads(line)
        for line in available_section.splitlines()
        if line.strip().startswith("{")
    ]
    assert '"path"' in available_section
    assert skill_metadata[0]["path"] == str((skill_dir / "SKILL.md").resolve())
    assert "read_file" in available_section
    assert "exec_command" in available_section
    assert "VP_SKILL_ROOT" in available_section
    assert "VP_PROJECT_ROOT" in available_section
    assert "never search for, read, or parse .env" in available_section
    assert "load_skill" not in available_section


def test_runtime_initial_prompt_never_omits_later_enabled_skills(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="done")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    available_skills = [
        {
            "key": f"builtin:long-skill-{index:02d}",
            "scope": "builtin",
            "name": f"long-skill-{index:02d}",
            "description": f"Use for workflow {index}. " + ("detail " * 180),
            "path": str(tmp_path / "skills" / "builtin" / f"long-skill-{index:02d}" / "SKILL.md"),
        }
        for index in range(12)
    ]
    available_skills.append(
        {
            "key": "team:work-summary",
            "scope": "team",
            "name": "work-summary",
            "description": "根据 Redmine 最新进展，把工作总结成一句话。",
            "path": str(tmp_path / "skills" / "team" / "work-summary" / "SKILL.md"),
        }
    )

    prompt = runtime._render_available_skills_prompt(available_skills)
    rendered_metadata = [
        json.loads(line)
        for line in prompt.splitlines()
        if line.strip().startswith("{")
    ]

    assert len(prompt) > 8000
    assert "team:work-summary" in prompt
    assert "根据 Redmine 最新进展，把工作总结成一句话。" in prompt
    work_summary = next(item for item in rendered_metadata if item["key"] == "team:work-summary")
    assert work_summary["path"] == str(tmp_path / "skills" / "team" / "work-summary" / "SKILL.md")
    assert "because the available skill list exceeded the prompt budget" not in prompt
    assert all(item["key"] in prompt for item in available_skills)


def test_runtime_reads_skill_with_standard_read_file_tool(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "repo_triage"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: repo_triage\n"
        "description: Use for repository triage.\n"
        "enabled: true\n"
        "---\n\n"
        "# Repo Triage\n\n"
        "Full skill instruction body.\n",
        encoding="utf-8",
    )
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-read-skill",
                        "name": "read_file",
                        "args": {"path": str((skill_dir / "SKILL.md").resolve())},
                    }
                ],
            ),
            _FakeMessage(content="skill read"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我看一下仓库状态",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-load-skill", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert backend.tools.calls == [
        ("read_file", {"path": str((skill_dir / "SKILL.md").resolve())})
    ]
    assert result["tool_events"][0]["name"] == "read_file"
    assert result["inspector"]["available_skills"][0]["key"] == "team:repo_triage"
    assert result["inspector"]["loaded_skills"] == []


def test_runtime_reads_skill_resource_with_standard_read_file_tool(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "protocol_rules"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: protocol_rules\ndescription: Use for protocol rules.\nenabled: true\n---\n\n# Protocol Rules\n\nLoad references/rules.md.\n",
        encoding="utf-8",
    )
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "rules.md").write_text("Use explicit error codes.\n", encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-read-main",
                        "name": "read_file",
                        "args": {"path": str((skill_dir / "SKILL.md").resolve())},
                    }
                ],
            ),
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-read-resource",
                        "name": "read_file",
                        "args": {"path": str((skill_dir / "references" / "rules.md").resolve())},
                    }
                ],
            ),
            _FakeMessage(content="rules loaded"),
        ]
    )
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=agent_dir, backend=backend)

    result = runtime.run(
        message="按协议规则处理",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-skill-resource", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert backend.tools.calls == [
        ("read_file", {"path": str((skill_dir / "SKILL.md").resolve())}),
        ("read_file", {"path": str((skill_dir / "references" / "rules.md").resolve())}),
    ]
    assert [event["name"] for event in result["tool_events"]] == ["read_file", "read_file"]
    assert result["inspector"]["loaded_skills"] == []


def test_runtime_boundary_makes_enabled_team_skill_writable_when_runtime_allows_writes(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "scripted"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scripted\ndescription: Use for a checked script.\nenabled: true\n---\n\n# Scripted\n",
        encoding="utf-8",
    )
    script = skill_dir / "scripts" / "check.py"
    script.parent.mkdir()
    script.write_text("print('ok')\n", encoding="utf-8")
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    boundary = RuntimeBoundary(
        workspace_write_allowed=False,
        allowed_roots=[str(tmp_path / "business-project")],
        writable_roots=[],
        command_allowed_roots=[str(tmp_path / "business-project")],
        cwd=str(tmp_path / "business-project"),
        project_root=str(tmp_path / "business-project"),
    )
    available = runtime._enabled_skills("vintage_programmer")

    runtime._extend_runtime_boundary_for_skills(boundary, available)

    assert str(skill_dir.resolve()) in boundary.allowed_roots
    assert str(skill_dir.resolve()) in boundary.command_allowed_roots
    assert str(skill_dir.resolve()) not in boundary.writable_roots
    assert boundary.enabled_skill_roots == [str(skill_dir.resolve())]
    assert boundary.team_skill_write_allowed is False

    writable_boundary = RuntimeBoundary(
        workspace_write_allowed=True,
        allowed_roots=[str(tmp_path / "business-project")],
        writable_roots=[str(tmp_path / "business-project")],
        command_allowed_roots=[str(tmp_path / "business-project")],
        cwd=str(tmp_path / "business-project"),
        project_root=str(tmp_path / "business-project"),
    )
    runtime._extend_runtime_boundary_for_skills(writable_boundary, available)
    assert str(skill_dir.resolve()) in writable_boundary.writable_roots
    assert writable_boundary.team_skill_write_allowed is True

    runtime._workbench.set_skill_enabled("scripted", False, scope="team")
    disabled_boundary = RuntimeBoundary(
        allowed_roots=[str(tmp_path / "business-project")],
        writable_roots=[str(tmp_path / "business-project")],
        command_allowed_roots=[str(tmp_path / "business-project")],
        cwd=str(tmp_path / "business-project"),
        project_root=str(tmp_path / "business-project"),
    )
    runtime._extend_runtime_boundary_for_skills(
        disabled_boundary,
        runtime._enabled_skills("vintage_programmer"),
    )
    assert str(skill_dir.resolve()) not in disabled_boundary.allowed_roots
    assert str(skill_dir.resolve()) not in disabled_boundary.command_allowed_roots
    assert disabled_boundary.enabled_skill_roots == []
    assert disabled_boundary.team_skill_write_allowed is False


@pytest.mark.parametrize(
    "message",
    [
        "把获取环境变量的逻辑直接写进这个 Team Skill 的 Python 脚本",
        "请只解释现状，不要修改任何文件",
        "好的",
    ],
)
def test_runtime_team_skill_write_scope_does_not_depend_on_message_wording(
    tmp_path: Path,
    message: str,
) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "skills" / "team" / "scripted"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scripted\ndescription: Use for environment collection.\nenabled: true\n---\n\n# Scripted\n",
        encoding="utf-8",
    )
    backend = _FakeBackend([_FakeMessage(content="updated")])
    backend.tools = _BoundaryCapturingTools()
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message=message,
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-team-skill-write",
            "project": {"project_root": str(tmp_path / "business-project")},
            "history_turns": [],
            "attachments": [],
        },
    )

    boundary = backend.tools.runtime_boundaries[-1]
    assert result["text"] == "updated"
    assert boundary["team_skill_write_allowed"] is True
    assert str(skill_dir.resolve()) in boundary["writable_roots"]
    assert str((tmp_path / "skills" / "builtin").resolve()) not in boundary["writable_roots"]
    assert result["write_capability_state"]["intent_owner"] == "model"


def test_runtime_save_skill_tool_creates_global_team_skill(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-save-skill",
                        "name": "save_skill",
                        "args": {
                            "name": "repo-triage",
                            "description": "Use when investigating repository structure.",
                            "body": "# Repo Triage\n\nInspect entry points before editing.",
                            "enabled": True,
                        },
                    }
                ],
            ),
            _FakeMessage(content="skill saved"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    business_project = tmp_path / "company-project"
    business_project.mkdir()
    result = runtime.run(
        message="把这次仓库排查流程总结成 skill",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-save-skill", "project": {"project_root": str(business_project)}, "history_turns": [], "attachments": []},
    )

    skill_path = tmp_path / "skills" / "team" / "repo-triage" / "SKILL.md"
    assert backend.tools.calls == [
        (
            "save_skill",
            {
                "name": "repo-triage",
                "description": "Use when investigating repository structure.",
                "body": "# Repo Triage\n\nInspect entry points before editing.",
                "enabled": True,
            },
        )
    ]
    assert result["tool_events"][0]["name"] == "save_skill"
    assert skill_path.is_file()
    assert not (business_project / "skills").exists()
    content = skill_path.read_text(encoding="utf-8")
    assert content.startswith("---\nname: repo-triage\n")
    assert "description: Use when investigating repository structure." in content
    assert "Inspect entry points before editing." in content


def test_runtime_save_task_tool_creates_project_task_snapshot(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-save-task",
                        "name": "save_task",
                        "args": {
                            "title": "Auth refactor",
                            "goal": "Finish the auth refactor",
                            "summary": "Backend is migrated; frontend work remains.",
                            "progress": ["Migrated backend"],
                            "next_steps": ["Update login form"],
                            "decisions": ["Keep refresh tokens server-side"],
                            "blockers": [],
                            "artifacts": ["app/auth.py"],
                            "status": "active",
                        },
                    }
                ],
            ),
            _FakeMessage(content="Task saved"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    project_root = tmp_path / "company-project"
    project_root.mkdir()

    result = runtime.run(
        message="把当前工作总结为一个 Task",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "thread-source",
            "project": {
                "project_id": "project-1",
                "project_title": "Company Project",
                "project_root": str(project_root),
            },
            "thread_transcript": {"schema_version": 2, "items": []},
            "attachments": [],
        },
    )

    task_files = list((tmp_path / "tasks").glob("*.json"))
    assert len(task_files) == 1
    task = json.loads(task_files[0].read_text(encoding="utf-8"))
    assert task["project_id"] == "project-1"
    assert task["source_thread_id"] == "thread-source"
    assert task["next_steps"] == ["Update login form"]
    assert result["tool_events"][0]["name"] == "save_task"


def test_runtime_injects_current_project_task_lister_for_agent_lookup(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-list-tasks",
                        "name": "list_tasks",
                        "args": {
                            "query": "Redmine 123",
                            "project_scope": "current_project",
                            "limit": 20,
                        },
                    }
                ],
            ),
            _FakeMessage(content="Found the matching Task."),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    list_calls: list[dict[str, Any]] = []

    def task_lister(*, project_id=None, include_archived=False, limit=100):
        list_calls.append(
            {
                "project_id": project_id,
                "include_archived": include_archived,
                "limit": limit,
            }
        )
        return [
            {
                "task_id": "task-redmine-123",
                "project_id": "project-1",
                "title": "Redmine 123",
                "goal": "Resolve the failure",
                "summary": "Investigation in progress.",
                "status": "active",
            }
        ]

    runtime._task_store.list = task_lister  # type: ignore[method-assign]
    project_root = tmp_path / "company-project"
    project_root.mkdir()

    result = runtime.run(
        message="刚才的 Redmine 已经处理完了，更新对应 Task",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "thread-task-lookup",
            "project": {
                "project_id": "project-1",
                "project_title": "Company Project",
                "project_root": str(project_root),
            },
            "thread_transcript": {"schema_version": 2, "items": []},
            "attachments": [],
        },
    )

    assert result["tool_events"][0]["name"] == "list_tasks"
    assert list_calls == [
        {
            "project_id": "project-1",
            "include_archived": False,
            "limit": 20,
        }
    ]


def test_loaded_task_can_update_from_another_active_project_without_moving_source(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    agent_spec = agent_dir / "agent.md"
    agent_spec.write_text(agent_spec.read_text(encoding="utf-8").replace("tool_scope: read_only", "tool_scope: all"), encoding="utf-8")
    backend = _FakeBackend([])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    source_root = tmp_path / "source-project"
    selected_root = tmp_path / "selected-project"
    source_root.mkdir()
    selected_root.mkdir()
    original = runtime._task_store.save(
        project_id="project-source",
        project_title="Source project",
        project_root=str(source_root),
        title="Portable task",
        goal="Continue from a different active project",
        summary="Original snapshot.",
        status="active",
        source_thread_id="thread-source",
    )
    task_id = str(original["task_id"])
    backend._scripted_messages.extend(
        [
            _FakeMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-update-loaded-task",
                        "name": "save_task",
                        "args": {
                            "task_id": task_id,
                            "title": "Portable task",
                            "goal": "Continue from a different active project",
                            "summary": "The selected-project investigation is now complete.",
                            "progress": ["Verified selected-project behavior"],
                            "next_steps": [],
                            "decisions": ["Keep the Task source project as metadata"],
                            "blockers": [],
                            "artifacts": ["selected/result.txt"],
                            "status": "completed",
                        },
                    }
                ],
            ),
            _FakeMessage(content="Task updated"),
        ]
    )

    result = runtime.run(
        message="更新现在这个 Task",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "thread-selected",
            "project": {
                "project_id": "project-selected",
                "project_title": "Selected project",
                "project_root": str(selected_root),
            },
            "task_context": original,
            "thread_transcript": {"schema_version": 2, "items": []},
            "attachments": [],
        },
    )

    updated = runtime._task_store.get(task_id)
    assert updated is not None
    assert updated["project_id"] == "project-source"
    assert updated["project_title"] == "Source project"
    assert updated["project_root"] == str(source_root)
    assert updated["summary"] == "The selected-project investigation is now complete."
    assert updated["status"] == "completed"
    assert result["tool_events"][0]["name"] == "save_task"
    human_prompts = [
        str(item.content)
        for item in backend.invocations[0]["messages"]
        if item.__class__.__name__ == "_FakeHumanMessage"
    ]
    assert any("active Runtime project and boundary remain authoritative" in prompt for prompt in human_prompts)


def test_loaded_task_context_precedes_visible_load_request_and_replays(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="Continuing the loaded Task")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )
    task_context = {
        "task_id": "task-1",
        "title": "Auth refactor",
        "goal": "Finish the auth refactor",
        "next_steps": ["Update login form"],
    }

    runtime.run(
        message="加载当前任务",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "thread-current",
            "project": {"project_id": "project-1", "project_root": str(tmp_path)},
            "task_context": task_context,
            "thread_transcript": {
                "schema_version": 2,
                "items": [
                    {
                        "id": "u-old",
                        "role": "user",
                        "content": "加载当前任务",
                        "task_context": {**task_context, "task_id": "task-old"},
                    }
                ],
            },
            "attachments": [],
        },
    )

    human_contents = [
        str(message.content)
        for message in backend.invocations[0]["messages"]
        if isinstance(message, _FakeHumanMessage)
    ]
    assert "\"task_id\":\"task-old\"" in human_contents[0]
    assert human_contents[1] == "加载当前任务"
    assert "\"task_id\":\"task-1\"" in human_contents[-2]
    assert human_contents[-1] == "加载当前任务"


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
    assert result["tool_events"] == []
    assert result["turn_status"] == "completed"
