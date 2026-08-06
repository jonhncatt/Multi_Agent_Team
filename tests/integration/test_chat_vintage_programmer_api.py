from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

import app.main as main_app
import app.storage as storage_mod
from app.config import load_config
from app.i18n import translate
from app.storage import ProjectStore, SessionStore, TokenStatsStore, UploadStore
from app.task_store import TaskStore
from app.workbench import WorkbenchStore, build_tool_descriptors


_FAKE_TOOL_SPECS = [
    {"name": "exec_command", "description": "run shell commands"},
    {"name": "apply_patch", "description": "apply workspace patch"},
    {"name": "read_file", "description": "read one local file"},
    {"name": "list_dir", "description": "list one local directory"},
    {"name": "glob_file_search", "description": "find files by glob pattern"},
    {"name": "search_contents_in_file", "description": "search one local file"},
    {"name": "search_contents_in_file_multi", "description": "search one local file with multiple queries"},
    {"name": "read_section", "description": "read one matched section"},
    {"name": "table_extract", "description": "extract document tables"},
    {"name": "fact_check_file", "description": "fact check one file"},
    {"name": "search_codebase", "description": "search codebase"},
    {"name": "web_search", "description": "search the web"},
    {"name": "web_fetch", "description": "fetch one web page"},
    {"name": "web_download", "description": "download one remote file"},
    {"name": "sessions_list", "description": "list sessions"},
    {"name": "image_inspect", "description": "inspect image"},
    {"name": "image_read", "description": "read image content"},
    {"name": "archive_extract", "description": "extract archive"},
    {"name": "mail_extract_attachments", "description": "extract mail attachments"},
    {"name": "update_plan", "description": "sync checklist"},
    {"name": "request_user_input", "description": "request structured input"},
    {"name": "load_skill", "description": "load selected skill instructions"},
    {"name": "save_skill", "description": "save workspace skill"},
]
_FAKE_TOOL_DESCRIPTORS = build_tool_descriptors(_FAKE_TOOL_SPECS)
_FAKE_TOOL_DESCRIPTOR_BY_NAME = {
    str(item.get("name") or ""): dict(item)
    for item in _FAKE_TOOL_DESCRIPTORS
    if str(item.get("name") or "")
}
_FAKE_ALLOWED_TOOLS = [str(item["name"]) for item in _FAKE_TOOL_SPECS]


def test_activity_duration_uses_end_to_end_total_when_larger() -> None:
    activity = main_app._activity_with_end_to_end_duration(
        {"run_duration_ms": 11369, "final_elapsed_ms": 11000},
        {"runtime_total_ms": 11369, "runtime_run_ms": 11369, "total_ms": 26183},
    )

    assert activity["run_duration_ms"] == 26183
    assert activity["final_elapsed_ms"] == 26183


def test_activity_duration_falls_back_to_runtime_total_without_request_total() -> None:
    activity = main_app._activity_with_end_to_end_duration(
        {"run_duration_ms": 0},
        {"runtime_total_ms": 11369, "runtime_run_ms": 11360},
    )

    assert activity["run_duration_ms"] == 11369
    assert activity["final_elapsed_ms"] == 11369


def test_previous_turn_changes_are_injected_only_for_the_immediate_retained_outcome() -> None:
    retained = {
        "files": [{"path": "app/runtime.py", "kind": "modified"}],
        "count": 1,
        "retained": True,
        "possible_untracked_changes": False,
        "verification": {"status": "failed"},
    }
    session = {
        "turns": [
            {"role": "assistant", "activity": {"status": "failed", "turn_changes": retained}},
        ]
    }

    assert main_app._previous_retained_turn_changes(session) == retained

    session["turns"].append(
        {"role": "assistant", "activity": {"status": "completed", "turn_changes": {}}}
    )
    assert main_app._previous_retained_turn_changes(session) == {}


class _FakeRuntimeStatusTools:
    def docker_status(self) -> tuple[bool, str]:
        return False, "stub"

    def ocr_status(self) -> dict[str, object]:
        return {"available": False, "reason": "stub"}


class _FakeVintageRuntime:
    def __init__(self) -> None:
        self._backend = type("Backend", (), {"tools": _FakeRuntimeStatusTools()})()

    def descriptor(self, locale: str | None = None, *, refresh: bool = False) -> dict[str, object]:
        _ = (locale, refresh)
        tools = [dict(item) for item in _FAKE_TOOL_DESCRIPTORS]
        return {
            "agent_id": "vintage_programmer",
            "title": "Vintage Programmer",
            "default_model": "gpt-test",
            "tool_policy": "all",
            "allowed_tools": list(_FAKE_ALLOWED_TOOLS),
            "spec_files": ["soul.md", "identity.md", "agent.md", "tools.md"],
            "identity": {"document": "identity", "sections": {"角色定义": ["primary agent"]}},
            "workflow": {
                "modes": ["default", "plan", "execute"],
                "phases": ["default", "plan", "execute"],
                "default_mode": "default",
            },
            "policies": {
                "tool_policy": "all",
                "approval_policy": "on_failure_or_high_impact",
                "evidence_policy": "required_for_external_or_runtime_facts",
            },
            "network": {"mode": "explicit_tools", "web_tool_contract": ["web_search", "web_fetch", "web_download"]},
            "capabilities": {
                "allowed_tools": list(_FAKE_ALLOWED_TOOLS),
                "tool_count": len(_FAKE_ALLOWED_TOOLS),
                "tools": [dict(item) for item in tools],
            },
            "tools": [dict(item) for item in tools],
            "available_skills": [{"key": "team:example-refactor-helper", "scope": "team", "name": "example-refactor-helper", "description": "Starter", "path": "/tmp/example/SKILL.md"}],
            "loaded_skills": [],
        }

    def invalidate_descriptor_cache(self) -> None:
        return None

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context)
        project = dict(context.get("project") or {})
        run_id = str(context.get("run_id") or "run-fake")
        web_search_tool = dict(_FAKE_TOOL_DESCRIPTOR_BY_NAME["web_search"])
        trace_events = [
            {
                "id": "trace-runtime",
                "run_id": run_id,
                "type": "runtime_contract.selected",
                "title": "Full Auto runtime enabled",
                "detail": "Tool policy: use when needed",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {"mode": "full_auto", "tool_policy": "use_when_needed"},
                "parent_id": None,
                "visible": True,
            },
            {
                "id": "trace-answer",
                "run_id": run_id,
                "type": "answer.finished",
                "title": "Answer generation finished",
                "detail": "",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {},
                "parent_id": None,
                "visible": True,
            },
        ]
        if progress_cb is not None:
            progress_cb({"event": "stage", "code": "execute", "phase": "execute", "label": "Execute", "status": "running", "detail": "fake runtime running"})
            progress_cb({"event": "plan_update", "plan": [{"step": "Inspect workspace", "status": "completed"}], "turn_status": "running"})
            for item in trace_events:
                progress_cb({"event": "trace_event", "trace": dict(item), "run_id": run_id})
        return {
            "text": "single-agent response",
            "effective_model": "gpt-test",
            "tool_events": [
                {
                    "name": "web_search",
                    "input": {"query": "x"},
                    "output_preview": "ok",
                    "status": "ok",
                    "group": str(web_search_tool.get("group") or ""),
                    "source": str(web_search_tool.get("source") or ""),
                    "summary": "searched",
                    "source_refs": ["https://example.com"],
                }
            ],
            "token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "llm_calls": 1},
            "answer_bundle": {"summary": "single-agent response", "claims": [], "citations": [], "warnings": []},
            "model_action": {
                "step_index": 1,
                "action_type": "tool_call",
                "tool_name": "web_search",
                "tool_names": ["web_search"],
                "tool_calls": [{"id": "tc-1", "name": "web_search", "args": {"query": "x"}}],
                "accepted": True,
                "reason": "Model requested web_search.",
                "source": "model_action",
            },
            "execution_trace": [
                {
                    "step_index": 1,
                    "action_type": "tool_call",
                    "status": "completed",
                    "title": "Tool execution step",
                    "tool_name": "web_search",
                    "tool_names": ["web_search"],
                    "result_summary": "web_search:ok",
                    "observation_summary": "Tool output collected for the next model turn.",
                    "error": "",
                    "detail": "",
                    "payload": {"completed_tool_calls": 1},
                }
            ],
            "route_state": {
                "agent_id": "vintage_programmer",
                "phase": "completed",
                "evidence_status": "collected",
                "loaded_skill_ids": ["example-refactor-helper"],
                "model_action": {
                    "step_index": 1,
                    "action_type": "tool_call",
                    "tool_name": "web_search",
                    "tool_names": ["web_search"],
                    "tool_calls": [{"id": "tc-1", "name": "web_search", "args": {"query": "x"}}],
                    "accepted": True,
                    "reason": "Model requested web_search.",
                    "source": "model_action",
                },
                "execution_trace": [
                    {
                        "step_index": 1,
                        "action_type": "tool_call",
                        "status": "completed",
                        "title": "Tool execution step",
                        "tool_name": "web_search",
                        "tool_names": ["web_search"],
                        "result_summary": "web_search:ok",
                        "observation_summary": "Tool output collected for the next model turn.",
                        "error": "",
                        "detail": "",
                        "payload": {"completed_tool_calls": 1},
                    }
                ],
                "task_checkpoint": {
                    "task_id": "task-fake-1",
                    "goal": "workspace inspection",
                    "project_root": str(project.get("project_root") or ""),
                    "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                    "active_files": [],
                    "active_attachments": [],
                    "last_completed_step": "web_search: searched",
                    "next_action": "",
                },
            },
            "permission_profile": "auto",
            "turn_status": "completed",
            "plan": [{"step": "Inspect workspace", "status": "completed"}],
            "pending_user_input": {},
            "activity": {
                "run_id": run_id,
                "status": "completed",
                "started_at": trace_events[0]["timestamp"],
                "finished_at": trace_events[-1]["timestamp"],
                "run_duration_ms": 0,
                "activity_summary": "Full Auto runtime enabled · Answer generation finished",
                "trace_events": trace_events,
            },
            "inspector": {
                "agent": self.descriptor(),
                "notes": ["fake runtime note"],
                "run_state": {
                    "goal": "workspace inspection",
                    "phase": "completed",
                    "permission_profile": "auto",
                    "turn_status": "completed",
                    "plan": [{"step": "Inspect workspace", "status": "completed"}],
                    "pending_user_input": {},
                    "inline_document": False,
                    "model_action": {
                        "step_index": 1,
                        "action_type": "tool_call",
                        "tool_name": "web_search",
                        "tool_names": ["web_search"],
                        "tool_calls": [{"id": "tc-1", "name": "web_search", "args": {"query": "x"}}],
                        "accepted": True,
                        "reason": "Model requested web_search.",
                        "source": "model_action",
                    },
                    "execution_trace": [
                        {
                            "step_index": 1,
                            "action_type": "tool_call",
                            "status": "completed",
                            "title": "Tool execution step",
                            "tool_name": "web_search",
                            "tool_names": ["web_search"],
                            "result_summary": "web_search:ok",
                            "observation_summary": "Tool output collected for the next model turn.",
                            "error": "",
                            "detail": "",
                            "payload": {"completed_tool_calls": 1},
                        }
                    ],
                    "task_checkpoint": {
                        "task_id": "task-fake-1",
                        "goal": "workspace inspection",
                        "project_root": str(project.get("project_root") or ""),
                        "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                        "active_files": [],
                        "active_attachments": [],
                        "last_completed_step": "web_search: searched",
                        "next_action": "",
                    },
                },
                "tool_timeline": [{"name": "web_search", "group": str(web_search_tool.get("group") or ""), "status": "ok", "summary": "searched", "source_refs": ["https://example.com"]}],
                "evidence": {"status": "collected", "required": True, "warning": "", "source_refs": ["https://example.com"]},
                "session": {
                    "session_id": "s-1",
                    "project_id": str(project.get("project_id") or ""),
                    "project_title": str(project.get("project_title") or ""),
                    "project_root": str(project.get("project_root") or ""),
                    "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                    "history_turn_count": 0,
                    "attachment_count": 0,
                },
                "token_usage": {"total_tokens": 18},
                "available_skills": [{"key": "team:example-refactor-helper", "scope": "team", "name": "example-refactor-helper", "description": "Starter", "path": "/tmp/example/SKILL.md"}],
                "loaded_skills": [],
            },
        }


class _FailingVintageRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context, progress_cb)
        raise RuntimeError(
            "{'error': {'message': 'Provider returned error', 'code': 429, "
            "'metadata': {'raw': 'google/gemma-4-31b-it:free is temporarily rate-limited upstream. "
            "Please retry shortly.', 'provider_name': 'Google AI Studio'}}}"
        )


class _PendingCommandApprovalRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        result = super().run(
            message=message,
            settings=settings,
            context=context,
            progress_cb=progress_cb,
        )
        command = 'python -c "print(\'x\')"'
        approval = {
            "type": "command_execution",
            "tool_call_id": "approval-tool-call",
            "command": command,
            "cwd": str((context.get("project") or {}).get("cwd") or ""),
            "approval_token": "approval-token",
            "single_use": True,
            "default_action": "cancel",
            "risks": [
                {
                    "kind": "blocked_supply_chain_command",
                    "message": "Command is blocked because inline Python execution bypasses file provenance checks.",
                }
            ],
        }
        summary = (
            "Approval required to run this command: Command is blocked because "
            "inline Python execution bypasses file provenance checks."
        )
        result.update(
            {
                "text": summary,
                "final_answer": "",
                "model_draft": "",
                "turn_status": "needs_user_input",
                "pending_user_input": {
                    "summary": summary,
                    "approval_request": approval,
                    "questions": [],
                },
                "pending_approval": approval,
                "pending_turn": {
                    "schema_version": 1,
                    "type": "command_execution",
                    "turn_id": str(context.get("logical_turn_id") or context.get("run_id") or "turn-approval"),
                    "request_message": str(message or ""),
                    "triggering_user_turn_id": str(context.get("triggering_user_turn_id") or ""),
                    "tool_call_id": "approval-tool-call",
                    "tool_call": {
                        "id": "approval-tool-call",
                        "name": "exec_command",
                        "args": {"cmd": command, "cwd": str((context.get("project") or {}).get("cwd") or "")},
                    },
                    "plan": [],
                },
                "tool_events": [],
                "answer_bundle": {"summary": "", "claims": [], "citations": [], "warnings": []},
                "transcript_delta": [
                    {
                        "id": "approval-model-call",
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "approval-tool-call",
                                "name": "exec_command",
                                "args": {"cmd": command},
                            }
                        ],
                    },
                ],
            }
        )
        result["activity"] = {
            **dict(result.get("activity") or {}),
            "status": "needs_user_input",
            "final_answer": "",
            "model_draft": "",
        }
        inspector = dict(result.get("inspector") or {})
        run_state = dict(inspector.get("run_state") or {})
        run_state.update(
            {
                "turn_status": "needs_user_input",
                "pending_user_input": dict(result["pending_user_input"]),
                "pending_approval": dict(approval),
                "pending_turn": dict(result["pending_turn"]),
                "final_answer": "",
                "model_draft": "",
            }
        )
        inspector["run_state"] = run_state
        result["inspector"] = inspector
        return result


