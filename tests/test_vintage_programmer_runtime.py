from __future__ import annotations

from pathlib import Path
import threading
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
            {"name": "exec_command", "description": "exec command", "parameters": {}},
            {"name": "write_stdin", "description": "write stdin", "parameters": {}},
            {"name": "read", "description": "read file or directory", "parameters": {}},
            {"name": "search_file", "description": "search one file", "parameters": {}},
            {"name": "search_file_multi", "description": "search one file with multiple queries", "parameters": {}},
            {"name": "read_section", "description": "read one section by heading", "parameters": {}},
            {"name": "table_extract", "description": "extract document tables", "parameters": {}},
            {"name": "fact_check_file", "description": "fact check one file", "parameters": {}},
            {"name": "search_codebase", "description": "search codebase", "parameters": {}},
            {"name": "web_search", "description": "search web", "parameters": {}},
            {"name": "web_fetch", "description": "fetch web", "parameters": {}},
            {"name": "web_download", "description": "download remote file", "parameters": {}},
            {"name": "browser_open", "description": "browser open", "parameters": {}},
            {"name": "sessions_list", "description": "list sessions", "parameters": {}},
            {"name": "sessions_history", "description": "session history", "parameters": {}},
            {"name": "image_inspect", "description": "inspect image", "parameters": {}},
            {"name": "image_read", "description": "read image content", "parameters": {}},
            {"name": "archive_extract", "description": "extract archive", "parameters": {}},
            {"name": "mail_extract_attachments", "description": "extract mail attachments", "parameters": {}},
            {"name": "apply_patch", "description": "apply patch", "parameters": {}},
            {"name": "update_plan", "description": "update plan", "parameters": {}},
            {"name": "request_user_input", "description": "request user input", "parameters": {}},
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
        model: str | None = None,
    ) -> None:
        payload = {
            "execution_mode": execution_mode,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "cwd": cwd,
            "model": model,
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


class _FakeToolsWithoutModel(_FakeTools):
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


class _FakeBackendWithoutModelContext(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        super().__init__(scripted_messages)
        self.tools = _FakeToolsWithoutModel()


class _CancellingTools(_FakeTools):
    def __init__(self, cancel_event: threading.Event, *, cancel_after_calls: int = 1) -> None:
        super().__init__()
        self._cancel_event = cancel_event
        self._cancel_after_calls = max(1, int(cancel_after_calls))

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().execute(name, arguments)
        if len(self.calls) >= self._cancel_after_calls:
            self._cancel_event.set()
        return result


class _FakeImageReadTools(_FakeTools):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "image_read":
            self.calls.append((name, dict(arguments)))
            path = str(arguments.get("path") or "")
            return {
                "ok": True,
                "path": path,
                "mime": "image/png",
                "width": 494,
                "height": 102,
                "visible_text": "Vintage\nVP\nnew_validation_agent",
                "analysis": "Extracted visible text from the image using local OCR.",
                "summary": "image_read · ocr_only · rapidocr",
                "diagnostics": {
                    "engines_tried": ["rapidocr"],
                    "ocr_available": True,
                    "ocr_engine": "rapidocr",
                    "fallback_reason": "no_runtime_image_reader",
                    "read_strategy": "ocr_only",
                    "visible_text_preview": "Vintage / VP / new_validation_agent",
                },
            }
        return super().execute(name, arguments)


class _FakeBackendWithTools(_FakeBackend):
    def __init__(self, scripted_messages: list[_FakeMessage], tools: _FakeTools) -> None:
        super().__init__(scripted_messages)
        self.tools = tools


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
        "collaboration_modes:\n"
        "  - default\n"
        "  - plan\n"
        "  - execute\n"
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
    assert descriptor["network"]["web_tool_contract"] == ["web_search", "web_fetch", "web_download"]
    assert descriptor["workflow"]["modes"] == ["default", "plan", "execute"]
    assert prompt.index("[soul.md]") < prompt.index("[identity.md]") < prompt.index("[agent.md]") < prompt.index("[tools.md]")


def test_runtime_runs_single_agent_tool_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}]),
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
    assert backend.tools.calls[0][0] == "web_search"
    assert backend.tools.last_runtime_context["project_id"] == "project_demo"
    assert backend.tools.last_runtime_context["model"] == "gpt-test"
    assert result["inspector"]["agent"]["tool_policy"] == "read_only"
    assert result["inspector"]["run_state"]["collaboration_mode"] == "default"
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert result["inspector"]["session"]["project_root"] == str(tmp_path)
    assert result["tool_events"][0]["project_root"] == str(tmp_path)


