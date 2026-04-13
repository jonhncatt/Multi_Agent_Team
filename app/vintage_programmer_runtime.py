from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from app.config import AppConfig
from app.models import ChatSettings, ToolEvent
from app.openai_auth import OpenAIAuthManager
from app.workbench import WorkbenchStore, build_tool_descriptors, split_frontmatter, tool_descriptor_by_name
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
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_snapshot",
    "browser_screenshot",
    "view_image",
    "list_skills",
    "read_skill",
    "list_agent_specs",
    "read_agent_spec",
}

_EXPLICIT_NETWORK_HINTS = (
    "最新",
    "news",
    "today",
    "网页",
    "web",
    "search",
    "搜索",
    "检索",
    "截图",
    "screenshot",
    "浏览器",
    "playwright",
    "image",
    "http://",
    "https://",
    "www.",
)

_EXPLICIT_WORKSPACE_HINTS = (
    "当前工作区",
    "整个仓库",
    "整个代码库",
    "这个仓库",
    "这个 repo",
    "repo",
    "codebase",
    "目录",
    "文件树",
    "读取文件",
    "打开文件",
    "查看文件",
    "修改文件",
    "补丁",
    "patch",
    "skill",
    "skills",
    "soul.md",
    "identity.md",
    "agent.md",
    "tools.md",
    "终端",
    "shell",
    "命令行",
    "命令",
    "run shell",
    "执行命令",
)

_INLINE_DOC_CODE_FENCE_HINTS = (
    "```xml",
    "```html",
    "```json",
    "```yaml",
    "```yml",
    "```rss",
    "```atom",
    "```python",
    "```py",
    "```ts",
    "```tsx",
    "```js",
    "```jsx",
)


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(item).lower() in lowered for item in hints)


def _looks_like_explicit_tool_request(text: str) -> bool:
    raw = str(text or "").strip()
    lowered = raw.lower()
    if not raw:
        return False
    if _contains_any(lowered, _EXPLICIT_NETWORK_HINTS):
        return True
    if _contains_any(lowered, _EXPLICIT_WORKSPACE_HINTS):
        return True
    if re.search(r"(^|[\s`])(?:rg|grep|find|ls|cat|sed|head|tail|git|python|pytest|npm|pnpm|yarn)\s", lowered):
        return True
    if re.search(r"(?:^|[\s(])(?:[A-Za-z]:\\|/)[^\s]+", raw):
        return True
    if re.search(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|md|txt|html|css|sh|ps1)\b", lowered):
        return True
    return False


def _looks_like_inline_code_payload(text: str) -> bool:
    raw = str(text or "").strip()
    if len(raw) < 60:
        return False
    fenced_blocks = re.findall(r"```[A-Za-z0-9_+.-]*\n([\s\S]{80,}?)```", raw)
    code_markers = (
        "def ",
        "class ",
        "return ",
        "import ",
        "from ",
        "const ",
        "let ",
        "function ",
        "public ",
        "private ",
        "if (",
        "=>",
        "</",
        "{",
        "};",
    )
    if any(any(marker in block for marker in code_markers) for block in fenced_blocks[:3]):
        return True
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 6:
        return False
    marker_hits = sum(1 for line in lines[:40] if any(marker in line for marker in code_markers))
    punctuation_hits = sum(1 for line in lines[:40] if line.count("{") + line.count("}") + line.count(";") >= 1)
    return marker_hits >= 4 or (marker_hits >= 2 and punctuation_hits >= 4)


