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


class _FollowupContextRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, *, message, settings, context, progress_cb=None):
        history_turns = list(context.get("history_turns") or [])
        current_turn = dict(context.get("current_turn") or {})
        active_task_focus = dict(context.get("active_task_focus") or context.get("current_task_focus") or {})
        recent_user_messages = [str(item or "") for item in list(context.get("recent_user_messages") or []) if str(item or "").strip()]
        self.calls.append(
            {
                "message": str(message or ""),
                "current_turn": dict(current_turn),
                "active_task_focus": dict(active_task_focus),
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
        goal = str(current_turn.get("goal") or active_task_focus.get("goal") or current).strip()
        followup_type = str(current_turn.get("followup_type") or "").strip()
        if current == "题目" and followup_type == "subject_request":
            text = "件名：明日の会議時間変更のお願い"
        elif current == "题目":
            text = (
                "当然，下面是一封自然、简洁的请假邮件：\n\n"
                "お世話になっております。\n\n"
                "明日は検査のため、一日お休みをいただきたく存じます。\n\n"
                "よろしくお願いいたします。"
            )
        elif current == "刚刚我问你什么了" and followup_type == "recent_user_message_recall":
            recalled = recent_user_messages[-1] if recent_user_messages else latest_previous_user
            text = f"你刚刚问的是“{recalled}”。"
        elif current == "刚刚我问你什么了":
            text = f"你刚刚问的是“{goal}”。"
        elif current == "我刚才问你的所有问题，罗列一下" and followup_type == "recent_user_messages_list":
            text = "\n".join(f"{index + 1}. {entry}" for index, entry in enumerate(recent_user_messages))
        elif current == "我刚才问你的所有问题，罗列一下":
            text = goal
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
            "current_turn_followup_type": followup_type,
            "active_task_focus": dict(active_task_focus),
            "recent_user_messages": list(recent_user_messages),
        }
        payload["inspector"] = {
            **dict(payload.get("inspector") or {}),
            "run_state": {
                **dict(((payload.get("inspector") or {}).get("run_state") or {})),
                "goal": goal,
                "current_turn": dict(current_turn),
                "active_task_focus": dict(active_task_focus),
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
    monkeypatch.setattr(main_app, "session_store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(main_app, "upload_store", UploadStore(tmp_path / "uploads"))
    monkeypatch.setattr(main_app, "token_stats_store", TokenStatsStore(tmp_path / "token_stats.json"))
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
    assert runtime_payload["runtime_status"]["loop_safeguards"]["max_turn_seconds"] > 0
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

    list_response = client.get(f"/api/threads?project_id={bootstrap_payload['default_project_id']}")
    assert list_response.status_code == 200
    thread_ids = {item["thread_id"] for item in list_response.json()["threads"]}
    assert thread_id in thread_ids

    delete_response = client.delete(f"/api/thread/{thread_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True, "thread_id": thread_id, "session_id": thread_id}

    detail_after_delete = client.get(f"/api/thread/{thread_id}")
    assert detail_after_delete.status_code == 404


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
    original_load = main_app.session_store.run_artifact_store.load
    original_load_by_ref = main_app.session_store.run_artifact_store.load_by_ref

    def _load_by_ref(trace_ref: str):
        calls["load_by_ref"] += 1
        return original_load_by_ref(trace_ref)

    def _load(*, session_id: str, run_id: str):
        calls["load"] += 1
        return original_load(session_id=session_id, run_id=run_id)

    monkeypatch.setattr(main_app.session_store.run_artifact_store, "load_by_ref", _load_by_ref)
    monkeypatch.setattr(main_app.session_store.run_artifact_store, "load", _load)

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
    }
    assert "triggering_user_message" not in summary_turn["activity"]
    assert "llm_exchanges" not in summary_turn["activity"]
    assert "answer_bundle" not in summary_turn
    assert "run_artifact" not in summary_turn

    full_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=full")

    assert full_response.status_code == 200
    assert calls["load_by_ref"] == 1
    assert calls["load"] == 1
    full_turn = full_response.json()
    assert full_turn["answer_bundle"]["summary"] == "done"
    assert full_turn["activity"]["llm_exchanges"][0]["round"] == 1
    assert full_turn["run_artifact"]["run_id"] == "run-1"


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
    original_body = session_path.read_text(encoding="utf-8")

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
    assert session_path.read_text(encoding="utf-8") == original_body


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
    assert session_payload["agent_state"]["phase"] == "completed"
    assert session_payload["agent_state"]["permission_profile"] == "auto"
    assert session_payload["agent_state"]["turn_status"] == "completed"
    assert session_payload["agent_state"]["evidence_status"] == "collected"
    assert session_payload["agent_state"]["enabled_skill_ids"] == ["example-refactor-helper"]
    assert session_payload["agent_state"]["task_checkpoint"]["task_id"] == "task-fake-1"
    assert session_payload["agent_state"]["context_meter"]["auto_compact_token_limit"] > 0
    assert session_payload["agent_state"]["compaction_status"]["mode"] == "token_budget"
    assert session_payload["context_meter"]["auto_compact_token_limit"] > 0
    assert session_payload["compaction_status"]["mode"] == "token_budget"


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
    assert loaded["compaction_state"]["last_compaction_phase"] == "pre_turn"
    assert loaded["compaction_state"]["reason"] in {
        "context_auto_limit",
        "context_danger_limit",
        "history_soft_limit",
    }
    assert loaded["compaction_state"]["compaction_source"] == "deterministic_fallback"
    assert loaded["compaction_state"]["after_tokens"] > 0
    assert len(loaded["compaction_state"]["retained_turn_ids"]) <= 12

    assert capture_runtime.seen_contexts
    seen = capture_runtime.seen_contexts[0]
    assert seen["summary"] == loaded["compaction_state"]["compacted_history"]
    assert seen["compaction_status"]["generation"] == loaded["compaction_state"]["generation"]
    assert seen["compaction_status"]["last_compaction_phase"] == "pre_turn"
    assert seen["compaction_status"]["reason"] == loaded["compaction_state"]["reason"]
    assert seen["compaction_status"]["compaction_source"] == "deterministic_fallback"
    assert 1 <= len(seen["history_turns"]) <= 12
    assert all(turn["text"] != "继续总结" for turn in seen["history_turns"])
    seen_transcript = list(dict(seen["thread_transcript"]).get("items") or [])
    assert seen_transcript
    assert all(item["content"] != "继续总结" for item in seen_transcript)


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
    assert response_payload["activity"]["final_elapsed_ms"] == phase_timings["total_ms"]
    assert run_finished_payload["duration_ms"] == response_payload["activity"]["run_duration_ms"]


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
        assert payload["status"] == "cancelling"
        assert cancel_event.is_set() is True
        assert main_app._active_chat_runs[run_id]["accepting_steers"] is False
    finally:
        with main_app._active_chat_runs_lock:
            main_app._active_chat_runs.pop(run_id, None)


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

        drained = main_app._drain_active_chat_run_steers(run_id)
        assert [item["message"] for item in drained] == ["先运行测试，再给结论"]
        assert drained[0]["accepted_at"] >= drained[0]["queued_at"]
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
    full_response = client.get(f"/api/thread/{session_id}/turn/{last_turn['id']}?view=full")
    assert full_response.status_code == 200
    full_turn = full_response.json()
    assert full_turn["activity"]["runtime_error"]["kind"] == "llm_empty_response"
    assert full_turn["activity"]["model_draft"] == payload["model_draft"]
    assert len(full_turn["activity"]["llm_exchanges"]) == 2
    assert full_turn["activity"]["llm_exchanges"][-1]["error"]["kind"] == "llm_empty_response"
    assert full_turn["run_artifact"]["inspector"]["run_state"]["llm_exchanges"] == full_turn["activity"]["llm_exchanges"]
    assert payload["inspector"]["run_state"]["llm_exchanges"] == payload["activity"]["llm_exchanges"]

    clean_turns = list(((session.get("context_manager") or {}).get("clean_turns")) or [])
    assert all("model_dump" not in str((turn or {}).get("text") or "") for turn in clean_turns)
    assert all("llm_exchanges" not in str(turn or "") for turn in clean_turns)


def test_chat_endpoint_keeps_task_state_canonical_on_update_plan_without_delta_merge(monkeypatch, tmp_path: Path) -> None:
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
    assert payload["task_state_delta"]["next_required_action"] == "Run focused tests"
    assert payload["task_state"]["task_id"] != "wrong-task"
    assert payload["task_state"]["completed_steps"] == []
    assert payload["task_state"]["progress_basis"] == []
    assert payload["task_state"]["next_required_action"] == ""
    assert payload["task_state"]["plan_items"][0]["status"] == "in_progress"
    assert "task_state_validation" not in payload

    saved = main_app.session_store.load(session["id"], default_project=main_app.project_store.ensure_default_project())
    assert saved is not None
    assert saved["task_state"]["completed_steps"] == []
    assert saved["task_state"]["task_id"] != "wrong-task"
    assert saved["task_state"]["progress_basis"] == []
    assert saved["task_state"]["next_required_action"] == ""
    assistant_turn = saved["turns"][-1]
    full_turn_response = client.get(f"/api/thread/{session['id']}/turn/{assistant_turn['id']}?view=full")
    assert full_turn_response.status_code == 200
    full_turn = full_turn_response.json()
    assert full_turn["run_artifact"]["task_state"]["completed_steps"] == []
    assert full_turn["run_artifact"]["task_state_delta"]["next_required_action"] == "Run focused tests"
    assert "task_state_validation" not in full_turn["run_artifact"]
    assert full_turn["run_artifact"]["inspector"]["run_state"]["task_state_delta"]["next_required_action"] == "Run focused tests"


def test_chat_endpoint_falls_back_to_after_turn_merge_when_no_delta(monkeypatch, tmp_path: Path) -> None:
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
    assert fallback_calls["count"] == 1
    assert "task_state_delta" not in payload
    assert payload["task_state"]["task_id"] != "wrong-task"
    assert payload["task_state"]["completed_steps"][-1]["step"] == "Inspect workspace"
    assert "task_state_validation" not in payload


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
    assert payload["task_state"]["goal"] == ""
    assert payload["task_state"]["status"] == "idle"
    assert payload["task_state"]["plan_items"] == []
    assert "task_state_validation" not in payload
    session = main_app.session_store.load(payload["session_id"], default_project=main_app.project_store.ensure_default_project())
    assert session is not None
    assert session["task_state"]["goal"] == ""
    assert session["task_state"]["status"] == "idle"


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
    assert payload["task_state"]["goal"] == ""
    assert payload["task_state"]["status"] == "idle"
    assert "task_state_validation" not in payload


def test_chat_simple_chat_does_not_overwrite_existing_task_state(monkeypatch, tmp_path: Path) -> None:
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
    assert payload["task_state"]["goal"] == "Fix update_plan schema"
    assert payload["task_state"]["updated_at"] == "2026-06-01T00:00:00Z"
    assert "task_state_validation" not in payload
    saved = main_app.session_store.load(session["id"], default_project=main_app.project_store.ensure_default_project())
    assert saved is not None
    assert saved["task_state"]["goal"] == "Fix update_plan schema"
    assert saved["task_state"]["updated_at"] == "2026-06-01T00:00:00Z"


def test_chat_continue_like_request_inherits_previous_task_goal(monkeypatch, tmp_path: Path) -> None:
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
    assert payload["task_state"]["goal"] == "Fix update_plan schema"
    assert payload["task_state"]["goal"] != "继续"


def test_chat_successful_update_plan_creates_task_state(monkeypatch, tmp_path: Path) -> None:
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
    assert payload["task_state"]["task_id"]
    assert payload["task_state"]["goal"] in {
        "This is a multi-step code change, so a plan is useful.",
        "Fix update_plan schema",
    }
    assert len(payload["task_state"]["plan_items"]) == 3
    assert payload["task_state"]["status"] == "in_progress"


def test_chat_preserves_thread_memory_for_new_turn(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    capture_runtime = _ContextCapturingRuntime()
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", capture_runtime)
    client = TestClient(main_app.app)

    session = main_app.session_store.create(main_app.project_store.ensure_default_project())
    session["summary"] = "old summary"
    session["turns"] = [
        {"role": "user", "text": "先看一下这个仓库", "attachments": [], "answer_bundle": {}, "created_at": "2026-04-20T00:00:00Z"},
        {"role": "assistant", "text": "我已经看过仓库", "attachments": [], "answer_bundle": {}, "created_at": "2026-04-20T00:00:01Z"},
    ]
    session["route_state"] = {
        "task_checkpoint": {
            "task_id": "task-old",
            "goal": "Inspect old task",
            "project_root": str(tmp_path),
            "cwd": str(tmp_path),
            "active_files": [str(tmp_path / "old.py")],
            "active_attachments": [],
            "last_completed_step": "read_file: old.py",
            "next_action": "modify old.py",
        }
    }
    session["agent_state"]["task_checkpoint"] = dict(session["route_state"]["task_checkpoint"])
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
    assert seen["summary"] == "old summary"
    assert len(seen["history_turns"]) == 2
    assert seen["thread_memory"]["summary"] == "old summary"
    assert [item["content"] for item in dict(seen["thread_transcript"])["items"]] == [
        "先看一下这个仓库",
        "我已经看过仓库",
    ]
    assert seen["current_task_focus"]["task_id"] == ""
    assert seen["route_state"]["task_checkpoint"]["task_id"] == "task-old"


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
    assert runtime.calls[1]["current_turn"]["followup_type"] == "subject_request"
    assert runtime.calls[1]["current_turn"]["goal"] == "Provide only a subject/title for the previous email or draft."
    assert runtime.calls[1]["active_task_focus"]["goal"] != runtime.calls[1]["current_turn"]["goal"]
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
    assert runtime.calls[2]["current_turn"]["followup_type"] == "recent_user_message_recall"
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
    assert runtime.calls[3]["current_turn"]["followup_type"] == "recent_user_messages_list"
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
    assert full_subject_activity["triggering_user_message"] == "题目"
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
    assert full_activity["triggering_user_message"] == "题目"
    assert full_activity["triggering_user_turn_id"]
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
    assert agent_row["path"].endswith("/agents/vintage_programmer/locales/ja-JP/agent.md")
    assert agent_row["resolved_path"].endswith("/agents/vintage_programmer/locales/ja-JP/agent.md")
    assert tools_row["locale"] == "ja-JP"
    assert tools_row["fallback_from_base"] is True
    assert tools_row["path"].endswith("/agents/vintage_programmer/locales/ja-JP/tools.md")
    assert tools_row["resolved_path"].endswith("/agents/vintage_programmer/tools.md")

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
    assert update_response.json()["path"].endswith("/agents/vintage_programmer/locales/ja-JP/tools.md")
    assert update_response.json()["resolved_path"].endswith("/agents/vintage_programmer/locales/ja-JP/tools.md")
    assert update_response.json()["fallback_from_base"] is False
    assert (localized_dir / "tools.md").read_text(encoding="utf-8") == "# Tools\n\nupdated"
    assert (tmp_path / "agents" / "vintage_programmer" / "tools.md").read_text(encoding="utf-8") == "tools"

    base_response = client.get("/api/workbench/specs/tools.md", params={"locale": "zh-CN"})
    assert base_response.status_code == 200
    assert base_response.json()["content"] == "tools"
    assert base_response.json()["fallback_from_base"] is True
    assert base_response.json()["path"].endswith("/agents/vintage_programmer/locales/zh-CN/tools.md")
    assert base_response.json()["resolved_path"].endswith("/agents/vintage_programmer/tools.md")

    zh_update_response = client.put(
        "/api/workbench/specs/tools.md?locale=zh-CN",
        json={"content": "# 中文工具\n\nupdated"},
    )
    assert zh_update_response.status_code == 200
    assert zh_update_response.json()["path"].endswith("/agents/vintage_programmer/locales/zh-CN/tools.md")
    assert zh_update_response.json()["resolved_path"].endswith("/agents/vintage_programmer/locales/zh-CN/tools.md")
    assert zh_update_response.json()["fallback_from_base"] is False
    assert (tmp_path / "agents" / "vintage_programmer" / "locales" / "zh-CN" / "tools.md").read_text(encoding="utf-8") == "# 中文工具\n\nupdated"
    assert (tmp_path / "agents" / "vintage_programmer" / "tools.md").read_text(encoding="utf-8") == "tools"
