from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
from app.context_meter import build_compaction_status, ensure_compaction_state
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _FakeTools:
    tool_specs: list[dict[str, Any]] = []


class _FakeBackend:
    tools = _FakeTools()


def _payload_from_human_message(text: str) -> dict[str, Any]:
    return json.loads(text.split("model_context_json:\n", 1)[1])["model_context"]


def test_compaction_status_uses_phase_reason_fields() -> None:
    session = {
        "compaction_state": {
            "last_compaction_phase": "pre_turn",
            "last_compaction_reason": "context_limit:100/90",
            "before_tokens": 100,
            "after_tokens": 60,
        }
    }

    state = ensure_compaction_state(session)
    status = build_compaction_status(session=session, model="gpt-test", pending_message="hello")

    assert state["phase"] == "pre_turn"
    assert status["phase"] == "pre_turn"
    assert status["reason"] == "context_limit"
    assert status["before_tokens"] == 100
    assert status["after_tokens"] == 60


def test_compaction_status_feeds_context_pack_without_legacy_context(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=tmp_path, backend=_FakeBackend())
    compaction_status = {
        "generation": 2,
        "phase": "mid_turn",
        "reason": "context_limit",
        "summary": "old tool observations compacted",
        "retained_turn_count": 4,
    }

    payload = _payload_from_human_message(
        runtime._build_human_payload(  # noqa: SLF001 - structure regression test
            message="继续",
            context={
                "session_id": "s-compact",
                "summary": "long summary",
                "history_turns": [{"role": "tool", "text": "recent observation"}],
                "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
                "compaction_status": compaction_status,
            },
        )
    )
    model_context = payload

    assert set(model_context) == {"task", "workspace", "memory", "plan", "permissions", "conversation"}
    assert model_context["memory"]["clean_summary"] == "long summary"
    assert model_context["conversation"]["recent_turns"] == []
    assert model_context["workspace"]["project_root"] == str(tmp_path.resolve())
    assert "legacy_context" not in model_context
    assert "route_hints" not in model_context
