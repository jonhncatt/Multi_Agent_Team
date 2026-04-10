from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

import yaml

from app.config import AppConfig
from app.models import ChatSettings, ToolEvent
from app.openai_auth import OpenAIAuthManager
from packages.office_modules.office_agent_runtime import create_office_runtime_backend


_STYLE_HINTS = {
    "short": "回答尽量简短，先给结论，再给最多 3 条关键点。",
    "normal": "回答清晰、可执行，避免冗长。",
    "long": "回答可以更详细，但保持结构化，优先给行动建议。",
}

_READ_ONLY_TOOL_NAMES = {
    "run_shell",
    "list_directory",
    "search_codebase",
    "copy_file",
    "extract_zip",
    "extract_msg_attachments",
    "read_text_file",
    "search_text_in_file",
    "multi_query_search",
    "doc_index_build",
    "read_section_by_heading",
    "table_extract",
    "fact_check_file",
    "fetch_web",
    "download_web_file",
    "search_web",
    "list_sessions",
    "read_session_history",
}

_TOOL_REQUIRED_HINTS = (
    "最新",
    "news",
    "today",
    "网页",
    "web",
    "search",
    "搜索",
    "检索",
    "文件",
    "附件",
    "read",
    "查看代码",
    "codebase",
    "代码库",
    "run",
    "执行",
    "修复",
    "fix",
    "写入",
    "保存",
    "update",
)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    raw = str(text or "")
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    frontmatter = raw[4:end]
    body = raw[end + 5 :]
    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except Exception as exc:
        raise RuntimeError(f"agent.md frontmatter parse failed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("agent.md frontmatter must be a mapping")
    return parsed, body


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(item).lower() in lowered for item in hints)


@dataclass(frozen=True, slots=True)
class VintageProgrammerSpec:
    agent_id: str
    title: str
    default_model: str
    tool_policy: str
    max_tool_rounds: int
    allowed_tools: tuple[str, ...]
    soul_text: str
    agent_text: str
    tools_text: str
    spec_files: tuple[str, ...]

    def descriptor(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "title": self.title,
            "default_model": self.default_model,
            "tool_policy": self.tool_policy,
            "max_tool_rounds": self.max_tool_rounds,
            "allowed_tools": list(self.allowed_tools),
            "spec_files": list(self.spec_files),
        }


