from __future__ import annotations

import json
from pathlib import Path

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
            "allowed_tools": ["search_web", "read_text_file"],
            "spec_files": ["soul.md", "identity.md", "agent.md", "tools.md"],
            "identity": {"document": "identity", "sections": {"角色定义": ["primary agent"]}},
            "workflow": {"phases": ["explore", "plan", "execute", "verify", "report"]},
            "policies": {
                "tool_policy": "all",
                "approval_policy": "on_failure_or_high_impact",
                "evidence_policy": "required_for_external_or_runtime_facts",
            },
            "network": {"mode": "explicit_tools", "web_tool_contract": ["search_web", "fetch_web", "download_web_file"]},
            "capabilities": {
                "allowed_tools": ["search_web", "read_text_file"],
                "tool_count": 2,
                "tools": [
                    {"name": "search_web", "group": "web", "source": "legacy_retained", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search web"},
                    {"name": "read_text_file", "group": "files", "source": "legacy_retained", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read file"},
                ],
            },
            "tools": [
                {"name": "search_web", "group": "web", "source": "legacy_retained", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "search web"},
                {"name": "read_text_file", "group": "files", "source": "legacy_retained", "enabled": True, "read_only": True, "requires_evidence": True, "summary": "read file"},
            ],
            "loaded_skills": [{"id": "example_refactor_helper", "title": "Example Refactor Helper", "summary": "Starter", "path": "/tmp/example"}],
        }

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context)
        project = dict(context.get("project") or {})
        if progress_cb is not None:
            progress_cb({"event": "stage", "code": "execute", "phase": "execute", "label": "Execute", "status": "running", "detail": "fake runtime running"})
        return {
            "text": "single-agent response",
            "effective_model": "gpt-test",
            "tool_events": [{"name": "search_web", "input": {"query": "x"}, "output_preview": "ok", "status": "ok", "group": "web", "source": "legacy_retained", "summary": "searched", "source_refs": ["https://example.com"]}],
            "token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "llm_calls": 1},
            "answer_bundle": {"summary": "single-agent response", "claims": [], "citations": [], "warnings": []},
            "route_state": {"agent_id": "vintage_programmer", "phase": "report", "evidence_status": "collected", "loaded_skill_ids": ["example_refactor_helper"]},
            "inspector": {
                "agent": self.descriptor(),
                "notes": ["fake runtime note"],
                "run_state": {"goal": "workspace inspection", "phase": "report", "workflow_phases": ["explore", "plan", "execute", "verify", "report"], "inline_document": False},
                "tool_timeline": [{"name": "search_web", "group": "web", "status": "ok", "summary": "searched", "source_refs": ["https://example.com"]}],
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
    assert payload["tool_events"][0]["name"] == "search_web"
    assert payload["tool_events"][0]["status"] == "ok"
    assert payload["inspector"]["agent"]["title"] == "Vintage Programmer"
    assert payload["inspector"]["run_state"]["phase"] == "report"
    assert "execution_trace" not in payload

    session_id = payload["session_id"]
    session_response = client.get(f"/api/session/{session_id}")
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["project_id"]
    assert session_payload["project_root"] == str(tmp_path)
    assert session_payload["agent_state"]["phase"] == "report"
    assert session_payload["agent_state"]["evidence_status"] == "collected"
    assert session_payload["agent_state"]["enabled_skill_ids"] == ["example_refactor_helper"]


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
    assert "final" in event_names
    assert event_names[-1] == "done"
    stage_payloads = [payload for name, payload in events if name == "stage"]
    assert any(payload.get("phase") == "execute" for payload in stage_payloads)
    final_payload = next(payload for name, payload in events if name == "final")
    response_payload = dict(final_payload.get("response") or {})
    assert response_payload["agent_id"] == "vintage_programmer"
    assert response_payload["text"] == "single-agent response"


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
    assert tools_response.json()["tools"][0]["name"]

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