class _ResumableCommandApprovalRuntime(_PendingCommandApprovalRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        response = dict(context.get("user_input_response") or {})
        if str(response.get("type") or "") != "command_execution":
            return super().run(
                message=message,
                settings=settings,
                context=context,
                progress_cb=progress_cb,
            )
        pending_turn = dict(context.get("pending_turn") or {})
        assert pending_turn.get("tool_call_id") == "approval-tool-call"
        assert str(context.get("logical_turn_id") or "") == str(pending_turn.get("turn_id") or "")
        assert float(pending_turn.get("turn_started_at") or 0.0) > 0
        assert float(context.get("logical_turn_started_at") or 0.0) == float(pending_turn["turn_started_at"])
        result = _FakeVintageRuntime.run(
            self,
            message=message,
            settings=settings,
            context=context,
            progress_cb=progress_cb,
        )
        tool_result = {
            "ok": False,
            "error_kind": "user_declined",
            "error": {"kind": "user_declined", "message": "Command execution was declined by the user."},
        }
        result.update(
            {
                "text": "Continued without running the command.",
                "final_answer": "Continued without running the command.",
                "turn_status": "completed",
                "pending_user_input": {},
                "pending_approval": {},
                "pending_turn": {},
                "transcript_delta": [
                    {
                        "role": "tool",
                        "content": json.dumps(tool_result),
                        "tool_call_id": "approval-tool-call",
                        "name": "exec_command",
                    }
                ],
            }
        )
        inspector = dict(result.get("inspector") or {})
        run_state = dict(inspector.get("run_state") or {})
        run_state.update(
            {
                "turn_status": "completed",
                "pending_user_input": {},
                "pending_approval": {},
                "pending_turn": {},
                "final_answer": result["final_answer"],
            }
        )
        inspector["run_state"] = run_state
        result["inspector"] = inspector
        return result


class _FailedResultVintageRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings)
        project = dict(context.get("project") or {})
        run_id = str(context.get("run_id") or "run-failed")
        llm_exchanges = [
            {
                "round": 1,
                "phase": "initial",
                "model": "gpt-test",
                "status": "completed",
                "sent_messages_exact": [
                    {"index": 0, "class_name": "SystemMessage", "role": "system", "content": "rules", "tool_call_id": "", "name": "", "tool_calls": [], "additional_kwargs": {}, "response_metadata": {}, "truncated": False, "original_chars": 5},
                    {"index": 1, "class_name": "HumanMessage", "role": "user", "content": "task", "tool_call_id": "", "name": "", "tool_calls": [], "additional_kwargs": {}, "response_metadata": {}, "truncated": False, "original_chars": 4},
                ],
                "model_returned_exact": {
                    "class_name": "AIMessage",
                    "role": "assistant",
                    "content": "I already inspected the skill files.",
                    "tool_calls": [{"id": "tc-1", "name": "web_search", "args": {"query": "x"}}],
                    "invalid_tool_calls": [],
                    "additional_kwargs": {},
                    "response_metadata": {},
                    "usage_metadata": {},
                    "finish_reason": "tool_calls",
                    "truncated": False,
                    "original_chars": 36,
                },
                "error": None,
                "harness_interpretation": {
                    "has_tool_calls": True,
                    "tool_count": 1,
                    "decision": "tool_call",
                    "final_answer_allowed": False,
                    "turn_status_after_round": "running",
                },
            },
            {
                "round": 2,
                "phase": "post_tool_response",
                "model": "gpt-test",
                "status": "failed",
                "sent_messages_exact": [
                    {"index": 0, "class_name": "ToolMessage", "role": "tool", "content": "{\"ok\": true}", "tool_call_id": "tc-1", "name": "web_search", "tool_calls": [], "additional_kwargs": {}, "response_metadata": {}, "truncated": False, "original_chars": 12},
                ],
                "model_returned_exact": None,
                "error": {
                    "kind": "llm_empty_response",
                    "message": "LLM provider returned empty response before ChatResult creation.",
                    "exception_type": "AttributeError",
                    "raw_message": "'NoneType' object has no attribute 'model_dump'",
                    "traceback_tail": "AttributeError: 'NoneType' object has no attribute 'model_dump'",
                },
                "harness_interpretation": {
                    "has_tool_calls": False,
                    "tool_count": 0,
                    "decision": "runtime_error",
                    "final_answer_allowed": False,
                    "turn_status_after_round": "failed",
                },
            },
        ]
        trace_events = [
            {
                "id": "trace-runtime",
                "run_id": run_id,
                "type": "runtime_contract.selected",
                "title": "Full Auto runtime enabled",
                "detail": "Tool policy: use when needed",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {"mode": "full_auto", "tool_policy": "use_when_needed"},
                "parent_id": None,
                "visible": True,
            },
            {
                "id": "trace-llm-failed",
                "run_id": run_id,
                "type": "llm.failed",
                "title": "LLM request failed",
                "detail": "LLM provider returned empty response before ChatResult creation.",
                "status": "failed",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {
                    "kind": "llm_empty_response",
                    "phase": "post_tool_response",
                    "model": "gpt-test",
                    "exception_type": "AttributeError",
                    "message": "LLM provider returned empty response before ChatResult creation.",
                    "raw_message": "'NoneType' object has no attribute 'model_dump'",
                    "tool_boundary_clean": True,
                    "last_successful_round": 1,
                    "failed_round": 2,
                    "tool_count_total": 0,
                    "traceback_tail": "AttributeError: 'NoneType' object has no attribute 'model_dump'",
                },
                "parent_id": None,
                "visible": True,
            },
        ]
        return {
            "text": "実行失敗：LLM リクエストに失敗しました。Debug Detail を展開して詳細を確認できます。",
            "final_answer": "",
            "model_draft": "I already inspected the skill files and was preparing the summary.",
            "runtime_error": {
                "kind": "llm_empty_response",
                "phase": "post_tool_response",
                "model": "gpt-test",
                "exception_type": "AttributeError",
                "message": "LLM provider returned empty response before ChatResult creation.",
                "raw_message": "'NoneType' object has no attribute 'model_dump'",
                "tool_boundary_clean": True,
                "last_successful_round": 1,
                "failed_round": 2,
                "tool_count_total": 0,
                "traceback_tail": "AttributeError: 'NoneType' object has no attribute 'model_dump'",
            },
            "tool_boundary_clean": True,
            "effective_model": "gpt-test",
            "tool_events": [],
            "token_usage": {"input_tokens": 11, "output_tokens": 0, "total_tokens": 11, "llm_calls": 2},
            "answer_bundle": {"summary": "", "claims": [], "citations": [], "warnings": []},
            "model_action": {
                "step_index": 2,
                "action_type": "tool_call",
                "tool_name": "web_search",
                "tool_names": ["web_search"],
                "tool_calls": [{"id": "tc-1", "name": "web_search", "args": {"query": "x"}}],
                "accepted": True,
                "reason": "Model requested web_search.",
                "source": "model_action",
            },
            "execution_trace": [
                {
                    "step_index": 2,
                    "action_type": "tool_call",
                    "status": "failed",
                    "title": "Tool execution step",
                    "tool_name": "web_search",
                    "tool_names": ["web_search"],
                    "result_summary": "web_search:ok",
                    "observation_summary": "LLM provider returned empty response before ChatResult creation.",
                    "error": "",
                    "detail": "",
                    "payload": {"completed_tool_calls": 1},
                }
            ],
            "route_state": {
                "agent_id": "vintage_programmer",
                "phase": "failed",
                "evidence_status": "collected",
                "loaded_skill_ids": ["example-refactor-helper"],
                "model_draft": "I already inspected the skill files and was preparing the summary.",
                "runtime_error": {
                    "kind": "llm_empty_response",
                    "phase": "post_tool_response",
                },
                "task_checkpoint": {
                    "task_id": "task-failed-1",
                    "goal": str(message or ""),
                    "project_root": str(project.get("project_root") or ""),
                    "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                    "active_files": [],
                    "active_attachments": [],
                    "last_completed_step": "web_search: searched",
                    "next_action": "failed",
                },
            },
            "permission_profile": "auto",
            "turn_status": "failed",
            "plan": [{"step": "Inspect workspace", "status": "completed"}],
            "pending_user_input": {},
            "activity": {
                "run_id": run_id,
                "status": "failed",
                "started_at": trace_events[0]["timestamp"],
                "finished_at": trace_events[-1]["timestamp"],
                "run_duration_ms": 0,
                "activity_summary": "Full Auto runtime enabled · LLM request failed",
                "model_draft": "I already inspected the skill files and was preparing the summary.",
                "final_answer": "",
                "runtime_error": {
                    "kind": "llm_empty_response",
                    "phase": "post_tool_response",
                    "message": "LLM provider returned empty response before ChatResult creation.",
                    "exception_type": "AttributeError",
                    "tool_boundary_clean": True,
                },
                "llm_exchanges": llm_exchanges,
                "tool_boundary_clean": True,
                "trace_events": trace_events,
            },
            "inspector": {
                "agent": self.descriptor(),
                "notes": ["fake failed runtime note"],
                "run_state": {
                    "goal": str(message or ""),
                    "phase": "failed",
                    "permission_profile": "auto",
                    "turn_status": "failed",
                    "plan": [{"step": "Inspect workspace", "status": "completed"}],
                    "pending_user_input": {},
                    "model_draft": "I already inspected the skill files and was preparing the summary.",
                    "final_answer": "",
                    "runtime_error": {
                        "kind": "llm_empty_response",
                        "phase": "post_tool_response",
                        "message": "LLM provider returned empty response before ChatResult creation.",
                        "exception_type": "AttributeError",
                        "tool_boundary_clean": True,
                    },
                    "llm_exchanges": llm_exchanges,
                    "task_checkpoint": {
                        "task_id": "task-failed-1",
                        "goal": str(message or ""),
                        "project_root": str(project.get("project_root") or ""),
                        "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                        "active_files": [],
                        "active_attachments": [],
                        "last_completed_step": "web_search: searched",
                        "next_action": "failed",
                    },
                },
                "tool_timeline": [],
                "evidence": {"status": "collected", "required": True, "warning": "", "source_refs": []},
                "session": {
                    "session_id": str(context.get("session_id") or ""),
                    "project_id": str(project.get("project_id") or ""),
                    "project_title": str(project.get("project_title") or ""),
                    "project_root": str(project.get("project_root") or ""),
                    "cwd": str(project.get("cwd") or project.get("project_root") or ""),
                    "history_turn_count": 0,
                    "attachment_count": 0,
                },
                "token_usage": {"total_tokens": 11},
                "loaded_skills": [{"key": "workspace:example-refactor-helper", "scope": "workspace", "name": "example-refactor-helper", "description": "Starter", "path": "/tmp/example"}],
            },
        }


class _ContextCapturingRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.seen_contexts: list[dict[str, object]] = []

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, progress_cb)
        self.seen_contexts.append(dict(context))
        return super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)


class _RequestTooLargeRecoveredRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(
            message=message,
            settings=settings,
            context=context,
            progress_cb=progress_cb,
        )
        payload["request_too_large_recovery"] = {
            "attempted": True,
            "compacted": True,
            "retried": True,
            "recovered": True,
            "before_bytes": 300_000,
            "after_bytes": 120_000,
        }
        return payload


class _StreamingVintageRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings)
        project = dict(context.get("project") or {})
        run_id = str(context.get("run_id") or "run-stream")
        trace_events = [
            {
                "id": "trace-runtime",
                "run_id": run_id,
                "type": "runtime_contract.selected",
                "title": "Full Auto runtime enabled",
                "detail": "Tool policy: use when needed",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {"mode": "full_auto", "tool_policy": "use_when_needed"},
                "parent_id": None,
                "visible": True,
            },
            {
                "id": "trace-activity",
                "run_id": run_id,
                "type": "activity.done",
                "title": "Answer path selected",
                "detail": "The model returned a direct answer path without tools.",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {"tool_count": 0, "direct_answer": True},
                "parent_id": None,
                "visible": True,
            },
            {
                "id": "trace-answer",
                "run_id": run_id,
                "type": "answer.done",
                "title": "Answer generation finished",
                "detail": "received streamed answer deltas",
                "status": "success",
                "timestamp": time.time(),
                "duration_ms": 0,
                "payload": {
                    "stream_diagnostics": {
                        "streamed": True,
                        "upstream_progressive": True,
                        "delta_count": 2,
                        "text_chars": 15,
                    }
                },
                "parent_id": None,
                "visible": True,
            },
        ]
        if progress_cb is not None:
            progress_cb({"event": "stage", "code": "execute", "phase": "execute", "label": "Execute", "status": "running", "detail": "fake runtime running"})
            for item in trace_events:
                progress_cb({"event": "trace_event", "trace": dict(item), "run_id": run_id})
            progress_cb(
                {
                    "event": "item/started",
                    "thread_id": str(context.get("session_id") or ""),
                    "turn_id": run_id,
                    "item": {"id": f"{run_id}:agent_message", "type": "agentMessage", "text": "", "status": "inProgress"},
                }
            )
            progress_cb(
                {
                    "event": "item/agentMessage/delta",
                    "thread_id": str(context.get("session_id") or ""),
                    "turn_id": run_id,
                    "item_id": f"{run_id}:agent_message",
                    "delta": "streamed ",
                }
            )
            progress_cb(
                {
                    "event": "item/agentMessage/delta",
                    "thread_id": str(context.get("session_id") or ""),
                    "turn_id": run_id,
                    "item_id": f"{run_id}:agent_message",
                    "delta": "answer",
                }
            )
            progress_cb(
                {
                    "event": "item/completed",
                    "thread_id": str(context.get("session_id") or ""),
                    "turn_id": run_id,
                    "item": {"id": f"{run_id}:agent_message", "type": "agentMessage", "text": "streamed answer", "status": "completed"},
                }
            )
        payload = super().run(message=message, settings=settings, context=context, progress_cb=None)
        payload["text"] = "streamed answer"
        payload["activity"]["trace_events"] = trace_events
        payload["activity"]["activity_summary"] = "Full Auto runtime enabled · Answer generation finished"
        payload["answer_stream"] = {
            "streamed": True,
            "upstream_progressive": True,
            "delta_count": 2,
            "text_chars": 15,
            "call_count": 1,
            "summary": "received streamed answer deltas",
        }
        payload["inspector"]["run_state"]["answer_stream"] = dict(payload["answer_stream"])
        return payload


class _ToolAuditStreamingRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=None)
        run_id = str(context.get("run_id") or "run-tool-audit")
        session_id = str(context.get("session_id") or "s-tool-audit")
        web_search_tool = dict(_FAKE_TOOL_DESCRIPTOR_BY_NAME["web_search"])
        tool_item = {
            "id": f"{run_id}:tool:web_search",
            "name": "web_search",
            "input": {"query": "PLAN.md"},
            "raw_tool_call": {"id": "tc-1", "name": "web_search", "arguments": {"q": "PLAN.md"}},
            "raw_arguments": {"query": "PLAN.md"},
            "normalized_arguments": {"query": "PLAN.md"},
            "validation_result": {
                "allowed": True,
                "code": "allowed",
                "message": "Action allowed: web_search",
                "tool_name": "web_search",
                "raw_tool_name": "web_search",
                "normalization_notes": ["q->query"],
                "checks": {
                    "json": "passed",
                    "tool_exists": "passed",
                    "schema": "normalized",
                    "policy": "passed",
                    "permission": "passed",
                },
            },
            "arguments_preview": "query=PLAN.md",
            "preview_error": "",
            "schema_validation": {"status": "valid", "checked": True},
            "output_preview": "ok",
            "status": "ok",
            "group": str(web_search_tool.get("group") or ""),
            "source": str(web_search_tool.get("source") or ""),
            "summary": "searched",
            "source_refs": ["https://example.com"],
        }
        if progress_cb is not None:
            typed_item = {
                **dict(tool_item),
                "id": f"{run_id}:tool:tc-1",
                "type": "toolCall",
                "tool": "web_search",
                "sourceRefs": ["https://example.com"],
                "status": "completed",
            }
            progress_cb(
                {
                    "event": "item/started",
                    "thread_id": session_id,
                    "turn_id": run_id,
                    "item": {**typed_item, "status": "inProgress"},
                }
            )
            progress_cb(
                {
                    "event": "item/completed",
                    "thread_id": session_id,
                    "turn_id": run_id,
                    "item": typed_item,
                }
            )
            progress_cb(
                {
                    "event": "tool",
                    "item": dict(tool_item),
                    "status": "ok",
                    "summary": "searched",
                    "source_refs": ["https://example.com"],
                    "tool_round": 1,
                    "tool_index": 1,
                    "group": str(web_search_tool.get("group") or ""),
                    "agent_id": "vintage_programmer",
                    "thread_id": session_id,
                    "run_id": run_id,
                }
            )
        payload["tool_events"] = [dict(tool_item)]
        payload["inspector"]["tool_timeline"] = [dict(tool_item)]
        return payload


class _BlockingVintageRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context, progress_cb)
        self.started.set()
        self.release.wait(timeout=5.0)
        return super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)


