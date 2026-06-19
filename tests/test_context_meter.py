from __future__ import annotations

import pytest

import app.context_meter as context_meter_module
from app.context_meter import (
    build_compaction_status,
    build_context_meter,
    build_context_meter_from_status,
    build_runtime_context_payload,
    maybe_auto_compact_session,
    resolve_context_window,
)


def test_resolve_context_window_prefers_explicit_model_registry() -> None:
    window, source = resolve_context_window("moonshot-v1-128k", max_output_tokens=128000)

    assert window == 128 * 1024
    assert source == "model_registry"


def test_resolve_context_window_matches_openai_large_context_models() -> None:
    window, source = resolve_context_window("gpt-5.4", max_output_tokens=128000)

    assert window == 1_000_000
    assert source == "model_registry"

    mini_window, mini_source = resolve_context_window("openai/gpt-5.4-mini", max_output_tokens=128000)

    assert mini_window == 400_000
    assert mini_source == "model_registry"


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
    assert meter["auto_compact_token_limit"] == int(256000 * 0.8)
    assert meter["threshold_source"] == "fallback_budget"
    assert meter["warning"]
    assert 0 <= meter["used_percent"] <= 100


def test_build_context_meter_from_status_reuses_existing_compaction_status() -> None:
    session = {
        "summary": "old summary",
        "turns": [
            {"role": "user", "text": "请帮我分析这个仓库"},
            {"role": "assistant", "text": "我先检查目录和关键入口。"},
        ],
        "thread_memory": {"summary": "recent thread summary"},
        "current_task_focus": {"task_id": "task-1", "goal": "inspect repo"},
        "artifact_memory": [],
        "route_state": {"task_type": "code"},
    }

    status = build_compaction_status(
        session=session,
        model="unknown/free-model",
        max_output_tokens=4096,
        pending_message="继续解释刚才的代码结构",
    )
    meter = build_context_meter_from_status(status)

    assert meter["estimated_tokens"] == status["estimated_context_tokens"]
    assert meter["estimated_payload_tokens"] == status["estimated_payload_tokens"]
    assert meter["auto_compact_token_limit"] == status["auto_compact_token_limit"]
    assert meter["context_window"] == status["effective_context_window"]


def test_quick_context_meter_marks_estimate_mode_without_forcing_stale() -> None:
    meter = build_context_meter(
        session={"turns": [{"role": "user", "text": "hello"}]},
        model="gpt-5.4",
        max_output_tokens=16384,
        pending_message="continue",
        estimate_mode="quick",
    )

    assert meter["estimate_mode"] == "quick"
    assert meter["stale"] is False
    assert meter["calculation_ms"] >= 0
    assert meter["remaining_tokens"] > 0


def test_maybe_auto_compact_session_skips_exact_when_quick_is_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_count_tokens(_text: str, _model: str | None = None) -> int:
        raise AssertionError("exact tokenizer should not run below compact thresholds")

    monkeypatch.setattr(context_meter_module, "count_tokens", fail_count_tokens)
    session = {
        "summary": "",
        "turns": [
            {"id": "turn-1", "role": "user", "text": "small question"},
            {"id": "turn-2", "role": "assistant", "text": "small answer"},
        ],
    }

    result = maybe_auto_compact_session(
        session=session,
        model="gpt-5.4",
        max_output_tokens=16384,
        pending_message="continue",
        phase="pre_turn",
    )

    assert result["compacted"] is False
    assert result["status_before"]["estimate_mode"] == "quick"
    assert result["status_before"]["compact_recommendation"] == "none"


