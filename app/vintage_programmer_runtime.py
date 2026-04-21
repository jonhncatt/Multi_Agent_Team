from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
import uuid

from app.config import AppConfig
from app.models import ChatSettings, ToolEvent
from app.openai_auth import OpenAIAuthManager
from app.session_context import compat_task_checkpoint_from_focus, normalize_current_task_focus
from app.workbench import WorkbenchStore, build_tool_descriptors, split_frontmatter, tool_descriptor_by_name
from packages.office_modules.intent_support import (
    has_image_attachments as has_image_attachments_helper,
    looks_like_image_capability_denial as looks_like_image_capability_denial_helper,
)
from packages.office_modules.office_agent_runtime import create_office_runtime_backend


_STYLE_HINTS = {
    "short": "回答尽量简短，先给结论，再给最多 3 条关键点。",
    "normal": "回答清晰、可执行，避免冗长。",
    "long": "回答可以更详细，但保持结构化，优先给行动建议。",
}

_READ_ONLY_TOOL_NAMES = {
    "read",
    "search_file",
    "search_file_multi",
    "read_section",
    "table_extract",
    "fact_check_file",
    "search_codebase",
    "web_search",
    "web_fetch",
    "image_read",
    "sessions_list",
    "sessions_history",
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_snapshot",
    "browser_screenshot",
    "image_inspect",
    "update_plan",
    "request_user_input",
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

_TOOL_NAME_ALIASES = {
    "analyze_image": "image_read",
    "download_web_file": "web_download",
    "extract_msg_attachments": "mail_extract_attachments",
    "extract_zip": "archive_extract",
    "fetch_web": "web_fetch",
    "image_analysis": "image_read",
    "image_analyze": "image_read",
    "image_ocr": "image_read",
    "image_reader": "image_read",
    "image_to_text": "image_read",
    "image_tool": "image_read",
    "list_sessions": "sessions_list",
    "multi_query_search": "search_file_multi",
    "ocr_image": "image_read",
    "read_image": "image_read",
    "read_section_by_heading": "read_section",
    "read_session_history": "sessions_history",
    "read_text_file": "read",
    "search_text_in_file": "search_file",
    "search_web": "web_search",
    "view_image": "image_inspect",
}

_DEFAULT_MAX_TOOL_CALLS_PER_TURN = 24
_DEFAULT_MAX_TURN_SECONDS = 1800
_DEFAULT_MAX_SAME_TOOL_REPEATS = 4
_DEFAULT_MAX_NO_PROGRESS_CYCLES = 4
_DEFAULT_COMPACT_AFTER_TOOL_CALLS = 8
_DEFAULT_COMPACT_KEEP_LAST_MESSAGES = 10
_IMAGE_READ_TOOL_HINTS = (
    "image",
    "screenshot",
    "picture",
    "photo",
    "vision",
)
_IMAGE_READ_ACTION_HINTS = (
    "read",
    "ocr",
    "analy",
    "describe",
    "caption",
    "tool",
)
_IMAGE_INSPECT_ACTION_HINTS = (
    "inspect",
    "meta",
    "info",
    "size",
    "dimension",
)
_MISSING_CONTEXT_RESPONSE_HINTS = (
    "没有提供任何任务",
    "没有提供任何上下文",
    "没有提供任何需要我处理的具体任务",
    "请告诉我你需要我做什么",
    "请您告诉我",
    "you have not provided any task",
    "you haven't provided any task",
    "you have not provided any context",
    "you haven't provided any context",
    "please tell me what you need me to do",
)
_GENERIC_IMAGE_READ_REQUEST_HINTS = (
    "看看图片内容",
    "解释图片内容",
    "看图",
    "读图",
    "读取图片",
    "读取截图",
    "识别图片",
    "识别截图",
    "提取图片文字",
    "提取截图文字",
    "图片里写了什么",
    "截图里写了什么",
    "查看附件内容",
    "read this image",
    "describe this image",
    "what is in this image",
    "what's in this image",
    "read image",
    "analyze image",
    "ocr this image",
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
    collaboration_modes: tuple[str, ...]
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
            "can_network": any(name in {"web_search", "web_fetch", "web_download", "browser_open"} for name in self.allowed_tools),
            "can_write": any(
                name in {"exec_command", "write_stdin", "apply_patch", "web_download", "archive_extract", "mail_extract_attachments"}
                for name in self.allowed_tools
            ),
        }
        workflow = {
            "modes": list(self.collaboration_modes),
            "phases": list(self.collaboration_modes),
            "default_mode": self.collaboration_modes[0] if self.collaboration_modes else "default",
            "document": self.agent_text,
        }
        policies = {
            "tool_policy": self.tool_policy,
            "approval_policy": self.approval_policy,
            "evidence_policy": self.evidence_policy,
        }
        network = {
            "mode": self.network_mode,
            "web_tool_contract": ["web_search", "web_fetch", "web_download"],
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
        collaboration_modes = _coerce_string_list(
            frontmatter.get("collaboration_modes") or frontmatter.get("workflow_phases"),
            default=("default", "plan", "execute"),
        )
        collaboration_modes = tuple(
            item for item in collaboration_modes if item in {"default", "plan", "execute"}
        ) or ("default", "plan", "execute")
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
            collaboration_modes=collaboration_modes,
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
        parts.append("如果 runtime_context_json.current_task_focus 里已经给出 goal/cwd/active_files/active_attachments，就把它们当作当前任务的硬上下文继续推进；不要重复声称不知道目录、文件或附件。")
        parts.append("如果 runtime_context_json.thread_memory.recent_tasks 或 recalled_context 里已经给出近期任务/附件回忆结果，回答'刚刚让我做什么'、'之前那张图'、'那封邮件'这类问题时必须优先基于这些结构化记忆。")
        parts.append("如果附件是图片，需要优先使用 image_read(path=...) 读取可见文字和画面内容；不要只报元数据，也不要声称未配置 OCR 或无法看图。")
        parts.append("如果附件是文档或 .msg，需要优先用 read/search_file/read_section/table_extract 等工具读取内容，不要只根据文件名猜测。")
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
        attachments = [
            {
                "name": str(item.get("name") or item.get("original_name") or ""),
                "mime": str(item.get("mime") or ""),
                "kind": str(item.get("kind") or ""),
                "path": str(item.get("path") or ""),
            }
            for item in list(context.get("attachments") or [])
            if isinstance(item, dict)
        ]
        route_state = dict(context.get("route_state") or {})
        current_task_focus = normalize_current_task_focus(
            context.get("current_task_focus")
            or route_state.get("current_task_focus")
            or route_state.get("task_checkpoint")
        )
        thread_memory = dict(context.get("thread_memory") or {})
        recent_tasks = list(context.get("recent_tasks") or thread_memory.get("recent_tasks") or [])
        artifact_memory_preview = list(context.get("artifact_memory_preview") or [])
        payload = {
            "session_id": str(context.get("session_id") or ""),
            "project": dict(context.get("project") or {}),
            "summary": str(context.get("summary") or "")[:4000],
            "thread_memory": {
                "summary": str(thread_memory.get("summary") or "")[:4000],
                "recent_tasks": recent_tasks[:8],
                "recent_cwds": list(thread_memory.get("recent_cwds") or [])[:6],
                "recent_files": list(thread_memory.get("recent_files") or [])[:8],
            },
            "route_state": route_state,
            "current_task_focus": current_task_focus,
            "recent_tasks": recent_tasks[:8],
            "artifact_memory_preview": artifact_memory_preview[:8],
            "recalled_context": dict(context.get("recalled_context") or {}),
            "user_input_response": dict(context.get("user_input_response") or {}),
            "attachments": attachments,
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

    @staticmethod
    def _build_run_snapshot(
        *,
        goal: str,
        current_task_focus: dict[str, Any],
        collaboration_mode: str,
        turn_status: str,
        plan_state: list[dict[str, Any]],
        pending_user_input: dict[str, Any],
        effective_cwd: str,
        evidence_status: str,
        tool_events: list[ToolEvent],
    ) -> dict[str, Any]:
        return {
            "goal": str(goal or "").strip(),
            "collaboration_mode": str(collaboration_mode or "default"),
            "turn_status": str(turn_status or "running"),
            "cwd": str(effective_cwd or current_task_focus.get("cwd") or "").strip(),
            "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
            "plan": [dict(item) for item in list(plan_state or [])[:12] if isinstance(item, dict)],
            "pending_user_input": dict(pending_user_input or {}),
            "tool_count": len(tool_events),
            "evidence_status": str(evidence_status or "not_needed"),
        }

    def _emit_stage(
        self,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        phase: str,
        label: str,
        detail: str,
        status: str = "running",
        run_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if progress_cb is None:
            return
        payload = {
            "event": "stage",
            "phase": phase,
            "label": label,
            "status": status,
            "detail": detail,
            "code": phase,
        }
        if run_snapshot:
            payload["run_snapshot"] = dict(run_snapshot)
        progress_cb(payload)

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
        diagnostics = dict(result.get("diagnostics") or {}) if isinstance(result.get("diagnostics"), dict) else {}
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
            diagnostics=diagnostics,
            source_refs=source_refs,
            project_root=str(result.get("project_root") or ""),
            cwd=str(result.get("cwd") or ""),
            module_group=group,
        )

    @staticmethod
    def _attachment_refs(attachments: list[dict[str, Any]]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in attachments:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            key = path or str(item.get("id") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "id": str(item.get("id") or "").strip(),
                    "name": str(item.get("name") or item.get("original_name") or "").strip(),
                    "kind": str(item.get("kind") or "").strip(),
                    "path": path,
                }
            )
        return refs[:8]

    @staticmethod
    def _normalize_task_checkpoint(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        active_files: list[str] = []
        for item in list(raw.get("active_files") or [])[:8]:
            value = str(item or "").strip()
            if value and value not in active_files:
                active_files.append(value)
        active_attachments: list[dict[str, str]] = []
        seen_attachment_keys: set[str] = set()
        for item in list(raw.get("active_attachments") or [])[:8]:
            if not isinstance(item, dict):
                continue
            ref = {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "kind": str(item.get("kind") or "").strip(),
                "path": str(item.get("path") or "").strip(),
            }
            key = ref["path"] or ref["id"] or ref["name"]
            if not key or key in seen_attachment_keys:
                continue
            seen_attachment_keys.add(key)
            active_attachments.append(ref)
        return {
            "task_id": str(raw.get("task_id") or "").strip(),
            "goal": str(raw.get("goal") or "").strip(),
            "project_root": str(raw.get("project_root") or "").strip(),
            "cwd": str(raw.get("cwd") or "").strip(),
            "active_files": active_files,
            "active_attachments": active_attachments,
            "last_completed_step": str(raw.get("last_completed_step") or "").strip(),
            "next_action": str(raw.get("next_action") or "").strip(),
        }

    def _initial_task_checkpoint(
        self,
        *,
        route_state: dict[str, Any],
        project_root: str,
        cwd: str,
        goal: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        restored = self._normalize_task_checkpoint((route_state or {}).get("task_checkpoint"))
        if restored:
            restored["task_id"] = restored.get("task_id") or str(uuid.uuid4())
            restored["project_root"] = restored.get("project_root") or project_root
            restored["cwd"] = restored.get("cwd") or cwd or project_root
            restored["goal"] = restored.get("goal") or goal
            if attachments:
                restored["active_attachments"] = self._attachment_refs(attachments)
            return restored
        return {
            "task_id": str(uuid.uuid4()),
            "goal": goal,
            "project_root": project_root,
            "cwd": cwd or project_root,
            "active_files": [],
            "active_attachments": self._attachment_refs(attachments),
            "last_completed_step": "",
            "next_action": "",
        }

    @staticmethod
    def _maybe_add_active_file(paths: list[str], raw_path: Any) -> None:
        value = str(raw_path or "").strip()
        if not value or value.startswith("http://") or value.startswith("https://"):
            return
        candidate = Path(value)
        if not candidate.is_absolute():
            return
        try:
            if candidate.exists() and candidate.is_dir():
                return
        except Exception:
            pass
        if value not in paths:
            paths.append(value)

    def _task_checkpoint_from_tool(
        self,
        *,
        checkpoint: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        attachments: list[dict[str, Any]],
        fallback_project_root: str,
        fallback_cwd: str,
    ) -> dict[str, Any]:
        updated = self._normalize_task_checkpoint(checkpoint)
        if not updated:
            updated = self._initial_task_checkpoint(
                route_state={},
                project_root=fallback_project_root,
                cwd=fallback_cwd,
                goal="",
                attachments=attachments,
            )
        updated["project_root"] = str(result.get("project_root") or updated.get("project_root") or fallback_project_root or "").strip()
        next_cwd = str(result.get("cwd") or "").strip()
        if next_cwd:
            updated["cwd"] = next_cwd
        elif not str(updated.get("cwd") or "").strip():
            updated["cwd"] = fallback_cwd or fallback_project_root

        active_files = list(updated.get("active_files") or [])
        primary_path = result.get("path") or arguments.get("path")
        if tool_name in {"read", "search_file", "search_file_multi", "read_section", "table_extract", "fact_check_file", "image_read", "image_inspect"}:
            self._maybe_add_active_file(active_files, primary_path)
        for item in list(result.get("files") or [])[:8]:
            self._maybe_add_active_file(active_files, item)
        for collection_key in ("results", "matches", "hits", "items"):
            for item in list(result.get(collection_key) or [])[:8]:
                if isinstance(item, dict):
                    self._maybe_add_active_file(active_files, item.get("path"))
        updated["active_files"] = active_files[:8]
        if not next_cwd:
            primary_path_text = str(primary_path or "").strip()
            if primary_path_text and Path(primary_path_text).is_absolute():
                candidate = Path(primary_path_text)
                try:
                    is_file = candidate.exists() and candidate.is_file()
                except Exception:
                    is_file = False
                if is_file:
                    candidate_parent = candidate.parent
                    if str(candidate_parent).strip():
                        updated["cwd"] = str(candidate_parent)
        updated["active_attachments"] = self._attachment_refs(attachments)
        summary = str(result.get("summary") or result.get("error") or "").strip()
        if summary:
            updated["last_completed_step"] = f"{tool_name}: {summary}"[:240]
        return updated

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

    def _looks_like_plan_only_response(self, text: str) -> bool:
        normalized = " ".join(str(text or "").split()).lower()
        if not normalized:
            return False
        markers = (
            "i'll",
            "i will",
            "plan",
            "next i",
            "接下来",
            "我会先",
            "计划是",
            "方案如下",
        )
        action_markers = (
            "done",
            "changed",
            "updated",
            "applied",
            "执行了",
            "已修改",
            "已完成",
            "已更新",
        )
        return any(marker in normalized for marker in markers) and not any(marker in normalized for marker in action_markers)

    @staticmethod
    def _attachment_paths(attachments: list[dict[str, Any]], *, kind: str | None = None) -> list[str]:
        wanted_kind = str(kind or "").strip().lower()
        paths: list[str] = []
        for meta in attachments:
            if not isinstance(meta, dict):
                continue
            meta_kind = str(meta.get("kind") or "").strip().lower()
            if wanted_kind and meta_kind != wanted_kind:
                continue
            path = str(meta.get("path") or "").strip()
            if path:
                paths.append(path)
        return paths

    @staticmethod
    def _attachments_require_tools(attachments: list[dict[str, Any]]) -> bool:
        for meta in attachments:
            if not isinstance(meta, dict):
                continue
            path = str(meta.get("path") or "").strip()
            name = str(meta.get("name") or "").strip()
            kind = str(meta.get("kind") or "").strip().lower()
            mime = str(meta.get("mime") or "").strip().lower()
            if kind in {"image", "document"} and (path or name):
                return True
            if path and (kind == "other" or mime.startswith("application/")):
                return True
        return False

    def _build_attachment_tool_guidance(self, attachments: list[dict[str, Any]]) -> str:
        if not attachments:
            return ""
        lines: list[str] = [
            "附件处理要求：如果 runtime_context_json 里存在 attachments，就把这些本地路径视为当前轮已提供材料。",
            "不要只根据文件名、尺寸或 MIME 猜测内容；需要先调用合适工具再下结论。",
        ]
        image_paths = self._attachment_paths(attachments, kind="image")
        if image_paths:
            lines.append(
                "图片附件优先使用 image_read(path=...) 获取可见文字和图像内容；"
                "不要声称未配置 OCR、无法看图，且不要只返回图片元数据。"
            )
            lines.append(f"本轮图片附件路径示例: {json.dumps(image_paths[:2], ensure_ascii=False)}")
        document_paths = self._attachment_paths(attachments, kind="document")
        if document_paths:
            lines.append(
                "文档附件优先使用 read、search_file、search_file_multi、read_section、table_extract 或 fact_check_file。"
            )
            lines.append("如果附件是 .msg，正文先用 read，附件再用 mail_extract_attachments。")
        return "\n".join(lines)

    def _build_act_now_steer(self, attachments: list[dict[str, Any]]) -> str:
        lines = ["不要只给计划。立即采取下一步实际行动，先调用合适工具或直接执行变更，然后再汇报。"]
        image_paths = self._attachment_paths(attachments, kind="image")
        if image_paths:
            lines.append(
                "本轮存在图片附件。先调用 image_read(path=...) 读取可见文字和画面内容；"
                "不要只返回尺寸/格式，也不要说未配置 OCR。"
            )
            lines.append(f"优先处理这些图片路径之一: {json.dumps(image_paths[:2], ensure_ascii=False)}")
        return "\n".join(lines)

    @staticmethod
    def _path_exists(raw_path: str) -> bool:
        value = str(raw_path or "").strip()
        if not value:
            return False
        try:
            return Path(value).expanduser().exists()
        except Exception:
            return False

    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return raw
        lowered = raw.lower()
        alias = _TOOL_NAME_ALIASES.get(lowered)
        if alias:
            return alias
        if any(hint in lowered for hint in _IMAGE_READ_TOOL_HINTS):
            if any(hint in lowered for hint in _IMAGE_INSPECT_ACTION_HINTS):
                return "image_inspect"
            if any(hint in lowered for hint in _IMAGE_READ_ACTION_HINTS):
                return "image_read"
        return raw

    @staticmethod
    def _looks_like_missing_context_response(text: str) -> bool:
        normalized = " ".join(str(text or "").split()).lower()
        if not normalized:
            return False
        return any(hint.lower() in normalized for hint in _MISSING_CONTEXT_RESPONSE_HINTS)

    @staticmethod
    def _looks_like_generic_image_read_request(message: str) -> bool:
        normalized = " ".join(str(message or "").split()).lower()
        if not normalized:
            return False
        return any(hint.lower() in normalized for hint in _GENERIC_IMAGE_READ_REQUEST_HINTS)

    @staticmethod
    def _first_attachment_path(
        attachments: list[dict[str, Any]],
        *,
        kind: str = "",
    ) -> str:
        paths = VintageProgrammerRuntime._attachment_paths(attachments, kind=kind or None)
        return paths[0] if len(paths) == 1 else ""

    @staticmethod
    def _callable_accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
            if parameter.name == name and parameter.kind in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }:
                return True
        return False

    def _set_tools_runtime_context(
        self,
        *,
        execution_mode: str,
        session_id: str,
        project_id: str,
        project_root: str,
        cwd: str,
        model: str,
    ) -> None:
        tools = getattr(self._backend, "tools", None)
        setter = getattr(tools, "set_runtime_context", None)
        if not callable(setter):
            return
        kwargs = {
            "execution_mode": execution_mode,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "cwd": cwd,
        }
        if self._callable_accepts_kwarg(setter, "model"):
            kwargs["model"] = model
        setter(**kwargs)

    def _resolve_attachment_argument_path(
        self,
        raw_value: Any,
        attachments: list[dict[str, Any]],
        *,
        preferred_kind: str = "",
    ) -> str:
        raw = str(raw_value or "").strip()
        if not raw:
            return raw
        if self._path_exists(raw):
            return raw

        wanted_kind = str(preferred_kind or "").strip().lower()
        candidate_paths: list[str] = []
        raw_basename = Path(raw).name.strip() if raw else ""
        for meta in attachments:
            if not isinstance(meta, dict):
                continue
            meta_kind = str(meta.get("kind") or "").strip().lower()
            if wanted_kind and meta_kind != wanted_kind:
                continue
            meta_path = str(meta.get("path") or "").strip()
            meta_id = str(meta.get("id") or "").strip()
            meta_name = str(meta.get("name") or meta.get("original_name") or "").strip()
            meta_basename = Path(meta_path).name.strip() if meta_path else ""
            candidate_keys = {meta_path, meta_id, meta_name, meta_basename}
            if raw in candidate_keys or (raw_basename and raw_basename in candidate_keys):
                return meta_path or raw
            if meta_path:
                candidate_paths.append(meta_path)

        if wanted_kind and len(candidate_paths) == 1:
            return candidate_paths[0]
        return raw

    def _rewrite_attachment_tool_arguments(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = dict(arguments or {})
        tool_name = str(name or "").strip()
        if tool_name in {"image_read", "image_inspect"}:
            for legacy_key in ("image_path", "file_path", "filepath", "file", "image", "attachment", "attachment_id"):
                if "path" not in normalized and legacy_key in normalized:
                    normalized["path"] = normalized.pop(legacy_key)
        if tool_name in {"image_read", "image_inspect"} and "path" not in normalized and "image_path" in normalized:
            normalized["path"] = normalized.pop("image_path")

        if tool_name in {"image_read", "image_inspect"} and "path" in normalized:
            normalized["path"] = self._resolve_attachment_argument_path(
                normalized.get("path"),
                attachments,
                preferred_kind="image",
            )
        elif tool_name in {"image_read", "image_inspect"}:
            fallback_path = self._first_attachment_path(attachments, kind="image")
            if fallback_path:
                normalized["path"] = fallback_path
        elif tool_name in {"read", "search_file", "search_file_multi", "read_section", "table_extract", "fact_check_file"} and "path" in normalized:
            normalized["path"] = self._resolve_attachment_argument_path(normalized.get("path"), attachments)
        elif tool_name == "archive_extract" and "zip_path" in normalized:
            normalized["zip_path"] = self._resolve_attachment_argument_path(normalized.get("zip_path"), attachments)
        elif tool_name == "mail_extract_attachments" and "msg_path" in normalized:
            normalized["msg_path"] = self._resolve_attachment_argument_path(normalized.get("msg_path"), attachments)
        return normalized

    def _auto_rescue_image_read(
        self,
        *,
        attachments: list[dict[str, Any]],
        tool_events: list[ToolEvent],
        messages: list[Any],
        runner: Any,
        effective_model: str,
        settings: ChatSettings,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        spec: VintageProgrammerSpec,
        round_idx: int,
    ) -> tuple[Any, Any, str, bool, list[str]]:
        image_path = self._first_attachment_path(attachments, kind="image")
        if not image_path:
            return runner, effective_model, "", False, []

        arguments = {"path": image_path}
        result = self._backend.tools.execute("image_read", arguments)
        event = self._build_tool_event(name="image_read", arguments=arguments, result=result)
        tool_events.append(event)
        if progress_cb is not None:
            progress_cb(
                {
                    "event": "tool",
                    "item": event.model_dump(),
                    "status": event.status,
                    "summary": event.summary,
                    "source_refs": list(event.source_refs),
                    "tool_round": round_idx,
                    "tool_index": 1,
                    "group": event.group,
                    "agent_id": spec.agent_id,
                }
            )
        result_json = json.dumps(result, ensure_ascii=False)
        messages.append(
            self._backend._SystemMessage(
                content=(
                    "Runtime fallback executed image_read(path=...) on the attached image because the model "
                    "did not use the required image tool correctly. Use the tool result below and answer the user.\n\n"
                    f"image_read_result_json:\n{self._backend._shorten(result_json, 60000)}"
                )
            )
        )
        ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_with_runner_recovery(
            runner=runner,
            messages=messages,
            model=effective_model,
            max_output_tokens=int(settings.max_output_tokens),
            enable_tools=True,
            tool_names=list(spec.allowed_tools),
        )
        return ai_msg, runner, effective_model, bool(result.get("ok")), invoke_notes

    @staticmethod
    def _build_image_read_fallback_answer(result: dict[str, Any]) -> str:
        payload = dict(result or {})
        visible_text = str(payload.get("visible_text") or "").strip()
        analysis = str(payload.get("analysis") or "").strip()
        warning = str(payload.get("warning") or "").strip()
        width = payload.get("width")
        height = payload.get("height")
        mime = str(payload.get("mime") or "").strip()
        has_meaningful_content = bool(visible_text or analysis or warning)
        if not has_meaningful_content:
            return ""

        lines: list[str] = ["我已经读取了这张图片。"]
        if visible_text:
            lines.append("识别到的可见文字如下：")
            lines.append("")
            lines.append("```text")
            lines.append(visible_text)
            lines.append("```")
        if analysis and analysis.lower() != "extracted visible text from the image using local ocr.":
            lines.append(f"图像说明：{analysis}")
        elif not visible_text and analysis:
            lines.append(f"图像说明：{analysis}")
        meta_bits = [str(item) for item in (width, height) if item not in (None, "")]
        if mime or meta_bits:
            detail = " · ".join(
                [item for item in [mime.upper() if mime else "", "x".join(meta_bits) if len(meta_bits) == 2 else ""] if item]
            )
            if detail:
                lines.append(f"基础信息：{detail}")
        if warning:
            lines.append(f"注意：{warning}")
        return "\n".join(item for item in lines if item is not None).strip()

    @staticmethod
    def _cancel_requested(context: dict[str, Any]) -> bool:
        event = context.get("cancel_event")
        return bool(event and hasattr(event, "is_set") and event.is_set())

    def _build_live_compaction_summary(
        self,
        *,
        tool_events: list[ToolEvent],
        start_index: int,
        end_index: int,
        plan_state: list[dict[str, Any]],
    ) -> str:
        if end_index <= start_index:
            return ""
        lines = [
            "Earlier progress summary for this turn.",
            "These tool calls were compacted to keep the live context small.",
        ]
        if plan_state:
            plan_bits = [
                f"{str(item.get('step') or 'step')}: {str(item.get('status') or 'pending')}"
                for item in plan_state[:8]
                if isinstance(item, dict)
            ]
            if plan_bits:
                lines.append("Checklist snapshot: " + " | ".join(plan_bits))
        for item in tool_events[start_index:end_index]:
            lines.append(
                f"- {item.name} [{item.status}] {self._backend._shorten(item.summary or item.output_preview, 220)}"
            )
        return "\n".join(lines)

    def _maybe_compact_live_messages(
        self,
        *,
        messages: list[Any],
        base_message_count: int,
        tool_events: list[ToolEvent],
        compacted_until: int,
        plan_state: list[dict[str, Any]],
    ) -> tuple[list[Any], int, bool]:
        if len(tool_events) - compacted_until < _DEFAULT_COMPACT_AFTER_TOOL_CALLS:
            return messages, compacted_until, False
        if len(messages) <= base_message_count + _DEFAULT_COMPACT_KEEP_LAST_MESSAGES:
            return messages, compacted_until, False

        end_index = max(compacted_until, len(tool_events) - 4)
        if end_index <= compacted_until:
            return messages, compacted_until, False

        summary = self._build_live_compaction_summary(
            tool_events=tool_events,
            start_index=compacted_until,
            end_index=end_index,
            plan_state=plan_state,
        )
        if not summary:
            return messages, compacted_until, False

        base_messages = list(messages[:base_message_count])
        tail_messages = list(messages[-_DEFAULT_COMPACT_KEEP_LAST_MESSAGES:])
        compacted_messages = [
            *base_messages,
            self._backend._SystemMessage(content=summary),
            *tail_messages,
        ]
        return compacted_messages, end_index, True

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
        attachment_metas = [
            item for item in list(context_payload.get("attachments") or [])
            if isinstance(item, dict)
        ]
        attachment_guidance = self._build_attachment_tool_guidance(attachment_metas)
        has_image_attachments = has_image_attachments_helper(attachment_metas)
        spec = self._load_spec()
        loaded_skills = self._enabled_skills(spec.agent_id)
        requested_model = str(settings.model or spec.default_model or self._config.default_model).strip() or self._config.default_model
        requested_mode = str(
            context_payload.get("mode_override")
            or getattr(settings, "collaboration_mode", "")
            or spec.collaboration_modes[0]
            or "default"
        ).strip().lower()
        collaboration_mode = (
            requested_mode if requested_mode in set(spec.collaboration_modes) else (spec.collaboration_modes[0] if spec.collaboration_modes else "default")
        )
        selected_tools = list(spec.allowed_tools if settings.enable_tools else ())
        if collaboration_mode == "plan":
            selected_tools = [
                name for name in selected_tools
                if name in _READ_ONLY_TOOL_NAMES and name != "update_plan"
            ]
        tool_round_limit = spec.max_tool_rounds if selected_tools else 0
        legacy_tool_loop_disabled = bool(selected_tools) and int(spec.max_tool_rounds or 0) == 0
        max_tool_calls_per_turn = 0 if legacy_tool_loop_disabled else (_DEFAULT_MAX_TOOL_CALLS_PER_TURN if selected_tools else 0)
        runnable_tools = list(selected_tools if max_tool_calls_per_turn > 0 else ())
        max_turn_seconds = _DEFAULT_MAX_TURN_SECONDS if max_tool_calls_per_turn > 0 else 0
        max_same_tool_repeats = _DEFAULT_MAX_SAME_TOOL_REPEATS
        max_no_progress_cycles = _DEFAULT_MAX_NO_PROGRESS_CYCLES
        inline_document = _looks_like_inline_document_payload(prompt_message)
        attachment_requires_tools = self._attachments_require_tools(attachment_metas)
        expects_tools = (
            collaboration_mode in {"default", "execute"}
            and bool(runnable_tools)
            and not inline_document
            and (_looks_like_explicit_tool_request(prompt_message) or attachment_requires_tools)
        )
        project_context = dict(context_payload.get("project") or {})
        project_root = str(project_context.get("project_root") or "").strip()
        project_id = str(project_context.get("project_id") or "").strip()
        effective_cwd = str(project_context.get("cwd") or project_root or "").strip()
        route_state_input = dict(context_payload.get("route_state") or {})
        current_task_focus = self._initial_task_checkpoint(
            route_state=route_state_input,
            project_root=project_root,
            cwd=effective_cwd,
            goal=_truncate_goal(prompt_message),
            attachments=attachment_metas,
        )
        current_goal = str(current_task_focus.get("goal") or _truncate_goal(prompt_message))
        current_task_focus["goal"] = current_goal
        if current_task_focus.get("cwd"):
            effective_cwd = str(current_task_focus.get("cwd") or effective_cwd)

        messages: list[Any] = [
            self._backend._SystemMessage(content=self._render_system_prompt(settings, spec=spec, loaded_skills=loaded_skills)),
        ]
        if attachment_guidance:
            messages.append(self._backend._SystemMessage(content=attachment_guidance))
        messages.append(self._backend._HumanMessage(content=self._build_human_payload(message=prompt_message, context=context_payload)))

        usage_total = self._backend._empty_usage()
        notes: list[str] = [
            f"agent_id:{spec.agent_id}",
            f"tool_policy:{spec.tool_policy}",
            f"collaboration_mode:{collaboration_mode}",
        ]
        if inline_document:
            notes.append("inline_document_context")
        if attachment_requires_tools:
            notes.append("attachment_tooling_expected")
        if has_image_attachments:
            notes.append("image_attachment_context")
        if route_state_input.get("current_task_focus") or route_state_input.get("task_checkpoint"):
            notes.append("current_task_focus_restored")
            notes.append("task_checkpoint_restored")
        tool_events: list[ToolEvent] = []
        effective_model = requested_model
        plan_state: list[dict[str, Any]] = []
        pending_user_input: dict[str, Any] = {}
        turn_status = "running"
        forced_text = ""
        last_image_read_result: dict[str, Any] | None = None

        self._set_tools_runtime_context(
            execution_mode=settings.execution_mode,
            session_id=str(context_payload.get("session_id") or ""),
            project_id=project_id,
            project_root=project_root,
            cwd=effective_cwd,
            model=requested_model,
        )

        ai_msg: Any = None
        try:
            ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_chat_with_runner(
                messages=messages,
                model=requested_model,
                max_output_tokens=int(settings.max_output_tokens),
                enable_tools=bool(runnable_tools),
                tool_names=runnable_tools if runnable_tools else None,
            )
            self._set_tools_runtime_context(
                execution_mode=settings.execution_mode,
                session_id=str(context_payload.get("session_id") or ""),
                project_id=project_id,
                project_root=project_root,
                cwd=effective_cwd,
                model=effective_model,
            )
            notes.extend(invoke_notes)
            usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))

            act_now_budget = 1 if collaboration_mode in {"default", "execute"} and max_tool_calls_per_turn > 0 else 0
            auto_image_rescue_budget = 1 if has_image_attachments and "image_read" in runnable_tools else 0
            halt_for_user_input = False
            turn_started_at = time.monotonic()
            round_idx = 0
            tool_call_count = 0
            same_tool_repeat_count = 0
            last_tool_name = ""
            no_progress_cycles = 0
            last_round_signature = ""
            compacted_tool_events = 0
            base_message_count = len(messages)

            while True:
                if self._cancel_requested(context_payload):
                    turn_status = "cancelled"
                    forced_text = "已取消当前运行。"
                    notes.append("run_cancelled_by_user")
                    self._emit_stage(
                        progress_cb,
                        phase="report",
                        label="Cancelled",
                        detail="用户已取消当前运行。",
                        status="cancelled",
                        run_snapshot=self._build_run_snapshot(
                            goal=current_goal,
                            current_task_focus=current_task_focus,
                            collaboration_mode=collaboration_mode,
                            turn_status=turn_status,
                            plan_state=plan_state,
                            pending_user_input=pending_user_input,
                            effective_cwd=effective_cwd,
                            evidence_status="not_needed",
                            tool_events=tool_events,
                        ),
                    )
                    break
                if max_turn_seconds and (time.monotonic() - turn_started_at) >= max_turn_seconds:
                    turn_status = "blocked"
                    forced_text = "本轮已达到连续执行时间预算，先在这里停止。"
                    notes.append("turn_budget_wall_clock_exceeded")
                    break

                tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
                if not tool_calls:
                    ai_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
                    should_steer = (
                        act_now_budget > 0
                        and not tool_events
                        and collaboration_mode in {"default", "execute"}
                        and (
                            expects_tools
                            or self._looks_like_plan_only_response(ai_text)
                            or (has_image_attachments and looks_like_image_capability_denial_helper(ai_text))
                        )
                    )
                    if should_steer:
                        act_now_budget -= 1
                        messages.append(ai_msg)
                        messages.append(
                            self._backend._SystemMessage(
                                content=self._build_act_now_steer(attachment_metas)
                            )
                        )
                        notes.append("strict_agentic_act_now_steer")
                        ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_with_runner_recovery(
                            runner=runner,
                            messages=messages,
                            model=effective_model,
                            max_output_tokens=int(settings.max_output_tokens),
                            enable_tools=True,
                            tool_names=runnable_tools,
                        )
                        self._set_tools_runtime_context(
                            execution_mode=settings.execution_mode,
                            session_id=str(context_payload.get("session_id") or ""),
                            project_id=project_id,
                            project_root=project_root,
                            cwd=effective_cwd,
                            model=effective_model,
                        )
                        notes.extend(invoke_notes)
                        usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
                        continue
                    should_auto_rescue_image = (
                        auto_image_rescue_budget > 0
                        and collaboration_mode in {"default", "execute"}
                        and has_image_attachments
                        and not any(item.name == "image_read" and item.status == "ok" for item in tool_events)
                        and (
                            looks_like_image_capability_denial_helper(ai_text)
                            or self._looks_like_missing_context_response(ai_text)
                        )
                    )
                    if should_auto_rescue_image:
                        auto_image_rescue_budget -= 1
                        messages.append(ai_msg)
                        notes.append("auto_image_read_rescue")
                        ai_msg, runner, effective_model, rescue_ok, rescue_notes = self._auto_rescue_image_read(
                            attachments=attachment_metas,
                            tool_events=tool_events,
                            messages=messages,
                            runner=runner,
                            effective_model=effective_model,
                            settings=settings,
                            progress_cb=progress_cb,
                            spec=spec,
                            round_idx=round_idx + 1,
                        )
                        self._set_tools_runtime_context(
                            execution_mode=settings.execution_mode,
                            session_id=str(context_payload.get("session_id") or ""),
                            project_id=project_id,
                            project_root=project_root,
                            cwd=effective_cwd,
                            model=effective_model,
                        )
                        notes.extend(rescue_notes)
                        usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
                        tool_call_count += 1
                        if last_tool_name == "image_read":
                            same_tool_repeat_count += 1
                        else:
                            last_tool_name = "image_read"
                            same_tool_repeat_count = 1
                        if rescue_ok:
                            no_progress_cycles = 0
                        continue
                    break

                messages.append(ai_msg)
                round_idx += 1
                round_success = False
                round_signature_parts: list[dict[str, Any]] = []
                stop_after_tools = False
                for call_idx, call in enumerate(tool_calls[:8], start=1):
                    if self._cancel_requested(context_payload):
                        turn_status = "cancelled"
                        forced_text = "已取消当前运行。"
                        notes.append("run_cancelled_by_user")
                        stop_after_tools = True
                        break
                    if max_tool_calls_per_turn and tool_call_count >= max_tool_calls_per_turn:
                        turn_status = "blocked"
                        forced_text = "本轮已达到工具调用预算，先在这里停止。"
                        notes.append("turn_budget_tool_calls_exceeded")
                        stop_after_tools = True
                        break
                    raw_name = str(call.get("name") or "").strip()
                    name = self._normalize_tool_name(raw_name)
                    arguments = call.get("args")
                    if not isinstance(arguments, dict):
                        arguments = {}
                    arguments = self._rewrite_attachment_tool_arguments(
                        name=name,
                        arguments=arguments,
                        attachments=attachment_metas,
                    )
                    if raw_name and raw_name != name:
                        notes.append(f"tool_alias:{raw_name}->{name}")
                    if name and name in runnable_tools:
                        result = self._backend.tools.execute(name, arguments)
                    else:
                        result = {
                            "ok": False,
                            "error": f"Tool not allowed: {name or '(empty)'}",
                            "allowed_tools": runnable_tools,
                        }
                    if name == "image_read" and bool(result.get("ok")):
                        last_image_read_result = dict(result)
                    current_task_focus = self._task_checkpoint_from_tool(
                        checkpoint=current_task_focus,
                        tool_name=name,
                        arguments=arguments,
                        result=result,
                        attachments=attachment_metas,
                        fallback_project_root=project_root,
                        fallback_cwd=effective_cwd,
                    )
                    effective_cwd = str(current_task_focus.get("cwd") or effective_cwd or project_root)
                    self._set_tools_runtime_context(
                        execution_mode=settings.execution_mode,
                        session_id=str(context_payload.get("session_id") or ""),
                        project_id=project_id,
                        project_root=project_root,
                        cwd=effective_cwd,
                        model=effective_model,
                    )
                    tool_call_count += 1
                    if name == last_tool_name:
                        same_tool_repeat_count += 1
                    else:
                        last_tool_name = name
                        same_tool_repeat_count = 1
                    event = self._build_tool_event(name=name, arguments=arguments, result=result)
                    tool_events.append(event)
                    round_signature_parts.append(
                        {
                            "name": name,
                            "input": arguments,
                            "status": event.status,
                        }
                    )
                    if event.status == "ok":
                        round_success = True
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "event": "tool",
                                "item": event.model_dump(),
                                "status": event.status,
                                "summary": event.summary,
                                "source_refs": list(event.source_refs),
                                "tool_round": round_idx,
                                "tool_index": call_idx,
                                "group": event.group,
                                "agent_id": spec.agent_id,
                                "run_snapshot": self._build_run_snapshot(
                                    goal=current_goal,
                                    current_task_focus=current_task_focus,
                                    collaboration_mode=collaboration_mode,
                                    turn_status=turn_status,
                                    plan_state=plan_state,
                                    pending_user_input=pending_user_input,
                                    effective_cwd=effective_cwd,
                                    evidence_status="collected" if any(item.status == "ok" for item in tool_events) else "not_needed",
                                    tool_events=tool_events,
                                ),
                            }
                        )
                    if name == "update_plan" and bool(result.get("ok")):
                        plan_state = list(result.get("plan") or [])
                        if progress_cb is not None:
                            progress_cb(
                                {
                                    "event": "plan_update",
                                    "plan": plan_state,
                                    "explanation": str(result.get("explanation") or ""),
                                    "collaboration_mode": collaboration_mode,
                                    "turn_status": turn_status,
                                    "run_snapshot": self._build_run_snapshot(
                                        goal=current_goal,
                                        current_task_focus=current_task_focus,
                                        collaboration_mode=collaboration_mode,
                                        turn_status=turn_status,
                                        plan_state=plan_state,
                                        pending_user_input=pending_user_input,
                                        effective_cwd=effective_cwd,
                                        evidence_status="collected" if any(item.status == "ok" for item in tool_events) else "not_needed",
                                        tool_events=tool_events,
                                    ),
                                }
                            )
                    if name == "request_user_input" and bool(result.get("ok")):
                        pending_user_input = {
                            "questions": list(result.get("questions") or []),
                            "summary": str(result.get("summary") or "user input required"),
                        }
                        turn_status = "needs_user_input"
                        halt_for_user_input = True
                        if progress_cb is not None:
                            progress_cb(
                                {
                                    "event": "request_user_input",
                                    "pending_user_input": pending_user_input,
                                    "collaboration_mode": collaboration_mode,
                                    "turn_status": turn_status,
                                    "run_snapshot": self._build_run_snapshot(
                                        goal=current_goal,
                                        current_task_focus=current_task_focus,
                                        collaboration_mode=collaboration_mode,
                                        turn_status=turn_status,
                                        plan_state=plan_state,
                                        pending_user_input=pending_user_input,
                                        effective_cwd=effective_cwd,
                                        evidence_status="collected" if any(item.status == "ok" for item in tool_events) else "not_needed",
                                        tool_events=tool_events,
                                    ),
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
                    if same_tool_repeat_count > max_same_tool_repeats:
                        if name == "image_read" and last_image_read_result:
                            fallback_answer = self._build_image_read_fallback_answer(last_image_read_result)
                            if fallback_answer:
                                turn_status = "completed"
                                forced_text = fallback_answer
                                notes.append("image_read_repeat_fallback_answer")
                            else:
                                turn_status = "blocked"
                                forced_text = "本轮多次重复同一工具且没有继续推进，先在这里停止。"
                                notes.append("turn_budget_same_tool_repeats_exceeded")
                        else:
                            turn_status = "blocked"
                            forced_text = "本轮多次重复同一工具且没有继续推进，先在这里停止。"
                            notes.append("turn_budget_same_tool_repeats_exceeded")
                        stop_after_tools = True
                        break

                if halt_for_user_input or stop_after_tools:
                    break
                if self._cancel_requested(context_payload):
                    turn_status = "cancelled"
                    forced_text = "已取消当前运行。"
                    notes.append("run_cancelled_by_user")
                    break

                round_signature = json.dumps(round_signature_parts, ensure_ascii=False, sort_keys=True)
                if round_signature:
                    if round_success:
                        no_progress_cycles = 0
                    elif round_signature == last_round_signature:
                        no_progress_cycles += 1
                    else:
                        no_progress_cycles = 1
                    last_round_signature = round_signature
                if no_progress_cycles > max_no_progress_cycles:
                    turn_status = "blocked"
                    forced_text = "本轮多次重复且没有新的有效进展，先在这里停止。"
                    notes.append("turn_budget_no_progress_exceeded")
                    break

                messages, compacted_tool_events, compacted = self._maybe_compact_live_messages(
                    messages=messages,
                    base_message_count=base_message_count,
                    tool_events=tool_events,
                    compacted_until=compacted_tool_events,
                    plan_state=plan_state,
                )
                if compacted:
                    notes.append("turn_context_compacted")
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "event": "trace",
                                "message": "本轮中间上下文已压缩，以支持更长的连续执行。",
                            }
                        )

                ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_with_runner_recovery(
                    runner=runner,
                    messages=messages,
                    model=effective_model,
                    max_output_tokens=int(settings.max_output_tokens),
                    enable_tools=True,
                    tool_names=runnable_tools,
                )
                self._set_tools_runtime_context(
                    execution_mode=settings.execution_mode,
                    session_id=str(context_payload.get("session_id") or ""),
                    project_id=project_id,
                    project_root=project_root,
                    cwd=effective_cwd,
                    model=effective_model,
                )
                notes.extend(invoke_notes)
                usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
        finally:
            if hasattr(self._backend.tools, "clear_runtime_context"):
                self._backend.tools.clear_runtime_context()

        raw_text = forced_text or (self._backend._content_to_text(getattr(ai_msg, "content", "")).strip() if ai_msg is not None else "")
        if not raw_text:
            raw_text = "需要你先提供补充输入后我再继续。" if pending_user_input else "(empty response)"
        if (
            has_image_attachments
            and last_image_read_result
            and self._looks_like_generic_image_read_request(prompt_message)
        ):
            fallback_answer = self._build_image_read_fallback_answer(last_image_read_result)
            if fallback_answer:
                raw_text = fallback_answer
                if turn_status not in {"cancelled", "blocked"}:
                    turn_status = "completed"
                notes.append("image_read_result_forced_summary")
        has_successful_tool = any(item.status == "ok" for item in tool_events)
        evidence_status = "not_needed"
        if expects_tools or (collaboration_mode == "plan" and tool_events):
            evidence_status = "collected" if has_successful_tool else "needs_evidence_review"
            if (expects_tools or tool_events) and not has_successful_tool:
                notes.append("tool_expectation_not_met")
        if turn_status in {"cancelled", "blocked"}:
            pass
        elif pending_user_input:
            turn_status = "needs_user_input"
        elif collaboration_mode in {"default", "execute"} and expects_tools and not tool_events:
            turn_status = "blocked"
            if has_image_attachments and looks_like_image_capability_denial_helper(raw_text):
                notes.append("image_attachment_tooling_not_used")
            else:
                notes.append("strict_agentic_blocked_without_required_tools")
        elif collaboration_mode in {"default", "execute"} and not tool_events and self._looks_like_plan_only_response(raw_text):
            turn_status = "blocked"
            notes.append("strict_agentic_blocked_after_steer")
        else:
            turn_status = "completed"
        current_task_focus["project_root"] = project_root
        current_task_focus["cwd"] = effective_cwd or project_root
        current_task_focus["active_attachments"] = self._attachment_refs(attachment_metas)
        if pending_user_input:
            current_task_focus["next_action"] = str(pending_user_input.get("summary") or "user input required")
        elif turn_status == "blocked":
            current_task_focus["next_action"] = raw_text[:240]
        elif turn_status == "cancelled":
            current_task_focus["next_action"] = "cancelled"
        else:
            current_task_focus["next_action"] = ""
        if not str(current_task_focus.get("last_completed_step") or "").strip() and tool_events:
            last_tool = tool_events[-1]
            current_task_focus["last_completed_step"] = f"{last_tool.name}: {last_tool.summary or last_tool.output_preview[:120]}"[:240]
        answer_bundle = self._build_answer_bundle(
            raw_text=raw_text,
            tool_events=tool_events,
            evidence_status=evidence_status,
        )
        if answer_bundle["warnings"]:
            notes.extend(answer_bundle["warnings"])

        legacy_phase = collaboration_mode if turn_status == "running" else turn_status
        inspector = {
            "agent": self.descriptor(),
            "run_state": {
                "goal": current_goal,
                "phase": legacy_phase,
                "workflow_phases": list(spec.collaboration_modes),
                "collaboration_mode": collaboration_mode,
                "turn_status": turn_status,
                "plan": plan_state,
                "pending_user_input": pending_user_input,
                "requires_tools": expects_tools,
                "tool_round_limit": tool_round_limit,
                "network_mode": spec.network_mode,
                "inline_document": inline_document,
                "thread_memory": dict(context_payload.get("thread_memory") or {}),
                "recent_tasks": list(context_payload.get("recent_tasks") or []),
                "artifact_memory_preview": list(context_payload.get("artifact_memory_preview") or []),
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
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
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
                "thread_memory": dict(context_payload.get("thread_memory") or {}),
                "recent_tasks": list(context_payload.get("recent_tasks") or []),
                "artifact_memory_preview": list(context_payload.get("artifact_memory_preview") or []),
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
            "collaboration_mode": collaboration_mode,
            "turn_status": turn_status,
            "plan": plan_state,
            "pending_user_input": pending_user_input,
            "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
            "recent_tasks": list(context_payload.get("recent_tasks") or []),
            "tool_events": [item.model_dump() for item in tool_events],
            "token_usage": usage_total,
            "inspector": inspector,
            "answer_bundle": answer_bundle,
            "route_state": {
                "agent_id": spec.agent_id,
                "tool_policy": spec.tool_policy,
                "phase": legacy_phase,
                "collaboration_mode": collaboration_mode,
                "turn_status": turn_status,
                "network_mode": spec.network_mode,
                "evidence_status": evidence_status,
                "tool_count": len(tool_events),
                "loaded_skill_ids": [str(item.get("id") or "") for item in loaded_skills],
                "inline_document": inline_document,
                "project_id": project_id,
                "project_root": project_root,
                "cwd": effective_cwd,
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
            },
        }