class VintageProgrammerRuntime:
    def __init__(
        self,
        *,
        config: AppConfig,
        kernel_runtime: Any,
        agent_dir: Path,
        backend: Any | None = None,
    ) -> None:
        self._config = config
        self._agent_dir = agent_dir.resolve()
        self._backend = backend or create_office_runtime_backend(
            config,
            kernel_runtime=kernel_runtime,
        )
        self._tool_specs_by_name = self._build_tool_spec_index()
        self._spec = self._load_spec()

    def _build_tool_spec_index(self) -> dict[str, dict[str, Any]]:
        specs = list(getattr(self._backend.tools, "tool_specs", []) or [])
        by_name: dict[str, dict[str, Any]] = {}
        for item in specs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            by_name[name] = dict(item)
        return by_name

    def _load_required_file(self, name: str) -> str:
        path = self._agent_dir / name
        if not path.is_file():
            raise RuntimeError(f"Missing required agent spec file: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _resolve_allowed_tools(self, *, tool_policy: str, explicit_tools: list[str]) -> tuple[str, ...]:
        if explicit_tools:
            names = [name for name in explicit_tools if name in self._tool_specs_by_name]
            return tuple(names)
        if tool_policy == "none":
            return ()
        if tool_policy == "read_only":
            return tuple(name for name in self._tool_specs_by_name if name in _READ_ONLY_TOOL_NAMES)
        return tuple(self._tool_specs_by_name.keys())

    def _load_spec(self) -> VintageProgrammerSpec:
        soul_text = self._load_required_file("soul.md")
        agent_text_raw = self._load_required_file("agent.md")
        tools_text = ""
        tools_path = self._agent_dir / "tools.md"
        if tools_path.is_file():
            tools_text = tools_path.read_text(encoding="utf-8").strip()

        frontmatter, agent_text = _split_frontmatter(agent_text_raw)
        agent_id = str(frontmatter.get("id") or "vintage_programmer").strip() or "vintage_programmer"
        title = str(frontmatter.get("title") or "Vintage Programmer").strip() or "Vintage Programmer"
        default_model = str(frontmatter.get("default_model") or self._config.default_model).strip() or self._config.default_model
        tool_policy = str(frontmatter.get("tool_policy") or "all").strip().lower() or "all"
        if tool_policy not in {"all", "read_only", "none"}:
            tool_policy = "all"
        max_tool_rounds = int(frontmatter.get("max_tool_rounds") or 8)
        max_tool_rounds = max(0, min(12, max_tool_rounds))
        explicit_tools = []
        if isinstance(frontmatter.get("allowed_tools"), list):
            explicit_tools = [str(item or "").strip() for item in frontmatter["allowed_tools"] if str(item or "").strip()]
        allowed_tools = self._resolve_allowed_tools(tool_policy=tool_policy, explicit_tools=explicit_tools)
        if not allowed_tools:
            max_tool_rounds = 0

        spec_files = ["soul.md", "agent.md"]
        if tools_text:
            spec_files.append("tools.md")

        return VintageProgrammerSpec(
            agent_id=agent_id,
            title=title,
            default_model=default_model,
            tool_policy=tool_policy,
            max_tool_rounds=max_tool_rounds,
            allowed_tools=allowed_tools,
            soul_text=soul_text,
            agent_text=agent_text.strip(),
            tools_text=tools_text,
            spec_files=tuple(spec_files),
        )

    def descriptor(self) -> dict[str, object]:
        payload = self._spec.descriptor()
        payload["tool_count"] = len(self._spec.allowed_tools)
        payload["tools"] = [
            {
                "name": name,
                "description": str((self._tool_specs_by_name.get(name) or {}).get("description") or "").strip(),
            }
            for name in self._spec.allowed_tools
        ]
        return payload

    def _render_system_prompt(self, settings: ChatSettings) -> str:
        parts = [
            f"[soul.md]\n{self._spec.soul_text}",
            f"[agent.md]\n{self._spec.agent_text}",
        ]
        if self._spec.tools_text:
            parts.append(f"[tools.md]\n{self._spec.tools_text}")
        parts.append(f"响应风格: {_STYLE_HINTS.get(settings.response_style, _STYLE_HINTS['normal'])}")
        parts.append("输出要求: 不输出思维链；不要虚构事实；不确定时明确说明；若已经使用工具，结论要基于工具结果。")
        return "\n\n".join(item for item in parts if str(item).strip())

    def _build_human_payload(self, *, message: str, context: dict[str, Any]) -> str:
        history_turns = list(context.get("history_turns") or [])
        recent_history = [
            {
                "role": str(item.get("role") or ""),
                "text": str(item.get("text") or "")[:1200],
            }
            for item in history_turns[-8:]
            if isinstance(item, dict)
        ]
        payload = {
            "session_id": str(context.get("session_id") or ""),
            "summary": str(context.get("summary") or "")[:4000],
            "route_state": dict(context.get("route_state") or {}),
            "attachments": list(context.get("attachments") or []),
            "history_turns": recent_history,
        }
        return "\n".join(
            [
                "user_message:",
                str(message or "").strip(),
                "",
                "runtime_context_json:",
                json.dumps(payload, ensure_ascii=False),
            ]
        )

    def _dedup_notes(self, notes: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in notes:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    def run(
        self,
        *,
        message: str,
        settings: ChatSettings,
        context: dict[str, Any] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        prompt_message = str(message or "").strip()
        if not prompt_message:
            raise ValueError("message cannot be empty")

        auth_summary = OpenAIAuthManager(self._config).auth_summary()
        if not bool(auth_summary.get("available")):
            raise RuntimeError(str(auth_summary.get("reason") or "LLM credentials are required"))

        context_payload = dict(context or {})
        requested_model = str(settings.model or self._spec.default_model or self._config.default_model).strip() or self._config.default_model
        selected_tools = list(self._spec.allowed_tools if settings.enable_tools else ())
        tool_round_limit = self._spec.max_tool_rounds if selected_tools else 0
        expects_tools = bool(selected_tools) and _contains_any(prompt_message, _TOOL_REQUIRED_HINTS)

        messages: list[Any] = [
            self._backend._SystemMessage(content=self._render_system_prompt(settings)),
            self._backend._HumanMessage(content=self._build_human_payload(message=prompt_message, context=context_payload)),
        ]

        usage_total = self._backend._empty_usage()
        notes: list[str] = [
            f"agent_id:{self._spec.agent_id}",
            f"tool_policy:{self._spec.tool_policy}",
        ]
        tool_events: list[ToolEvent] = []

        if hasattr(self._backend.tools, "set_runtime_context"):
            self._backend.tools.set_runtime_context(
                execution_mode=settings.execution_mode,
                session_id=str(context_payload.get("session_id") or ""),
            )

        try:
            ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_chat_with_runner(
                messages=messages,
                model=requested_model,
                max_output_tokens=int(settings.max_output_tokens),
                enable_tools=bool(selected_tools),
                tool_names=selected_tools if selected_tools else None,
            )
            notes.extend(invoke_notes)
            usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))

            tool_nudge_budget = 1 if expects_tools and tool_round_limit > 0 else 0

            for round_idx in range(tool_round_limit):
                tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
                if not tool_calls:
                    if tool_nudge_budget > 0 and not tool_events:
                        tool_nudge_budget -= 1
                        messages.append(ai_msg)
                        messages.append(
                            self._backend._SystemMessage(
                                content="当前任务需要先调用至少一个合适工具再下结论。请先完成取证或执行，再输出结果。"
                            )
                        )
                        ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_with_runner_recovery(
                            runner=runner,
                            messages=messages,
                            model=effective_model,
                            max_output_tokens=int(settings.max_output_tokens),
                            enable_tools=True,
                            tool_names=selected_tools,
                        )
                        notes.extend(invoke_notes)
                        usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
                        continue
                    break

                messages.append(ai_msg)
                for call_idx, call in enumerate(tool_calls[:8], start=1):
                    name = str(call.get("name") or "").strip()
                    arguments = call.get("args")
                    if not isinstance(arguments, dict):
                        arguments = {}
                    if name and name in selected_tools:
                        result = self._backend.tools.execute(name, arguments)
                    else:
                        result = {
                            "ok": False,
                            "error": f"Tool not allowed: {name or '(empty)'}",
                            "allowed_tools": selected_tools,
                        }
                    result_json = json.dumps(result, ensure_ascii=False)
                    event = ToolEvent(
                        name=name or "(unknown)",
                        input=arguments,
                        output_preview=self._backend._shorten(result_json, 1200),
                    )
                    tool_events.append(event)
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "event": "tool",
                                "item": event.model_dump(),
                                "tool_round": round_idx + 1,
                                "tool_index": call_idx,
                                "agent_id": self._spec.agent_id,
                            }
                        )
                    messages.append(
                        self._backend._ToolMessage(
                            content=self._backend._shorten(result_json, 60000),
                            tool_call_id=str(call.get("id") or f"{self._spec.agent_id}_{round_idx}_{call_idx}"),
                            name=name or "unknown_tool",
                        )
                    )

                ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_with_runner_recovery(
                    runner=runner,
                    messages=messages,
                    model=effective_model,
                    max_output_tokens=int(settings.max_output_tokens),
                    enable_tools=True,
                    tool_names=selected_tools,
                )
                notes.extend(invoke_notes)
                usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
        finally:
            if hasattr(self._backend.tools, "clear_runtime_context"):
                self._backend.tools.clear_runtime_context()

        raw_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
        if not raw_text:
            raw_text = "(empty response)"
        if expects_tools and not tool_events:
            notes.append("tool_expectation_not_met")

        inspector = {
            "agent": self._spec.descriptor(),
            "notes": self._dedup_notes(notes),
            "session": {
                "session_id": str(context_payload.get("session_id") or ""),
                "history_turn_count": len(list(context_payload.get("history_turns") or [])),
                "attachment_count": len(list(context_payload.get("attachments") or [])),
            },
            "token_usage": dict(usage_total),
            "tool_count": len(tool_events),
            "tool_names": [item.name for item in tool_events],
        }

        return {
            "ok": True,
            "agent_id": self._spec.agent_id,
            "agent_title": self._spec.title,
            "text": raw_text,
            "effective_model": effective_model or requested_model,
            "tool_events": [item.model_dump() for item in tool_events],
            "token_usage": usage_total,
            "inspector": inspector,
            "answer_bundle": {
                "summary": raw_text[:500],
                "claims": [],
                "citations": [],
                "warnings": [],
            },
            "route_state": {
                "agent_id": self._spec.agent_id,
                "tool_policy": self._spec.tool_policy,
                "tool_count": len(tool_events),
            },
        }
