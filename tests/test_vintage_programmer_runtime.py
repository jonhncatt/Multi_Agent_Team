from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import load_config
from app.models import ChatSettings
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        self.content = content
        self.tool_calls = list(tool_calls or [])
        self.kwargs = kwargs


class _FakeTools:
    def __init__(self) -> None:
        self.tool_specs = [
            {"name": "search_web", "description": "search web", "parameters": {}},
            {"name": "read_text_file", "description": "read file", "parameters": {}},
            {"name": "write_text_file", "description": "write file", "parameters": {}},
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.runtime_context: tuple[str | None, str | None] | None = None

    def set_runtime_context(self, *, execution_mode: str | None = None, session_id: str | None = None) -> None:
        self.runtime_context = (execution_mode, session_id)

    def clear_runtime_context(self) -> None:
        self.runtime_context = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {"ok": True, "name": name}


class _FakeBackend:
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        self.tools = _FakeTools()
        self._scripted_messages = list(scripted_messages)
        self._SystemMessage = _FakeMessage
        self._HumanMessage = _FakeMessage
        self._ToolMessage = _FakeMessage

    def _next(self) -> _FakeMessage:
        if self._scripted_messages:
            return self._scripted_messages.pop(0)
        return _FakeMessage(content="fallback")

    def _empty_usage(self) -> dict[str, int]:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}

    def _merge_usage(self, left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        merged = dict(left)
        for key, value in right.items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
        return merged

    def _extract_usage_from_message(self, _message: Any) -> dict[str, int]:
        return self._empty_usage()

    def _content_to_text(self, content: Any) -> str:
        return str(content or "")

    def _shorten(self, value: Any, limit: int) -> str:
        return str(value or "")[: max(0, int(limit))]

    def _invoke_chat_with_runner(
        self,
        *,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = (messages, max_output_tokens, enable_tools, tool_names)
        return self._next(), object(), model, []

    def _invoke_with_runner_recovery(
        self,
        *,
        runner: Any,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        _ = (runner, messages, max_output_tokens, enable_tools, tool_names)
        return self._next(), object(), model, []


def _write_specs(agent_dir: Path, *, include_soul: bool = True, include_tools: bool = True) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    if include_soul:
        (agent_dir / "soul.md").write_text("soul rules", encoding="utf-8")
    (agent_dir / "agent.md").write_text(
        "---\n"
        "id: vintage_programmer\n"
        "title: Vintage Programmer\n"
        "default_model: gpt-test\n"
        "tool_policy: read_only\n"
        "max_tool_rounds: 4\n"
        "---\n"
        "\n"
        "agent workflow\n",
        encoding="utf-8",
    )
    if include_tools:
        (agent_dir / "tools.md").write_text("tool rules", encoding="utf-8")


def test_runtime_requires_soul_and_agent_specs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir, include_soul=False)

    with pytest.raises(RuntimeError, match="Missing required agent spec file"):
        VintageProgrammerRuntime(
            config=load_config(),
            kernel_runtime=object(),
            agent_dir=agent_dir,
            backend=_FakeBackend([_FakeMessage(content="ok")]),
        )


def test_runtime_parses_frontmatter_and_prompt_order(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )

    descriptor = runtime.descriptor()
    prompt = runtime._render_system_prompt(ChatSettings(model="gpt-test"))

    assert descriptor["agent_id"] == "vintage_programmer"
    assert descriptor["tool_policy"] == "read_only"
    assert prompt.index("[soul.md]") < prompt.index("[agent.md]") < prompt.index("[tools.md]")


def test_runtime_runs_single_agent_tool_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "search_web", "args": {"query": "latest"}}]),
            _FakeMessage(content="final answer"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我查一下最新情况",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-1", "history_turns": [], "attachments": []},
    )

    assert result["text"] == "final answer"
    assert result["agent_id"] == "vintage_programmer"
    assert len(result["tool_events"]) == 1
    assert backend.tools.calls[0][0] == "search_web"
    assert result["inspector"]["agent"]["tool_policy"] == "read_only"