def test_maybe_auto_compact_session_runs_exact_review_after_quick_crosses_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_count_tokens(_text: str, _model: str | None = None) -> int:
        calls["count"] += 1
        return 10000

    monkeypatch.setattr(context_meter_module, "count_tokens", fake_count_tokens)
    session = {
        "summary": "",
        "turns": [
            {
                "id": f"turn-{idx}",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": ("long history " if idx % 2 == 0 else "long answer ") + ("A" * 5000),
            }
            for idx in range(16)
        ],
    }

    result = maybe_auto_compact_session(
        session=session,
        model="moonshot-v1-8k",
        max_output_tokens=2048,
        pending_message="continue",
        phase="pre_turn",
    )

    assert calls["count"] >= 1
    assert result["status_before"]["estimate_mode"] == "exact"
    assert result["status_before"]["compact_recommendation"] in {"suggested", "required"}
    assert result["compacted"] is True


def test_manual_compact_can_pack_short_history_with_smaller_retention() -> None:
    session = {
        "summary": "",
        "turns": [
            {"id": "turn-1", "role": "user", "text": "hi"},
            {"id": "turn-2", "role": "assistant", "text": "Hi! How can I help you today?"},
            {"id": "turn-3", "role": "user", "text": "介绍自己"},
            {"id": "turn-4", "role": "assistant", "text": "我是 vintage_programmer。"},
        ],
    }

    result = maybe_auto_compact_session(
        session=session,
        model="gpt-5.4",
        max_output_tokens=16384,
        phase="manual",
        force=True,
        trigger="manual",
        retained_raw_turns=2,
    )

    assert result["compacted"] is True
    assert result["compacted_turn_count"] == 2
    assert session["compaction_state"]["reason"] == "manual"
    assert session["compaction_state"]["compacted_until_turn_id"] == "turn-2"
    runtime_view = build_runtime_context_payload(session=session)
    assert [turn["id"] for turn in runtime_view["history_turns"]] == ["turn-3", "turn-4"]
    assert "hi" in runtime_view["summary"]


def test_current_long_user_input_does_not_trigger_history_noise_compaction() -> None:
    status = build_compaction_status(
        session={"summary": "", "turns": []},
        model="gpt-5.4",
        max_output_tokens=16384,
        pending_message="A" * 500_000,
        estimate_mode="quick",
    )

    assert status["estimated_context_tokens"] > status["history_soft_limit_tokens"]
    assert status["history_noise_tokens"] < status["history_soft_limit_tokens"]
    assert status["compact_recommendation"] == "none"


def test_old_history_noise_can_suggest_compaction_without_context_pressure() -> None:
    session = {
        "summary": "",
        "turns": [
            {
                "id": f"turn-{idx}",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": ("old context " if idx % 2 == 0 else "tool output ") + ("B" * 3000),
            }
            for idx in range(32)
        ],
    }

    status = build_compaction_status(
        session=session,
        model="gpt-5.4",
        max_output_tokens=16384,
        pending_message="continue",
        estimate_mode="quick",
        history_soft_limit_tokens=2000,
    )

    assert status["estimated_context_tokens"] < status["auto_compact_token_limit"]
    assert status["history_noise_tokens"] >= status["history_soft_limit_tokens"]
    assert status["compact_recommendation"] == "suggested"
    assert status["compact_reason"] == "history_soft_limit"


def test_maybe_auto_compact_session_writes_replacement_history_state() -> None:
    session = {
        "summary": "",
        "turns": [
            {
                "id": f"turn-{idx}",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": ("解释这个线程上下文 " if idx % 2 == 0 else "我已经查看过这些内容 ") + ("A" * 5000),
            }
            for idx in range(16)
        ],
        "thread_memory": {
            "summary": "",
            "recent_tasks": [],
            "recent_cwds": ["/tmp/project"],
            "recent_files": [],
        },
        "current_task_focus": {
            "task_id": "focus-1",
            "goal": "inspect long thread",
            "project_root": "/tmp/project",
            "cwd": "/tmp/project",
            "active_files": [],
            "active_attachments": [],
            "last_completed_step": "",
            "next_action": "continue",
        },
        "artifact_memory": [],
        "route_state": {"task_type": "code"},
    }

    result = maybe_auto_compact_session(
        session=session,
        model="moonshot-v1-8k",
        max_output_tokens=2048,
        pending_message="继续回答",
        phase="pre_turn",
    )

    assert result["compacted"] is True
    assert session["compaction_state"]["generation"] == 1
    assert session["compaction_state"]["compacted_history"]
    assert session["compaction_state"]["last_compaction_phase"] == "pre_turn"
    runtime_view = build_runtime_context_payload(session=session)
    assert runtime_view["summary"] == session["compaction_state"]["compacted_history"]
    assert len(runtime_view["history_turns"]) <= 12


