from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_app
from app.evolution import EvolutionStore
from app.storage import SessionStore, ShadowLogStore, TokenStatsStore, UploadStore


class _FakeVintageRuntime:
    def descriptor(self) -> dict[str, object]:
        return {
            "agent_id": "vintage_programmer",
            "title": "Vintage Programmer",
            "default_model": "gpt-test",
            "tool_policy": "all",
            "allowed_tools": ["search_web", "read_text_file"],
            "spec_files": ["soul.md", "agent.md", "tools.md"],
        }

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context)
        if progress_cb is not None:
            progress_cb({"event": "stage", "code": "agent_run", "detail": "fake runtime running"})
        return {
            "text": "single-agent response",
            "effective_model": "gpt-test",
            "tool_events": [{"name": "search_web", "input": {"query": "x"}, "output_preview": "ok"}],
            "token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "llm_calls": 1},
            "answer_bundle": {"summary": "single-agent response", "claims": [], "citations": [], "warnings": []},
            "route_state": {"agent_id": "vintage_programmer"},
            "inspector": {
                "agent": self.descriptor(),
                "notes": ["fake runtime note"],
                "token_usage": {"total_tokens": 18},
            },
        }


def _patch_runtime_state(monkeypatch, tmp_path: Path) -> None:
    for name in ("sessions", "uploads", "shadow_logs", "evolution_logs"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_app, "session_store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(main_app, "upload_store", UploadStore(tmp_path / "uploads"))
    monkeypatch.setattr(main_app, "token_stats_store", TokenStatsStore(tmp_path / "token_stats.json"))
    monkeypatch.setattr(main_app, "shadow_log_store", ShadowLogStore(tmp_path / "shadow_logs"))
    monkeypatch.setattr(
        main_app,
        "evolution_store",
        EvolutionStore(tmp_path / "overlay_profile.json", tmp_path / "evolution_logs"),
    )
    monkeypatch.setattr(main_app, "vintage_programmer_runtime", _FakeVintageRuntime())
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
    assert payload["inspector"]["agent"]["title"] == "Vintage Programmer"
    assert "execution_trace" not in payload


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
    final_payload = next(payload for name, payload in events if name == "final")
    response_payload = dict(final_payload.get("response") or {})
    assert response_payload["agent_id"] == "vintage_programmer"
    assert response_payload["text"] == "single-agent response"