def test_runtime_can_continue_past_legacy_max_tool_rounds_with_internal_budget(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "one"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "read", "args": {"path": "README.md"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "search_codebase", "args": {"query": "needle"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "web_fetch", "args": {"url": "https://example.com"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "sessions_list", "args": {"limit": 5}}]),
            _FakeMessage(content="long loop done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="继续工作直到完成",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-long-loop",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["text"] == "long loop done"
    assert len(result["tool_events"]) == 5
    assert [item["name"] for item in result["tool_events"]] == [
        "web_search",
        "read",
        "search_codebase",
        "web_fetch",
        "sessions_list",
    ]
    assert result["inspector"]["run_state"]["turn_status"] == "completed"


def test_runtime_blocks_when_same_tool_repeats_too_many_times(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "same"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "web_search", "args": {"query": "same"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "web_search", "args": {"query": "same"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "web_search", "args": {"query": "same"}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "web_search", "args": {"query": "same"}}]),
            _FakeMessage(content="should not reach"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="持续搜索直到有结果",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-repeat-budget",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "blocked"
    assert "turn_budget_same_tool_repeats_exceeded" in result["inspector"]["notes"]
    assert "should not reach" not in result["text"]


def test_runtime_cancels_turn_when_cancel_event_is_set(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    cancel_event = threading.Event()
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}]),
            _FakeMessage(content="should not reach"),
        ],
        _CancellingTools(cancel_event, cancel_after_calls=1),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="先开始，再取消",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-cancelled",
            "cancel_event": cancel_event,
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
    )

    assert result["turn_status"] == "cancelled"
    assert result["text"] == "已取消当前运行。"
    assert len(result["tool_events"]) == 1
    assert "run_cancelled_by_user" in result["inspector"]["notes"]


