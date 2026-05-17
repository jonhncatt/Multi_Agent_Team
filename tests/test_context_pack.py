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


def test_context_pack_is_the_only_structured_context_envelope(tmp_path: Path) -> None:
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
        message="整理会议纪要",
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
            "route_state": {"task_checkpoint": {"task_id": "old", "goal": "previous goal"}},
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "compaction_status": {"phase": "pre_turn", "reason": "context_limit", "retained_turn_count": 1},
        },
        runtime_boundary=boundary,
    )
    payload = _runtime_context_payload(runtime, payload_text)
    context_pack = payload["context_pack"]

    assert "legacy_context" not in payload
    assert "route_state" not in payload
    assert set(context_pack) == {
        "current_turn",
        "turn_memory",
        "conversation_window",
        "route_hints",
        "compaction",
        "runtime_boundary",
    }
    assert context_pack["current_turn"]["user_message"] == "整理会议纪要"
    assert context_pack["current_turn"]["attachment_evidence"][0]["summary"] == "decisions"
    assert context_pack["current_turn"]["user_input_response"]["answer"] == "yes"
    assert context_pack["turn_memory"]["short_memory"]["current_task_focus"]["goal"] == "previous goal"
    assert context_pack["turn_memory"]["long_memory"]["summary"] == "older summary"
    assert context_pack["turn_memory"]["long_memory"]["thread_summary"] == "thread summary"
    assert context_pack["turn_memory"]["long_memory"]["recent_tasks"][0]["goal"] == "old"
    assert context_pack["turn_memory"]["long_memory"]["recent_files"] == ["README.md"]
    assert context_pack["turn_memory"]["long_memory"]["artifact_memory_preview"][0]["path"] == "report.md"
    assert context_pack["turn_memory"]["long_memory"]["recalled_context"]["topic"] == "meeting"
    assert context_pack["conversation_window"]["recent_turns"][0]["text"] == "turn"
    assert context_pack["route_hints"]["priority"] == "weak"
    assert context_pack["route_hints"]["route_state"]["task_checkpoint"]["goal"] == "previous goal"
    assert context_pack["compaction"]["status"]["phase"] == "pre_turn"
    assert context_pack["compaction"]["status"]["reason"] == "context_limit"
    assert context_pack["runtime_boundary"]["cwd"] == str(tmp_path.resolve())