class _CancellableThenRetryRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.first_started = threading.Event()
        self.first_cancel_seen = threading.Event()
        self.allow_first_return = threading.Event()
        self.second_started = threading.Event()
        self.contexts: list[dict[str, object]] = []
        self._call_lock = threading.Lock()

    def run(self, *, message, settings, context, progress_cb=None):
        with self._call_lock:
            call_index = len(self.contexts)
            self.contexts.append(dict(context))
        if call_index == 0:
            self.first_started.set()
            cancel_event = context["cancel_event"]
            assert cancel_event.wait(timeout=5.0)
            self.first_cancel_seen.set()
            assert self.allow_first_return.wait(timeout=5.0)
            payload = super().run(
                message=message,
                settings=settings,
                context=context,
                progress_cb=progress_cb,
            )
            payload["text"] = "stopped"
            payload["turn_status"] = "cancelled"
            payload["pending_user_input"] = {}
            payload["pending_approval"] = {}
            payload["activity"] = {
                **dict(payload.get("activity") or {}),
                "status": "cancelled",
            }
            payload["inspector"]["run_state"]["turn_status"] = "cancelled"
            payload["inspector"]["run_state"]["pending_user_input"] = {}
            payload["inspector"]["run_state"]["pending_approval"] = {}
            return payload
        self.second_started.set()
        return super().run(
            message=message,
            settings=settings,
            context=context,
            progress_cb=progress_cb,
        )


class _FollowupContextRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, *, message, settings, context, progress_cb=None):
        transcript_items = [
            dict(item)
            for item in list((context.get("thread_transcript") or {}).get("items") or [])
            if isinstance(item, dict)
        ]
        history_turns = [
            {"role": str(item.get("role") or ""), "text": str(item.get("content") or "")}
            for item in transcript_items
            if str(item.get("role") or "") in {"user", "assistant"}
        ]
        recent_user_messages = [
            str(item.get("content") or "")
            for item in transcript_items
            if str(item.get("role") or "") == "user" and str(item.get("content") or "").strip()
        ][-8:]
        self.calls.append(
            {
                "message": str(message or ""),
                "recent_user_messages": list(recent_user_messages),
                "history_turns": [
                    {
                        "role": str(item.get("role") or ""),
                        "text": str(item.get("text") or ""),
                    }
                    for item in history_turns
                    if isinstance(item, dict)
                ],
            }
        )
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        current = str(message or "").strip()
        latest_previous_user = next(
            (
                str(item.get("text") or "")
                for item in reversed(history_turns)
                if isinstance(item, dict) and str(item.get("role") or "") == "user"
            ),
            "",
        )
        goal = current
        prior_context = "\n".join(str(item.get("text") or "") for item in history_turns)
        if current == "题目" and ("メール" in prior_context or "邮件" in prior_context):
            text = "件名：明日の会議時間変更のお願い"
        elif current == "题目":
            text = (
                "当然，下面是一封自然、简洁的请假邮件：\n\n"
                "お世話になっております。\n\n"
                "明日は検査のため、一日お休みをいただきたく存じます。\n\n"
                "よろしくお願いいたします。"
            )
        elif current == "刚刚我问你什么了":
            recalled = recent_user_messages[-1] if recent_user_messages else latest_previous_user
            text = f"你刚刚问的是“{recalled}”。"
        elif current == "我刚才问你的所有问题，罗列一下":
            text = "\n".join(f"{index + 1}. {entry}" for index, entry in enumerate(recent_user_messages))
        elif "メール" in current or "邮件" in current or "メールを書いて" in current:
            text = (
                "お世話になっております。\n\n"
                "明日の会議ですが、10時から11時に変更させていただけますでしょうか。\n\n"
                "よろしくお願いいたします。"
            )
        else:
            text = f"echo:{current}"
        payload["text"] = text
        payload["answer_bundle"] = {"summary": text, "claims": [], "citations": [], "warnings": []}
        payload["activity"] = {
            **dict(payload.get("activity") or {}),
            "current_turn_goal": goal,
            "recent_user_messages": list(recent_user_messages),
        }
        payload["inspector"] = {
            **dict(payload.get("inspector") or {}),
            "run_state": {
                **dict(((payload.get("inspector") or {}).get("run_state") or {})),
                "goal": goal,
                "recent_user_messages": list(recent_user_messages),
            },
        }
        return payload


class _DeltaTaskStateRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        payload["plan"] = [
            {"step": "Patch task_state merge", "status": "in_progress"},
            {"step": "Run focused tests", "status": "pending"},
        ]
        payload["tool_events"] = [
            {
                "name": "apply_patch",
                "input": {"path": "app/session_context.py"},
                "output_preview": "patched",
                "result_preview": {"files": ["app/session_context.py"]},
                "status": "ok",
                "group": "edit",
                "source": "native",
                "summary": "Patched app/session_context.py",
                "source_refs": ["app/session_context.py"],
            }
        ]
        payload["task_state_delta"] = {
            "progress_basis": ["apply_patch: app/session_context.py"],
            "evidence_refs": [{"tool": "apply_patch", "ref": "app/session_context.py"}],
            "next_required_action": "Run focused tests",
        }
        payload["task_state"] = {
            "task_id": "wrong-task",
            "goal": "WRONG GOAL",
            "status": "completed",
            "plan_items": [],
        }
        payload["inspector"]["run_state"]["goal"] = "Patch validator"
        payload["inspector"]["run_state"]["plan"] = list(payload["plan"])
        payload["inspector"]["run_state"]["task_state"] = dict(payload["task_state"])
        payload["inspector"]["run_state"]["task_state_delta"] = dict(payload["task_state_delta"])
        return payload


class _NoDeltaTaskStateRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        payload["plan"] = [{"step": "Inspect workspace", "status": "completed"}]
        payload["tool_events"] = [
            {
                "name": "update_plan",
                "input": {"plan": list(payload["plan"])},
                "result_preview": {"ok": True, "plan": list(payload["plan"])},
                "output_preview": "plan updated",
                "status": "ok",
                "group": "control",
                "source": "native",
                "summary": "plan updated (1 step)",
            }
        ]
        payload["task_state"] = {
            "task_id": "wrong-task",
            "goal": "WRONG GOAL",
            "status": "completed",
            "plan_items": [],
        }
        payload["inspector"]["run_state"]["goal"] = "Inspect workspace"
        payload["inspector"]["run_state"]["plan"] = list(payload["plan"])
        payload["inspector"]["run_state"]["task_state"] = dict(payload["task_state"])
        return payload