def test_runtime_steers_image_attachment_requests_into_image_read(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
            _FakeMessage(content="", tool_calls=[{"id": "tc-image", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="图片里写着 hello world"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我看看这张图里写了什么",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image",
            "project": {
                "project_id": "project_demo",
                "project_title": "Demo",
                "project_root": str(tmp_path),
                "cwd": str(tmp_path),
            },
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里写着 hello world"
    assert result["inspector"]["run_state"]["requires_tools"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert "attachment_tooling_expected" in result["inspector"]["notes"]
    assert "image_attachment_context" in result["inspector"]["notes"]


def test_runtime_rewrites_image_tool_arguments_from_attachment_refs(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_read", "args": {"image_path": "img-1"}}],
            ),
            _FakeMessage(content="done"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我读图",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-ref",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "done"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}


def test_runtime_aliases_image_analysis_tool_name_and_attachment_ref(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_analysis", "args": {"image_path": "img-1"}}],
            ),
            _FakeMessage(content="图片里是登录报错截图"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="解释图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-alias",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里是登录报错截图"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}
    assert "tool_alias:image_analysis->image_read" in result["inspector"]["notes"]


def test_runtime_aliases_image_tool_name_and_uses_single_attached_image(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(
                content="",
                tool_calls=[{"id": "tc-image", "name": "image_tool", "args": {}}],
            ),
            _FakeMessage(content="图片里是一个登录页截图"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-tool-alias",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里是一个登录页截图"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert result["tool_events"][0]["input"] == {"path": str(image_path)}
    assert "tool_alias:image_tool->image_read" in result["inspector"]["notes"]


def test_runtime_auto_rescues_missing_context_reply_for_image_attachments(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="我需要更多上下文后才能操作这张图片。"),
            _FakeMessage(content="我理解你希望我进行操作，但是你没有提供任何任务或上下文。"),
            _FakeMessage(content="图片里显示的是 Vintage Programmer 的首页。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-auto-rescue",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["text"] == "图片里显示的是 Vintage Programmer 的首页。"
    assert backend.tools.calls == [("image_read", {"path": str(image_path)})]
    assert result["tool_events"][0]["name"] == "image_read"
    assert "strict_agentic_act_now_steer" in result["inspector"]["notes"]
    assert "auto_image_read_rescue" in result["inspector"]["notes"]


def test_runtime_finishes_with_image_read_fallback_after_repeat_loop(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc2", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc3", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc4", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="", tool_calls=[{"id": "tc5", "name": "image_read", "args": {"path": str(image_path)}}]),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-repeat-fallback",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert result["turn_status"] == "completed"
    assert "Vintage" in result["text"]
    assert "new_validation_agent" in result["text"]
    assert len(result["tool_events"]) == 5
    assert "image_read_repeat_fallback_answer" in result["inspector"]["notes"]


def test_runtime_forces_tool_based_summary_for_generic_image_read_requests(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="产品名称是 MetaPixel，Logo 也是 MetaPixel。"),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-forced-summary",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert "MetaPixel" not in result["text"]
    assert "Vintage" in result["text"]
    assert "new_validation_agent" in result["text"]
    assert "image_read_result_forced_summary" in result["inspector"]["notes"]
    assert result["tool_events"][0]["diagnostics"]["ocr_engine"] == "rapidocr"
    assert "Vintage" in result["tool_events"][0]["diagnostics"]["visible_text_preview"]


def test_runtime_restores_task_checkpoint_for_followup_turn(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackend([_FakeMessage(content="继续沿用当前任务上下文处理")])
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="让其修改",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-followup-task",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "route_state": {
                "task_checkpoint": {
                    "task_id": "task-1",
                    "goal": "Inspect the current code and patch it",
                    "project_root": str(tmp_path),
                    "cwd": str(tmp_path),
                    "active_files": [str(tmp_path / "app.py")],
                    "active_attachments": [],
                    "last_completed_step": "read: app.py",
                    "next_action": "modify app.py",
                }
            },
        },
    )

    assert result["inspector"]["run_state"]["goal"] == "Inspect the current code and patch it"
    assert result["inspector"]["run_state"]["task_checkpoint"]["task_id"] == "task-1"
    assert result["route_state"]["task_checkpoint"]["active_files"] == [str(tmp_path / "app.py")]
    assert "task_checkpoint_restored" in result["inspector"]["notes"]


def test_runtime_updates_task_checkpoint_from_successful_tool(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackendWithTools(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "image_read", "args": {"path": str(image_path)}}]),
            _FakeMessage(content="图片里是 Vintage Programmer 的首页"),
        ],
        _FakeImageReadTools(),
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="看看图片内容",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-task-checkpoint",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    checkpoint = result["route_state"]["task_checkpoint"]
    assert checkpoint["cwd"] == str(tmp_path)
    assert checkpoint["active_files"] == [str(image_path)]
    assert checkpoint["active_attachments"][0]["id"] == "img-1"
    assert checkpoint["last_completed_step"].startswith("image_read:")


def test_runtime_handles_runtime_context_setters_without_model_kwarg(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    backend = _FakeBackendWithoutModelContext(
        [
            _FakeMessage(content="", tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "latest"}}]),
            _FakeMessage(content="ok"),
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
            "session_id": "s-no-model-kw",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
        },
    )

    assert result["text"] == "ok"
    assert backend.tools.calls == [("web_search", {"query": "latest"})]
    assert backend.tools.last_runtime_context == {
        "execution_mode": None,
        "session_id": "s-no-model-kw",
        "project_id": "",
        "project_root": str(tmp_path),
        "cwd": str(tmp_path),
    }


def test_runtime_auto_rescues_image_attachment_turn_when_model_refuses_to_use_tools(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake-image")
    backend = _FakeBackend(
        [
            _FakeMessage(content="由于当前环境未配置图像文字识别（OCR）功能，我无法直接提取图片中的可见文字。"),
            _FakeMessage(content="我还是无法直接对图像执行 OCR。"),
            _FakeMessage(content="我已经根据工具结果读取了这张截图。"),
        ]
    )
    runtime = VintageProgrammerRuntime(
        config=load_config(),
        kernel_runtime=object(),
        agent_dir=agent_dir,
        backend=backend,
    )

    result = runtime.run(
        message="帮我读一下这张截图",
        settings=ChatSettings(model="gpt-test", enable_tools=True, response_style="short"),
        context={
            "session_id": "s-image-blocked",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [
                {
                    "id": "img-1",
                    "name": "screen.png",
                    "mime": "image/png",
                    "kind": "image",
                    "path": str(image_path),
                }
            ],
        },
    )

    assert [item["name"] for item in result["tool_events"]] == ["image_read"]
    assert result["inspector"]["run_state"]["requires_tools"] is True
    assert result["inspector"]["run_state"]["turn_status"] == "completed"
    assert result["inspector"]["evidence"]["status"] == "collected"
    assert "strict_agentic_act_now_steer" in result["inspector"]["notes"]
    assert "auto_image_read_rescue" in result["inspector"]["notes"]


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
