from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
from app.context_meter import count_tokens
from app.local_tools import LocalToolExecutor
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _ToolMessage:
    def __init__(self, *, content: str, tool_call_id: str, name: str) -> None:
        self.content = content
        self.tool_call_id = tool_call_id
        self.name = name


class _Backend:
    requires_auth = False

    def __init__(self, tools: LocalToolExecutor) -> None:
        self.tools = tools
        self._ToolMessage = _ToolMessage


def _config(monkeypatch, tmp_path: Path, *, token_limit: int = 512):
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_TOOL_OUTPUT_TOKEN_LIMIT", str(token_limit))
    return load_config()


def test_large_tool_result_is_token_bounded_and_resumable_without_rerun(monkeypatch, tmp_path: Path) -> None:
    config = _config(monkeypatch, tmp_path)
    tools = LocalToolExecutor(config)
    tools.set_runtime_context(session_id="thread-one", run_id="run-one", model="gpt-5.6-sol")
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_Backend(tools),
    )
    result: dict[str, Any] = {
        "ok": True,
        "summary": "large test output",
        # Large enough to require several continuation reads without making
        # Windows security scanners repeatedly inspect dozens of sidecar reads.
        "output": "\n".join(f"line-{index}: {'x' * 80}" for index in range(100)),
    }

    message = runtime._tool_message_for_result(
        result=result,
        call_id="call-one",
        name="exec_command",
    )
    model_payload = json.loads(message.content)

    assert model_payload["truncated"] is True
    assert count_tokens(message.content, config.default_model) <= config.tool_output_token_limit
    result_ref = model_payload["truncation"]["result_ref"]
    assert result_ref.startswith("tr_")
    assert model_payload["truncation"]["next_cursor"] == 0

    chunks: list[str] = []
    cursor = 0
    for _ in range(20):
        continuation = tools.read_tool_result(result_ref=result_ref, cursor=cursor, max_tokens=512)
        assert continuation["ok"] is True
        continuation_message = runtime._tool_message_for_result(
            result=continuation,
            call_id="continuation-call",
            name="read_tool_result",
        )
        assert count_tokens(continuation_message.content, config.default_model) <= config.tool_output_token_limit
        assert json.loads(continuation_message.content).get("truncated") is not True
        chunks.append(str(continuation["content"]))
        if continuation["complete"]:
            break
        cursor = int(continuation["next_cursor"])
    else:
        raise AssertionError("tool result continuation did not complete within 20 reads")

    assert len(chunks) > 1
    assert "".join(chunks) == json.dumps(result, ensure_ascii=False)


def test_tool_result_reference_is_scoped_to_originating_thread(monkeypatch, tmp_path: Path) -> None:
    config = _config(monkeypatch, tmp_path)
    tools = LocalToolExecutor(config)
    tools.set_runtime_context(session_id="thread-one", run_id="run-one", model="gpt-5.6-sol")
    result_ref = tools._persist_tool_result(
        call_id="call-one",
        tool_name="exec_command",
        content="private output",
        token_count=2,
    )

    tools.set_runtime_context(session_id="thread-two", run_id="run-two", model="gpt-5.6-sol")
    denied = tools.read_tool_result(result_ref=result_ref)

    assert denied["ok"] is False
    assert denied["error"]["kind"] == "tool_result_not_found"


def test_small_tool_result_does_not_create_sidecar(monkeypatch, tmp_path: Path) -> None:
    config = _config(monkeypatch, tmp_path, token_limit=10_000)
    tools = LocalToolExecutor(config)
    tools.set_runtime_context(session_id="thread-one", run_id="run-one", model="gpt-5.6-sol")
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=tmp_path / "agents" / "vintage_programmer",
        backend=_Backend(tools),
    )

    message = runtime._tool_message_for_result(
        result={"ok": True, "output": "small"},
        call_id="call-small",
        name="exec_command",
    )

    assert json.loads(message.content) == {"ok": True, "output": "small"}
    assert list((config.sessions_dir.parent / "tool_results").rglob("tr_*.json")) == []