def _looks_like_inline_document_payload(text: str) -> bool:
    raw = str(text or "").strip()
    lowered = raw.lower()
    if any(marker in lowered for marker in _INLINE_DOC_CODE_FENCE_HINTS):
        return True
    if len(raw) < 60:
        return False
    if "<?xml" in lowered:
        return True
    if _looks_like_inline_code_payload(raw):
        return True
    xml_tag_matches = re.findall(r"</?[a-zA-Z_][\w:.-]*(?:\s[^<>]{0,200})?>", raw)
    if len(xml_tag_matches) >= 6 and ("\n" in raw or len(raw) >= 240):
        return True
    json_key_count = len(re.findall(r'"[^"\n]{1,80}"\s*:', raw))
    if json_key_count >= 4 and len(raw) >= 180:
        return True
    yaml_key_count = len(re.findall(r"(?m)^[A-Za-z0-9_.-]{1,60}:\s+\S", raw))
    return yaml_key_count >= 5 and len(raw) >= 180


def _coerce_string_list(value: Any, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if isinstance(value, list):
        cleaned = [str(item or "").strip() for item in value if str(item or "").strip()]
        return tuple(cleaned) if cleaned else tuple(default)
    return tuple(default)


def _parse_labeled_sections(text: str) -> dict[str, Any]:
    current_key = ""
    sections: dict[str, list[str]] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.endswith("："):
            current_key = line[:-1].strip()
            sections.setdefault(current_key, [])
            continue
        if current_key:
            sections.setdefault(current_key, []).append(line.lstrip("- ").strip())
    return {
        key: items if len(items) != 1 else items[0]
        for key, items in sections.items()
        if items
    }


def _truncate_goal(text: str, limit: int = 140) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class VintageProgrammerSpec:
    agent_id: str
    title: str
    default_model: str
    tool_policy: str
    network_mode: str
    approval_policy: str
    evidence_policy: str
    workflow_phases: tuple[str, ...]
    max_tool_rounds: int
    allowed_tools: tuple[str, ...]
    soul_text: str
    identity_text: str
    agent_text: str
    tools_text: str
    spec_files: tuple[str, ...]

    def descriptor(self) -> dict[str, object]:
        identity_sections = _parse_labeled_sections(self.identity_text)
        capabilities = {
            "allowed_tools": list(self.allowed_tools),
            "tool_count": len(self.allowed_tools),
            "can_network": any(name in {"search_web", "fetch_web", "download_web_file", "browser_open"} for name in self.allowed_tools),
            "can_write": any(name in {"write_text_file", "append_text_file", "replace_in_file", "apply_patch", "write_skill", "toggle_skill", "write_agent_spec"} for name in self.allowed_tools),
        }
        workflow = {
            "phases": list(self.workflow_phases),
            "default_phase": self.workflow_phases[0] if self.workflow_phases else "explore",
            "document": self.agent_text,
        }
        policies = {
            "tool_policy": self.tool_policy,
            "approval_policy": self.approval_policy,
            "evidence_policy": self.evidence_policy,
        }
        network = {
            "mode": self.network_mode,
            "web_tool_contract": ["search_web", "fetch_web", "download_web_file"],
            "browser_tool_contract": [
                "browser_open",
                "browser_click",
                "browser_type",
                "browser_wait",
                "browser_snapshot",
                "browser_screenshot",
            ],
        }
        return {
            "agent_id": self.agent_id,
            "title": self.title,
            "default_model": self.default_model,
            "tool_policy": self.tool_policy,
            "max_tool_rounds": self.max_tool_rounds,
            "allowed_tools": list(self.allowed_tools),
            "spec_files": list(self.spec_files),
            "identity": {
                "document": self.identity_text,
                "sections": identity_sections,
            },
            "workflow": workflow,
            "policies": policies,
            "network": network,
            "capabilities": capabilities,
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
        # Injected backends are treated as already-authenticated or auth-free test doubles
        # unless they opt back into the standard OpenAI auth gate.
        self._require_runtime_auth = backend is None
        self._backend = backend or create_office_runtime_backend(
            config,
            kernel_runtime=kernel_runtime,
        )
        if backend is not None:
            self._require_runtime_auth = bool(getattr(self._backend, "requires_auth", False))
        self._tool_specs = list(getattr(self._backend.tools, "tool_specs", []) or [])
        self._tool_specs_by_name = self._build_tool_spec_index()
        self._tool_descriptors = build_tool_descriptors(self._tool_specs)
        self._tool_descriptors_by_name = tool_descriptor_by_name(self._tool_specs)
        self._workbench = WorkbenchStore(config=config, agent_dir=self._agent_dir)

    def _build_tool_spec_index(self) -> dict[str, dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for item in self._tool_specs:
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
        identity_text = self._load_required_file("identity.md")
        agent_text_raw = self._load_required_file("agent.md")
        tools_text = ""
        tools_path = self._agent_dir / "tools.md"
        if tools_path.is_file():
            tools_text = tools_path.read_text(encoding="utf-8").strip()

        try:
            frontmatter, agent_text = split_frontmatter(agent_text_raw)
        except Exception as exc:
            raise RuntimeError(f"agent.md frontmatter parse failed: {exc}") from exc
        agent_id = str(frontmatter.get("id") or "vintage_programmer").strip() or "vintage_programmer"
        title = str(frontmatter.get("title") or "Vintage Programmer").strip() or "Vintage Programmer"
        default_model = str(self._config.default_model or frontmatter.get("default_model") or "").strip() or self._config.default_model
        tool_policy = str(frontmatter.get("tool_policy") or "all").strip().lower() or "all"
        if tool_policy not in {"all", "read_only", "none"}:
            tool_policy = "all"
        network_mode = str(frontmatter.get("network_mode") or "explicit_tools").strip().lower() or "explicit_tools"
        approval_policy = str(frontmatter.get("approval_policy") or "on_failure_or_high_impact").strip() or "on_failure_or_high_impact"
        evidence_policy = str(frontmatter.get("evidence_policy") or "required_for_external_or_runtime_facts").strip() or "required_for_external_or_runtime_facts"
        workflow_phases = _coerce_string_list(
            frontmatter.get("workflow_phases"),
            default=("explore", "plan", "execute", "verify", "report"),
        )
        max_tool_rounds = int(frontmatter.get("max_tool_rounds") or 8)
        max_tool_rounds = max(0, min(12, max_tool_rounds))
        explicit_tools = []
        if isinstance(frontmatter.get("allowed_tools"), list):
            explicit_tools = [str(item or "").strip() for item in frontmatter["allowed_tools"] if str(item or "").strip()]
        allowed_tools = self._resolve_allowed_tools(tool_policy=tool_policy, explicit_tools=explicit_tools)
        if not allowed_tools:
            max_tool_rounds = 0

        spec_files = ["soul.md", "identity.md", "agent.md"]
        if tools_text:
            spec_files.append("tools.md")

        return VintageProgrammerSpec(
            agent_id=agent_id,
            title=title,
            default_model=default_model,
            tool_policy=tool_policy,
            network_mode=network_mode,
            approval_policy=approval_policy,
            evidence_policy=evidence_policy,
            workflow_phases=workflow_phases,
            max_tool_rounds=max_tool_rounds,
            allowed_tools=allowed_tools,
            soul_text=soul_text,
            identity_text=identity_text,
            agent_text=agent_text.strip(),
            tools_text=tools_text,
            spec_files=tuple(spec_files),
        )

    def _enabled_skills(self, agent_id: str) -> list[dict[str, Any]]:
        return self._workbench.enabled_skills_for_agent(agent_id)

    def descriptor(self) -> dict[str, object]:
        spec = self._load_spec()
        loaded_skills = self._enabled_skills(spec.agent_id)
        payload = spec.descriptor()
        allowed_tool_descriptors = [
            dict(self._tool_descriptors_by_name.get(name) or {"name": name, "group": "", "source": "", "enabled": True, "read_only": False, "requires_evidence": False, "summary": ""})
            for name in spec.allowed_tools
        ]
        payload["capabilities"] = dict(payload.get("capabilities") or {})
        payload["capabilities"]["tools"] = allowed_tool_descriptors
        payload["capabilities"]["tool_groups"] = sorted({str(item.get("group") or "") for item in allowed_tool_descriptors if str(item.get("group") or "")})
        payload["tool_count"] = len(spec.allowed_tools)
        payload["tools"] = allowed_tool_descriptors
        payload["loaded_skills"] = [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or ""),
                "path": str(item.get("path") or ""),
            }
            for item in loaded_skills
        ]
        return payload

    def _render_system_prompt(
        self,
        settings: ChatSettings,
        *,
        spec: VintageProgrammerSpec,
        loaded_skills: list[dict[str, Any]],
    ) -> str:
        parts = [
            f"[soul.md]\n{spec.soul_text}",
            f"[identity.md]\n{spec.identity_text}",
            f"[agent.md]\n{spec.agent_text}",
        ]
        if spec.tools_text:
            parts.append(f"[tools.md]\n{spec.tools_text}")
        for skill in loaded_skills:
            skill_id = str(skill.get("id") or "").strip()
            skill_content = str(skill.get("content") or "").strip()
            if skill_id and skill_content:
                parts.append(f"[skill:{skill_id}]\n{skill_content}")
        parts.append(f"响应风格: {_STYLE_HINTS.get(settings.response_style, _STYLE_HINTS['normal'])}")
        parts.append("输出要求: 不输出思维链；不要虚构事实；不确定时明确说明；若已经使用工具，结论要基于工具结果。")
        parts.append("当用户直接在消息里粘贴代码、XML、HTML、JSON、YAML 或长文本时，应先就地分析当前消息内容，不要默认追问 workspace 路径。")
        parts.append("当用户贴出报错、代码片段、配置文本或日志时，默认把这些内容当作本轮要分析的对象；只有用户明确要求查看仓库文件、目录、网页或执行命令时，才优先调用工具。")
        parts.append("如果 runtime_context_json 里已经给出 attachments 的 name/path，就把它们视为当前轮已提供上下文，不要先否认附件或要求用户重新描述路径。")
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
            "project": dict(context.get("project") or {}),
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

    def _emit_stage(
        self,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        phase: str,
        label: str,
        detail: str,
        status: str = "running",
    ) -> None:
        if progress_cb is None:
            return
        progress_cb(
            {
                "event": "stage",
                "phase": phase,
                "label": label,
                "status": status,
                "detail": detail,
                "code": phase,
            }
        )

    def _collect_source_refs(self, result: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        candidates = [
            result.get("url"),
            result.get("path"),
            result.get("canonical_url"),
        ]
        for item in list(result.get("results") or [])[:6]:
            if isinstance(item, dict):
                candidates.extend([item.get("url"), item.get("path"), item.get("title")])
        for raw in candidates:
            value = str(raw or "").strip()
            if value and value not in refs:
                refs.append(value)
        return refs[:6]

    def _build_tool_event(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> ToolEvent:
        result_json = json.dumps(result, ensure_ascii=False)
        source_refs = self._collect_source_refs(result)
        status = "ok" if bool(result.get("ok")) else "error"
        summary = str(result.get("summary") or result.get("error") or "").strip()
        if not summary:
            summary = self._backend._shorten(result_json, 180)
        descriptor = dict(self._tool_descriptors_by_name.get(name) or {})
        group = str(descriptor.get("group") or "")
        source = str(descriptor.get("source") or "")
        return ToolEvent(
            name=name or "(unknown)",
            input=arguments,
            output_preview=self._backend._shorten(result_json, 1200),
            status=status,
            group=group,
            source=source,
            summary=summary,
            source_refs=source_refs,
            project_root=str(result.get("project_root") or ""),
            cwd=str(result.get("cwd") or ""),
            module_group=group,
        )

    def _build_answer_bundle(
        self,
        *,
        raw_text: str,
        tool_events: list[ToolEvent],
        evidence_status: str,
    ) -> dict[str, Any]:
        citations: list[dict[str, Any]] = []
        for index, item in enumerate(tool_events, start=1):
            for ref in item.source_refs[:4]:
                citations.append(
                    {
                        "id": f"tool-{index}-{len(citations) + 1}",
                        "source_type": "web" if ref.startswith("http://") or ref.startswith("https://") else "tool",
                        "kind": "evidence",
                        "tool": item.name,
                        "label": ref,
                        "url": ref if ref.startswith("http://") or ref.startswith("https://") else None,
                        "path": None if ref.startswith("http://") or ref.startswith("https://") else ref,
                        "excerpt": item.summary or item.output_preview[:240],
                        "confidence": "medium",
                    }
                )
        warnings: list[str] = []
        if evidence_status == "needs_evidence_review":
            warnings.append("任务涉及外部或运行时事实，但当前轮没有形成完整证据链。")
        return {
            "summary": raw_text[:500],
            "claims": [],
            "citations": citations,
            "warnings": warnings,
        }

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

        if self._require_runtime_auth:
            auth_summary = OpenAIAuthManager(self._config).auth_summary()
            if not bool(auth_summary.get("available")):
                raise RuntimeError(str(auth_summary.get("reason") or "LLM credentials are required"))

        context_payload = dict(context or {})
        spec = self._load_spec()
        loaded_skills = self._enabled_skills(spec.agent_id)
        requested_model = str(settings.model or spec.default_model or self._config.default_model).strip() or self._config.default_model
        selected_tools = list(spec.allowed_tools if settings.enable_tools else ())
        tool_round_limit = spec.max_tool_rounds if selected_tools else 0
        inline_document = _looks_like_inline_document_payload(prompt_message)
        expects_tools = bool(selected_tools) and not inline_document and _looks_like_explicit_tool_request(prompt_message)
        current_goal = _truncate_goal(prompt_message)
        active_phase = spec.workflow_phases[0] if spec.workflow_phases else "explore"
        project_context = dict(context_payload.get("project") or {})
        project_root = str(project_context.get("project_root") or "").strip()
        project_id = str(project_context.get("project_id") or "").strip()
        effective_cwd = str(project_context.get("cwd") or project_root or "").strip()

        messages: list[Any] = [
            self._backend._SystemMessage(content=self._render_system_prompt(settings, spec=spec, loaded_skills=loaded_skills)),
            self._backend._HumanMessage(content=self._build_human_payload(message=prompt_message, context=context_payload)),
        ]

        usage_total = self._backend._empty_usage()
        notes: list[str] = [
            f"agent_id:{spec.agent_id}",
            f"tool_policy:{spec.tool_policy}",
        ]
        if inline_document:
            notes.append("inline_document_context")
        tool_events: list[ToolEvent] = []
        effective_model = requested_model
        self._emit_stage(
            progress_cb,
            phase="explore",
            label="Explore",
            detail="已装载 agent 规范与会话上下文，开始判断是否需要工具取证。",
        )
        self._emit_stage(
            progress_cb,
            phase="plan",
            label="Plan",
            detail=f"已确定本轮目标：{current_goal or '处理当前请求'}",
            status="completed",
        )

        if hasattr(self._backend.tools, "set_runtime_context"):
            self._backend.tools.set_runtime_context(
                execution_mode=settings.execution_mode,
                session_id=str(context_payload.get("session_id") or ""),
                project_id=project_id,
                project_root=project_root,
                cwd=effective_cwd,
            )

        try:
            active_phase = "execute"
            self._emit_stage(
                progress_cb,
                phase="execute",
                label="Execute",
                detail="开始请求模型并准备执行允许的工具。",
            )
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
                        notes.append("tool_nudge_applied")
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
                    event = self._build_tool_event(name=name, arguments=arguments, result=result)
                    tool_events.append(event)
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "event": "tool",
                                "item": event.model_dump(),
                                "status": event.status,
                                "summary": event.summary,
                                "source_refs": list(event.source_refs),
                                "tool_round": round_idx + 1,
                                "tool_index": call_idx,
                                "group": event.group,
                                "agent_id": spec.agent_id,
                            }
                        )
                    result_json = json.dumps(result, ensure_ascii=False)
                    messages.append(
                        self._backend._ToolMessage(
                            content=self._backend._shorten(result_json, 60000),
                            tool_call_id=str(call.get("id") or f"{spec.agent_id}_{round_idx}_{call_idx}"),
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
        active_phase = "verify"
        self._emit_stage(
            progress_cb,
            phase="verify",
            label="Verify",
            detail="正在整理工具结果并检查证据状态。",
        )
        has_successful_tool = any(item.status == "ok" for item in tool_events)
        evidence_status = "not_needed"
        if expects_tools:
            evidence_status = "collected" if has_successful_tool else "needs_evidence_review"
            if not has_successful_tool:
                notes.append("tool_expectation_not_met")
        answer_bundle = self._build_answer_bundle(
            raw_text=raw_text,
            tool_events=tool_events,
            evidence_status=evidence_status,
        )
        if answer_bundle["warnings"]:
            notes.extend(answer_bundle["warnings"])

        active_phase = "report"
        self._emit_stage(
            progress_cb,
            phase="report",
            label="Report",
            detail="已完成本轮汇报与结果封装。",
            status="completed",
        )
        inspector = {
            "agent": self.descriptor(),
            "run_state": {
                "goal": current_goal,
                "phase": active_phase,
                "workflow_phases": list(spec.workflow_phases),
                "requires_tools": expects_tools,
                "tool_round_limit": tool_round_limit,
                "network_mode": spec.network_mode,
                "inline_document": inline_document,
                "project_root": project_root,
                "cwd": effective_cwd,
            },
            "tool_timeline": [item.model_dump() for item in tool_events],
            "evidence": {
                "status": evidence_status,
                "required": expects_tools,
                "warning": answer_bundle["warnings"][0] if answer_bundle["warnings"] else "",
                "source_refs": [ref for item in tool_events for ref in item.source_refs][:12],
                "tool_count": len(tool_events),
            },
            "session": {
                "session_id": str(context_payload.get("session_id") or ""),
                "project_id": project_id,
                "project_title": str(project_context.get("project_title") or ""),
                "project_root": project_root,
                "git_branch": str(project_context.get("git_branch") or ""),
                "cwd": effective_cwd,
                "history_turn_count": len(list(context_payload.get("history_turns") or [])),
                "attachment_count": len(list(context_payload.get("attachments") or [])),
            },
            "token_usage": dict(usage_total),
            "loaded_skills": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or ""),
                    "summary": str(item.get("summary") or ""),
                    "path": str(item.get("path") or ""),
                }
                for item in loaded_skills
            ],
            "notes": self._dedup_notes(notes),
        }

        return {
            "ok": True,
            "agent_id": spec.agent_id,
            "agent_title": spec.title,
            "text": raw_text,
            "effective_model": effective_model or requested_model,
            "tool_events": [item.model_dump() for item in tool_events],
            "token_usage": usage_total,
            "inspector": inspector,
            "answer_bundle": answer_bundle,
            "route_state": {
                "agent_id": spec.agent_id,
                "tool_policy": spec.tool_policy,
                "phase": active_phase,
                "network_mode": spec.network_mode,
                "evidence_status": evidence_status,
                "tool_count": len(tool_events),
                "loaded_skill_ids": [str(item.get("id") or "") for item in loaded_skills],
                "inline_document": inline_document,
                "project_id": project_id,
                "project_root": project_root,
                "cwd": effective_cwd,
            },
        }
