from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
from app.runtime_boundary import build_turn_runtime_boundary
from app.runtime_contract import RuntimeContract
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _FakeTools:
    tool_specs: list[dict[str, Any]] = []


class _FakeBackend:
    tools = _FakeTools()


def _runtime_context_payload(runtime: VintageProgrammerRuntime, text: str) -> dict[str, Any]:
    return json.loads(text.split("runtime_context_json:\n", 1)[1])


def test_context_pack_is_minimal_and_non_duplicative(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=tmp_path, backend=_FakeBackend())
    boundary = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(shell_allowed=False, network_allowed=False),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )

    payload_text = runtime._build_human_payload(  # noqa: SLF001 - structure regression test
        message="整理会议纪要\n这是一个很长的当前用户消息，ContextPack 里只能保留预览，不能重复完整正文。" * 3,
        context={
            "session_id": "s-context",
            "summary": "older summary",
            "thread_memory": {"summary": "thread summary", "recent_tasks": [{"goal": "old"}], "recent_files": ["README.md"]},
            "recent_tool_results": [{"tool": "read_file", "summary": "ok"}],
            "recent_errors": [{"tool": "read_file", "summary": "missing"}],
            "artifact_memory_preview": [{"path": "report.md"}],
            "recalled_context": {"topic": "meeting"},
            "user_input_response": {"answer": "yes"},
            "attachment_evidence_pack": [{"name": "notes.pdf", "summary": "decisions"}],
            "history_turns": [{"role": "user", "text": "turn"}],
            "current_task_focus": {"task_id": "current", "goal": "previous goal"},
            "route_state": {"task_checkpoint": {"task_id": "old", "goal": "route-derived goal"}},
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "compaction_status": {"phase": "pre_turn", "reason": "context_limit", "retained_turn_count": 1},
        },
        runtime_boundary=boundary,
    )
    payload = _runtime_context_payload(runtime, payload_text)
    context_pack = payload["context_pack"]

    assert "legacy_context" not in payload
    assert "route_state" not in payload
    assert "context_priority" not in payload
    assert set(context_pack) == {
        "current_turn",
        "conversation_window",
        "turn_memory",
        "plan_state",
        "compaction",
        "runtime_boundary",
    }
    assert set(context_pack["current_turn"]) == {
        "user_message_preview",
        "attachments",
        "attachment_evidence",
        "current_files",
    }
    assert len(context_pack["current_turn"]["user_message_preview"]) <= 80
    assert "user_message" not in context_pack["current_turn"]
    assert context_pack["current_turn"]["attachment_evidence"][0]["summary"] == "decisions"
    assert "user_input_response" not in context_pack["current_turn"]
    assert set(context_pack["turn_memory"]) == {"active_task", "summary", "recent_observations"}
    assert context_pack["turn_memory"]["active_task"]["goal"] == "previous goal"
    assert "route-derived goal" not in json.dumps(context_pack, ensure_ascii=False)
    assert context_pack["turn_memory"]["summary"] == "older summary"
    assert "thread_summary" not in context_pack["turn_memory"]
    assert "recent_tasks" not in context_pack["turn_memory"]
    assert "recent_files" not in context_pack["turn_memory"]
    assert "artifact_memory_preview" not in context_pack["turn_memory"]
    assert "recalled_context" not in context_pack["turn_memory"]
    assert context_pack["turn_memory"]["recent_observations"][0]["summary"] == "ok"
    assert context_pack["conversation_window"]["recent_turns"][0]["text"] == "turn"
    assert "route_hints" not in context_pack
    assert "route_state" not in json.dumps(context_pack, ensure_ascii=False)
    assert context_pack["plan_state"] == {"active": False, "items": [], "updated_at_turn": None}
    assert context_pack["compaction"]["phase"] == "pre_turn"
    assert context_pack["compaction"]["reason"] == "context_limit"
    assert set(context_pack["compaction"]) == {"active", "phase", "reason", "summary_available"}
    assert context_pack["runtime_boundary"]["cwd"] == str(tmp_path.resolve())
    assert "allowed_roots" not in context_pack["runtime_boundary"]
    assert "writable_roots" not in context_pack["runtime_boundary"]