class _DirectAnswerNoTaskRuntime(_FakeVintageRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        project = dict(context.get("project") or {})
        payload["text"] = f"echo:{str(message or '').strip()}"
        payload["tool_events"] = []
        payload["plan"] = []
        payload["route_state"] = {
            "agent_id": "vintage_programmer",
            "phase": "completed",
            "evidence_status": "not_needed",
            "loaded_skill_ids": ["example-refactor-helper"],
        }
        payload["inspector"]["run_state"]["goal"] = str(message or "").strip()
        payload["inspector"]["run_state"]["plan"] = []
        payload["inspector"]["run_state"].pop("task_checkpoint", None)
        payload["inspector"]["session"] = {
            **dict(payload["inspector"].get("session") or {}),
            "project_id": str(project.get("project_id") or ""),
            "project_title": str(project.get("project_title") or ""),
            "project_root": str(project.get("project_root") or ""),
            "cwd": str(project.get("cwd") or project.get("project_root") or ""),
        }
        return payload


class _ToolEvidenceOnlyRuntime(_DirectAnswerNoTaskRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        payload["tool_events"] = [
            {
                "name": "read_file",
                "input": {"path": "README.md"},
                "output_preview": "ok",
                "status": "ok",
                "group": "file",
                "source": "native",
                "summary": "Read README.md",
                "source_refs": ["README.md"],
            }
        ]
        return payload


class _UpdatePlanCreatesTaskRuntime(_DirectAnswerNoTaskRuntime):
    def run(self, *, message, settings, context, progress_cb=None):
        payload = super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)
        payload["plan"] = [
            {"step": "Inspect current update_plan schema", "status": "completed"},
            {"step": "Align update_plan schema with task_state plan_items", "status": "in_progress"},
            {"step": "Add tests for greetings, continue requests, and update_plan behavior", "status": "pending"},
        ]
        payload["tool_events"] = [
            {
                "name": "update_plan",
                "input": {
                    "explanation": "This is a multi-step code change, so a plan is useful.",
                    "plan": list(payload["plan"]),
                },
                "result_preview": {
                    "ok": True,
                    "plan": list(payload["plan"]),
                    "explanation": "This is a multi-step code change, so a plan is useful.",
                },
                "output_preview": "plan updated",
                "status": "ok",
                "group": "control",
                "source": "native",
                "summary": "plan updated (3 steps)",
            }
        ]
        payload["inspector"]["run_state"]["goal"] = "Fix update_plan schema"
        payload["inspector"]["run_state"]["plan"] = list(payload["plan"])
        return payload


def _patch_runtime_state(monkeypatch, tmp_path: Path) -> None:
    with main_app._active_chat_runs_lock:
        main_app._active_chat_runs.clear()
    for name in ("sessions", "uploads", "workspace/skills", "agents/vintage_programmer"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents" / "vintage_programmer" / "soul.md").write_text("soul", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "identity.md").write_text("identity", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "agent.md").write_text("---\nid: vintage_programmer\n---\nagent", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "tools.md").write_text("tools", encoding="utf-8")
    skill_dir = tmp_path / "workspace" / "skills" / "example_refactor_helper"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: example_refactor_helper\n"
        "description: Starter\n"
        "enabled: false\n"
        "---\n\n"
        "# Example\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_app.config, "workspace_root", tmp_path)
    monkeypatch.setattr(main_app.config, "projects_registry_path", tmp_path / "projects.json")
    monkeypatch.setattr(main_app.config, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(main_app.config, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(main_app.config, "token_stats_path", tmp_path / "token_stats.json")
    monkeypatch.setattr(main_app.config, "allowed_roots", [tmp_path])
    monkeypatch.setattr(main_app.config, "permission_profile", "auto")
    monkeypatch.setattr(main_app, "session_store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(main_app, "upload_store", UploadStore(tmp_path / "uploads"))
    monkeypatch.setattr(main_app, "token_stats_store", TokenStatsStore(tmp_path / "token_stats.json"))
    monkeypatch.setattr(main_app, "task_store", TaskStore(tmp_path / "tasks"))
    monkeypatch.setattr(main_app, "project_store", ProjectStore(tmp_path / "projects.json", default_root=tmp_path))
    main_app.project_store.ensure_default_project()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _FakeVintageRuntime())
    monkeypatch.setattr(
        main_app,
        "workbench_store",
        WorkbenchStore(config=type("Cfg", (), {"workspace_root": tmp_path})(), agent_dir=tmp_path / "agents" / "vintage_programmer"),
    )
    monkeypatch.setattr(
        main_app.OpenAIAuthManager,
        "auth_summary",
        lambda self: {"available": True, "reason": "", "mode": "test", "provider": "test"},
    )
    main_app._invalidate_provider_payload_cache()


def _parse_sse_events(raw: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            if data_lines:
                events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_health_endpoint_is_lightweight(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    monkeypatch.setattr(
        main_app,
        "_bootstrap_response_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("health should not build bootstrap payload")),
    )
    monkeypatch.setattr(
        main_app,
        "_runtime_status_response_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("health should not build runtime status payload")),
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ok": True,
        "app_version": main_app.APP_VERSION,
        "build_version": main_app.BUILD_VERSION,
        "uptime_sec": payload["uptime_sec"],
    }
    assert isinstance(payload["uptime_sec"], int)
    assert payload["uptime_sec"] >= 0


def test_tasks_api_loads_snapshot_into_current_thread_as_hidden_context(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    class CapturingRuntime(_FakeVintageRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.last_message = ""
            self.last_context: dict[str, object] = {}

        def run(self, *, message, settings, context, progress_cb=None):
            self.last_message = str(message)
            self.last_context = dict(context)
            return super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)

    runtime = CapturingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    project = main_app.project_store.ensure_default_project()
    project_id = str(project["project_id"])

    create_task_response = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "title": "Auth refactor",
            "goal": "Finish the auth refactor",
            "summary": "Backend is migrated; frontend error handling remains.",
            "progress": ["Migrated backend"],
            "next_steps": ["Update login form"],
            "decisions": ["Keep refresh tokens server-side"],
            "blockers": [],
            "artifacts": ["app/auth.py"],
            "status": "active",
        },
    )
    assert create_task_response.status_code == 200
    task = create_task_response.json()

    list_response = client.get(f"/api/tasks?project_id={project_id}")
    assert list_response.status_code == 200
    assert [item["task_id"] for item in list_response.json()["tasks"]] == [task["task_id"]]

    other_root = tmp_path / "other-project"
    other_root.mkdir()
    other_project = main_app.project_store.create(root_path=str(other_root), title="Other project")
    other_task_response = client.post(
        "/api/tasks",
        json={
            "project_id": other_project["project_id"],
            "title": "Other task",
            "goal": "Keep a task visible across project switches",
            "summary": "This task belongs to another project.",
            "status": "active",
        },
    )
    assert other_task_response.status_code == 200
    other_task = other_task_response.json()

    global_list_response = client.get("/api/tasks")
    assert global_list_response.status_code == 200
    assert {item["task_id"] for item in global_list_response.json()["tasks"]} == {
        task["task_id"],
        other_task["task_id"],
    }
    assert [item["task_id"] for item in client.get(f"/api/tasks?project_id={project_id}").json()["tasks"]] == [
        task["task_id"]
    ]

    thread_response = client.post("/api/thread/new", json={"project_id": project_id})
    thread_id = thread_response.json()["thread_id"]
    chat_response = client.post(
        "/api/chat",
        json={
            "session_id": thread_id,
            "project_id": project_id,
            "task_id": task["task_id"],
            "message": "加载当前任务",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert chat_response.status_code == 200
    assert chat_response.json()["session_id"] == thread_id
    assert runtime.last_message == "加载当前任务"
    assert runtime.last_context["task_context"]["task_id"] == task["task_id"]
    loaded = main_app.session_store.load(thread_id)
    assert loaded is not None
    user_item = next(item for item in loaded["thread_transcript"]["items"] if item["role"] == "user")
    assert user_item["content"] == "加载当前任务"
    assert user_item["task_context"]["summary"] == task["summary"]
    loaded_task = main_app.task_store.get(task["task_id"])
    assert loaded_task and loaded_task["last_loaded_thread_id"] == thread_id


def test_tasks_api_updates_and_deletes_snapshot(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    project = main_app.project_store.ensure_default_project()
    project_id = str(project["project_id"])

    created_response = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "title": "Original title",
            "goal": "Original goal",
            "summary": "Original summary",
            "status": "active",
        },
    )
    assert created_response.status_code == 200
    task_id = created_response.json()["task_id"]

    updated_response = client.put(
        f"/api/tasks/{task_id}",
        json={
            "project_id": project_id,
            "title": "Updated title",
            "goal": "Updated goal",
            "summary": "Updated summary",
            "progress": ["Implemented editor"],
            "next_steps": ["Verify deletion"],
            "decisions": ["Edit without an LLM call"],
            "blockers": [],
            "artifacts": ["app/static/app.js"],
            "status": "blocked",
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["task_id"] == task_id
    assert updated["title"] == "Updated title"
    assert updated["status"] == "blocked"
    assert updated["progress"] == ["Implemented editor"]
    assert updated["decisions"] == ["Edit without an LLM call"]

    archived_response = client.put(
        f"/api/tasks/{task_id}",
        json={
            "project_id": project_id,
            "title": "Updated title",
            "goal": "Updated goal",
            "summary": "Updated summary",
            "progress": ["Implemented editor"],
            "next_steps": ["Verify deletion"],
            "decisions": ["Edit without an LLM call"],
            "blockers": [],
            "artifacts": ["app/static/app.js"],
            "status": "archived",
        },
    )
    assert archived_response.status_code == 200
    assert archived_response.json()["status"] == "archived"
    assert task_id not in {
        item["task_id"] for item in client.get("/api/tasks").json()["tasks"]
    }
    assert task_id in {
        item["task_id"]
        for item in client.get("/api/tasks?include_archived=true").json()["tasks"]
    }

    delete_response = client.delete(f"/api/tasks/{task_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True, "task_id": task_id}
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_task_from_another_project_loads_into_selected_project_thread(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    class CapturingRuntime(_FakeVintageRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.last_context: dict[str, object] = {}

        def run(self, *, message, settings, context, progress_cb=None):
            self.last_context = dict(context)
            return super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)

    runtime = CapturingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    source_project = main_app.project_store.ensure_default_project()
    source_project_id = str(source_project["project_id"])
    task_response = client.post(
        "/api/tasks",
        json={
            "project_id": source_project_id,
            "title": "Portable task",
            "goal": "Continue in the selected project",
            "summary": "The Task originated in another project.",
            "status": "active",
        },
    )
    assert task_response.status_code == 200
    task = task_response.json()

    selected_root = tmp_path / "selected-project"
    selected_root.mkdir()
    selected_project = main_app.project_store.create(root_path=str(selected_root), title="Selected project")
    selected_project_id = str(selected_project["project_id"])
    thread_response = client.post("/api/thread/new", json={"project_id": selected_project_id})
    assert thread_response.status_code == 200
    thread_id = thread_response.json()["thread_id"]

    chat_response = client.post(
        "/api/chat",
        json={
            "session_id": thread_id,
            "project_id": selected_project_id,
            "task_id": task["task_id"],
            "message": "加载当前任务",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert chat_response.status_code == 200
    assert chat_response.json()["session_id"] == thread_id
    loaded_session = main_app.session_store.load(thread_id)
    assert loaded_session is not None
    assert loaded_session["project_id"] == selected_project_id
    assert runtime.last_context["project"]["project_id"] == selected_project_id
    assert runtime.last_context["task_context"]["project_id"] == source_project_id
    loaded_task = main_app.task_store.get(task["task_id"])
    assert loaded_task and loaded_task["last_loaded_thread_id"] == thread_id


def test_runtime_status_uses_live_project_branch_instead_of_startup_constant(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    live_project = {
        "project_id": "project_live_branch",
        "title": "Live Repo",
        "root_path": str(tmp_path),
        "created_at": "2026-04-22T00:00:00Z",
        "updated_at": "2026-04-22T00:00:00Z",
        "last_opened_at": "2026-04-22T00:00:00Z",
        "pinned": True,
        "is_default": True,
        "git_root": str(tmp_path),
        "git_branch": "feature/live-branch",
        "is_worktree": False,
    }
    monkeypatch.setattr(main_app.project_store, "ensure_default_project", lambda: dict(live_project))
    monkeypatch.setattr(main_app.project_store, "list_projects", lambda: [dict(live_project)])

    response = client.get("/api/runtime-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_status"]["git_branch"] == "feature/live-branch"


def test_bootstrap_runtime_status_and_thread_alias_endpoints(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    bootstrap_response = client.get("/api/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["ok"] is True
    assert bootstrap_payload["app_version"] == main_app.APP_VERSION
    assert bootstrap_payload["default_project_id"]
    assert bootstrap_payload["supported_locales"]
    assert bootstrap_payload["default_max_output_tokens"] == main_app.config.max_output_tokens

    runtime_response = client.get("/api/runtime-status")
    assert runtime_response.status_code == 200
    runtime_payload = runtime_response.json()
    assert runtime_payload["ok"] is True
    assert runtime_payload["project_id"] == bootstrap_payload["default_project_id"]
    assert runtime_payload["runtime_status"]["workspace_label"]
    assert runtime_payload["runtime_status"]["workspace_boundary"]["model_view"]["permission_profile"] == "auto"
    assert runtime_payload["runtime_status"]["workspace_boundary"]["model_view"]["network_reason"] == "profile_disabled"
    assert "emergency_max_tool_calls_per_turn" not in runtime_payload["runtime_status"]["loop_safeguards"]
    assert "max_total_tool_calls_per_turn" not in runtime_payload["runtime_status"]["loop_safeguards"]
    assert runtime_payload["runtime_status"]["loop_safeguards"]["continuation_policy"] == "model_led"
    assert "max_turn_seconds" not in runtime_payload["runtime_status"]["loop_safeguards"]
    assert "max_total_failures" not in runtime_payload["runtime_status"]["loop_safeguards"]
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["runtime_status_total_ms"] >= 0
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["runtime_status_runtime_meta_ms"] >= 0
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["runtime_status_provider_cache_ms"] >= 0
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["runtime_status_provider_options_ms"] >= 0
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["runtime_status_auth_summary_ms"] >= 0
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["provider_payload_cached"] is True
    assert runtime_payload["runtime_status"]["provider_diagnostics"]["provider_cache_generation"] >= 1
    assert runtime_payload["context_meter"]["auto_compact_token_limit"] > 0
    assert runtime_payload["compaction_status"]["mode"] == "token_budget"

    create_response = client.post("/api/thread/new", json={"project_id": bootstrap_payload["default_project_id"]})
    assert create_response.status_code == 200
    create_payload = create_response.json()
    thread_id = create_payload["thread_id"]
    assert thread_id
    assert create_payload["session_id"] == thread_id

    detail_response = client.get(f"/api/thread/{thread_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["thread_id"] == thread_id
    assert detail_payload["session_id"] == thread_id
    assert detail_payload.get("status", "idle") == "idle"
    assert detail_payload.get("activity_revision", 0) == 0
    assert detail_payload["activity_kind"] == "created"
    assert detail_payload["activity_at"]

    list_response = client.get(f"/api/threads?project_id={bootstrap_payload['default_project_id']}")
    assert list_response.status_code == 200
    thread_ids = {item["thread_id"] for item in list_response.json()["threads"]}
    assert thread_id in thread_ids

    delete_response = client.delete(f"/api/thread/{thread_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True, "thread_id": thread_id, "session_id": thread_id}

    detail_after_delete = client.get(f"/api/thread/{thread_id}")
    assert detail_after_delete.status_code == 404


def test_provider_models_refresh_is_manual_and_updates_cached_presets(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)

    class FakeProviderModelCatalog:
        def __init__(self) -> None:
            self.models: dict[str, list[str]] = {}
            self.refresh_calls = 0

        def models_for(self, provider: str) -> list[str]:
            return list(self.models.get(provider, []))

        def refresh(self, provider: str, _config) -> dict[str, object]:
            self.refresh_calls += 1
            self.models[provider] = ["company-model-new", "company-model-small"]
            return {
                "provider": provider,
                "models": list(self.models[provider]),
                "updated_at": "2026-07-17T00:00:00+00:00",
            }

    catalog = FakeProviderModelCatalog()
    monkeypatch.setattr(main_app, "provider_model_catalog", catalog)
    main_app._invalidate_provider_payload_cache()
    client = TestClient(main_app.app)
    provider = str(main_app.config.llm_provider)

    bootstrap_response = client.get("/api/bootstrap")
    assert bootstrap_response.status_code == 200
    assert catalog.refresh_calls == 0

    refresh_response = client.post(f"/api/providers/{provider}/models/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert catalog.refresh_calls == 1
    assert payload["provider"] == provider
    assert payload["models"] == ["company-model-new", "company-model-small"]
    assert "company-model-new" in payload["model_options"]
    active = next(item for item in payload["provider_options"] if item["provider"] == provider)
    assert "company-model-small" in active["model_options"]


def test_app_update_endpoint_runs_manual_update_manager(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    calls: list[str] = []

    class FakeUpdateManager:
        def status(self) -> dict[str, object]:
            calls.append("status")
            return {
                "ok": True,
                "version": "v2.9.19-test",
                "commit": "def5678",
                "branch": "main",
                "repo_root": str(tmp_path),
                "is_git_repo": True,
            }

        def update(self) -> dict[str, object]:
            calls.append("update")
            return {
                "ok": True,
                "repo_root": str(tmp_path),
                "branch": "main",
                "before": "abc1234",
                "after": "def5678",
                "dirty_before_update": True,
                "commands": [
                    {"command": "git fetch --tags origin", "exit_code": 0, "stdout": "ok", "stderr": ""},
                    {"command": "git reset --hard origin/main", "exit_code": 0, "stdout": "ok", "stderr": ""},
                    {"command": "git pull --ff-only", "exit_code": 0, "stdout": "ok", "stderr": ""},
                ],
                "message": "Update completed. Restart the app to use the latest code.",
            }

    monkeypatch.setattr(main_app, "app_update_manager", FakeUpdateManager())

    status_response = client.get("/api/app/status")
    assert status_response.status_code == 200
    assert status_response.json()["commit"] == "def5678"

    update_response = client.post("/api/app/update", json={"command": "rm -rf /"})
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["ok"] is True
    assert payload["before"] == "abc1234"
    assert payload["after"] == "def5678"
    assert [item["command"] for item in payload["commands"]] == [
        "git fetch --tags origin",
        "git reset --hard origin/main",
        "git pull --ff-only",
    ]
    assert calls == ["status", "update"]


def test_app_update_endpoint_returns_failure_detail(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    class FakeUpdateManager:
        def update(self) -> dict[str, object]:
            return {
                "ok": False,
                "repo_root": str(tmp_path),
                "branch": "main",
                "before": "abc1234",
                "after": "abc1234",
                "dirty_before_update": False,
                "commands": [
                    {"command": "git reset --hard origin/main", "exit_code": 128, "stdout": "", "stderr": "boom"},
                ],
                "failed_command": "git reset --hard origin/main",
                "exit_code": 128,
                "stdout": "",
                "stderr": "boom",
                "message": "Update failed.",
            }

    monkeypatch.setattr(main_app, "app_update_manager", FakeUpdateManager())

    response = client.post("/api/app/update")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["failed_command"] == "git reset --hard origin/main"
    assert payload["stderr"] == "boom"


def test_runtime_status_uses_cached_provider_payload(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    main_app._invalidate_provider_payload_cache()
    monkeypatch.setattr(
        main_app,
        "list_provider_profiles",
        lambda cfg: [
            {
                "provider": cfg.llm_provider,
                "label": cfg.llm_provider,
                "default_model": cfg.default_model,
                "model_options": [cfg.default_model],
            }
        ],
    )
    calls = {"auth_summary": 0}

    def counting_auth_summary(self):
        calls["auth_summary"] += 1
        return {"available": True, "reason": "", "mode": "test", "provider": "test"}

    monkeypatch.setattr(main_app.OpenAIAuthManager, "auth_summary", counting_auth_summary)
    monkeypatch.setattr(
        main_app.vintage_programmer_runtime._backend.tools,
        "docker_status",
        lambda: (_ for _ in ()).throw(AssertionError("runtime-status should not check Docker")),
    )

    first = client.get("/api/runtime-status")
    second = client.get("/api/runtime-status")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["auth_summary"] == 0


def test_runtime_status_does_not_require_descriptor(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    monkeypatch.setattr(
        main_app.vintage_programmer_runtime,
        "descriptor",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runtime-status should not need descriptor")),
    )

    response = client.get("/api/runtime-status")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_workbench_writes_invalidate_descriptor_cache(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    class _CountingRuntime(_FakeVintageRuntime):
        def __init__(self) -> None:
            self.invalidations = 0

        def invalidate_descriptor_cache(self) -> None:
            self.invalidations += 1

    runtime = _CountingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)

    create_response = client.post(
        "/api/workbench/skills",
        json={
            "content": "---\nname: new_skill\ndescription: cache invalidation test\nenabled: true\n---\n\n# Skill\n"
        },
    )
    assert create_response.status_code == 200
    spec_response = client.put("/api/workbench/specs/agent.md", json={"content": "---\nid: vintage_programmer\n---\nupdated"}, params={"locale": main_app.config.default_locale})
    assert spec_response.status_code == 200
    assert runtime.invalidations == 2


def test_thread_detail_uses_lightweight_pagination_and_stable_turn_ids(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    for index in range(6):
        main_app.session_store.append_turn(session, "user" if index % 2 == 0 else "assistant", f"turn-{index}")
    main_app.session_store.save(session)

    first_page = client.get(f"/api/thread/{session['id']}?max_turns=2")
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert [item["text"] for item in first_payload["turns"]] == ["turn-4", "turn-5"]
    assert all(item["id"] for item in first_payload["turns"])

    before_id = first_payload["turns"][0]["id"]
    previous_page = client.get(f"/api/thread/{session['id']}?max_turns=2&before_turn_id={before_id}")
    assert previous_page.status_code == 200
    assert [item["text"] for item in previous_page.json()["turns"]] == ["turn-2", "turn-3"]


def test_empty_thread_title_stays_unlocalized_across_api_reload(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    project = main_app.project_store.ensure_default_project()

    created = client.post("/api/thread/new", json={"project_id": project["project_id"]})
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]

    listed = client.get(f"/api/threads?project_id={project['project_id']}")
    detail = client.get(f"/api/thread/{thread_id}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    listed_thread = next(item for item in listed.json()["threads"] if item["thread_id"] == thread_id)
    assert listed_thread["title"] == ""
    assert listed_thread["has_custom_title"] is False
    assert detail.json()["title"] == ""
    assert detail.json()["display_title"] == ""
    assert detail.json()["has_custom_title"] is False


def test_thread_rename_reuses_session_title_and_exposes_display_title(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    main_app.session_store.append_turn(session, role="user", text="derive title from this first turn")
    main_app.session_store.save(session)

    initial_thread = client.get(f"/api/thread/{session['id']}")
    assert initial_thread.status_code == 200
    initial_payload = initial_thread.json()
    assert initial_payload["title"] == ""
    assert initial_payload["display_title"] == "derive title from this first turn"
    assert initial_payload["has_custom_title"] is False

    renamed = client.patch(f"/api/session/{session['id']}/title", json={"title": "  Custom Thread  "})
    assert renamed.status_code == 200
    renamed_payload = renamed.json()
    assert renamed_payload == {
        "ok": True,
        "session_id": session["id"],
        "title": "Custom Thread",
        "display_title": "Custom Thread",
        "has_custom_title": True,
    }

    thread_detail = client.get(f"/api/thread/{session['id']}")
    session_detail = client.get(f"/api/session/{session['id']}")
    thread_list = client.get("/api/threads")
    assert thread_detail.status_code == 200
    assert session_detail.status_code == 200
    assert thread_list.status_code == 200
    assert thread_detail.json()["title"] == "Custom Thread"
    assert thread_detail.json()["display_title"] == "Custom Thread"
    assert thread_detail.json()["has_custom_title"] is True
    assert session_detail.json()["title"] == "Custom Thread"
    assert session_detail.json()["display_title"] == "Custom Thread"
    assert session_detail.json()["has_custom_title"] is True
    assert thread_list.json()["threads"][0]["title"] == "Custom Thread"
    assert thread_list.json()["threads"][0]["has_custom_title"] is True

    main_app.session_store.rebuild_metadata_index(default_project=main_app.project_store.ensure_default_project())
    reset = client.patch(f"/api/session/{session['id']}/title", json={"title": ""})
    assert reset.status_code == 200
    reset_payload = reset.json()
    assert reset_payload["title"] == ""
    assert reset_payload["display_title"] == "derive title from this first turn"
    assert reset_payload["has_custom_title"] is False


def test_first_successful_turn_generates_one_model_title_without_overwriting_manual_title(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    class _TitleRuntime(_FakeVintageRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.title_calls = 0

        def generate_thread_title(self, *, user_text, assistant_text, model=None, locale=""):
            self.title_calls += 1
            assert "重复工具失败" in str(user_text)
            assert str(assistant_text) == "single-agent response"
            assert str(model or "")
            assert locale == main_app.config.default_locale
            return {
                "title": '标题："修复重复工具失败判定。"',
                "effective_model": "gpt-title-test",
                "token_usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "llm_calls": 1,
                },
            }

    runtime = _TitleRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)

    first = client.post(
        "/api/chat",
        json={
            "message": "请修复重复工具失败判定，并补充验证",
            "settings": {
                "model": "gpt-test",
                "locale": main_app.config.default_locale,
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["token_usage"] == {
        "input_tokens": 14,
        "output_tokens": 9,
        "total_tokens": 23,
        "llm_calls": 2,
        "estimated_cost_usd": 0.0,
        "pricing_known": False,
    }
    session_id = first_payload["session_id"]
    loaded = main_app.session_store.load(session_id)
    assert loaded
    assert loaded["title"] == ""
    assert loaded["auto_title"] == "修复重复工具失败判定"
    assert loaded["title_generation"]["status"] == "generated"
    assert loaded["title_generation"]["model"] == "gpt-title-test"
    assert runtime.title_calls == 1

    listed = client.get("/api/threads").json()["threads"][0]
    assert listed["title"] == "修复重复工具失败判定"
    assert listed["has_custom_title"] is False

    renamed = client.patch(f"/api/session/{session_id}/title", json={"title": "我的手动标题"})
    assert renamed.status_code == 200
    assert renamed.json()["display_title"] == "我的手动标题"

    second = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "继续补充测试",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert second.status_code == 200
    assert runtime.title_calls == 1
    assert client.get(f"/api/thread/{session_id}").json()["display_title"] == "我的手动标题"

    reset = client.patch(f"/api/session/{session_id}/title", json={"title": ""})
    assert reset.status_code == 200
    assert reset.json()["display_title"] == "修复重复工具失败判定"


def test_thread_summary_view_skips_run_artifact_load_until_full_turn_request(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    main_app.session_store.append_turn(session, role="user", text="inspect")
    assistant_turn = main_app.session_store.append_turn(
        session,
        role="assistant",
        text="done",
        answer_bundle={"summary": "done", "claims": [], "citations": [], "warnings": []},
        activity={
            "run_id": "run-1",
            "status": "completed",
            "summary": "read and answered",
            "activity_summary": "read and answered",
            "run_duration_ms": 12,
            "turn_changes": {
                "files": [
                    {"path": "app/main.py", "kind": "modified"},
                    {"path": "tests/test_main.py", "kind": "modified"},
                ],
                "count": 2,
                "retained": False,
                "possible_untracked_changes": False,
                "verification": {"status": "passed", "tool": "exec_command", "summary": "2 passed"},
            },
            "triggering_user_message": "inspect",
            "trace_events": [{"id": "trace-1", "type": "tool.started", "payload": {"call_id": "call-1"}}],
            "llm_exchanges": [{"round": 1, "status": "completed"}],
            "model_draft": "draft",
            "runtime_error": {"kind": "debug"},
            "tool_items": [{"type": "toolCall", "tool": "read_file"}],
        },
    )
    main_app.session_store.persist_turn_artifact(
        session,
        turn_id=str(assistant_turn["id"]),
        run_id="run-1",
        activity=assistant_turn["activity"],
        answer_bundle=assistant_turn["answer_bundle"],
        tool_events=[{"name": "read_file", "status": "ok", "summary": "read"}],
        inspector={"run_state": {"turn_status": "completed"}},
    )
    main_app.session_store.save(session)

    calls = {"load": 0, "load_by_ref": 0}
    original_load_by_ref = main_app.session_store.turn_trace_store.load_by_ref

    def _load_by_ref(trace_ref: str):
        calls["load_by_ref"] += 1
        return original_load_by_ref(trace_ref)

    monkeypatch.setattr(main_app.session_store.turn_trace_store, "load_by_ref", _load_by_ref)

    summary_response = client.get(f"/api/thread/{session['id']}?view=summary")

    assert summary_response.status_code == 200
    assert calls == {"load": 0, "load_by_ref": 0}
    summary_turn = summary_response.json()["turns"][-1]
    assert set(summary_turn["activity"]) <= {
        "run_id",
        "trace_ref",
        "status",
        "summary",
        "activity_summary",
        "tool_count",
        "run_duration_ms",
        "turn_changes",
    }
    assert summary_turn["activity"]["turn_changes"]["count"] == 2
    assert [item["path"] for item in summary_turn["activity"]["turn_changes"]["files"]] == [
        "app/main.py",
        "tests/test_main.py",
    ]
    assert "triggering_user_message" not in summary_turn["activity"]
    assert "llm_exchanges" not in summary_turn["activity"]
    assert "answer_bundle" not in summary_turn
    assert "run_artifact" not in summary_turn

    activity_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=activity")

    assert activity_response.status_code == 200
    assert calls == {"load": 0, "load_by_ref": 1}
    activity_turn = activity_response.json()
    assert activity_turn["activity"]["activity_loaded"] is True
    assert "llm_exchanges" not in activity_turn["activity"]
    assert "run_artifact" not in activity_turn
    assert "answer_bundle" not in activity_turn

    debug_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=debug")

    assert debug_response.status_code == 200
    assert calls == {"load": 0, "load_by_ref": 2}
    debug_turn = debug_response.json()
    assert debug_turn["activity"]["debug_loaded"] is True
    assert debug_turn["activity"]["turn_trace"]["turn_trace_schema_version"] == 1
    assert [item["role"] for item in debug_turn["activity"]["thread_items"]] == ["user", "assistant"]
    assert "answer_bundle" not in debug_turn
    assert "run_artifact" not in debug_turn

    full_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=full")

    assert full_response.status_code == 200
    assert calls["load_by_ref"] == 3
    assert calls["load"] == 0
    full_turn = full_response.json()
    assert full_turn["activity"]["turn_trace"]["turn_trace_schema_version"] == 1
    assert "answer_bundle" not in full_turn
    assert "run_artifact" not in full_turn


def test_thread_detail_uses_fast_view_without_runtime_prechecks(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    session_id = "legacy-fast-view"
    session_path = tmp_path / "sessions" / f"{session_id}.json"
    session_path.write_text(
        json.dumps(
            {
                "id": session_id,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "turns": [
                    {"id": "u1", "role": "user", "text": "hello", "created_at": "2026-01-01T00:00:00Z"},
                    {"id": "a1", "role": "assistant", "text": "hi", "created_at": "2026-01-01T00:00:01Z"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main_app,
        "_default_project",
        lambda: (_ for _ in ()).throw(AssertionError("thread detail should not load default project")),
    )
    monkeypatch.setattr(
        main_app.OpenAIAuthManager,
        "auth_summary",
        lambda self: (_ for _ in ()).throw(AssertionError("thread detail should not precheck provider auth")),
    )
    monkeypatch.setattr(
        main_app.vintage_programmer_runtime._backend.tools,
        "docker_status",
        lambda: (_ for _ in ()).throw(AssertionError("thread detail should not check Docker")),
    )

    detail_response = client.get(f"/api/thread/{session_id}")
    full_turn_response = client.get(f"/api/thread/{session_id}/turn/a1?view=full")

    assert detail_response.status_code == 200
    assert full_turn_response.status_code == 200
    assert [item["text"] for item in detail_response.json()["turns"]] == ["hello", "hi"]
    assert full_turn_response.json()["text"] == "hi"
    migrated = json.loads(session_path.read_text(encoding="utf-8"))
    assert migrated["thread_record_schema_version"] == 5
    assert "turns" not in migrated
    assert (tmp_path / "session_backups" / f"{session_id}.v2.json").exists()


def test_thread_new_uses_cached_project_without_live_metadata_refresh(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    project = {
        "project_id": "project_cached",
        "title": "Cached Project",
        "root_path": str(tmp_path),
        "git_branch": "cached-branch",
    }
    monkeypatch.setattr(main_app.project_store, "get_cached", lambda project_id: dict(project) if project_id == "project_cached" else None)
    monkeypatch.setattr(main_app.project_store, "list_projects", lambda: (_ for _ in ()).throw(AssertionError("list_projects should not run")))
    monkeypatch.setattr(main_app.project_store, "touch", lambda project_id: (_ for _ in ()).throw(AssertionError("touch should not run")))

    response = client.post("/api/thread/new", json={"project_id": "project_cached"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"]
    loaded = main_app.session_store.load(payload["thread_id"])
    assert loaded and loaded["project_id"] == "project_cached"


def test_chat_uses_cached_project_without_live_metadata_refresh(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    project = {
        "project_id": "project_cached_chat",
        "title": "Cached Chat Project",
        "root_path": str(tmp_path),
        "git_branch": "cached-chat-branch",
    }
    touched: list[str] = []
    monkeypatch.setattr(main_app.project_store, "get_cached", lambda project_id: dict(project) if project_id == "project_cached_chat" else None)
    monkeypatch.setattr(main_app.project_store, "list_projects", lambda: (_ for _ in ()).throw(AssertionError("list_projects should not run")))
    monkeypatch.setattr(main_app.project_store, "get", lambda project_id: (_ for _ in ()).throw(AssertionError("get should not run")))
    monkeypatch.setattr(main_app.project_store, "touch", lambda project_id: (_ for _ in ()).throw(AssertionError("touch should not run")))
    monkeypatch.setattr(main_app.project_store, "touch_cached", lambda project_id: touched.append(project_id) or dict(project))

    response = client.post(
        "/api/chat",
        json={
            "project_id": "project_cached_chat",
            "message": "介绍一下你自己",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "single-agent response"
    assert touched == ["project_cached_chat"]
    loaded = main_app.session_store.load(payload["session_id"])
    assert loaded and loaded["project_id"] == "project_cached_chat"


def test_thread_started_event_uses_session_snapshot_without_reload(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    session = main_app.session_store.create(main_app.project_store.get_cached(None) or {})
    main_app.session_store.append_turn(session, role="user", text="介绍一下你自己")
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_app,
        "_thread_list_item_for_session_id",
        lambda session_id: (_ for _ in ()).throw(AssertionError("thread started should not reload session")),
    )

    main_app._emit_thread_started(lambda payload: events.append(payload), session["id"], session=session)

    assert events
    assert events[0]["event"] == "thread/started"
    thread = events[0]["thread"]
    assert thread["thread_id"] == session["id"]
    assert thread["title"] == "介绍一下你自己"
    assert thread["activity_revision"] == 0
    assert thread["activity_kind"] == "created"


def test_projects_endpoint_returns_live_git_branch_from_project_store(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    repo_root = tmp_path / "repo-live"
    repo_root.mkdir(parents=True, exist_ok=True)
    created = main_app.project_store.create(root_path=str(repo_root), title="Repo Live")
    registry_payload = json.loads(main_app.project_store.registry_path.read_text(encoding="utf-8"))
    registry_payload["projects"][created["project_id"]]["git_branch"] = "stale-branch"
    registry_payload["projects"][created["project_id"]]["git_root"] = "/stale/root"
    main_app.project_store.registry_path.write_text(json.dumps(registry_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        storage_mod,
        "_git_metadata",
        lambda root: {
            "git_root": str(root),
            "git_branch": "feature/live-project-list",
            "is_worktree": True,
        },
    )

    response = client.get("/api/projects")

    assert response.status_code == 200
    payload = response.json()
    project_row = next(item for item in payload["projects"] if item["project_id"] == created["project_id"])
    assert project_row["git_branch"] == "feature/live-project-list"
    assert project_row["git_root"] == str(repo_root)
    assert project_row["is_worktree"] is True


def test_chat_endpoint_uses_single_agent_runtime(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "帮我看一下当前工作区",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "vintage_programmer"
    assert payload["text"] == "single-agent response"
    assert payload["tool_events"][0]["name"] == "web_search"
    assert payload["tool_events"][0]["source"] == "adapter"
    assert payload["tool_events"][0]["group"] == "web"
    assert payload["tool_events"][0]["status"] == "ok"
    assert payload["permission_profile"] == "auto"
    assert payload["turn_status"] == "completed"
    assert payload["plan"] == [{"step": "Inspect workspace", "status": "completed"}]
    assert payload["context_meter"]["auto_compact_token_limit"] > 0
    assert payload["compaction_status"]["mode"] == "token_budget"
    assert payload["inspector"]["agent"]["title"] == "Vintage Programmer"
    assert payload["inspector"]["run_state"]["permission_profile"] == "auto"
    assert payload["inspector"]["run_state"]["turn_status"] == "completed"
    assert payload["inspector"]["run_state"]["context_meter"]["auto_compact_token_limit"] > 0
    assert payload["inspector"]["run_state"]["compaction_status"]["mode"] == "token_budget"
    assert payload["inspector"]["run_state"]["model_action"]["action_type"] == "tool_call"
    assert payload["inspector"]["run_state"]["execution_trace"][0]["action_type"] == "tool_call"
    assert "execution_trace" not in payload

    session_id = payload["session_id"]
    session_response = client.get(f"/api/session/{session_id}")
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["project_id"]
    assert session_payload["project_root"] == str(tmp_path)
    assert session_payload["agent_state"]["phase"] == "idle"
    assert session_payload.get("pending_interaction", {}) == {}
    assert session_payload["agent_state"]["turn_status"] == "idle"
    assert session_payload["agent_state"]["last_run_id"] == ""
    assert "task_checkpoint" not in session_payload["agent_state"]
    assert [item["role"] for item in session_payload["thread_items"]] == ["user", "assistant"]
    assert session_payload.get("context_meter", {}) == {}
    assert session_payload.get("compaction_status", {}) == {}


def test_command_approval_notice_is_runtime_turn_not_model_history(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _PendingCommandApprovalRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "运行这条命令",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turn_status"] == "needs_user_input"
    assert payload["pending_approval"]["type"] == "command_execution"

    session = main_app.session_store.load(payload["session_id"])
    assert session is not None
    assert [item["role"] for item in session["turns"]] == ["user", "runtime"]
    assert session["turns"][-1]["text"].startswith("Approval required to run this command")
    transcript_items = list((session.get("thread_transcript") or {}).get("items") or [])
    assert [item["role"] for item in transcript_items] == ["user", "assistant"]
    assert not any(
        item.get("role") == "assistant"
        and str(item.get("content") or "").startswith("Approval required to run this command")
        for item in transcript_items
    )

    thread_response = client.get(f"/api/thread/{payload['session_id']}?view=summary")
    assert thread_response.status_code == 200
    assert thread_response.json()["turns"][-1]["role"] == "runtime"


def test_command_approval_decision_resumes_same_turn_without_new_human_message(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _ResumableCommandApprovalRuntime())
    client = TestClient(main_app.app)

    first = client.post(
        "/api/chat",
        json={
            "message": "运行这条命令",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    session_id = first_payload["session_id"]
    original_turn_id = str(first_payload["pending_approval"].get("tool_call_id") or "")
    assert original_turn_id == "approval-tool-call"
    original_started_at = float(first_payload["activity"]["turn_started_at"])
    assert original_started_at > 0
    pending_session = main_app.session_store.load(session_id)
    assert pending_session is not None
    assert float(pending_session["pending_interaction"]["turn"]["turn_started_at"]) == original_started_at
    assert float(
        first_payload["inspector"]["run_state"]["pending_turn"]["turn_started_at"]
    ) == original_started_at

    second = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "取消执行 Python",
            "user_input_response": {
                "type": "command_execution",
                "action": "cancel",
                "tool_call_id": "approval-tool-call",
            },
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["turn_status"] == "completed"
    assert float(second_payload["activity"]["turn_started_at"]) == original_started_at
    session = main_app.session_store.load(session_id)
    assert session is not None
    assert [item["role"] for item in session["turns"]] == ["user", "assistant"]
    transcript_items = list((session.get("thread_transcript") or {}).get("items") or [])
    assert [item["role"] for item in transcript_items] == ["user", "assistant", "tool", "assistant"]
    assert transcript_items[2]["tool_call_id"] == "approval-tool-call"
    assert "user_declined" in transcript_items[2]["content"]
    assert not any("command_execution_cancelled" in str(item.get("content") or "") for item in transcript_items)
    assert session["pending_interaction"] == {}


def test_legacy_command_approval_placeholder_migrates_to_pending_turn() -> None:
    session = {
        "cwd": "/tmp/project",
        "task_state": {"plan_items": [{"step": "Run check", "status": "in_progress"}]},
        "agent_state": {
            "last_run_id": "legacy-turn",
            "pending_approval": {
                "type": "command_execution",
                "command": "python check.py",
                "cwd": "/tmp/project",
                "approval_token": "token",
            },
            "pending_user_input": {"summary": "Approval required"},
        },
        "thread_transcript": {
            "schema_version": 1,
            "items": [
                {"id": "u1", "turn_id": "u1", "role": "user", "content": "Run the check"},
                {
                    "id": "a1",
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc-legacy",
                            "name": "exec_command",
                            "args": {"cmd": "python check.py", "cwd": "/tmp/project"},
                        }
                    ],
                },
                {
                    "id": "tool-placeholder",
                    "role": "tool",
                    "content": json.dumps(
                        {"ok": False, "approval_required": True, "error_kind": "command_execution_approval_required"}
                    ),
                    "tool_call_id": "tc-legacy",
                    "name": "exec_command",
                },
            ],
        },
    }

    pending = main_app._migrate_legacy_pending_command_turn(session)

    assert pending["tool_call_id"] == "tc-legacy"
    assert pending["turn_id"] == "legacy-turn"
    assert pending["request_message"] == "Run the check"
    assert pending["plan"] == [{"step": "Run check", "status": "in_progress"}]
    assert [item["role"] for item in session["thread_transcript"]["items"]] == ["user", "assistant"]
    assert session["pending_interaction"]["approval"]["tool_call_id"] == "tc-legacy"
    assert session["pending_interaction"]["turn"]["tool_call_id"] == "tc-legacy"


def test_chat_persists_intermediate_assistant_reply_before_steered_user_turn(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)

    class SteeredRuntime(_FakeVintageRuntime):
        def run(self, *, message, settings, context, progress_cb=None):
            payload = super().run(
                message=message,
                settings=settings,
                context=context,
                progress_cb=progress_cb,
            )
            payload["text"] = "第二段最终回复"
            payload["final_answer"] = "第二段最终回复"
            payload["activity"] = {
                **dict(payload.get("activity") or {}),
                "llm_exchanges": [
                    {
                        "round": 1,
                        "model": "gpt-test",
                        "status": "completed",
                        "sent_messages_exact": [
                            {"role": "system", "content": "[system]\nShared rules"},
                            {"role": "user", "content": "先处理原任务"},
                        ],
                        "request_composition": {"bound_tool_names": []},
                        "model_returned_exact": {
                            "role": "assistant",
                            "content": "第一段回复",
                            "finish_reason": "stop",
                        },
                    }
                ],
            }
            payload["intermediate_turns"] = [
                {
                    "role": "assistant",
                    "text": "第一段回复",
                    "activity": {"status": "completed", "run_id": context.get("run_id")},
                },
                {
                    "role": "user",
                    "text": "追加：再检查测试",
                    "activity": {"status": "steer_accepted", "steer_id": "steer-1"},
                },
            ]
            payload["transcript_delta"] = [
                {
                    "id": "segment-first",
                    "turn_id": str(context.get("logical_turn_id") or context.get("run_id") or ""),
                    "role": "assistant",
                    "content": "第一段回复",
                },
                {
                    "id": "steer-1",
                    "turn_id": str(context.get("logical_turn_id") or context.get("run_id") or ""),
                    "role": "user",
                    "content": "追加：再检查测试",
                },
            ]
            payload["steered_user_messages"] = [
                {"id": "steer-1", "message": "追加：再检查测试", "queued_at": 1.0, "accepted_at": 2.0}
            ]
            return payload

    monkeypatch.setattr(main_app, "vintage_programmer_runtime", SteeredRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "先处理原任务",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    session = main_app.session_store.load(response.json()["session_id"])
    assert session is not None
    assert [(item["role"], item["text"]) for item in session["turns"]] == [
        ("user", "先处理原任务"),
        ("assistant", "第一段回复"),
        ("user", "追加：再检查测试"),
        ("assistant", "第二段最终回复"),
    ]
    first_assistant = session["turns"][1]
    final_assistant = session["turns"][3]
    assert first_assistant["activity"]["trace_ref"]
    assert first_assistant["activity"]["trace_ref"] == final_assistant["activity"]["trace_ref"]

    first_debug = client.get(
        f"/api/thread/{session['id']}/turn/{first_assistant['id']}?view=debug"
    )
    assert first_debug.status_code == 200
    first_contexts = first_debug.json()["activity"]["turn_trace"]["contexts"]
    assert first_contexts[0]["system_message"] == "[system]\nShared rules"


def test_chat_endpoint_runs_and_persists_pre_turn_compaction(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    capture_runtime = _ContextCapturingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", capture_runtime)
    client = TestClient(main_app.app)

    project = main_app.project_store.ensure_default_project()
    session = main_app.session_store.create(project)
    for index in range(18):
        words = " ".join(f"legacy_{index}_{item}" for item in range(650))
        main_app.session_store.append_turn(
            session,
            role="user" if index % 2 == 0 else "assistant",
            text=f"需要保留但可压缩的旧上下文 {index}: {words}",
        )
    main_app.session_store.save(session)

    pre_status = main_app._build_compaction_status_for_session(
        session=session,
        model="moonshot-v1-8k",
        max_output_tokens=1024,
        pending_message="继续总结",
    )
    assert pre_status["estimated_context_tokens"] >= pre_status["auto_compact_token_limit"]

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "继续总结",
            "settings": {
                "model": "moonshot-v1-8k",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compaction_status"]["generation"] >= 1
    assert payload["compaction_status"]["compacted_history_present"] is True
    assert payload["compaction_status"]["last_compaction_phase"] == "pre_turn"
    assert payload["compaction_status"]["last_compaction_reason"].split(":", 1)[0] in {
        "context_auto_limit",
        "context_danger_limit",
        "history_soft_limit",
    }

    loaded = main_app.session_store.load(session["id"], default_project=project)
    assert loaded is not None
    assert loaded["compaction_state"]["generation"] >= 1
    assert loaded["compaction_state"]["compacted_history"]
    assert loaded["summary"] == loaded["compaction_state"]["compacted_history"]
    assert loaded["compaction"]["compacted_at"]
    assert set(loaded["compaction"]) == {
        "generation", "summary", "compacted_until_item_id", "compacted_at",
    }

    assert capture_runtime.seen_contexts
    seen = capture_runtime.seen_contexts[0]
    assert seen["summary"] == loaded["compaction_state"]["compacted_history"]
    assert seen["compaction_status"]["generation"] == loaded["compaction_state"]["generation"]
    assert seen["compaction_status"]["last_compaction_phase"] == "pre_turn"
    assert seen["compaction_status"]["reason"] in {
        "context_auto_limit", "context_danger_limit", "history_soft_limit",
    }
    assert seen["compaction_status"]["compaction_source"] == "deterministic_fallback"
    assert "history_turns" not in seen
    seen_transcript = list(dict(seen["thread_transcript"]).get("items") or [])
    assert seen_transcript
    assert all(item["content"] != "继续总结" for item in seen_transcript)


def test_chat_persists_runtime_413_compaction_for_the_next_turn(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _RequestTooLargeRecoveredRuntime())
    client = TestClient(main_app.app)

    project = main_app.project_store.ensure_default_project()
    session = main_app.session_store.create(project)
    for index in range(24):
        words = " ".join(f"legacy_{index}_{item}" for item in range(1_000))
        main_app.session_store.append_turn(
            session,
            role="user" if index % 2 == 0 else "assistant",
            text=f"large but normally sub-threshold history {index}: {words}",
        )
    main_app.session_store.save(session)

    pre_status = main_app._build_compaction_status_for_session(
        session=session,
        model="gpt-test",
        max_output_tokens=1024,
        pending_message="继续调查",
    )
    assert pre_status["compact_recommendation"] == "none"

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "继续调查",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 40,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compaction_status"]["last_compaction_phase"] == (
        "request_too_large_recovery"
    )

    loaded = main_app.session_store.load(session["id"], default_project=project)
    assert loaded is not None
    assert loaded["compaction_state"]["generation"] == 1
    assert loaded["compaction_state"]["compacted_history"]


def test_chat_stream_emits_stage_trace_run_events_final_and_done(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat/stream",
        json={
            "message": "流式返回当前状态",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(response.text)
    event_names = [name for name, _ in events]
    assert "stage" in event_names
    assert "plan_update" in event_names
    assert "thread/started" in event_names
    assert "thread/status/changed" in event_names
    assert "thread/updated" in event_names
    assert "thread/tokenUsage/updated" in event_names
    assert "turn/started" in event_names
    assert "turn/plan/updated" in event_names
    assert "turn/completed" in event_names
    assert "item/started" in event_names
    assert "item/agentMessage/delta" in event_names
    assert "item/completed" in event_names
    assert "run_started" in event_names
    assert "trace_event" in event_names
    assert "run_finished" in event_names
    assert "final" in event_names
    assert event_names[-1] == "done"
    assert event_names.index("run_started") < event_names.index("item/agentMessage/delta")
    assert event_names.index("run_finished") < event_names.index("done")
    started_thread = next(payload["thread"] for name, payload in events if name == "thread/started")
    updated_thread = next(payload["thread"] for name, payload in events if name == "thread/updated")
    assert started_thread["activity_revision"] == 1
    assert started_thread["activity_kind"] == "user_message"
    assert updated_thread["activity_revision"] == 2
    assert updated_thread["activity_kind"] == "turn_completed"
    assert updated_thread["activity_at"] >= started_thread["activity_at"]
    stage_payloads = [payload for name, payload in events if name == "stage"]
    assert any(payload.get("phase") == "execute" for payload in stage_payloads)
    trace_payloads = [payload for name, payload in events if name == "trace_event"]
    assert any((payload.get("trace") or {}).get("type") == "runtime_contract.selected" for payload in trace_payloads)
    thread_status_payloads = [payload for name, payload in events if name == "thread/status/changed"]
    assert {payload["status"]["type"] for payload in thread_status_payloads} >= {"active", "idle"}
    typed_turn = next(payload for name, payload in events if name == "turn/started")
    assert typed_turn["turn"]["status"] == "inProgress"
    typed_plan = next(payload for name, payload in events if name == "turn/plan/updated")
    assert typed_plan["plan"] == [{"step": "Inspect workspace", "status": "completed"}]
    typed_delta = next(payload for name, payload in events if name == "item/agentMessage/delta")
    assert typed_delta["delta"] == "single-agent response"
    run_finished_payload = next(payload for name, payload in events if name == "run_finished")
    assert run_finished_payload["turn_status"] == "completed"
    final_payload = next(payload for name, payload in events if name == "final")
    response_payload = dict(final_payload.get("response") or {})
    assert response_payload["agent_id"] == "vintage_programmer"
    assert response_payload["text"] == "single-agent response"
    assert response_payload["permission_profile"] == "auto"
    assert response_payload["turn_status"] == "completed"
    assert response_payload["activity"]["trace_events"][0]["type"] == "runtime_contract.selected"
    assert "phase_timings" not in response_payload["activity"]
    phase_timings = response_payload["inspector"]["run_state"]["phase_timings"]
    assert phase_timings["provider_auth_summary_ms"] >= 0
    assert phase_timings["session_load_ms"] >= 0
    assert phase_timings["runtime_context_ms"] >= 0
    assert phase_timings["runtime_run_ms"] >= 0
    assert phase_timings["total_ms"] >= 0
    assert response_payload["activity"]["run_duration_ms"] == phase_timings["total_ms"]
    assert response_payload["activity"]["final_elapsed_ms"] >= phase_timings["total_ms"]
    assert run_finished_payload["duration_ms"] == response_payload["activity"]["run_duration_ms"]


def test_chat_stream_preserves_client_message_id_in_authoritative_thread(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    client_message_id = "client-message-first-turn"

    response = client.post(
        "/api/chat/stream",
        json={
            "message": "hi",
            "client_message_id": client_message_id,
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    final_payload = next(payload for name, payload in events if name == "final")
    session_id = str(dict(final_payload.get("response") or {}).get("session_id") or "")
    assert session_id
    detail = client.get(f"/api/thread/{session_id}?view=summary&max_turns=40")
    assert detail.status_code == 200
    turns = detail.json()["turns"]
    assert turns[0]["role"] == "user"
    assert turns[0]["text"] == "hi"
    assert turns[0]["id"] == client_message_id
    assert sum(1 for turn in turns if turn["role"] == "user" and turn["text"] == "hi") == 1


def test_chat_stream_preserves_multiple_runtime_answer_deltas(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _StreamingVintageRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat/stream",
        json={
            "message": "请把这句话润色一下",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    deltas = [payload["delta"] for name, payload in events if name == "item/agentMessage/delta"]
    final_payload = next(payload for name, payload in events if name == "final")
    response_payload = dict(final_payload.get("response") or {})

    assert deltas == ["streamed ", "answer"]
    assert "streamed answer" not in deltas
    assert response_payload["text"] == "streamed answer"
    assert response_payload["inspector"]["run_state"]["answer_stream"]["upstream_progressive"] is True


def test_chat_stream_surfaces_tool_audit_fields_on_live_items(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _ToolAuditStreamingRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat/stream",
        json={
            "message": "查一下 PLAN.md",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    completed_tool = next(
        payload["item"]
        for name, payload in events
        if name == "item/completed" and str((payload.get("item") or {}).get("tool") or "") == "web_search"
    )

    assert completed_tool["raw_arguments"]["query"] == "PLAN.md"
    assert completed_tool["raw_tool_call"]["arguments"]["q"] == "PLAN.md"
    assert completed_tool["normalized_arguments"]["query"] == "PLAN.md"
    assert completed_tool["validation_result"]["allowed"] is True
    assert completed_tool["arguments_preview"] == "query=PLAN.md"
    assert completed_tool["schema_validation"]["status"] == "valid"


def test_cancel_chat_run_endpoint_sets_active_run_flag(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    run_id = "run-cancel-test"
    cancel_event = threading.Event()

    with main_app._active_chat_runs_lock:
        main_app._active_chat_runs[run_id] = {
            "run_id": run_id,
            "cancel_event": cancel_event,
            "status": "running",
            "session_id": "s-1",
            "project_id": "project_demo",
            "accepting_steers": True,
            "pending_steers": [],
        }

    try:
        response = client.post(f"/api/chat/runs/{run_id}/cancel")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["cancelled"] is True
        assert payload["status"] == "cancel_requested"
        assert cancel_event.is_set() is True
        assert main_app._active_chat_runs[run_id]["accepting_steers"] is False

        status_response = client.get(f"/api/chat/runs/{run_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "cancel_requested"
        assert status_response.json()["terminal"] is False
    finally:
        with main_app._active_chat_runs_lock:
            main_app._active_chat_runs.pop(run_id, None)


def test_queued_chat_run_is_visible_and_cancellable_before_model_start(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    bounded_queue = main_app.AgentRunQueue(max_concurrent_runs=1)
    monkeypatch.setattr(main_app, "run_queue", bounded_queue)
    occupied_ticket = bounded_queue.run_slot("occupied-thread")
    queued = threading.Event()
    finished = threading.Event()
    events: list[dict[str, object]] = []
    result: dict[str, object] = {}

    def progress(payload: dict[str, object]) -> None:
        events.append(dict(payload))
        if payload.get("event") == "run_queued":
            queued.set()

    request = main_app.ChatRequest(
        message="This should be cancelled while queued.",
        client_message_id="queued-user-message",
        settings=main_app.ChatSettings(
            model="gpt-test",
            max_output_tokens=1024,
            max_context_turns=20,
            enable_tools=True,
            response_style="short",
        ),
    )

    def worker() -> None:
        try:
            result["response"] = main_app._process_chat_request(request, progress_cb=progress)
        finally:
            finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert queued.wait(timeout=2)
        queued_payload = next(item for item in events if item.get("event") == "run_queued")
        run_id = str(queued_payload.get("run_id") or "")
        assert run_id
        assert queued_payload["active_count"] == 1
        assert queued_payload["max_concurrent_runs"] == 1
        with main_app._active_chat_runs_lock:
            assert main_app._active_chat_runs[run_id]["status"] == "queued"

        cancelled = main_app.cancel_chat_run(run_id)
        assert cancelled["cancelled"] is True
        assert finished.wait(timeout=2), "queued cancellation should not wait for the occupied slot"

        response = result["response"]
        assert response.turn_status == "cancelled"
        assert response.queue_wait_ms >= 0
        event_names = [str(item.get("event") or "") for item in events]
        assert "run_queued" in event_names
        assert "run_started" not in event_names
        assert "run_finished" in event_names
        assert next(item for item in events if item.get("event") == "run_finished")["turn_status"] == "cancelled"
        loaded = main_app.session_store.load(response.session_id)
        assert loaded is not None
        assert [str(item.get("role") or "") for item in loaded.get("turns") or []][-2:] == ["user", "assistant"]
        assert str((loaded.get("turns") or [])[-1].get("activity", {}).get("status") or "") == "cancelled"
    finally:
        occupied_ticket.release()
        thread.join(timeout=2)


def test_desktop_lifecycle_reports_active_agent_and_eval_work(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)

    class _EvalManager:
        def list(self, *, limit=20):
            assert limit == 100
            return [
                {"id": "eval-running", "status": "running"},
                {"id": "eval-done", "status": "passed"},
            ]

    monkeypatch.setattr(main_app, "_eval_job_manager", _EvalManager())
    run_id = "run-desktop-lifecycle"
    with main_app._active_chat_runs_lock:
        main_app._active_chat_runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "session_id": "thread-1",
            "project_id": "project-1",
        }
    try:
        response = TestClient(main_app.app).get("/api/desktop/lifecycle")
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "active": True,
            "active_runs": [
                {
                    "run_id": run_id,
                    "session_id": "thread-1",
                    "project_id": "project-1",
                    "status": "running",
                }
            ],
            "active_evals": [{"job_id": "eval-running", "status": "running"}],
        }
    finally:
        with main_app._active_chat_runs_lock:
            main_app._active_chat_runs.pop(run_id, None)


def test_chrome_desktop_exit_requires_local_token_and_cancels_active_runs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "desktop-control-token"
    token_path.write_text("desktop-secret-token-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    monkeypatch.setattr(main_app, "DESKTOP_CONTROL_TOKEN_PATH", token_path)
    scheduled: list[list[str]] = []
    monkeypatch.setattr(
        main_app,
        "_schedule_desktop_exit",
        lambda run_ids: scheduled.append(list(run_ids)) or True,
    )
    run_id = "run-desktop-exit"
    cancel_event = threading.Event()
    with main_app._active_chat_runs_lock:
        main_app._active_chat_runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "session_id": "thread-1",
            "project_id": "project-1",
            "cancel_event": cancel_event,
        }
    try:
        with TestClient(main_app.app) as client:
            assert client.post("/api/desktop/exit").status_code == 403
            assert client.post(
                "/api/desktop/exit",
                headers={"X-VP-Desktop-Token": "wrong"},
            ).status_code == 403
            response = client.post(
                "/api/desktop/exit",
                headers={"X-VP-Desktop-Token": "desktop-secret-token-abcdefghijklmnopqrstuvwxyz"},
            )
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "shutdown_scheduled": True,
            "active_count": 1,
            "cancelled_run_count": 1,
        }
        assert scheduled == [[run_id]]
        assert cancel_event.is_set() is True
        with main_app._active_chat_runs_lock:
            assert main_app._active_chat_runs[run_id]["status"] == "cancel_requested"
    finally:
        with main_app._active_chat_runs_lock:
            main_app._active_chat_runs.pop(run_id, None)


def test_cancelled_turn_reaches_terminal_state_before_same_thread_retry_starts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    runtime = _CancellableThenRetryRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    responses: dict[str, object] = {}

    def post_first() -> None:
        with TestClient(main_app.app) as client:
            responses["first"] = client.post(
                "/api/chat/stream",
                json={
                    "message": "first turn",
                    "settings": {"model": "gpt-test", "max_output_tokens": 1024},
                },
            )

    first_thread = threading.Thread(target=post_first)
    first_thread.start()
    assert runtime.first_started.wait(timeout=5.0)
    first_context = runtime.contexts[0]
    first_run_id = str(first_context["run_id"])
    session_id = str(first_context["session_id"])

    with TestClient(main_app.app) as client:
        cancel_payload = client.post(f"/api/chat/runs/{first_run_id}/cancel").json()
    assert cancel_payload["status"] == "cancel_requested"
    assert runtime.first_cancel_seen.wait(timeout=5.0)

    def post_second() -> None:
        with TestClient(main_app.app) as client:
            responses["second"] = client.post(
                "/api/chat/stream",
                json={
                    "session_id": session_id,
                    "message": "second turn",
                    "settings": {"model": "gpt-test", "max_output_tokens": 1024},
                },
            )

    second_thread = threading.Thread(target=post_second)
    second_thread.start()
    time.sleep(0.1)
    assert runtime.second_started.is_set() is False

    runtime.allow_first_return.set()
    first_thread.join(timeout=8.0)
    second_thread.join(timeout=8.0)
    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert runtime.second_started.is_set() is True
    assert len(runtime.contexts) == 2
    assert runtime.contexts[0]["cancel_event"] is not runtime.contexts[1]["cancel_event"]

    first_events = _parse_sse_events(responses["first"].text)
    second_events = _parse_sse_events(responses["second"].text)
    first_final = dict(next(payload for name, payload in first_events if name == "final")["response"])
    second_final = dict(next(payload for name, payload in second_events if name == "final")["response"])
    assert first_final["turn_status"] == "cancelled"
    assert second_final["turn_status"] == "completed"

    second_run_id = str(runtime.contexts[1]["run_id"])
    with TestClient(main_app.app) as client:
        assert client.get(f"/api/chat/runs/{first_run_id}").json()["status"] == "interrupted"
        assert client.get(f"/api/chat/runs/{second_run_id}").json()["status"] == "completed"
    stored = main_app.session_store.load(session_id)
    assert stored is not None
    assert stored.get("pending_interaction") == {}


def test_steer_chat_run_endpoint_queues_and_drains_at_model_boundary(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    run_id = "run-steer-test"
    with main_app._active_chat_runs_lock:
        main_app._active_chat_runs[run_id] = {
            "run_id": run_id,
            "cancel_event": threading.Event(),
            "status": "running",
            "session_id": "s-1",
            "project_id": "project_demo",
            "accepting_steers": True,
            "pending_steers": [],
        }

    try:
        response = client.post(
            f"/api/chat/runs/{run_id}/steer",
            json={"message": "先运行测试，再给结论", "client_steer_id": "steer-client-1"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["id"] == "steer-client-1"

        second_response = client.post(
            f"/api/chat/runs/{run_id}/steer",
            json={"message": "然后检查文档", "client_steer_id": "steer-client-2"},
        )
        assert second_response.status_code == 200
        assert second_response.json()["id"] == "steer-client-2"

        first_drained = main_app._drain_active_chat_run_steers(run_id)
        assert [item["message"] for item in first_drained] == ["先运行测试，再给结论"]
        assert first_drained[0]["accepted_at"] >= first_drained[0]["queued_at"]

        second_drained = main_app._drain_active_chat_run_steers(run_id)
        assert [item["message"] for item in second_drained] == ["然后检查文档"]
        assert second_drained[0]["accepted_at"] >= second_drained[0]["queued_at"]
        assert main_app._drain_active_chat_run_steers(run_id, final=True) == []

        closed = client.post(
            f"/api/chat/runs/{run_id}/steer",
            json={"message": "这条已经太晚"},
        )
        assert closed.status_code == 409
        assert closed.json()["detail"]["kind"] == "turn_not_accepting_guidance"
    finally:
        with main_app._active_chat_runs_lock:
            main_app._active_chat_runs.pop(run_id, None)


def test_eval_background_api_catalog_start_and_status(monkeypatch) -> None:
    class FakeEvalManager:
        def __init__(self) -> None:
            self.submitted = None

        def catalog(self):
            return [{"path": "evals/cases.json", "suite": "cases", "cases": ["subagent"], "case_count": 1}]

        def list(self, *, limit=20):
            _ = limit
            return [{"id": "eval-1", "status": "running", "completed_attempts": 1, "total_attempts": 3}]

        def get(self, job_id):
            return {"id": job_id, "status": "passed"} if job_id == "eval-1" else None

        def submit(self, payload):
            self.submitted = dict(payload)
            return {"id": "eval-2", "status": "queued", "total_attempts": 3}

    manager = FakeEvalManager()
    monkeypatch.setattr(main_app, "_eval_job_manager", manager)
    client = TestClient(main_app.app)

    catalog = client.get("/api/evals/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["suites"][0]["cases"] == ["subagent"]
    runs = client.get("/api/evals/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["status"] == "running"
    started = client.post(
        "/api/evals/runs",
        json={
            "cases": "evals/cases.json",
            "name": "subagent",
            "repeat": 3,
            "provider": "openai_compatible",
            "model": "gpt-test",
            "live": True,
        },
    )
    assert started.status_code == 200
    assert started.json()["status"] == "queued"
    assert manager.submitted["name"] == "subagent"
    assert client.get("/api/evals/runs/eval-1").status_code == 200
    assert client.get("/api/evals/runs/missing").status_code == 404


def test_chat_endpoint_normalizes_provider_errors(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _FailingVintageRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "帮我问一下模型",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 429
    payload = response.json()
    assert payload["detail"]["kind"] == "rate_limit"
    assert payload["detail"]["summary"] == translate("ja-JP", "error.rate_limit")
    assert payload["detail"]["provider"] == "Google AI Studio"
    assert payload["detail"]["retryable"] is True


def test_chat_stream_emits_structured_error_payload(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _FailingVintageRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat/stream",
        json={
            "message": "流式失败场景",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    run_failed_payload = next(payload for name, payload in events if name == "run_failed")
    assert run_failed_payload["run_id"]
    error_payload = next(payload for name, payload in events if name == "error")
    assert error_payload["status_code"] == 429
    assert error_payload["kind"] == "rate_limit"
    assert error_payload["summary"] == translate("ja-JP", "error.rate_limit")
    assert error_payload["provider"] == "Google AI Studio"
    assert error_payload["retryable"] is True


def test_chat_endpoint_persists_failed_runtime_result_without_promoting_diagnostics(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    runtime = _FailedResultVintageRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "继续处理这个任务",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turn_status"] == "failed"
    assert payload["final_answer"] == ""
    assert payload["model_draft"] == "I already inspected the skill files and was preparing the summary."
    assert payload["runtime_error"]["kind"] == "llm_empty_response"
    assert "model_dump" not in payload["text"]

    session_id = payload["session_id"]
    session = main_app.session_store.load(session_id, default_project=main_app.project_store.ensure_default_project())
    assert session is not None
    last_turn = session["turns"][-1]
    assert last_turn["role"] == "assistant"
    assert last_turn["text"] == payload["text"]
    assert last_turn["activity"]["status"] == "failed"
    assert last_turn["activity"]["trace_ref"]
    assert "runtime_error" not in last_turn["activity"]
    assert "model_draft" not in last_turn["activity"]
    assert "llm_exchanges" not in last_turn["activity"]
    activity_response = client.get(f"/api/thread/{session_id}/turn/{last_turn['id']}?view=activity")
    assert activity_response.status_code == 200
    assert activity_response.json()["activity"]["runtime_outcome"] == {
        "status": "failed",
        "error_kind": "llm_empty_response",
        "error_message": payload["runtime_error"]["message"],
    }
    full_response = client.get(f"/api/thread/{session_id}/turn/{last_turn['id']}?view=full")
    assert full_response.status_code == 200
    full_turn = full_response.json()
    assert full_turn["activity"]["turn_trace"]["terminal"]["error_kind"] == "llm_empty_response"
    assert full_turn["activity"]["turn_trace"]["steps"][-1]["type"] == "model_failed"
    assert payload["inspector"]["run_state"]["llm_exchanges"] == payload["activity"]["llm_exchanges"]

    assert all("model_dump" not in str(item.get("content") or "") for item in session["thread_transcript"]["items"])
    assert all("llm_exchanges" not in str(item or "") for item in session["thread_transcript"]["items"])


def test_chat_endpoint_ignores_legacy_task_state_and_delta_payloads(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _DeltaTaskStateRuntime())
    client = TestClient(main_app.app)

    delta_calls = {"count": 0}
    fallback_calls = {"count": 0}
    original_delta = main_app.session_context_impl.merge_task_state_delta
    original_fallback = main_app.session_context_impl.merge_task_state_after_turn

    def _spy_delta(*args, **kwargs):
        delta_calls["count"] += 1
        return original_delta(*args, **kwargs)

    def _spy_fallback(*args, **kwargs):
        fallback_calls["count"] += 1
        return original_fallback(*args, **kwargs)

    monkeypatch.setattr(main_app.session_context_impl, "merge_task_state_delta", _spy_delta)
    monkeypatch.setattr(main_app.session_context_impl, "merge_task_state_after_turn", _spy_fallback)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    session["task_state"] = main_app.session_context_impl.normalize_task_state(
        {
            "task_id": "task-delta",
            "goal": "Patch validator",
            "status": "in_progress",
            "plan_items": [
                {"id": "step-1", "step": "Patch task_state merge", "status": "in_progress"},
                {"id": "step-2", "step": "Run focused tests", "status": "pending"},
            ],
        }
    )
    main_app.session_store.save(session)

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "继续修 task_state",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert delta_calls["count"] == 0
    assert fallback_calls["count"] == 0
    assert payload.get("task_state") == {}
    assert "task_state_delta" not in payload
    assert payload["plan"][0]["status"] == "in_progress"

    saved = main_app.session_store.load(session["id"], default_project=main_app.project_store.ensure_default_project())
    assert saved is not None
    assert "task_state" not in saved
    assistant_turn = saved["turns"][-1]
    full_turn_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=full")
    assert full_turn_response.status_code == 200
    full_turn = full_turn_response.json()
    assert "task_state" not in full_turn["activity"]["turn_trace"]
    assert "task_state_delta" not in full_turn["activity"]["turn_trace"]


def test_chat_endpoint_does_not_run_after_turn_task_merge(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _NoDeltaTaskStateRuntime())
    client = TestClient(main_app.app)

    delta_calls = {"count": 0}
    fallback_calls = {"count": 0}
    original_delta = main_app.session_context_impl.merge_task_state_delta
    original_fallback = main_app.session_context_impl.merge_task_state_after_turn

    def _spy_delta(*args, **kwargs):
        delta_calls["count"] += 1
        return original_delta(*args, **kwargs)

    def _spy_fallback(*args, **kwargs):
        fallback_calls["count"] += 1
        return original_fallback(*args, **kwargs)

    monkeypatch.setattr(main_app.session_context_impl, "merge_task_state_delta", _spy_delta)
    monkeypatch.setattr(main_app.session_context_impl, "merge_task_state_after_turn", _spy_fallback)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    session["task_state"] = main_app.session_context_impl.normalize_task_state(
        {
            "task_id": "task-fallback",
            "goal": "Inspect workspace",
            "status": "in_progress",
            "plan_items": [{"id": "step-10", "step": "Inspect workspace", "status": "in_progress"}],
        }
    )
    main_app.session_store.save(session)

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "继续",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert delta_calls["count"] == 0
    assert fallback_calls["count"] == 0
    assert "task_state_delta" not in payload
    assert payload.get("task_state") == {}
    assert payload["plan"] == [{"step": "Inspect workspace", "status": "completed"}]


def test_chat_greeting_does_not_enter_task_mode_without_update_plan(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _DirectAnswerNoTaskRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "你好",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("task_state") == {}
    session = main_app.session_store.load(payload["session_id"], default_project=main_app.project_store.ensure_default_project())
    assert session is not None
    assert "task_state" not in session


def test_chat_tool_evidence_alone_does_not_create_task_state(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _ToolEvidenceOnlyRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "解释一下这个仓库",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_events"]
    assert payload.get("task_state") == {}


def test_chat_discards_legacy_task_state_in_favor_of_thread_history(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _DirectAnswerNoTaskRuntime())
    client = TestClient(main_app.app)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    session["task_state"] = main_app.session_context_impl.normalize_task_state(
        {
            "task_id": "task-existing",
            "goal": "Fix update_plan schema",
            "status": "in_progress",
            "plan_items": [{"id": "step-1", "step": "Inspect schema", "status": "in_progress"}],
            "updated_at": "2026-06-01T00:00:00Z",
        }
    )
    main_app.session_store.save(session)

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "谢谢",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("task_state") == {}
    saved = main_app.session_store.load(session["id"], default_project=main_app.project_store.ensure_default_project())
    assert saved is not None
    assert "task_state" not in saved


def test_chat_continue_request_does_not_use_legacy_task_goal_heuristics(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _DirectAnswerNoTaskRuntime())
    client = TestClient(main_app.app)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    session["task_state"] = main_app.session_context_impl.normalize_task_state(
        {
            "task_id": "task-continue",
            "goal": "Fix update_plan schema",
            "status": "in_progress",
            "plan_items": [{"id": "step-1", "step": "Inspect schema", "status": "in_progress"}],
        }
    )
    main_app.session_store.save(session)

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "继续",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("task_state") == {}
    assert payload["text"] == "echo:继续"


def test_chat_successful_update_plan_stays_run_scoped(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _UpdatePlanCreatesTaskRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "修复 update_plan schema 和 task_state 对齐问题",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("task_state") == {}
    assert len(payload["plan"]) == 3
    saved = main_app.session_store.load(payload["session_id"])
    assert saved is not None
    assert "task_state" not in saved


def test_chat_passes_thread_transcript_without_legacy_memory_state(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    capture_runtime = _ContextCapturingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", capture_runtime)
    client = TestClient(main_app.app)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    main_app.session_store.append_turn(session, role="user", text="先看一下这个仓库")
    main_app.session_store.append_turn(session, role="assistant", text="我已经看过仓库")
    main_app.session_store.save(session)

    response = client.post(
        "/api/chat",
        json={
            "session_id": session["id"],
            "message": "帮我看个代码",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    seen = capture_runtime.seen_contexts[0]
    assert seen["summary"] == ""
    assert [item["content"] for item in dict(seen["thread_transcript"])["items"]] == [
        "先看一下这个仓库",
        "我已经看过仓库",
    ]
    for removed_key in (
        "history_turns", "thread_memory", "current_turn", "recent_user_messages",
        "active_task_focus", "current_task_focus", "work_cursor", "task_state",
        "recent_tasks", "artifact_memory_preview", "recalled_context",
    ):
        assert removed_key not in seen


def test_chat_stream_persists_latest_user_turn_before_runtime_completes(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    runtime = _BlockingVintageRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    client = TestClient(main_app.app)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    response_holder: dict[str, object] = {}

    def _run_stream() -> None:
        response_holder["response"] = client.post(
            "/api/chat/stream",
            json={
                "session_id": session["id"],
                "message": "题目",
                "settings": {
                    "model": "gpt-test",
                    "max_output_tokens": 1024,
                    "max_context_turns": 20,
                    "enable_tools": True,
                    "response_style": "short",
                },
            },
        )

    worker = threading.Thread(target=_run_stream, daemon=True)
    worker.start()
    assert runtime.started.wait(timeout=2.0) is True

    detail_response = client.get(f"/api/thread/{session['id']}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert any(item["role"] == "user" and item["text"] == "题目" for item in detail_payload["turns"])

    runtime.release.set()
    worker.join(timeout=5.0)
    response = response_holder.get("response")
    assert response is not None
    assert response.status_code == 200


def test_chat_followup_short_message_is_persisted_and_visible_in_context(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    runtime = _FollowupContextRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", runtime)
    client = TestClient(main_app.app)

    first = client.post(
        "/api/chat",
        json={
            "message": "日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]

    second = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "题目",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert second.status_code == 200
    assert second.json()["text"] == "件名：明日の会議時間変更のお願い"
    assert runtime.calls[1]["recent_user_messages"] == ["日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。"]

    third = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "刚刚我问你什么了",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert third.status_code == 200
    assert third.json()["text"] == "你刚刚问的是“题目”。"
    assert runtime.calls[2]["recent_user_messages"][-1] == "题目"

    fourth = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "我刚才问你的所有问题，罗列一下",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )
    assert fourth.status_code == 200
    assert fourth.json()["text"] == "\n".join(
        [
            "1. 日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。",
            "2. 题目",
            "3. 刚刚我问你什么了",
        ]
    )
    assert runtime.calls[3]["recent_user_messages"] == [
        "日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。",
        "题目",
        "刚刚我问你什么了",
    ]

    detail_response = client.get(f"/api/thread/{session_id}")
    assert detail_response.status_code == 200
    turns = detail_response.json()["turns"]
    assert [(item["role"], item["text"]) for item in turns[-8:]] == [
        ("user", "日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。"),
        ("assistant", "お世話になっております。\n\n明日の会議ですが、10時から11時に変更させていただけますでしょうか。\n\nよろしくお願いいたします。"),
        ("user", "题目"),
        ("assistant", "件名：明日の会議時間変更のお願い"),
        ("user", "刚刚我问你什么了"),
        ("assistant", "你刚刚问的是“题目”。"),
        ("user", "我刚才问你的所有问题，罗列一下"),
        ("assistant", "1. 日语で丁寧なメールを書いて。内容は、明日の会議を10時から11時に変更したいです。\n2. 题目\n3. 刚刚我问你什么了"),
    ]
    assert runtime.calls[1]["message"] == "题目"
    assert runtime.calls[1]["history_turns"][-1]["role"] == "assistant"
    assert runtime.calls[2]["message"] == "刚刚我问你什么了"
    assert runtime.calls[2]["history_turns"][-2] == {"role": "user", "text": "题目"}
    assert runtime.calls[2]["history_turns"][-1] == {"role": "assistant", "text": "件名：明日の会議時間変更のお願い"}
    assert runtime.calls[3]["message"] == "我刚才问你的所有问题，罗列一下"
    subject_assistant_turn = turns[-5]
    assert subject_assistant_turn["role"] == "assistant"
    assert "triggering_user_message" not in subject_assistant_turn["activity"]
    full_subject_response = client.get(f"/api/thread/{session_id}/turn/{subject_assistant_turn['id']}?view=full")
    assert full_subject_response.status_code == 200
    full_subject_activity = full_subject_response.json()["activity"]
    assert any(
        item.get("role") == "user" and item.get("content") == "题目"
        for item in full_subject_activity["thread_items"]
    )
    assert "current_turn_goal" not in full_subject_activity
    assert "current_turn_followup_type" not in full_subject_activity
    assert "active_task_focus" not in full_subject_activity
    assert "recent_user_messages" not in full_subject_activity


def test_assistant_activity_exposes_triggering_user_message(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _FollowupContextRuntime())
    client = TestClient(main_app.app)

    response = client.post(
        "/api/chat",
        json={
            "message": "题目",
            "settings": {
                "model": "gpt-test",
                "max_output_tokens": 1024,
                "max_context_turns": 20,
                "enable_tools": True,
                "response_style": "short",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turn_id"]
    assert payload["activity"]["triggering_user_message"] == "题目"
    assert payload["activity"]["triggering_user_turn_id"]
    assert "current_turn_goal" not in payload["activity"]
    assert "active_task_focus" not in payload["activity"]
    assert "recent_user_messages" not in payload["activity"]

    direct_full_response = client.get(f"/api/thread/{payload['session_id']}/turn/{payload['turn_id']}?view=full")
    assert direct_full_response.status_code == 200

    detail_response = client.get(f"/api/thread/{payload['session_id']}")
    assert detail_response.status_code == 200
    assistant_turn = detail_response.json()["turns"][-1]
    assert assistant_turn["role"] == "assistant"
    assert "triggering_user_message" not in assistant_turn["activity"]
    full_response = client.get(f"/api/thread/{payload['session_id']}/turn/{assistant_turn['id']}?view=full")
    assert full_response.status_code == 200
    full_activity = full_response.json()["activity"]
    assert any(
        item.get("role") == "user" and item.get("content") == "题目"
        for item in full_activity["thread_items"]
    )
    assert "current_turn_goal" not in full_activity


def test_project_endpoints_and_project_scoped_sessions(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    create_a = client.post("/api/projects", json={"root_path": str(repo_a), "title": "Repo A"})
    create_b = client.post("/api/projects", json={"root_path": str(repo_b), "title": "Repo B"})
    assert create_a.status_code == 200
    assert create_b.status_code == 200
    project_a = create_a.json()["project_id"]
    project_b = create_b.json()["project_id"]
    assert create_a.json()["profile_key"] == ""
    assert create_a.json()["profile_available"] is False

    profiles = client.get("/api/project-profiles")
    assert profiles.status_code == 200
    assert "builtin:vintage-programmer" in {
        item["profile_key"] for item in profiles.json()["profiles"]
    }

    invalid_profile = client.put(
        f"/api/projects/{project_b}/profile",
        json={"profile_key": "team:missing"},
    )
    assert invalid_profile.status_code == 400

    bind_profile = client.put(
        f"/api/projects/{project_b}/profile",
        json={"profile_key": "builtin:vintage-programmer"},
    )
    assert bind_profile.status_code == 200
    assert bind_profile.json()["profile_key"] == "builtin:vintage-programmer"
    assert bind_profile.json()["profile_display_name"] == "Vintage Programmer"
    assert bind_profile.json()["profile_available"] is True

    unbind_profile = client.put(
        f"/api/projects/{project_b}/profile",
        json={"profile_key": ""},
    )
    assert unbind_profile.status_code == 200
    assert unbind_profile.json()["profile_key"] == ""
    assert unbind_profile.json()["profile_available"] is False

    session_a = client.post("/api/session/new", json={"project_id": project_a})
    session_b = client.post("/api/session/new", json={"project_id": project_b})
    assert session_a.status_code == 200
    assert session_b.status_code == 200
    session_a_id = session_a.json()["session_id"]
    session_b_id = session_b.json()["session_id"]

    list_a = client.get(f"/api/sessions?project_id={project_a}")
    list_b = client.get(f"/api/sessions?project_id={project_b}")
    assert list_a.status_code == 200
    assert list_b.status_code == 200
    assert all(item["project_id"] == project_a for item in list_a.json()["sessions"])
    assert all(item["project_id"] == project_b for item in list_b.json()["sessions"])

    duplicate = client.post("/api/projects", json={"root_path": str(repo_a)})
    assert duplicate.status_code == 409

    delete_a = client.delete(f"/api/projects/{project_a}")
    assert delete_a.status_code == 200
    assert delete_a.json()["ok"] is True
    assert delete_a.json()["project_id"] == project_a
    assert delete_a.json()["deleted_session_count"] == 1

    projects_after_delete = client.get("/api/projects")
    assert projects_after_delete.status_code == 200
    assert project_a not in {item["project_id"] for item in projects_after_delete.json()["projects"]}
    assert project_b in {item["project_id"] for item in projects_after_delete.json()["projects"]}

    session_a_after_delete = client.get(f"/api/session/{session_a_id}")
    session_b_after_delete = client.get(f"/api/session/{session_b_id}")
    assert session_a_after_delete.status_code == 404
    assert session_b_after_delete.status_code == 200

    list_a_after_delete = client.get(f"/api/sessions?project_id={project_a}")
    list_b_after_delete = client.get(f"/api/sessions?project_id={project_b}")
    assert list_a_after_delete.status_code == 200
    assert list_b_after_delete.status_code == 200
    assert list_a_after_delete.json()["sessions"] == []
    assert all(item["project_id"] == project_b for item in list_b_after_delete.json()["sessions"])

    default_project_id = client.get("/api/bootstrap").json()["default_project_id"]
    delete_default = client.delete(f"/api/projects/{default_project_id}")
    assert delete_default.status_code == 400

    delete_missing = client.delete("/api/projects/project_missing")
    assert delete_missing.status_code == 404


def test_workbench_endpoints_list_and_edit_local_skills(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    tools_response = client.get("/api/workbench/tools")
    assert tools_response.status_code == 200
    tool_rows = tools_response.json()["tools"]
    assert tool_rows[0]["name"]
    assert all(item["source"] != "legacy_retained" for item in tool_rows)
    assert {"control", "shell", "edit", "file", "document", "web", "session", "media", "archive"}.issubset(
        {item["group"] for item in tool_rows}
    )
    assert "image_inspect" in {item["name"] for item in tool_rows}
    assert "read_file" in {item["name"] for item in tool_rows}
    assert {"web_download", "image_read", "list_dir", "glob_file_search", "search_contents_in_file_multi", "read_section", "table_extract", "fact_check_file"}.issubset(
        {item["name"] for item in tool_rows}
    )

    skills_response = client.get("/api/workbench/skills")
    assert skills_response.status_code == 200
    assert skills_response.json()["skills"][0]["id"] == "example_refactor_helper"
    assert skills_response.json()["skills"][0]["content"] == ""

    create_response = client.post(
        "/api/workbench/skills",
        json={
            "content": "---\nname: repo_triage\ndescription: triage skill\nenabled: false\n---\n\n# Repo Triage\n"
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["id"] == "repo_triage"

    toggle_response = client.post("/api/workbench/skills/repo_triage/toggle", json={"enabled": True})
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is True

    delete_response = client.delete("/api/workbench/skills/repo_triage")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True, "skill_id": "repo_triage"}

    after_delete = client.get("/api/workbench/skills")
    assert after_delete.status_code == 200
    assert "repo_triage" not in {item["id"] for item in after_delete.json()["skills"]}


def test_workbench_skill_endpoints_include_read_only_builtin_skills(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    builtin_skill_dir = tmp_path / "skills" / "builtin" / "system_helper"
    builtin_skill_dir.mkdir(parents=True, exist_ok=True)
    (builtin_skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: system_helper\n"
        "description: built in helper\n"
        "enabled: true\n"
        "---\n\n"
        "# System Helper\n",
        encoding="utf-8",
    )
    client = TestClient(main_app.app)

    skills_response = client.get("/api/workbench/skills")
    assert skills_response.status_code == 200
    builtin_entry = next(item for item in skills_response.json()["skills"] if item["key"] == "builtin:system_helper")
    assert builtin_entry["read_only"] is True
    assert builtin_entry["content"] == ""

    detail_response = client.get("/api/workbench/skills/system_helper?scope=builtin")
    assert detail_response.status_code == 200
    assert "# System Helper" in detail_response.json()["content"]

    legacy_alias_response = client.get("/api/workbench/skills/system_helper?scope=system")
    assert legacy_alias_response.status_code == 200
    assert legacy_alias_response.json()["key"] == "builtin:system_helper"

    update_response = client.put(
        "/api/workbench/skills/system_helper?scope=builtin",
        json={"content": "---\nname: system_helper\ndescription: x\nenabled: true\n---\n\n# X\n"},
    )
    assert update_response.status_code == 403

    delete_response = client.delete("/api/workbench/skills/system_helper?scope=builtin")
    assert delete_response.status_code == 403


def test_workbench_specs_endpoint_reads_and_writes_agent_specs(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)
    localized_dir = tmp_path / "agents" / "vintage_programmer" / "locales" / "ja-JP"
    localized_dir.mkdir(parents=True, exist_ok=True)
    (localized_dir / "agent.md").write_text("---\nid: vintage_programmer\n---\nja-agent", encoding="utf-8")

    specs_response = client.get("/api/workbench/specs", params={"locale": "ja-JP"})
    assert specs_response.status_code == 200
    specs_payload = specs_response.json()["specs"]
    agent_row = next(item for item in specs_payload if item["name"] == "agent.md")
    tools_row = next(item for item in specs_payload if item["name"] == "tools.md")
    assert agent_row["locale"] == "ja-JP"
    assert agent_row["fallback_from_base"] is False
    assert Path(agent_row["path"]) == localized_dir / "agent.md"
    assert Path(agent_row["resolved_path"]) == localized_dir / "agent.md"
    assert tools_row["locale"] == "ja-JP"
    assert tools_row["fallback_from_base"] is True
    assert Path(tools_row["path"]) == localized_dir / "tools.md"
    assert Path(tools_row["resolved_path"]) == tmp_path / "agents" / "vintage_programmer" / "tools.md"

    spec_response = client.get("/api/workbench/specs/agent.md", params={"locale": "ja-JP"})
    assert spec_response.status_code == 200
    assert "ja-agent" in spec_response.json()["content"]
    assert spec_response.json()["fallback_from_base"] is False

    fallback_response = client.get("/api/workbench/specs/tools.md", params={"locale": "ja-JP"})
    assert fallback_response.status_code == 200
    assert fallback_response.json()["fallback_from_base"] is True
    assert fallback_response.json()["content"] == "tools"

    update_response = client.put(
        "/api/workbench/specs/tools.md?locale=ja-JP",
        json={"content": "# Tools\n\nupdated"},
    )
    assert update_response.status_code == 200
    assert "updated" in update_response.json()["content"]
    assert Path(update_response.json()["path"]) == localized_dir / "tools.md"
    assert Path(update_response.json()["resolved_path"]) == localized_dir / "tools.md"
    assert update_response.json()["fallback_from_base"] is False
    assert (localized_dir / "tools.md").read_text(encoding="utf-8") == "# Tools\n\nupdated"
    assert (tmp_path / "agents" / "vintage_programmer" / "tools.md").read_text(encoding="utf-8") == "tools"

    base_response = client.get("/api/workbench/specs/tools.md", params={"locale": "zh-CN"})
    assert base_response.status_code == 200
    assert base_response.json()["content"] == "tools"
    assert base_response.json()["fallback_from_base"] is True
    assert Path(base_response.json()["path"]) == tmp_path / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md"
    assert Path(base_response.json()["resolved_path"]) == tmp_path / "agents" / "vintage_programmer" / "tools.md"

    zh_update_response = client.put(
        "/api/workbench/specs/tools.md?locale=zh-CN",
        json={"content": "# 中文工具\n\nupdated"},
    )
    assert zh_update_response.status_code == 200
    assert Path(zh_update_response.json()["path"]) == tmp_path / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md"
    assert Path(zh_update_response.json()["resolved_path"]) == tmp_path / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md"
    assert zh_update_response.json()["fallback_from_base"] is False
    assert (tmp_path / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md").read_text(encoding="utf-8") == "# 中文工具\n\nupdated"
    assert (tmp_path / "agents" / "vintage_programmer" / "tools.md").read_text(encoding="utf-8") == "tools"
