from __future__ import annotations

from app.context_meter import build_context_meter, resolve_context_window


def test_resolve_context_window_prefers_explicit_model_registry() -> None:
    window, source = resolve_context_window("moonshot-v1-128k", max_output_tokens=128000)

    assert window == 128 * 1024
    assert source == "model_registry"


def test_resolve_context_window_uses_model_name_hint() -> None:
    window, source = resolve_context_window("mixtral-8x7b-32768", max_output_tokens=4096)

    assert window == 32768
    assert source == "model_registry"


def test_build_context_meter_uses_fallback_budget_for_unknown_models() -> None:
    session = {
        "summary": "old summary",
        "turns": [
            {"role": "user", "text": "请帮我分析这个仓库"},
            {"role": "assistant", "text": "我先检查目录和关键入口。"},
        ],
        "thread_memory": {
            "summary": "recent thread summary",
            "recent_tasks": [],
            "recent_cwds": ["/tmp/project"],
            "recent_files": ["app/main.py"],
        },
        "current_task_focus": {
            "task_id": "task-1",
            "goal": "inspect repo",
            "project_root": "/tmp/project",
            "cwd": "/tmp/project",
            "active_files": ["app/main.py"],
            "active_attachments": [],
            "last_completed_step": "",
            "next_action": "search codebase",
        },
        "artifact_memory": [],
        "route_state": {"task_type": "code"},
    }

    meter = build_context_meter(
        session=session,
        model="unknown/free-model",
        max_output_tokens=128000,
        pending_message="继续解释刚才的代码结构",
    )

    assert meter["estimated_tokens"] > 0
    assert meter["auto_compact_token_limit"] == int(256000 * 0.9)
    assert meter["threshold_source"] == "fallback_budget"
    assert meter["warning"]
    assert 0 <= meter["used_percent"] <= 100
