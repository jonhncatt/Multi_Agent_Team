from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_app


class _CompatRuntime:
    def descriptor(self) -> dict[str, object]:
        return {
            "agent_id": "vintage_programmer",
            "title": "Vintage Programmer",
            "default_model": "gpt-test",
            "tool_policy": "all",
            "allowed_tools": [],
            "spec_files": ["soul.md", "identity.md", "agent.md", "tools.md"],
            "identity": {"document": "identity", "sections": {}},
            "workflow": {
                "modes": ["default", "plan", "execute"],
                "phases": ["default", "plan", "execute"],
                "default_mode": "default",
            },
            "policies": {"tool_policy": "all"},
            "network": {"mode": "explicit_tools"},
            "capabilities": {"allowed_tools": [], "tool_count": 0, "tools": []},
            "tools": [],
            "loaded_skills": [],
        }

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context, progress_cb)
        return {
            "text": "compat router response",
            "effective_model": "gpt-test",
            "tool_events": [],
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0},
            "answer_bundle": {"summary": "compat router response", "claims": [], "citations": [], "warnings": []},
            "route_state": {"agent_id": "vintage_programmer", "phase": "completed", "evidence_status": "not_needed"},
            "collaboration_mode": "default",
            "turn_status": "completed",
            "plan": [],
            "pending_user_input": {},
            "inspector": {
                "agent": self.descriptor(),
                "notes": [],
                "run_state": {
                    "goal": "compat",
                    "phase": "completed",
                    "workflow_phases": ["default", "plan", "execute"],
                    "collaboration_mode": "default",
                    "turn_status": "completed",
                    "plan": [],
                    "pending_user_input": {},
                },
                "tool_timeline": [],
                "evidence": {"status": "not_needed", "required": False, "warning": "", "source_refs": []},
                "session": {"session_id": "compat-session", "project_id": "", "project_title": "", "project_root": "", "cwd": ""},
                "token_usage": {"total_tokens": 0},
                "loaded_skills": [],
            },
        }


def test_agents_list_and_reload_api() -> None:
    client = TestClient(main_app.app)
    listed = client.get("/api/agents")
    assert listed.status_code == 200
    payload = listed.json()
    assert int(payload.get("count") or 0) >= 12

    reloaded = client.post("/api/agents/worker_agent/reload")
    assert reloaded.status_code == 200
    assert bool(reloaded.json().get("ok")) is True


def test_chat_api_runs_via_llm_router(monkeypatch) -> None:
    monkeypatch.setattr(
        main_app.OpenAIAuthManager,
        "auth_summary",
        lambda self: {"available": True, "mode": "test", "reason": ""},
    )
    monkeypatch.setattr(
        main_app,
        "_provider_runtime",
        lambda requested_provider: (main_app.config, _CompatRuntime()),
    )
    client = TestClient(main_app.app)
    response = client.post(
        "/api/chat",
        json={
            "message": "请做一个简单计划",
            "settings": {"enable_tools": True},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert str(payload.get("selected_business_module")) == "llm_router_core"


def test_chat_api_without_auth_still_returns_stable_reply(monkeypatch) -> None:
    monkeypatch.setattr(
        main_app.OpenAIAuthManager,
        "auth_summary",
        lambda self: {"available": False, "mode": "unconfigured", "reason": "missing"},
    )
    client = TestClient(main_app.app)
    response = client.post(
        "/api/chat",
        json={"message": "你好", "settings": {"enable_tools": True}},
    )
    assert response.status_code == 200
    payload = response.json()
    text = str(payload.get("text") or "").lower()
    assert "unavailable" not in text
    assert "connection" not in text
