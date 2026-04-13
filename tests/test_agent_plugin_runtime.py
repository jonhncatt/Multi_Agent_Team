from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_config
from app.agents import plugin_runtime as plugin_runtime_mod


class _FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = list(tool_calls or [])


class _FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tool_specs = [
            {
                "name": "search_web",
                "description": "search web",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "read_text_file",
                "description": "read text file",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(args)))
        return {"ok": True, "tool": name}


class _FakeBackend:
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        self._scripted_messages = list(scripted_messages)
        self.tools = _FakeTools()
        self._SystemMessage = _FakeMessage
        self._HumanMessage = _FakeMessage
        self._ToolMessage = _FakeMessage
        self.recovery_calls = 0

    def _next_message(self) -> _FakeMessage:
        if self._scripted_messages:
            return self._scripted_messages.pop(0)
        return _FakeMessage(content="{}")

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
        return self._next_message(), object(), model, []

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
        self.recovery_calls += 1
        return self._next_message(), runner, model, []


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_runtime(
    tmp_path: Path,
    monkeypatch,
    *,
    manifest_payload: dict[str, Any] | None = None,
    manifest_payloads: list[dict[str, Any]] | None = None,
    scripted_messages: list[_FakeMessage],
):
    backend = _FakeBackend(scripted_messages)
    manifest_dir = tmp_path / "manifests"
    payloads = list(manifest_payloads or [])
    if manifest_payload is not None:
        payloads.append(dict(manifest_payload))
    if not payloads:
        raise ValueError("manifest payload is required")
    for payload in payloads:
        _write_manifest(manifest_dir / f"{payload['plugin_id']}.json", payload)

    monkeypatch.setattr(plugin_runtime_mod, "create_office_runtime_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(
        plugin_runtime_mod.OpenAIAuthManager,
        "auth_summary",
        lambda self: {"available": True, "reason": "", "provider": "test"},
    )

    runtime = plugin_runtime_mod.AgentPluginRuntime(
        config=load_config(),
        kernel_runtime=object(),
        manifest_dir=manifest_dir,
    )
    return runtime, backend


def test_quality_preset_applies_to_minimal_manifest(tmp_path, monkeypatch):
    runtime, _backend = _build_runtime(
        tmp_path,
        monkeypatch,
        manifest_payload={
            "plugin_id": "planner_agent",
            "title": "Planner Agent",
            "description": "planner",
            "tool_profile": "none",
            "allowed_tools": [],
            "max_tool_rounds": 0,
            "system_prompt": "你是 Planner Agent。",
        },
        scripted_messages=[_FakeMessage(content="{}")],
    )

    manifests = runtime.list_manifests()
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.quality_profile == "planning_contract_v2"
    assert manifest.response_mode == "json"
    assert "plan" in manifest.response_keys
    assert len(manifest.stop_rules) >= 2


def test_json_contract_fallback_when_model_returns_plain_text(tmp_path, monkeypatch):
    runtime, _backend = _build_runtime(
        tmp_path,
        monkeypatch,
        manifest_payload={
            "plugin_id": "summarizer_agent",
            "title": "Summarizer Agent",
            "description": "summarizer",
            "tool_profile": "none",
            "allowed_tools": [],
            "max_tool_rounds": 0,
            "system_prompt": "你是 Summarizer Agent。",
        },
        scripted_messages=[_FakeMessage(content="这是普通文本，不是 JSON")],
    )

    result = runtime.run_plugin(
        plugin_id="summarizer_agent",
        message="请总结下面内容",
        settings=plugin_runtime_mod.ChatSettings(model="gpt-test", max_output_tokens=1000, max_context_turns=20, enable_tools=False),
        context={},
    )

    payload = json.loads(result["text"])
    assert isinstance(payload, dict)
    assert "summary" in payload
    assert any(str(note).startswith("response_contract_json_fallback") for note in result["notes"])


