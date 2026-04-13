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
            {"name": "browser_open", "description": "browser open", "parameters": {}},
            {"name": "view_image", "description": "view image", "parameters": {}},
            {"name": "apply_patch", "description": "apply patch", "parameters": {}},
            {"name": "list_skills", "description": "list skills", "parameters": {}},
            {"name": "read_agent_spec", "description": "read spec", "parameters": {}},
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.runtime_context: dict[str, Any] | None = None
        self.last_runtime_context: dict[str, Any] | None = None

    def set_runtime_context(
        self,
        *,
        execution_mode: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
    ) -> None:
        payload = {
            "execution_mode": execution_mode,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "cwd": cwd,
        }
        self.runtime_context = payload
        self.last_runtime_context = dict(payload)

    def clear_runtime_context(self) -> None:
        self.runtime_context = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": True,
            "name": name,
            "project_root": str((self.runtime_context or {}).get("project_root") or ""),
            "cwd": str((self.runtime_context or {}).get("cwd") or ""),
        }


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
    (agent_dir / "identity.md").write_text(
        "# Identity\n\n角色定义：\n- primary agent\n",
        encoding="utf-8",
    )
    (agent_dir / "agent.md").write_text(
        "---\n"
        "id: vintage_programmer\n"
        "title: Vintage Programmer\n"
        "default_model: gpt-test\n"
        "tool_policy: read_only\n"
        "network_mode: explicit_tools\n"
        "approval_policy: on_failure_or_high_impact\n"
        "evidence_policy: required_for_external_or_runtime_facts\n"
        "workflow_phases:\n"
        "  - explore\n"
        "  - plan\n"
        "  - execute\n"
        "  - verify\n"
        "  - report\n"
        "max_tool_rounds: 4\n"
        "---\n"
        "\n"
        "agent workflow\n",
        encoding="utf-8",
    )
    if include_tools:
        (agent_dir / "tools.md").write_text("tool rules", encoding="utf-8")


def _isolated_config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_runtime_requires_soul_and_agent_specs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir, include_soul=False)

    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    with pytest.raises(RuntimeError, match="Missing required agent spec file"):
        runtime.descriptor()

    agent_dir = tmp_path / "agents" / "missing_identity"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "soul.md").write_text("soul", encoding="utf-8")
    (agent_dir / "agent.md").write_text("---\nid: vintage_programmer\n---\nagent\n", encoding="utf-8")
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=_FakeBackend([_FakeMessage(content="ok")]),
    )
    with pytest.raises(RuntimeError, match="Missing required agent spec file"):
        runtime.descriptor()


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
    spec = runtime._load_spec()
    prompt = runtime._render_system_prompt(ChatSettings(model="gpt-test"), spec=spec, loaded_skills=[])

    assert descriptor["agent_id"] == "vintage_programmer"
    assert descriptor["tool_policy"] == "read_only"
    assert descriptor["network"]["mode"] == "explicit_tools"
    assert descriptor["workflow"]["phases"] == ["explore", "plan", "execute", "verify", "report"]
    assert prompt.index("[soul.md]") < prompt.index("[identity.md]") < prompt.index("[agent.md]") < prompt.index("[tools.md]")


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
        context={
            "session_id": "s-1",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "final answer"
    assert result["agent_id"] == "vintage_programmer"
    assert len(result["tool_events"]) == 1
    assert backend.tools.calls[0][0] == "search_web"
    assert backend.tools.last_runtime_context["project_id"] == "project_demo"
    assert result["inspector"]["agent"]["tool_policy"] == "read_only"
    assert result["inspector"]["run_state"]["phase"] == "report"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert result["inspector"]["session"]["project_root"] == str(tmp_path)
    assert result["tool_events"][0]["project_root"] == str(tmp_path)


def test_runtime_loads_enabled_skills_and_skips_workspace_nudge_for_inline_code(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    skill_dir = tmp_path / "workspace" / "skills" / "inline_helper"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "id: inline_helper\n"
        "title: Inline Helper\n"
        "enabled: true\n"
        "bind_to:\n"
        "  - vintage_programmer\n"
        "summary: Helps with inline pasted code.\n"
        "---\n\n"
        "# Inline Helper\n\n"
        "When the user pastes code directly, analyze it in place.\n",
        encoding="utf-8",
    )
    backend = _FakeBackend([_FakeMessage(content="inline analysis complete")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="请直接分析这段代码，不要去 workspace 里再找：\n```python\nclass A:\n    def run(self):\n        return 1\n```\n这里哪里有问题？",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-inline", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert result["text"] == "inline analysis complete"
    assert result["inspector"]["run_state"]["inline_document"] is True
    assert result["inspector"]["run_state"]["requires_tools"] is False
    assert result["inspector"]["loaded_skills"][0]["id"] == "inline_helper"


def test_runtime_treats_short_pasted_code_as_direct_context_even_with_fix_language(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="直接分析短代码")])
    runtime = VintageProgrammerRuntime(
        config=config,
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我修一下这段代码：\ndef f(x):\n    return x +\n报错在哪里？",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={"session_id": "s-short-inline", "project": {"project_root": str(tmp_path)}, "history_turns": [], "attachments": []},
    )

    assert result["text"] == "直接分析短代码"
    assert result["inspector"]["run_state"]["requires_tools"] is False