def test_maybe_auto_compact_session_uses_llm_compactor_when_available() -> None:
    captured: dict[str, object] = {}
    session = {
        "summary": "",
        "turns": [
            {
                "id": f"turn-{idx}",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": ("处理 3.1.6 compaction " if idx % 2 == 0 else "已完成部分实现 ") + ("B" * 5000),
            }
            for idx in range(16)
        ],
        "task_state": {
            "task_id": "task-llm",
            "goal": "finish compaction",
            "status": "in_progress",
            "plan_items": [{"step": "实现 LLM compaction", "status": "in_progress"}],
            "next_required_action": "继续修 derived view",
        },
        "work_cursor": {"cwd": "/tmp/project", "active_files": ["app/context_meter.py"]},
        "context_manager": {
            "recent_observations": [{"summary": "sidecar already stores raw traces", "status": "ok"}],
            "active_files": ["app/context_meter.py"],
        },
    }

    def llm_compactor(compaction_input: dict[str, object]) -> dict[str, object]:
        captured["input"] = compaction_input
        return {
            "summary": {
                "confirmed_facts": ["LLM confirmed compacted history"],
                "files_touched": ["app/context_meter.py"],
                "decisions": ["Use an isolated compaction subtask"],
                "failed_attempts": [],
                "current_state": "pre-turn compaction is active",
                "next_steps": ["verify derived fields"],
                "open_questions": [],
                "do_not_repeat": ["do not keep raw traces in summary"],
            },
            "source": "llm",
        }

    result = maybe_auto_compact_session(
        session=session,
        model="moonshot-v1-8k",
        max_output_tokens=2048,
        pending_message="继续",
        phase="pre_turn",
        llm_compactor=llm_compactor,
    )

    assert result["compacted"] is True
    assert captured["input"]["task_state"]["goal"] == "finish compaction"
    assert session["compaction_state"]["llm_compaction_used"] is True
    assert session["compaction_state"]["compaction_source"] == "llm"
    assert session["compaction_state"]["fallback_reason"] == ""
    assert "confirmed_facts" in session["compaction_state"]["compaction_schema"]
    assert "LLM confirmed compacted history" in session["compaction_state"]["compacted_history"]
    assert session["task_state"]["next_required_action"] == "verify derived fields"
    assert session["work_cursor"]["active_files"][0] == "app/context_meter.py"


def test_maybe_auto_compact_session_records_llm_fallback_reason() -> None:
    session = {
        "summary": "",
        "turns": [
            {
                "id": f"turn-{idx}",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": ("需要压缩 " if idx % 2 == 0 else "继续 ") + ("C" * 5000),
            }
            for idx in range(16)
        ],
        "task_state": {"goal": "fallback", "status": "in_progress"},
        "work_cursor": {"cwd": "/tmp/project"},
    }

    result = maybe_auto_compact_session(
        session=session,
        model="moonshot-v1-8k",
        max_output_tokens=2048,
        pending_message="继续",
        phase="pre_turn",
        llm_compactor=lambda _: "not json",
    )

    assert result["compacted"] is True
    assert session["compaction_state"]["llm_compaction_used"] is False
    assert session["compaction_state"]["compaction_source"] == "deterministic_fallback"
    assert session["compaction_state"]["fallback_reason"] == "llm_output_invalid"