def test_tool_expectation_nudges_when_no_tool_call(tmp_path, monkeypatch):
    runtime, backend = _build_runtime(
        tmp_path,
        monkeypatch,
        manifest_payload={
            "plugin_id": "researcher_agent",
            "title": "Researcher Agent",
            "description": "research",
            "tool_profile": "web",
            "allowed_tools": ["search_web"],
            "max_tool_rounds": 2,
            "system_prompt": "你是 Researcher Agent。",
        },
        scripted_messages=[
            _FakeMessage(content="我直接回答，不用工具", tool_calls=[]),
            _FakeMessage(content="仍然没有工具调用", tool_calls=[]),
        ],
    )

    result = runtime.run_plugin(
        plugin_id="researcher_agent",
        message="请给我最新新闻",
        settings=plugin_runtime_mod.ChatSettings(model="gpt-test", max_output_tokens=1200, max_context_turns=20, enable_tools=True),
        context={},
    )

    assert backend.recovery_calls >= 1
    assert any(str(note).startswith("tool_expectation_not_met") for note in result["notes"])


def test_swarm_parent_child_tree_is_returned(tmp_path, monkeypatch):
    runtime, _backend = _build_runtime(
        tmp_path,
        monkeypatch,
        manifest_payloads=[
            {
                "plugin_id": "coordinator_agent",
                "title": "Coordinator Agent",
                "description": "coord",
                "supports_swarm": True,
                "swarm_mode": "supervisor",
                "tool_profile": "none",
                "allowed_tools": [],
                "max_tool_rounds": 0,
                "system_prompt": "你是 Coordinator Agent。",
            },
            {
                "plugin_id": "planner_agent",
                "title": "Planner Agent",
                "description": "planner",
                "supports_swarm": True,
                "swarm_mode": "plan-then-swarm",
                "tool_profile": "none",
                "allowed_tools": [],
                "max_tool_rounds": 0,
                "system_prompt": "你是 Planner Agent。",
            },
        ],
        scripted_messages=[
            _FakeMessage(content='{"objective":"coord","constraints":[],"plan":[],"watchouts":[],"success_signals":[]}'),
            _FakeMessage(content='{"objective":"plan","constraints":[],"plan":[],"watchouts":[],"success_signals":[]}'),
        ],
    )

    result = runtime.run_plugin(
        plugin_id="coordinator_agent",
        message="请用 swarm 父子分支并行拆解这个任务。",
        settings=plugin_runtime_mod.ChatSettings(model="gpt-test", max_output_tokens=1200, max_context_turns=20, enable_tools=False),
        context={"swarm": {"enabled": True, "max_depth": 2, "max_children": 2}},
    )

    assert result["ok"] is True
    swarm = dict((result.get("decision") or {}).get("swarm") or {})
    assert swarm.get("enabled") is True
    assert int(swarm.get("node_count") or 0) >= 2
    tree = dict(swarm.get("tree") or {})
    assert tree.get("plugin_id") == "coordinator_agent"
    assert len(list(tree.get("children") or [])) >= 1
    assert any(str(note).startswith("swarm_enabled:coordinator_agent") for note in result.get("notes") or [])


def test_swarm_can_be_disabled_for_swarm_plugin(tmp_path, monkeypatch):
    runtime, _backend = _build_runtime(
        tmp_path,
        monkeypatch,
        manifest_payload={
            "plugin_id": "researcher_agent",
            "title": "Researcher Agent",
            "description": "research",
            "supports_swarm": True,
            "swarm_mode": "parallel-research",
            "tool_profile": "none",
            "allowed_tools": [],
            "max_tool_rounds": 0,
            "system_prompt": "你是 Researcher Agent。",
        },
        scripted_messages=[_FakeMessage(content='{"summary":"ok","evidence":[],"sources":[],"open_questions":[],"next_steps":[]}')],
    )

    result = runtime.run_plugin(
        plugin_id="researcher_agent",
        message="swarm 测试，但这次禁用。",
        settings=plugin_runtime_mod.ChatSettings(model="gpt-test", max_output_tokens=900, max_context_turns=20, enable_tools=False),
        context={"swarm": {"enabled": False}},
    )

    assert result["ok"] is True
    assert "swarm" not in dict(result.get("decision") or {})
