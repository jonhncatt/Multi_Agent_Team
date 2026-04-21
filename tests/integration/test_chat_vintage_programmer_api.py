from __future__ import annotations

import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient

import app.main as main_app
from app.evolution import EvolutionStore
from app.storage import ProjectStore, SessionStore, ShadowLogStore, TokenStatsStore, UploadStore
from app.workbench import WorkbenchStore


class _FakeVintageRuntime:
    def descriptor(self) -> dict[str, object]:
        return {
            "agent_id": "vintage_programmer",
            "title": "Vintage Programmer",
            "default_model": "gpt-test",
            "tool_policy": "all",
            "allowed_tools": [
                "exec_command",
                "apply_patch",
                "read",
                "search_file",
                "search_file_multi",
                "read_section",
                "table_extract",
                "fact_check_file",
                "search_codebase",
                "web_search",
                "web_fetch",
                "web_download",
                "sessions_list",
                "image_inspect",
                "image_read",
                "archive_extract",
                "mail_extract_attachments",
                "update_plan",
                "request_user_input",
            ],
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
                "allowed_tools": [
                    "exec_command",
                    "apply_patch",
                    "read",
                    "search_file",
                    "search_file_multi",
                    "read_section",
                    "table_extract",
                    "fact_check_file",
                    "search_codebase",
                    "web_search",
                    "web_fetch",
                    "web_download",
                    "sessions_list",
                    "image_inspect",
                    "image_read",
                    "archive_extract",
                    "mail_extract_attachments",
                    "update_plan",
                    "request_user_input",
                ],
                "tool_count": 17,
                "tools": [
                    {"name": "exec_command", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "run shell commands"},
                    {"name": "apply_patch", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "apply workspace patch"},
                    {"name": "read", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read file or directory"},
                    {"name": "search_file", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search one local file"},
                    {"name": "search_file_multi", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search one local file with multiple queries"},
                    {"name": "read_section", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read one matched section"},
                    {"name": "table_extract", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "extract document tables"},
                    {"name": "fact_check_file", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "fact check one file"},
                    {"name": "search_codebase", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search codebase"},
                    {"name": "web_search", "group": "web_context", "source": "local_hosted", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search the web"},
                    {"name": "web_fetch", "group": "web_context", "source": "local_hosted", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "fetch one web page"},
                    {"name": "web_download", "group": "web_context", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": True, "summary": "download one remote file"},
                    {"name": "sessions_list", "group": "session_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "list sessions"},
                    {"name": "image_inspect", "group": "media_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "inspect image"},
                    {"name": "image_read", "group": "media_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read image content"},
                    {"name": "archive_extract", "group": "content_unpack", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "extract archive"},
                    {"name": "mail_extract_attachments", "group": "content_unpack", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "extract mail attachments"},
                    {"name": "update_plan", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": True, "requires_evidence": False, "summary": "sync checklist"},
                    {"name": "request_user_input", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": True, "requires_evidence": False, "summary": "request structured input"},
                ],
            },
            "tools": [
                {"name": "exec_command", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "run shell commands"},
                {"name": "apply_patch", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "apply workspace patch"},
                {"name": "read", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read file or directory"},
                {"name": "search_file", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search one local file"},
                {"name": "search_file_multi", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search one local file with multiple queries"},
                {"name": "read_section", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read one matched section"},
                {"name": "table_extract", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "extract document tables"},
                {"name": "fact_check_file", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "fact check one file"},
                {"name": "search_codebase", "group": "fs_content", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search codebase"},
                {"name": "web_search", "group": "web_context", "source": "local_hosted", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search the web"},
                {"name": "web_fetch", "group": "web_context", "source": "local_hosted", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "fetch one web page"},
                {"name": "web_download", "group": "web_context", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": True, "summary": "download one remote file"},
                {"name": "sessions_list", "group": "session_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "list sessions"},
                {"name": "image_inspect", "group": "media_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "inspect image"},
                {"name": "image_read", "group": "media_context", "source": "openclaw_inspired", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read image content"},
                {"name": "archive_extract", "group": "content_unpack", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "extract archive"},
                {"name": "mail_extract_attachments", "group": "content_unpack", "source": "local_specialized", "enabled": True, "read_only": False, "requires_evidence": False, "summary": "extract mail attachments"},
                {"name": "update_plan", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": True, "requires_evidence": False, "summary": "sync checklist"},
                {"name": "request_user_input", "group": "codex_core", "source": "codex_core", "enabled": True, "read_only": True, "requires_evidence": False, "summary": "request structured input"},
            ],
            "loaded_skills": [{"id": "example_refactor_helper", "title": "Example Refactor Helper", "summary": "Starter", "path": "/tmp/example"}],
        }

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context)
        project = dict(context.get("project") or {})
        if progress_cb is not None:
            progress_cb({"event": "stage", "code": "execute", "phase": "execute", "label": "Execute", "status": "running", "detail": "fake runtime running"})
            progress_cb({"event": "plan_update", "plan": [{"step": "Inspect workspace", "status": "completed"}], "collaboration_mode": "default", "turn_status": "running"})
        return {
            "text": "single-agent response",
            "effective_model": "gpt-test",
            "tool_events": [{"name": "web_search", "input": {"query": "x"}, "output_preview": "ok", "status": "ok", "group": "web_context", "source": "local_hosted", "summary": "searched", "source_refs": ["https://example.com"]}],
            "token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "llm_calls": 1},
            "answer_bundle": {"summary": "single-agent response", "claims": [], "citations": [], "warnings": []},
            "route_state": {
                "agent_id": "vintage_programmer",
                "phase": "completed",
                "evidence_status": "collected",
                "loaded_skill_ids": ["example_refactor_helper"],
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
            "collaboration_mode": "default",
            "turn_status": "completed",
            "plan": [{"step": "Inspect workspace", "status": "completed"}],
            "pending_user_input": {},
            "inspector": {
                "agent": self.descriptor(),
                "notes": ["fake runtime note"],
                "run_state": {
                    "goal": "workspace inspection",
                    "phase": "completed",
                    "workflow_phases": ["default", "plan", "execute"],
                    "collaboration_mode": "default",
                    "turn_status": "completed",
                    "plan": [{"step": "Inspect workspace", "status": "completed"}],
                    "pending_user_input": {},
                    "inline_document": False,
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
                "tool_timeline": [{"name": "web_search", "group": "web_context", "status": "ok", "summary": "searched", "source_refs": ["https://example.com"]}],
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
                "loaded_skills": [{"id": "example_refactor_helper", "title": "Example Refactor Helper", "summary": "Starter", "path": "/tmp/example"}],
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


class _ContextCapturingRuntime(_FakeVintageRuntime):
    def __init__(self) -> None:
        self.seen_contexts: list[dict[str, object]] = []

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, progress_cb)
        self.seen_contexts.append(dict(context))
        return super().run(message=message, settings=settings, context=context, progress_cb=progress_cb)


def _patch_runtime_state(monkeypatch, tmp_path: Path) -> None:
    for name in ("sessions", "uploads", "shadow_logs", "evolution_logs", "workspace/skills", "agents/vintage_programmer"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents" / "vintage_programmer" / "soul.md").write_text("soul", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "identity.md").write_text("identity", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "agent.md").write_text("---\nid: vintage_programmer\n---\nagent", encoding="utf-8")
    (tmp_path / "agents" / "vintage_programmer" / "tools.md").write_text("tools", encoding="utf-8")
    skill_dir = tmp_path / "workspace" / "skills" / "example_refactor_helper"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: example_refactor_helper\n"
        "title: Example Refactor Helper\n"
        "enabled: false\n"
        "bind_to:\n"
        "  - vintage_programmer\n"
        "summary: Starter\n"
        "---\n\n"
        "# Example\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_app.config, "workspace_root", tmp_path)
    monkeypatch.setattr(main_app.config, "projects_registry_path", tmp_path / "projects.json")
    monkeypatch.setattr(main_app.config, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(main_app.config, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(main_app.config, "shadow_logs_dir", tmp_path / "shadow_logs")
    monkeypatch.setattr(main_app.config, "token_stats_path", tmp_path / "token_stats.json")
    monkeypatch.setattr(main_app.config, "allowed_roots", [tmp_path])
    monkeypatch.setattr(main_app, "session_store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(main_app, "upload_store", UploadStore(tmp_path / "uploads"))
    monkeypatch.setattr(main_app, "token_stats_store", TokenStatsStore(tmp_path / "token_stats.json"))
    monkeypatch.setattr(main_app, "shadow_log_store", ShadowLogStore(tmp_path / "shadow_logs"))
    monkeypatch.setattr(main_app, "project_store", ProjectStore(tmp_path / "projects.json", default_root=tmp_path))
    main_app.project_store.ensure_default_project()
    monkeypatch.setattr(
        main_app,
        "evolution_store",
        EvolutionStore(tmp_path / "overlay_profile.json", tmp_path / "evolution_logs"),
    )
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


def test_health_endpoint_exposes_single_agent_descriptor(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app_title"] == "Vintage Programmer"
    assert payload["agent"]["agent_id"] == "vintage_programmer"
    assert payload["runtime_status"]["workspace_label"]
    assert "rapidocr_available" in payload["ocr_status"]
    assert "default_engine" in payload["ocr_status"]
    assert payload["default_project_id"]
    assert payload["projects"][0]["project_id"]
    assert payload["allow_custom_model"] is True
    assert payload["provider_options"]
    assert payload["llm_provider"] in [item["provider"] for item in payload["provider_options"]]
    assert payload["default_model"] in payload["model_options"]
    assert "control_panel_topology" not in payload


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
    assert payload["tool_events"][0]["source"] == "local_hosted"
    assert payload["tool_events"][0]["group"] == "web_context"
    assert payload["tool_events"][0]["status"] == "ok"
    assert payload["collaboration_mode"] == "default"
    assert payload["turn_status"] == "completed"
    assert payload["plan"] == [{"step": "Inspect workspace", "status": "completed"}]
    assert payload["inspector"]["agent"]["title"] == "Vintage Programmer"
    assert payload["inspector"]["run_state"]["collaboration_mode"] == "default"
    assert payload["inspector"]["run_state"]["turn_status"] == "completed"
    assert "execution_trace" not in payload

    session_id = payload["session_id"]
    session_response = client.get(f"/api/session/{session_id}")
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["project_id"]
    assert session_payload["project_root"] == str(tmp_path)
    assert session_payload["agent_state"]["phase"] == "completed"
    assert session_payload["agent_state"]["collaboration_mode"] == "default"
    assert session_payload["agent_state"]["turn_status"] == "completed"
    assert session_payload["agent_state"]["evidence_status"] == "collected"
    assert session_payload["agent_state"]["enabled_skill_ids"] == ["example_refactor_helper"]
    assert session_payload["agent_state"]["task_checkpoint"]["task_id"] == "task-fake-1"


def test_chat_stream_emits_stage_final_and_done(monkeypatch, tmp_path: Path) -> None:
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
    assert "final" in event_names
    assert event_names[-1] == "done"
    stage_payloads = [payload for name, payload in events if name == "stage"]
    assert any(payload.get("phase") == "execute" for payload in stage_payloads)
    final_payload = next(payload for name, payload in events if name == "final")
    response_payload = dict(final_payload.get("response") or {})
    assert response_payload["agent_id"] == "vintage_programmer"
    assert response_payload["text"] == "single-agent response"
    assert response_payload["collaboration_mode"] == "default"
    assert response_payload["turn_status"] == "completed"


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
        }

    try:
        response = client.post(f"/api/chat/runs/{run_id}/cancel")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["cancelled"] is True
        assert payload["status"] == "cancelling"
        assert cancel_event.is_set() is True
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
    assert payload["detail"]["summary"] == "模型提供方限流，请稍后重试。"
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
    error_payload = next(payload for name, payload in events if name == "error")
    assert error_payload["status_code"] == 429
    assert error_payload["kind"] == "rate_limit"
    assert error_payload["summary"] == "模型提供方限流，请稍后重试。"
    assert error_payload["provider"] == "Google AI Studio"
    assert error_payload["retryable"] is True


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
            "last_completed_step": "read: old.py",
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
    assert seen["current_task_focus"]["task_id"] == "task-old"
    assert seen["route_state"]["task_checkpoint"]["task_id"] == "task-old"


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

    list_a = client.get(f"/api/sessions?project_id={project_a}")
    list_b = client.get(f"/api/sessions?project_id={project_b}")
    assert list_a.status_code == 200
    assert list_b.status_code == 200
    assert all(item["project_id"] == project_a for item in list_a.json()["sessions"])
    assert all(item["project_id"] == project_b for item in list_b.json()["sessions"])

    duplicate = client.post("/api/projects", json={"root_path": str(repo_a)})
    assert duplicate.status_code == 409


def test_workbench_endpoints_list_and_edit_local_skills(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    tools_response = client.get("/api/workbench/tools")
    assert tools_response.status_code == 200
    tool_rows = tools_response.json()["tools"]
    assert tool_rows[0]["name"]
    assert all(item["source"] != "legacy_retained" for item in tool_rows)
    assert {"codex_core", "fs_content", "web_context", "session_context", "media_context", "content_unpack"}.issubset(
        {item["group"] for item in tool_rows}
    )
    assert "view_image" not in {item["name"] for item in tool_rows}
    assert "read_text_file" not in {item["name"] for item in tool_rows}
    assert {"web_download", "image_read", "search_file_multi", "read_section", "table_extract", "fact_check_file"}.issubset(
        {item["name"] for item in tool_rows}
    )

    skills_response = client.get("/api/workbench/skills")
    assert skills_response.status_code == 200
    assert skills_response.json()["skills"][0]["id"] == "example_refactor_helper"

    create_response = client.post(
        "/api/workbench/skills",
        json={
            "content": "---\nid: repo_triage\ntitle: Repo Triage\nenabled: false\nbind_to:\n  - vintage_programmer\nsummary: triage skill\n---\n\n# Repo Triage\n"
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["id"] == "repo_triage"

    toggle_response = client.post("/api/workbench/skills/repo_triage/toggle", json={"enabled": True})
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is True


def test_workbench_specs_endpoint_reads_and_writes_agent_specs(monkeypatch, tmp_path: Path) -> None:
    _patch_runtime_state(monkeypatch, tmp_path)
    client = TestClient(main_app.app)

    specs_response = client.get("/api/workbench/specs")
    assert specs_response.status_code == 200
    assert any(item["name"] == "agent.md" for item in specs_response.json()["specs"])

    spec_response = client.get("/api/workbench/specs/agent.md")
    assert spec_response.status_code == 200
    assert "agent" in spec_response.json()["content"]

    update_response = client.put(
        "/api/workbench/specs/tools.md",
        json={"content": "# Tools\n\nupdated"},
    )
    assert update_response.status_code == 200
    assert "updated" in update_response.json()["content"]
