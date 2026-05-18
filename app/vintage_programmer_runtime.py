from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable
import uuid

from app.action_validator import ActionValidator, ValidationResult, validation_observation
from app.config import AppConfig
from app.context_pack import build_context_pack
from app.context_meter import count_tokens
from app.i18n import normalize_locale, response_style_hint, translate
from app.models import (
    ChatSettings,
    ExecutionTraceEntry,
    ProgressSignal,
    ToolEvent,
)
from app.openai_auth import OpenAIAuthManager
from app.phase_timing import PhaseTimer
from app.runtime_boundary import RuntimeBoundary, build_turn_runtime_boundary
from app.runtime_contract import RuntimeContract, build_full_auto_runtime_contract
from app.serialization import dump_model
from app.session_context import compat_task_checkpoint_from_focus, normalize_current_task_focus
from app.tool_trace_summary import (
    build_tool_argument_audit,
    normalize_tool_arguments,
    safe_error_message,
    safe_preview,
    summarize_tool_args,
    summarize_tool_result,
    validate_tool_arguments,
)
from app.trace_events import make_activity_event, make_trace_event
from app.workbench import WorkbenchStore, build_tool_descriptors, split_frontmatter, tool_descriptor_by_name
from packages.office_modules.intent_support import has_image_attachments as has_image_attachments_helper
from packages.office_modules.office_agent_runtime import create_office_runtime_backend


_READ_ONLY_TOOL_NAMES = {
    "read_file",
    "list_dir",
    "glob_file_search",
    "search_contents_in_file",
    "search_contents_in_file_multi",
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

_REVISION_REQUEST_HINTS = (
    "润色",
    "改写",
    "改成",
    "重写",
    "校对",
    "语法",
    "文法",
    "proofread",
    "grammar",
    "rewrite",
    "rephrase",
    "polish",
    "revise",
    "edit",
    "more natural",
)

_JAPANESE_REQUEST_HINTS = (
    "日语",
    "日文",
    "日本语",
    "日本語",
    "japanese",
    "敬语",
    "敬語",
)

_JAPANESE_KANA_RE = re.compile(r"[ぁ-んァ-ヶ]")

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
    "ocr_image": "image_read",
    "read_image": "image_read",
    "read_section_by_heading": "read_section",
    "read_session_history": "sessions_history",
    "search_web": "web_search",
    "view_image": "image_inspect",
}

_DEFAULT_EMERGENCY_MAX_TOOL_CALLS_PER_TURN = 1000
_DEFAULT_MAX_TURN_SECONDS = 1800
_DEFAULT_MAX_SAME_ACTION_REPEATS = 4
_DEFAULT_NO_PROGRESS_THRESHOLD_BEFORE_REPLAN = 3
_DEFAULT_NO_PROGRESS_THRESHOLD_AFTER_REPLAN = 2
_DEFAULT_MAX_GUARD_REJECTIONS = 2
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


def default_loop_safeguards() -> dict[str, Any]:
    return {
        "max_same_action_repeats": int(_DEFAULT_MAX_SAME_ACTION_REPEATS),
        "no_progress_threshold_before_replan": int(_DEFAULT_NO_PROGRESS_THRESHOLD_BEFORE_REPLAN),
        "no_progress_threshold_after_replan": int(_DEFAULT_NO_PROGRESS_THRESHOLD_AFTER_REPLAN),
        "max_guard_rejections": int(_DEFAULT_MAX_GUARD_REJECTIONS),
        "max_turn_seconds": int(_DEFAULT_MAX_TURN_SECONDS),
        "long_task_guard": True,
        "progress_signal_guard": True,
        "same_action_repeat_guard": True,
        "automatic_replan": True,
        "tool_output_truncation": True,
        "supports_user_cancel": True,
        "context_compaction": True,
    }
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

_WRITE_INTENT_HINTS = (
    "直接补",
    "直接改",
    "大胆修改",
    "大胆改",
    "补齐",
    "补全",
    "补上",
    "补一下",
    "修改",
    "修复",
    "实现",
    "完善",
    "加上",
    "添加",
    "替换",
    "更新",
    "改成",
    "改为",
    "apply_patch",
    "patch",
    "fix",
    "implement",
    "modify",
    "update",
    "change",
    "補完",
    "修正",
    "変更",
    "実装",
    "追加",
    "直して",
)

_EXPLICIT_WRITE_AUTH_HINTS = (
    "直接",
    "大胆",
    "不用确认",
    "不需要确认",
    "不用问我",
    "不要问我",
    "有版本控制",
    "我有版本控制",
    "直接做",
    "直接补",
    "直接改",
    "go ahead",
    "no need to ask",
    "without asking",
    "just do it",
    "直接",
    "確認不要",
    "そのまま",
)

_WRITE_TOOL_NAMES = {
    "apply_patch",
    "exec_command",
    "write_stdin",
    "web_download",
    "archive_extract",
    "mail_extract_attachments",
}


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(item).lower() in lowered for item in hints)


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
            "loop_safeguards": default_loop_safeguards(),
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
        kernel_runtime: Any | None = None,
        agent_dir: Path,
        backend: Any | None = None,
    ) -> None:
        self._config = config
        self._agent_dir = agent_dir.resolve()
        # Injected backends are treated as already-authenticated or auth-free test doubles
        # unless they opt back into the standard OpenAI auth gate.
        self._require_runtime_auth = backend is None
        self._backend = backend or create_office_runtime_backend(config)
        if backend is not None:
            self._require_runtime_auth = bool(getattr(self._backend, "requires_auth", False))
        self._tool_specs = list(getattr(self._backend.tools, "tool_specs", []) or [])
        self._tool_specs_by_name = self._build_tool_spec_index()
        self._tool_descriptors = build_tool_descriptors(self._tool_specs)
        self._tool_descriptors_by_name = tool_descriptor_by_name(self._tool_specs)
        self._workbench = WorkbenchStore(config=config, agent_dir=self._agent_dir)
        self._descriptor_lock = threading.Lock()
        self._descriptor_cache: dict[str, dict[str, object]] = {}
        self._descriptor_cache_generation = 0

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

    def _load_required_file(self, name: str, *, locale: str | None = None) -> str:
        normalized_locale = normalize_locale(locale, self._config.default_locale)
        candidates: list[Path] = []
        locale_family = normalized_locale.split("-", 1)[0]
        for candidate in (
            self._agent_dir / "locales" / normalized_locale / name,
            self._agent_dir / "locales" / locale_family / name,
            self._agent_dir / name,
        ):
            if candidate in candidates:
                continue
            candidates.append(candidate)
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        raise RuntimeError(f"Missing required agent spec file: {self._agent_dir / name}")

    def _resolve_allowed_tools(self, *, tool_policy: str, explicit_tools: list[str]) -> tuple[str, ...]:
        if explicit_tools:
            names = [name for name in explicit_tools if name in self._tool_specs_by_name]
            return tuple(names)
        if tool_policy == "none":
            return ()
        if tool_policy == "read_only":
            return tuple(name for name in self._tool_specs_by_name if name in _READ_ONLY_TOOL_NAMES)
        return tuple(self._tool_specs_by_name.keys())

    def _load_spec(self, *, locale: str | None = None) -> VintageProgrammerSpec:
        soul_text = self._load_required_file("soul.md", locale=locale)
        identity_text = self._load_required_file("identity.md", locale=locale)
        agent_text_raw = self._load_required_file("agent.md", locale=locale)
        tools_text = ""
        for tools_path in (
            self._agent_dir / "locales" / normalize_locale(locale, self._config.default_locale) / "tools.md",
            self._agent_dir / "locales" / normalize_locale(locale, self._config.default_locale).split("-", 1)[0] / "tools.md",
            self._agent_dir / "tools.md",
        ):
            if tools_path.is_file():
                tools_text = tools_path.read_text(encoding="utf-8").strip()
                break

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
        explicit_tools = []
        if isinstance(frontmatter.get("allowed_tools"), list):
            explicit_tools = [str(item or "").strip() for item in frontmatter["allowed_tools"] if str(item or "").strip()]
        allowed_tools = self._resolve_allowed_tools(tool_policy=tool_policy, explicit_tools=explicit_tools)

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
            allowed_tools=allowed_tools,
            soul_text=soul_text,
            identity_text=identity_text,
            agent_text=agent_text.strip(),
            tools_text=tools_text,
            spec_files=tuple(spec_files),
        )

    def _enabled_skills(self, agent_id: str) -> list[dict[str, Any]]:
        return self._workbench.enabled_skills_for_agent(agent_id)

    def invalidate_descriptor_cache(self) -> None:
        with self._descriptor_lock:
            self._descriptor_cache.clear()
            self._descriptor_cache_generation += 1

    def descriptor(self, locale: str | None = None, *, refresh: bool = False) -> dict[str, object]:
        cache_key = normalize_locale(locale, self._config.default_locale)
        if not refresh:
            with self._descriptor_lock:
                cached = self._descriptor_cache.get(cache_key)
                if isinstance(cached, dict):
                    return copy.deepcopy(cached)
        spec = self._load_spec(locale=locale)
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
        with self._descriptor_lock:
            self._descriptor_cache[cache_key] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    def _render_system_prompt(
        self,
        settings: ChatSettings,
        *,
        spec: VintageProgrammerSpec,
        loaded_skills: list[dict[str, Any]],
        project_contract_text: str = "",
    ) -> str:
        locale = normalize_locale(getattr(settings, "locale", ""), self._config.default_locale)
        parts = [
            f"[soul.md]\n{spec.soul_text}",
            f"[identity.md]\n{spec.identity_text}",
            f"[agent.md]\n{spec.agent_text}",
        ]
        if project_contract_text:
            parts.append(f"[AGENTS.md]\n{project_contract_text}")
        if spec.tools_text:
            parts.append(f"[tools.md]\n{spec.tools_text}")
        for skill in loaded_skills:
            skill_id = str(skill.get("id") or "").strip()
            skill_content = str(skill.get("content") or "").strip()
            if skill_id and skill_content:
                parts.append(f"[skill:{skill_id}]\n{skill_content}")
        parts.append(translate(locale, "runtime.system.language_instruction"))
        parts.append(f"Response style: {response_style_hint(locale, settings.response_style)}")
        parts.append(translate(locale, "runtime.system.output_requirements"))
        parts.append(translate(locale, "runtime.system.inline_message_analysis"))
        parts.append(translate(locale, "runtime.system.inline_error_analysis"))
        parts.append(translate(locale, "runtime.system.attachment_context"))
        parts.append(translate(locale, "runtime.system.focus_context"))
        parts.append(translate(locale, "runtime.system.thread_memory"))
        parts.append(translate(locale, "runtime.system.image_read"))
        parts.append(translate(locale, "runtime.system.document_read"))
        runtime_contract = build_full_auto_runtime_contract(
            settings=settings,
            config=self._config,
        )
        parts.append(
            self._build_codex_agentic_harness_prompt(
                locale=locale,
                model=str(settings.model or spec.default_model or ""),
                runtime_contract=runtime_contract,
                python_command=self._config.python_command,
            )
        )
        return "\n\n".join(item for item in parts if str(item).strip())

    @staticmethod
    def _build_runtime_contract_prompt(*, runtime_contract: RuntimeContract) -> str:
        payload = runtime_contract.as_payload()
        lines = ["[runtime_contract]"]
        ordered_keys = (
            "mode",
            "tool_policy",
            "tools_available",
            "workspace_write_allowed",
            "shell_allowed",
            "network_allowed",
            "sandbox_scope",
            "approval_policy",
            "reason",
        )
        for key in ordered_keys:
            lines.append(f"{key}: {json.dumps(payload.get(key), ensure_ascii=False)}")
        return "\n".join(lines)

    @staticmethod
    def _build_anti_permission_gate_prompt() -> str:
        return (
            "[anti_permission_gate]\n"
            "- The user has already asked you to complete the current request.\n"
            "- Do not end with unnecessary permission questions.\n"
            "- Do not ask 'shall I continue?', 'do you want me to proceed?', '要不要我继续？', '是否需要我执行？', or equivalent unless essential information is missing, the action is outside the current runtime boundary, or explicit approval is required.\n"
            "- If the request can be completed under the current runtime contract, complete it directly.\n"
            "- If the request is self-contained and does not require external context or workspace action, answer directly.\n"
        )

    @staticmethod
    def _build_model_led_action_prompt() -> str:
        return (
            "[model_led_action_protocol]\n"
            "- Decide the next action yourself: answer directly or call one appropriate tool.\n"
            "- A concrete tool call is the action.\n"
            "- Do not wait for or emit a separate proposal before acting.\n"
            "- Tool calls are validated by the harness for schema, permissions, runtime boundaries, and safety.\n"
            "- If a tool call is rejected, read the validation observation and choose a corrected next action.\n"
            "- Do not repeat the same invalid tool call.\n"
            "- If current context is sufficient, answer directly.\n"
            "- Use update_plan only when you need to track a multi-step execution task and can provide a valid plan payload.\n"
            "[context_priority]\n"
            "- The current user message has highest priority.\n"
            "- Task memory helps maintain long-running work.\n"
            "- ContextPack contains recent conversation, task memory, plan state, compaction status, and runtime boundary.\n"
            "- runtime_boundary describes what the harness will enforce.\n"
        )

    @staticmethod
    def _build_full_auto_tool_policy_prompt(
        *,
        locale: str,
        runtime_contract: RuntimeContract,
        model: str = "",
        python_command: str = "python",
    ) -> str:
        model_label = str(model or "").strip().lower()
        coding_agent_like = any(token in model_label for token in ("codex", "claude", "coder", "devstral", "qwen3-coder"))
        strength = "standard" if coding_agent_like else "strict"
        detected_python = str(python_command or "python").strip() or "python"
        return (
            "[full_auto_tool_policy]\n"
            f"enforcement_level: {strength}\n"
            f"- Current runtime mode is {runtime_contract.mode}. Tool policy is {runtime_contract.tool_policy}.\n"
            "- In default/execute mode, when the user asks to modify, fix, implement, update, complete, or patch workspace content, do the work now.\n"
            "- Use tools when needed.\n"
            "- Do not force tools for self-contained text tasks such as plain chat, explanation, translation, rewriting, meeting minutes, or summarization of text already provided by the user.\n"
            "- Use tools when the request requires external context, workspace inspection, file reading, code search, file modification, testing, command execution, or long-running task progress.\n"
            "- File edits use apply_patch. Workspace inspection uses read_file/list_dir/glob_file_search/search_codebase/exec_command. Attachment understanding uses read_file/image_read/search_contents_in_file/read_section/table_extract as appropriate.\n"
            "- Use update_plan only when a valid checklist helps a multi-step execution task. If planning is unnecessary, answer directly or call the concrete tool needed now.\n"
            f"- When running Python commands, prefer the project virtual environment when available (for example ./.venv/bin/python on macOS/Linux or .venv\\Scripts\\python.exe on Windows). Otherwise use the detected interpreter command ({detected_python}). Do not assume python3 exists. Prefer project-level module execution via the selected interpreter with -m ...\n"
            "- If runtime permission is truly required, use the structured request_user_input/approval channel. Do not ask for approval in ordinary assistant prose.\n"
            "- After each tool result, continue the turn until the task is complete, needs structured user input, is blocked by a concrete policy, is cancelled, or a runtime budget is exhausted.\n"
            f"- Keep the final response in the active locale ({locale}), but keep tool decisions concrete and agentic."
        )

    @classmethod
    def _build_codex_agentic_harness_prompt(
        cls,
        *,
        locale: str,
        model: str = "",
        runtime_contract: RuntimeContract | None = None,
        python_command: str = "python",
    ) -> str:
        contract = runtime_contract or RuntimeContract()
        return "\n".join(
            [
                cls._build_runtime_contract_prompt(runtime_contract=contract),
                cls._build_anti_permission_gate_prompt(),
                cls._build_model_led_action_prompt(),
                cls._build_full_auto_tool_policy_prompt(
                    locale=locale,
                    runtime_contract=contract,
                    model=model,
                    python_command=python_command,
                ),
            ]
        )

    def _build_human_payload(
        self,
        *,
        message: str,
        context: dict[str, Any],
        runtime_boundary: RuntimeBoundary | None = None,
    ) -> str:
        current_task_focus = normalize_current_task_focus(context.get("current_task_focus"))
        project_payload = dict(context.get("project") or {})
        project_root = str(project_payload.get("project_root") or project_payload.get("root") or self._config.workspace_root)
        boundary = runtime_boundary or build_turn_runtime_boundary(
            config=self._config,
            project_root=project_root,
            cwd=str(project_payload.get("cwd") or project_root or ""),
            attachments=list(context.get("attachments") or []),
        )
        context_pack = build_context_pack(
            message=message,
            context=context,
            current_task_focus=current_task_focus,
            runtime_boundary_model_view=boundary.to_model_view(),
        )
        payload = {
            "session_id": str(context.get("session_id") or ""),
            "project": project_payload,
            "python_command": str(self._config.python_command or "python"),
            "python_command_source": str(self._config.python_command_source or ""),
            "context_pack": dump_model(context_pack),
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

    @staticmethod
    def _load_project_contract_text(project_root: str) -> str:
        candidates: list[Path] = []
        raw_root = str(project_root or "").strip()
        if raw_root:
            candidates.append(Path(raw_root) / "AGENTS.md")
        candidates.append(Path.cwd() / "AGENTS.md")
        candidates.append(Path(__file__).resolve().parents[1] / "AGENTS.md")
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.is_file():
                    return candidate.read_text(encoding="utf-8")[:24000]
            except Exception:
                continue
        return ""

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

    @staticmethod
    def _trace_label(locale: str, key: str, **replacements: Any) -> str:
        catalog = {
            "zh-CN": {
                "run.started": "开始处理请求",
                "run.finished": "完成",
                "run.failed": "执行失败",
                "runtime_contract.selected": "Full Auto runtime 已启用",
                "runtime_contract.detail": "工具策略：需要时使用",
                "llm.started": "模型开始分析",
                "llm.finished": "模型分析完成",
                "action.detected": "检测到模型行动：{tool}",
                "action.validating": "验证行动边界：{tool}",
                "action.allowed": "行动通过验证：{tool}",
                "action.blocked": "行动被边界拦截：{tool}",
                "tool.call_detected": "检测到工具调用：{tool}",
                "tool.guard": "工具检查：{tool}",
                "tool.started": "调用工具：{tool}",
                "tool.finished": "工具完成：{tool}",
                "tool.failed": "工具失败：{tool}",
                "observation.returned": "已将观察结果返回模型：{tool}",
                "loop.safeguard": "循环保护触发",
                "approval.required": "需要确认",
                "approval.resolved": "确认已处理",
                "repair.started": "开始修复执行偏差",
                "repair.finished": "执行偏差修复完成",
                "activity.started": "开始分析请求",
                "activity.delta": "处理中",
                "activity.done": "已确定回答路径",
                "answer.started": "开始生成回答",
                "answer.delta": "正在流式生成回答",
                "answer.done": "生成回答完成",
                "answer.finished": "生成回答完成",
                "blocked": "已阻塞",
                "cancelled": "已取消",
            },
            "ja-JP": {
                "run.started": "リクエストの処理を開始",
                "run.finished": "完了",
                "run.failed": "実行失敗",
                "runtime_contract.selected": "Full Auto runtime を有効化",
                "runtime_contract.detail": "ツール方針：必要なときのみ使用",
                "llm.started": "モデルが解析を開始",
                "llm.finished": "モデル解析が完了",
                "action.detected": "モデル行動を検出: {tool}",
                "action.validating": "行動境界を検証: {tool}",
                "action.allowed": "行動が検証を通過: {tool}",
                "action.blocked": "行動が境界でブロック: {tool}",
                "tool.call_detected": "ツール呼び出しを検出: {tool}",
                "tool.guard": "ツール検査: {tool}",
                "tool.started": "ツール呼び出し: {tool}",
                "tool.finished": "ツール完了: {tool}",
                "tool.failed": "ツール失敗: {tool}",
                "observation.returned": "観察結果をモデルへ返却: {tool}",
                "loop.safeguard": "ループ保護が発動",
                "approval.required": "確認が必要",
                "approval.resolved": "確認が処理されました",
                "repair.started": "実行修復を開始",
                "repair.finished": "実行修復が完了",
                "activity.started": "リクエスト分析を開始",
                "activity.delta": "処理中",
                "activity.done": "回答方針を確定",
                "answer.started": "回答の生成を開始",
                "answer.delta": "回答をストリーミング中",
                "answer.done": "回答の生成が完了",
                "answer.finished": "回答の生成が完了",
                "blocked": "停止",
                "cancelled": "キャンセル済み",
            },
            "en": {
                "run.started": "Started processing request",
                "run.finished": "Completed",
                "run.failed": "Run failed",
                "runtime_contract.selected": "Full Auto runtime enabled",
                "runtime_contract.detail": "Tool policy: use when needed",
                "llm.started": "Model analysis started",
                "llm.finished": "Model analysis finished",
                "action.detected": "Model action detected: {tool}",
                "action.validating": "Validating action boundary: {tool}",
                "action.allowed": "Action validation passed: {tool}",
                "action.blocked": "Action blocked by boundary: {tool}",
                "tool.call_detected": "Tool call detected: {tool}",
                "tool.guard": "Tool guard: {tool}",
                "tool.started": "Calling tool: {tool}",
                "tool.finished": "Tool finished: {tool}",
                "tool.failed": "Tool failed: {tool}",
                "observation.returned": "Observation returned to model: {tool}",
                "loop.safeguard": "Loop safeguard triggered",
                "approval.required": "Needs confirmation",
                "approval.resolved": "Confirmation resolved",
                "repair.started": "Repairing execution flow",
                "repair.finished": "Execution flow repaired",
                "activity.started": "Analyzing request",
                "activity.delta": "Working",
                "activity.done": "Answer path selected",
                "answer.started": "Generating answer",
                "answer.delta": "Streaming answer",
                "answer.done": "Answer generation finished",
                "answer.finished": "Answer generation finished",
                "blocked": "Blocked",
                "cancelled": "Cancelled",
            },
        }
        table = catalog.get(normalize_locale(locale), catalog["en"])
        template = table.get(key, key)
        try:
            return template.format(**replacements)
        except Exception:
            return template

    def _emit_trace(
        self,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        run_id: str,
        type: str,
        title: str,
        detail: str = "",
        status: str = "running",
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
        parent_id: str | None = None,
        visible: bool = True,
        trace_events: list[dict[str, Any]] | None = None,
    ) -> str | None:
        trace = make_trace_event(
            run_id=run_id,
            type=type,
            title=title,
            detail=detail,
            status=status,
            duration_ms=duration_ms,
            payload=dict(payload or {}),
            parent_id=parent_id,
            visible=visible,
        )
        if trace_events is not None:
            trace_events.append(dict(trace))
        if progress_cb is not None:
            progress_cb(
                {
                    "event": "trace_event",
                    "type": "trace_event",
                    "trace": trace,
                    "run_id": str(run_id or ""),
                }
            )
        return str(trace.get("id") or "")

    def _emit_activity_trace(
        self,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        run_id: str,
        locale: str,
        type: str,
        stage: str,
        detail: str = "",
        status: str = "running",
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
        parent_id: str | None = None,
        visible: bool = True,
        trace_events: list[dict[str, Any]] | None = None,
        sequence: int | None = None,
    ) -> str | None:
        trace = make_activity_event(
            run_id=run_id,
            type=type,
            title=self._trace_label(locale, type),
            stage=stage,
            detail=detail,
            status=status,
            duration_ms=duration_ms,
            payload=dict(payload or {}),
            parent_id=parent_id,
            visible=visible,
            sequence=sequence,
        )
        if trace_events is not None:
            trace_events.append(dict(trace))
        if progress_cb is not None:
            progress_cb(
                {
                    "event": "trace_event",
                    "type": "trace_event",
                    "trace": trace,
                    "run_id": str(run_id or ""),
                }
            )
        return str(trace.get("id") or "")

    @staticmethod
    def _emit_message_item_event(
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        event: str,
        thread_id: str,
        turn_id: str,
        item: dict[str, Any] | None = None,
        item_id: str = "",
        delta: str = "",
    ) -> None:
        if progress_cb is None:
            return
        payload: dict[str, Any] = {
            "event": event,
            "thread_id": str(thread_id or ""),
            "turn_id": str(turn_id or ""),
        }
        if item is not None:
            payload["item"] = dict(item)
        if item_id:
            payload["item_id"] = str(item_id)
        if delta:
            payload["delta"] = str(delta)
        progress_cb(payload)

    @staticmethod
    def _new_answer_stream_state(*, run_id: str, thread_id: str) -> dict[str, Any]:
        return {
            "thread_id": str(thread_id or ""),
            "turn_id": str(run_id or ""),
            "item_id": f"{str(run_id or 'turn')}:agent_message",
            "item_started": False,
            "item_completed": False,
            "trace_started_id": "",
            "trace_done_id": "",
            "text": "",
            "delta_count": 0,
            "delta_chars": 0,
            "text_delta_trace_count": 0,
            "calls": [],
            "started_at": 0.0,
            "finished_at": 0.0,
        }

    @staticmethod
    def _start_answer_stream_call(
        state: dict[str, Any],
        *,
        model: str,
        phase: str,
        tool_round: int,
    ) -> dict[str, Any]:
        call_state = {
            "index": len(list(state.get("calls") or [])) + 1,
            "model": str(model or ""),
            "phase": str(phase or ""),
            "tool_round": max(0, int(tool_round)),
            "event_count": 0,
            "text_delta_count": 0,
            "text_chars": 0,
            "first_event_at": 0.0,
            "first_text_delta_at": 0.0,
            "last_text_delta_at": 0.0,
            "completed_at": 0.0,
        }
        state.setdefault("calls", []).append(call_state)
        return call_state

    @staticmethod
    def _consume_stream_delta_for_display(state: dict[str, Any], delta: str) -> str:
        return str(delta or "")

    def _make_model_stream_observer(
        self,
        *,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        run_id: str,
        thread_id: str,
        locale: str,
        trace_events: list[dict[str, Any]],
        answer_stream_state: dict[str, Any],
        stage: str,
        model: str,
        tool_round: int,
        answer_context: dict[str, Any] | None = None,
        phase_timer: PhaseTimer | None = None,
    ) -> Callable[[dict[str, Any]], None]:
        call_state = self._start_answer_stream_call(
            answer_stream_state,
            model=model,
            phase=stage,
            tool_round=tool_round,
        )
        activity_context = dict(answer_context or {})

        def observer(event: dict[str, Any]) -> None:
            payload = dict(event or {})
            event_type = str(payload.get("type") or "").strip()
            timestamp = float(payload.get("timestamp") or time.time())
            arrival_perf = time.perf_counter()
            call_state["event_count"] = int(call_state.get("event_count") or 0) + 1
            if not call_state["first_event_at"]:
                call_state["first_event_at"] = timestamp
                if phase_timer is not None:
                    phase_timer.record_offset_ms("model_first_event_ms", perf_value=arrival_perf, if_missing=True)
            if (
                event_type
                and event_type != "response.completed"
                and not answer_stream_state.get("trace_started_id")
            ):
                answer_stream_state["trace_started_id"] = self._emit_activity_trace(
                    progress_cb,
                    run_id=run_id,
                    locale=locale,
                    type="answer.started",
                    stage="answer_generation",
                    detail=(
                        self._activity_detail(
                            task_type=activity_context.get("task_type"),
                            output_mode=activity_context.get("output_mode"),
                            stream_stage=stage,
                        )
                        or "Waiting for the model to finish generating the answer."
                    ),
                    status="running",
                    payload={
                        "model": str(model or ""),
                        "stream_stage": str(stage or ""),
                        "event_type": event_type,
                        **activity_context,
                    },
                    trace_events=trace_events,
                    sequence=int(answer_stream_state.get("delta_count") or 0),
                ) or ""
            if event_type != "response.output_text.delta":
                if event_type == "response.completed":
                    diagnostics = dict(payload.get("diagnostics") or {})
                    for key, value in diagnostics.items():
                        if value not in ("", None, [], {}):
                            call_state[key] = value
                    call_state["completed_at"] = float(diagnostics.get("completed_at") or timestamp or 0.0)
                return

            raw_delta = str(payload.get("delta") or "")
            delta = self._consume_stream_delta_for_display(answer_stream_state, raw_delta)
            if not delta:
                return
            if not answer_stream_state.get("item_started"):
                self._emit_message_item_event(
                    progress_cb,
                    event="item/started",
                    thread_id=thread_id,
                    turn_id=run_id,
                    item={
                        "id": str(answer_stream_state.get("item_id") or ""),
                        "type": "agentMessage",
                        "text": "",
                        "status": "inProgress",
                    },
                )
                answer_stream_state["item_started"] = True
                answer_stream_state["started_at"] = timestamp
            if not answer_stream_state.get("trace_started_id"):
                answer_stream_state["trace_started_id"] = self._emit_activity_trace(
                    progress_cb,
                    run_id=run_id,
                    locale=locale,
                    type="answer.started",
                    stage="answer_generation",
                    detail=(
                        self._activity_detail(
                            task_type=activity_context.get("task_type"),
                            output_mode=activity_context.get("output_mode"),
                            stream_stage=stage,
                        )
                        or "Receiving streamed answer chunks from the model."
                    ),
                    status="running",
                    payload={
                        "model": str(model or ""),
                        "stream_stage": str(stage or ""),
                        **activity_context,
                    },
                    trace_events=trace_events,
                    sequence=int(answer_stream_state.get("delta_count") or 0),
                ) or ""
            self._emit_message_item_event(
                progress_cb,
                event="item/agentMessage/delta",
                thread_id=thread_id,
                turn_id=run_id,
                item_id=str(answer_stream_state.get("item_id") or ""),
                delta=delta,
            )
            answer_stream_state["text"] = f"{str(answer_stream_state.get('text') or '')}{delta}"
            answer_stream_state["delta_count"] = int(answer_stream_state.get("delta_count") or 0) + 1
            answer_stream_state["delta_chars"] = int(answer_stream_state.get("delta_chars") or 0) + len(delta)
            answer_stream_state["finished_at"] = timestamp
            call_state["text_delta_count"] = int(call_state.get("text_delta_count") or 0) + 1
            call_state["text_chars"] = int(call_state.get("text_chars") or 0) + len(delta)
            if not call_state["first_text_delta_at"]:
                call_state["first_text_delta_at"] = timestamp
                if phase_timer is not None:
                    phase_timer.record_offset_ms("model_first_text_delta_ms", perf_value=arrival_perf, if_missing=True)
            call_state["last_text_delta_at"] = timestamp
            trace_delta_budget = int(answer_stream_state.get("text_delta_trace_count") or 0)
            if trace_delta_budget < 4:
                self._emit_activity_trace(
                    progress_cb,
                    run_id=run_id,
                    locale=locale,
                    type="answer.delta",
                    stage="answer_generation",
                    detail=self._activity_detail(
                        chunk=int(answer_stream_state.get("delta_count") or 0),
                        chars=len(delta),
                    ),
                    status="running",
                    payload={
                        "delta_length": len(delta),
                        "delta_preview": safe_preview(delta, limit=120),
                        "model": str(model or ""),
                        "stream_stage": str(stage or ""),
                        **activity_context,
                    },
                    trace_events=trace_events,
                    sequence=int(answer_stream_state.get("delta_count") or 0),
                )
                answer_stream_state["text_delta_trace_count"] = trace_delta_budget + 1

        return observer

    def _answer_stream_diagnostics(self, state: dict[str, Any]) -> dict[str, Any]:
        calls = [dict(item) for item in list(state.get("calls") or []) if isinstance(item, dict)]
        total_delta_count = int(state.get("delta_count") or 0)
        total_chars = int(state.get("delta_chars") or 0)
        upstream_progressive = total_delta_count > 1
        summary = "received streamed answer deltas" if total_delta_count else "no streamed answer deltas observed"
        return {
            "streamed": bool(total_delta_count),
            "upstream_progressive": upstream_progressive,
            "delta_count": total_delta_count,
            "text_chars": total_chars,
            "call_count": len(calls),
            "summary": summary,
            "calls": calls,
        }

    def _finalize_answer_stream(
        self,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        *,
        run_id: str,
        thread_id: str,
        locale: str,
        trace_events: list[dict[str, Any]],
        answer_stream_state: dict[str, Any],
        final_text: str,
        answer_context: dict[str, Any] | None = None,
        revision_summary: dict[str, Any] | None = None,
        phase_timer: PhaseTimer | None = None,
    ) -> dict[str, Any]:
        final_text_value = str(final_text or "")
        streamed_text = str(answer_stream_state.get("text") or "")
        activity_context = dict(answer_context or {})
        revision_payload = dict(revision_summary or {})
        if answer_stream_state.get("item_started"):
            if final_text_value.startswith(streamed_text):
                tail = final_text_value[len(streamed_text) :]
                if tail:
                    self._emit_message_item_event(
                        progress_cb,
                        event="item/agentMessage/delta",
                        thread_id=thread_id,
                        turn_id=run_id,
                        item_id=str(answer_stream_state.get("item_id") or ""),
                        delta=tail,
                    )
                    answer_stream_state["text"] = f"{streamed_text}{tail}"
            self._emit_message_item_event(
                progress_cb,
                event="item/completed",
                thread_id=thread_id,
                turn_id=run_id,
                item={
                    "id": str(answer_stream_state.get("item_id") or ""),
                    "type": "agentMessage",
                    "text": final_text_value,
                    "status": "completed",
                },
            )
            answer_stream_state["item_completed"] = True
            answer_stream_state["finished_at"] = float(answer_stream_state.get("finished_at") or time.time())
        if phase_timer is not None and final_text_value:
            phase_timer.record_offset_ms("answer_ready_ms", if_missing=True)

        diagnostics = self._answer_stream_diagnostics(answer_stream_state)
        if not answer_stream_state.get("trace_started_id") and final_text_value:
            answer_stream_state["trace_started_id"] = self._emit_activity_trace(
                progress_cb,
                run_id=run_id,
                locale=locale,
                type="answer.started",
                stage="answer_generation",
                detail=(
                    self._activity_detail(
                        task_type=activity_context.get("task_type"),
                        output_mode=activity_context.get("output_mode"),
                        answer_source="final_text",
                    )
                    or "Preparing the final answer text."
                ),
                status="running",
                payload={**diagnostics, **activity_context},
                trace_events=trace_events,
            ) or ""
        if final_text_value and not answer_stream_state.get("trace_done_id"):
            done_detail = diagnostics.get("summary") or ""
            context_detail = self._activity_detail(
                task_type=activity_context.get("task_type"),
                output_mode=activity_context.get("output_mode"),
            )
            if context_detail:
                done_detail = f"{context_detail} · {done_detail}" if done_detail else context_detail
            answer_stream_state["trace_done_id"] = self._emit_activity_trace(
                progress_cb,
                run_id=run_id,
                locale=locale,
                type="answer.done",
                stage="answer_generation",
                detail=done_detail,
                status="success",
                payload={
                    "preview": safe_preview(final_text_value, limit=240),
                    "stream_diagnostics": diagnostics,
                    **activity_context,
                    **({"revision_summary": revision_payload} if revision_payload else {}),
                },
                parent_id=str(answer_stream_state.get("trace_started_id") or "") or None,
                trace_events=trace_events,
                sequence=int(answer_stream_state.get("delta_count") or 0),
            ) or ""
        return diagnostics

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
        locale: str,
        raw_tool_call: dict[str, Any] | None = None,
        validation_result: dict[str, Any] | None = None,
        raw_arguments: Any = None,
    ) -> ToolEvent:
        result_json = json.dumps(result, ensure_ascii=False)
        tool_schema = dict((self._tool_specs_by_name.get(name) or {}).get("parameters") or {})
        tool_audit = build_tool_argument_audit(name, arguments, tool_schema, locale=locale)
        raw_call_payload = dict(raw_tool_call or {})
        raw_argument_payload = raw_arguments if raw_arguments is not None else raw_call_payload.get("arguments")
        if raw_argument_payload is None:
            raw_argument_payload = arguments
        source_refs = self._collect_source_refs(result)
        status = "ok" if bool(result.get("ok")) else "error"
        error_value = result.get("error")
        summary = str(result.get("summary") or "").strip()
        if not summary and error_value:
            if isinstance(error_value, dict):
                summary = safe_error_message(error_value.get("message") or error_value.get("kind") or translate(locale, "runtime.tool.failed"))
            else:
                summary = safe_error_message(error_value)
        if not summary:
            summary = summarize_tool_result(name, result, locale=locale) or self._backend._shorten(result_json, 180)
        diagnostics = dict(result.get("diagnostics") or {}) if isinstance(result.get("diagnostics"), dict) else {}
        descriptor = dict(self._tool_descriptors_by_name.get(name) or {})
        group = str(descriptor.get("group") or "")
        source = str(descriptor.get("source") or "")
        validation_payload = dict(validation_result or {})
        return ToolEvent(
            name=name or "(unknown)",
            input=arguments,
            raw_tool_call=safe_preview(raw_call_payload, limit=4000) if raw_call_payload else {},
            raw_arguments=safe_preview(raw_argument_payload, limit=4000),
            normalized_arguments=safe_preview(arguments, limit=4000) if isinstance(arguments, dict) else {},
            validation_result=validation_payload,
            arguments_preview=str(tool_audit.get("arguments_preview") or ""),
            preview_error=str(tool_audit.get("preview_error") or ""),
            schema_validation=dict(tool_audit.get("schema_validation") or {}),
            output_preview=self._backend._shorten(result_json, 1200),
            result_preview=safe_preview(result, limit=4000),
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
    def _structured_tool_error_result(tool_name: str, exc: BaseException | str) -> dict[str, Any]:
        message = safe_error_message(exc)
        return {
            "ok": False,
            "error": {
                "kind": "tool_execution_error",
                "tool": str(tool_name or ""),
                "message": message,
            },
            "summary": message,
        }

    def _execute_tool_with_trace(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        raw_tool_call: dict[str, Any] | None,
        validation_result: dict[str, Any] | None,
        raw_arguments: Any = None,
        run_id: str,
        locale: str,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        trace_events: list[dict[str, Any]],
        tool_events: list[ToolEvent],
        current_goal: str,
        current_task_focus: dict[str, Any],
        collaboration_mode: str,
        turn_status: str,
        plan_state: list[dict[str, Any]],
        pending_user_input: dict[str, Any],
        effective_cwd: str,
        spec: VintageProgrammerSpec,
        round_idx: int,
        call_idx: int,
    ) -> tuple[dict[str, Any], ToolEvent]:
        tool_schema = dict((self._tool_specs_by_name.get(name) or {}).get("parameters") or {})
        tool_audit = build_tool_argument_audit(name, arguments, tool_schema, locale=locale)
        started_id = self._emit_trace(
            progress_cb,
            run_id=run_id,
            type="tool.started",
            title=self._trace_label(locale, "tool.started", tool=name or "tool"),
            detail=str(tool_audit.get("arguments_preview") or summarize_tool_args(name, arguments)),
            status="running",
            payload={
                "tool_name": name,
                "raw_tool_call": safe_preview(raw_tool_call, limit=4000),
                "normalized_arguments": safe_preview(arguments, limit=4000),
                "validation_result": dict(validation_result or {}),
                **tool_audit,
            },
            trace_events=trace_events,
        )
        started_at = time.monotonic()
        try:
            result = self._backend.tools.execute(name, arguments)
        except Exception as exc:
            result = self._structured_tool_error_result(name, exc)
        duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
        event = self._build_tool_event(
            name=name,
            arguments=arguments,
            result=result,
            locale=locale,
            raw_tool_call=raw_tool_call,
            validation_result=validation_result,
            raw_arguments=raw_arguments,
        )
        tool_events.append(event)
        trace_type = "tool.finished" if event.status == "ok" else "tool.failed"
        trace_status = "success" if event.status == "ok" else "failed"
        self._emit_trace(
            progress_cb,
            run_id=run_id,
            type=trace_type,
            title=self._trace_label(locale, trace_type, tool=name or "tool"),
            detail=summarize_tool_result(name, result, locale=locale),
            status=trace_status,
            duration_ms=duration_ms,
            payload={
                "tool_name": name,
                "raw_tool_call": safe_preview(raw_tool_call, limit=4000),
                "normalized_arguments": safe_preview(arguments, limit=4000),
                "validation_result": dict(validation_result or {}),
                **tool_audit,
                "result_preview": safe_preview(result),
            },
            parent_id=started_id,
            trace_events=trace_events,
        )
        if progress_cb is not None:
            progress_cb(
                    {
                        "event": "tool",
                        "item": dump_model(event),
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
        return result, event

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
        prefer_goal: bool = False,
    ) -> dict[str, Any]:
        restored = self._normalize_task_checkpoint((route_state or {}).get("task_checkpoint"))
        if restored:
            restored["task_id"] = restored.get("task_id") or str(uuid.uuid4())
            restored["project_root"] = restored.get("project_root") or project_root
            restored["cwd"] = restored.get("cwd") or cwd or project_root
            restored["goal"] = goal if prefer_goal and goal else (restored.get("goal") or goal)
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
        if tool_name in {
            "read_file",
            "list_dir",
            "glob_file_search",
            "search_contents_in_file",
            "search_contents_in_file_multi",
            "read_section",
            "table_extract",
            "fact_check_file",
            "image_read",
            "image_inspect",
        }:
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

    @staticmethod
    def _activity_detail(**fields: Any) -> str:
        parts: list[str] = []
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized = "true" if value else "false"
            else:
                normalized = str(value).strip()
            if not normalized:
                continue
            parts.append(f"{key}={normalized}")
        return " · ".join(parts)

    @staticmethod
    def _looks_like_revision_request(text: str, *, route_state: dict[str, Any] | None = None) -> bool:
        route = dict(route_state or {})
        if bool(route.get("use_revision")):
            return True
        raw = str(text or "")
        lowered = raw.lower()
        return any(token in raw for token in _REVISION_REQUEST_HINTS) or any(token in lowered for token in _REVISION_REQUEST_HINTS)

    @classmethod
    def _looks_like_japanese_review_request(cls, text: str, *, route_state: dict[str, Any] | None = None) -> bool:
        raw = str(text or "")
        lowered = raw.lower()
        route = dict(route_state or {})
        route_task_type = str(route.get("task_type") or "").strip().lower()
        if route_task_type == "translation_session":
            return False
        has_japanese_hint = any(token in raw for token in _JAPANESE_REQUEST_HINTS) or any(token in lowered for token in _JAPANESE_REQUEST_HINTS)
        has_kana = bool(_JAPANESE_KANA_RE.search(raw))
        return cls._looks_like_revision_request(raw, route_state=route) and (has_japanese_hint or has_kana)

    @staticmethod
    def _extract_activity_excerpt(text: str, *, prefer_japanese: bool = False) -> str:
        lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = " ".join(str(raw_line or "").split())
            if not line:
                continue
            for separator in ("：", ":"):
                if separator in line:
                    prefix, suffix = line.split(separator, 1)
                    candidate = suffix.strip()
                    if candidate and (bool(_JAPANESE_KANA_RE.search(candidate)) or len(candidate) >= len(prefix.strip())):
                        line = candidate
                        break
            lines.append(line)
        if prefer_japanese:
            japanese_lines = [line for line in lines if _JAPANESE_KANA_RE.search(line)]
            if japanese_lines:
                return str(safe_preview(" / ".join(japanese_lines[:2]), limit=220) or "")
        candidates = [line for line in lines if len(line) >= 8] or lines
        if not candidates:
            return ""
        return str(safe_preview(" / ".join(candidates[:2]), limit=220) or "")

    def _normalize_model_tool_calls(self, tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        proposed_tool_calls: list[dict[str, Any]] = []
        normalization_notes: list[str] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            raw_name = str(call.get("name") or "").strip()
            name = self._normalize_tool_name(raw_name)
            raw_arguments = call.get("args")
            arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
            normalized_call = {
                "id": str(call.get("id") or ""),
                "name": name,
                "raw_name": raw_name,
                "args": dict(arguments),
                "raw_args": raw_arguments,
            }
            if raw_name and raw_name != name:
                normalization_notes.append(f"{raw_name}->{name}")
            proposed_tool_calls.append(normalized_call)
        return proposed_tool_calls, normalization_notes

    def _resolve_model_action(
        self,
        *,
        ai_text: str,
        tool_calls: list[dict[str, Any]],
        step_index: int,
    ) -> dict[str, Any]:
        proposed_tool_calls, normalization_notes = self._normalize_model_tool_calls(tool_calls)
        if proposed_tool_calls:
            action_type = "tool_call"
            reason = (
                f"Model requested {len(proposed_tool_calls)} tool call(s); ActionValidator will validate each call before execution."
                if len(proposed_tool_calls) > 1
                else f"Model requested {proposed_tool_calls[0].get('name') or proposed_tool_calls[0].get('raw_name') or 'a tool'}; ActionValidator will validate it before execution."
            )
        elif str(ai_text or "").strip():
            action_type = "final_answer"
            reason = "Answer directly from the available context."
        else:
            action_type = "empty"
            reason = "The model did not emit an executable current step."
        tool_names = [
            str(item.get("name") or item.get("raw_name") or "")
            for item in proposed_tool_calls
            if str(item.get("name") or item.get("raw_name") or "").strip()
        ]
        return {
            "step_index": max(1, int(step_index)),
            "action_type": action_type,
            "tool_name": tool_names[0] if tool_names else "",
            "tool_names": tool_names,
            "tool_calls": proposed_tool_calls,
            "accepted": action_type != "empty",
            "reason": reason,
            "normalization_notes": normalization_notes,
            "text_chars": len(str(ai_text or "")),
            "source": "model_action",
        }

    def _validate_model_tool_call(
        self,
        *,
        call: dict[str, Any],
        runnable_tools: list[str],
        locale: str,
        runtime_boundary: RuntimeBoundary,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ValidationResult:
        raw_tool_name = str(call.get("raw_name") or call.get("name") or "").strip()
        validator = ActionValidator(
            tool_specs=self._tool_specs,
            allowed_tools=runnable_tools,
            boundary=runtime_boundary,
            locale=locale,
            normalize_tool_name=self._normalize_tool_name,
            argument_rewriter=lambda tool_name, arguments: self._rewrite_attachment_tool_arguments(
                name=tool_name,
                arguments=arguments,
                attachments=list(attachments or []),
            ),
        )
        validation = validator.validate_tool_call(call)
        tool_name = validation.tool_name or self._normalize_tool_name(str(call.get("name") or raw_tool_name).strip())
        if raw_tool_name and raw_tool_name != tool_name:
            validation.normalization_notes = [*list(validation.normalization_notes or []), f"{raw_tool_name}->{tool_name}"]
        if validation.code == "unknown_tool":
            allowed_preview = ", ".join(runnable_tools[:8])
            validation.message = (
                translate(locale, "runtime.tool.guard.unknown_tool", tool=raw_tool_name or tool_name or "(empty)", allowed_tools=allowed_preview)
                if allowed_preview
                else translate(locale, "runtime.tool.guard.rejected_call", tool=raw_tool_name or tool_name or "(empty)")
            )
        elif validation.code == "tool_not_allowed":
            validation.message = translate(locale, "runtime.tool.guard.outside_boundary", tool=tool_name or raw_tool_name or "(empty)")
        return validation

    @staticmethod
    def _validation_activity_detail(locale: str, validation_result: dict[str, Any]) -> str:
        validation = dict(validation_result or {})
        tool_name = str(validation.get("tool_name") or validation.get("raw_tool_name") or "tool").strip() or "tool"
        if bool(validation.get("allowed")):
            notes = [str(item) for item in list(validation.get("normalization_notes") or []) if str(item or "")]
            suffix = f" ({', '.join(notes[:3])})" if notes else ""
            return translate(locale, "runtime.activity.guard.normalized_continued", tool=tool_name, suffix=suffix)
        return str(validation.get("message") or translate(locale, "runtime.activity.guard.rejected", tool=tool_name))[:280]

    @staticmethod
    def _execution_activity_detail(locale: str, entry: dict[str, Any]) -> str:
        item = dict(entry or {})
        observation = str(item.get("observation_summary") or "").strip()
        if observation:
            return observation
        return str(item.get("result_summary") or "").strip() or translate(locale, "runtime.activity.execution.recorded")

    @staticmethod
    def _activity_context_from_action(model_action: dict[str, Any]) -> dict[str, Any]:
        action = dict(model_action or {})
        action_type = str(action.get("action_type") or "empty").strip() or "empty"
        response_mode = "tool_call" if action_type == "tool_call" else ("final_answer" if action_type == "final_answer" else "empty")
        return {
            "task_type": "model_action",
            "primary_intent": action_type,
            "output_mode": response_mode,
            "response_mode": response_mode,
            "action_type": action_type,
            "tool_names": list(action.get("tool_names") or []),
            "source": "model_action",
        }

    @staticmethod
    def _append_execution_trace(
        execution_trace: list[dict[str, Any]],
        entry: ExecutionTraceEntry,
    ) -> list[dict[str, Any]]:
        next_trace = [*list(execution_trace or []), dump_model(entry)]
        return next_trace[-24:]

    @staticmethod
    def _stable_json_for_hash(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return repr(value)

    @classmethod
    def _hash_payload(cls, value: Any) -> str:
        raw = cls._stable_json_for_hash(value)
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]

    @classmethod
    def _action_fingerprint(cls, tool_name: str, normalized_arguments: dict[str, Any]) -> str:
        name = str(tool_name or "").strip() or "tool"
        return f"{name}:{cls._hash_payload(dict(normalized_arguments or {}))}"

    @staticmethod
    def _new_progress_tracker() -> dict[str, Any]:
        return {
            "file_reads": set(),
            "directory_entries": set(),
            "glob_matches": set(),
            "search_hits": set(),
            "section_reads": set(),
            "command_results": set(),
            "web_results": set(),
            "generic_results": set(),
            "patches": set(),
            "plan_completed": set(),
            "error_kinds": set(),
        }

    @staticmethod
    def _tool_result_items(result: dict[str, Any], *keys: str) -> list[Any]:
        payload = dict(result or {}) if isinstance(result, dict) else {}
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
        return []

    @staticmethod
    def _progress_detail_from_result(tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
        payload = dict(result or {}) if isinstance(result, dict) else {}
        if tool_name in {"read_file", "read_section"}:
            return str(arguments.get("path") or payload.get("path") or "").strip()
        if tool_name in {"search_contents_in_file", "search_contents_in_file_multi", "search_codebase"}:
            query = arguments.get("query")
            if query in ("", None):
                queries = list(arguments.get("queries") or [])
                query = ",".join(str(item) for item in queries[:4])
            path = str(arguments.get("path") or payload.get("path") or "").strip()
            return " · ".join(item for item in [path, str(query or "").strip()] if item)
        if tool_name == "glob_file_search":
            return str(arguments.get("pattern") or "").strip()
        if tool_name == "list_dir":
            return str(arguments.get("path") or payload.get("path") or "").strip()
        if tool_name == "apply_patch":
            files = list(payload.get("files") or [])
            return ", ".join(str(item) for item in files[:4] if str(item or "").strip())
        if tool_name == "exec_command":
            return str(arguments.get("cmd") or "").strip()
        if tool_name == "update_plan":
            return str(payload.get("summary") or "").strip()
        return str(payload.get("summary") or "").strip()

    @classmethod
    def _progress_signal_from_tool_result(
        cls,
        *,
        locale: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        event_status: str,
        plan_state_before: list[dict[str, Any]],
        tracker: dict[str, Any],
        action_fingerprint: str,
    ) -> ProgressSignal:
        name = str(tool_name or "").strip() or "tool"
        payload = dict(result or {}) if isinstance(result, dict) else {}
        ok = bool(payload.get("ok"))
        detail = cls._progress_detail_from_result(name, arguments, payload)
        if not ok:
            error = payload.get("error")
            error_kind = str(error.get("kind") or "") if isinstance(error, dict) else ""
            error_message = safe_error_message(
                (error.get("message") if isinstance(error, dict) else error)
                or payload.get("summary")
                or translate(locale, "runtime.tool.failed")
            )
            error_key = f"{name}:{error_kind or 'error'}"
            seen_error_kinds = tracker.setdefault("error_kinds", set())
            if error_key not in seen_error_kinds:
                seen_error_kinds.add(error_key)
                return ProgressSignal(
                    has_progress=True,
                    score=1,
                    kind="new_error_type",
                    summary=translate(locale, "runtime.progress.new_error_type", detail=error_message[:120]),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=detail,
                    payload={"error_kind": error_kind or "error", "event_status": event_status},
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="repeated_error",
                summary=translate(locale, "runtime.progress.repeated_error", detail=error_message[:120]),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=detail,
                payload={"error_kind": error_kind or "error", "event_status": event_status},
            )

        if name == "read_file":
            path = str(arguments.get("path") or payload.get("path") or "").strip()
            content_key = f"{path}:{cls._hash_payload(payload.get('content') or payload.get('summary') or path)}"
            seen = tracker.setdefault("file_reads", set())
            if content_key not in seen:
                seen.add(content_key)
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_file_read",
                    summary=translate(locale, "runtime.progress.new_file_read", target=path or name),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=path,
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="duplicate_result",
                summary=translate(locale, "runtime.progress.duplicate_result", detail=path or name),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=path,
            )

        if name == "list_dir":
            base_path = str(arguments.get("path") or payload.get("path") or ".").strip() or "."
            entries = cls._tool_result_items(payload, "entries")
            new_entries = 0
            seen = tracker.setdefault("directory_entries", set())
            for entry in entries:
                if isinstance(entry, dict):
                    entry_key = str(entry.get("path") or f"{base_path}:{entry.get('name') or ''}")
                else:
                    entry_key = str(entry)
                if entry_key and entry_key not in seen:
                    seen.add(entry_key)
                    new_entries += 1
            if new_entries > 0:
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_directory_entries",
                    summary=translate(locale, "runtime.progress.new_directory_entries", target=base_path, count=new_entries),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=base_path,
                    payload={"new_entries": new_entries},
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="no_new_info",
                summary=translate(locale, "runtime.progress.no_new_info", detail=base_path),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=base_path,
            )

        if name == "glob_file_search":
            matches = cls._tool_result_items(payload, "matches")
            seen = tracker.setdefault("glob_matches", set())
            new_matches = 0
            for item in matches:
                match_key = str(item.get("path") or item) if isinstance(item, dict) else str(item)
                if match_key and match_key not in seen:
                    seen.add(match_key)
                    new_matches += 1
            if new_matches > 0:
                pattern = str(arguments.get("pattern") or "").strip()
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_glob_matches",
                    summary=translate(locale, "runtime.progress.new_glob_matches", target=pattern or name, count=new_matches),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=pattern,
                    payload={"new_matches": new_matches},
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="no_new_info",
                summary=translate(locale, "runtime.progress.no_new_info", detail=str(arguments.get("pattern") or name)),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=str(arguments.get("pattern") or ""),
            )

        if name in {"search_contents_in_file", "search_contents_in_file_multi", "search_codebase", "web_search"}:
            hits = cls._tool_result_items(payload, "matches", "results")
            seen = tracker.setdefault("search_hits", set())
            new_hits = 0
            for item in hits:
                item_key = cls._hash_payload(item)
                scoped_key = f"{name}:{item_key}"
                if scoped_key not in seen:
                    seen.add(scoped_key)
                    new_hits += 1
            query_value = arguments.get("query")
            if query_value in ("", None):
                queries = list(arguments.get("queries") or [])
                query_value = ",".join(str(item) for item in queries[:4])
            query_text = str(query_value or "").strip()
            if new_hits > 0:
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_search_hits",
                    summary=translate(locale, "runtime.progress.new_search_hits", target=query_text or name, count=new_hits),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=detail,
                    payload={"new_hits": new_hits},
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="no_new_info",
                summary=translate(locale, "runtime.progress.no_new_info", detail=query_text or detail or name),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=detail,
            )

        if name == "read_section":
            path = str(arguments.get("path") or payload.get("path") or "").strip()
            heading = str(arguments.get("heading") or "").strip()
            section_key = f"{path}:{heading}:{cls._hash_payload(payload.get('content') or payload.get('summary') or '')}"
            seen = tracker.setdefault("section_reads", set())
            if section_key not in seen:
                seen.add(section_key)
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_section_read",
                    summary=translate(locale, "runtime.progress.new_section_read", target=path or heading or name),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=detail,
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="duplicate_result",
                summary=translate(locale, "runtime.progress.duplicate_result", detail=detail or name),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=detail,
            )

        if name == "apply_patch":
            patch_key = cls._hash_payload({"files": payload.get("files") or [], "summary": payload.get("summary") or ""})
            seen = tracker.setdefault("patches", set())
            if patch_key not in seen:
                seen.add(patch_key)
                return ProgressSignal(
                    has_progress=True,
                    score=4,
                    kind="patch_applied",
                    summary=translate(locale, "runtime.progress.patch_applied", detail=detail or name),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=detail,
                )

        if name == "exec_command":
            command = str(arguments.get("cmd") or "").strip()
            signature = cls._hash_payload(
                {
                    "cmd": command,
                    "returncode": payload.get("returncode"),
                    "output": payload.get("output"),
                }
            )
            seen = tracker.setdefault("command_results", set())
            if signature not in seen:
                seen.add(signature)
                is_test_command = bool(re.search(r"\b(pytest|test|npm test|pnpm test|yarn test|uv run)\b", command))
                return ProgressSignal(
                    has_progress=True,
                    score=2 if not is_test_command else 3,
                    kind="test_result_changed" if is_test_command else "command_result_changed",
                    summary=translate(
                        locale,
                        "runtime.progress.test_result_changed" if is_test_command else "runtime.progress.command_result_changed",
                        detail=command[:120] or name,
                    ),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=command,
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="duplicate_result",
                summary=translate(locale, "runtime.progress.duplicate_result", detail=command[:120] or name),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=command,
            )

        if name == "update_plan":
            previous_completed = {
                f"{str(item.get('step') or '')}:{str(item.get('status') or '')}"
                for item in list(plan_state_before or [])
                if isinstance(item, dict) and str(item.get("status") or "").strip() == "completed"
            }
            next_plan = list(payload.get("plan") or [])
            next_completed = {
                f"{str(item.get('step') or '')}:{str(item.get('status') or '')}"
                for item in next_plan
                if isinstance(item, dict) and str(item.get("status") or "").strip() == "completed"
            }
            newly_completed = sorted(next_completed - previous_completed)
            seen = tracker.setdefault("plan_completed", set())
            for item in newly_completed:
                seen.add(item)
            if newly_completed:
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="plan_updated",
                    summary=translate(locale, "runtime.progress.plan_updated", count=len(newly_completed)),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=str(payload.get("summary") or ""),
                    payload={"completed_items": newly_completed[:8]},
                )
            return ProgressSignal(
                has_progress=False,
                score=0,
                kind="no_new_info",
                summary=translate(locale, "runtime.progress.no_new_info", detail=str(payload.get("summary") or name)),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=str(payload.get("summary") or ""),
            )

        if name in {"web_fetch", "web_download", "image_read", "image_inspect"}:
            signature = cls._hash_payload(
                {
                    "url": payload.get("url") or arguments.get("url"),
                    "path": payload.get("path") or arguments.get("path"),
                    "title": payload.get("title"),
                    "summary": payload.get("summary"),
                    "visible_text": payload.get("visible_text"),
                }
            )
            seen = tracker.setdefault("web_results", set())
            if signature not in seen:
                seen.add(signature)
                return ProgressSignal(
                    has_progress=True,
                    score=2,
                    kind="new_web_result",
                    summary=translate(locale, "runtime.progress.new_web_result", detail=detail or name),
                    action_fingerprint=action_fingerprint,
                    tool_name=name,
                    detail=detail,
                )

        generic_signature = f"{name}:{event_status}:{cls._hash_payload(payload.get('summary') or payload)}"
        seen = tracker.setdefault("generic_results", set())
        if generic_signature not in seen:
            seen.add(generic_signature)
            return ProgressSignal(
                has_progress=True,
                score=1,
                kind="new_tool_output",
                summary=translate(locale, "runtime.progress.new_tool_output", detail=detail or name),
                action_fingerprint=action_fingerprint,
                tool_name=name,
                detail=detail,
            )
        return ProgressSignal(
            has_progress=False,
            score=0,
            kind="duplicate_result",
            summary=translate(locale, "runtime.progress.duplicate_result", detail=detail or name),
            action_fingerprint=action_fingerprint,
            tool_name=name,
            detail=detail,
        )

    @staticmethod
    def _recent_action_summaries(signals: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
        items: list[str] = []
        for signal in list(signals or [])[-limit:]:
            if not isinstance(signal, dict):
                continue
            summary = str(signal.get("summary") or "").strip()
            if summary:
                items.append(summary)
        return items[-limit:]

    @staticmethod
    def _recent_failed_action_summaries(tool_events: list[ToolEvent], *, limit: int = 6) -> list[str]:
        items: list[str] = []
        for event in list(tool_events or [])[-limit:]:
            if getattr(event, "status", "") == "ok":
                continue
            detail = str(getattr(event, "summary", "") or getattr(event, "output_preview", "")).strip()
            label = str(getattr(event, "name", "") or "tool").strip() or "tool"
            if detail:
                items.append(f"{label}: {detail[:160]}")
            else:
                items.append(label)
        return items[-limit:]

    def _build_replan_checkpoint_prompt(
        self,
        *,
        locale: str,
        current_goal: str,
        current_task_focus: dict[str, Any],
        progress_signals: list[dict[str, Any]],
        tool_events: list[ToolEvent],
        trigger: str,
    ) -> str:
        active_files = [str(item) for item in list(current_task_focus.get("active_files") or []) if str(item or "").strip()]
        recent_progress = self._recent_action_summaries(progress_signals)
        recent_failures = self._recent_failed_action_summaries(tool_events)
        lines = [
            translate(locale, "runtime.replan.system_prompt", trigger=trigger),
            f"current_goal: {current_goal}",
        ]
        if active_files:
            lines.append("active_files: " + json.dumps(active_files[:6], ensure_ascii=False))
        if recent_progress:
            lines.append(translate(locale, "runtime.replan.known_facts_intro"))
            lines.extend(f"- {item}" for item in recent_progress[:6])
        if recent_failures:
            lines.append(translate(locale, "runtime.replan.failed_actions_intro"))
            lines.extend(f"- {item}" for item in recent_failures[:6])
        lines.append(translate(locale, "runtime.replan.required_next_move"))
        return "\n".join(item for item in lines if item).strip()

    def _resolve_model_step(
        self,
        *,
        ai_text: str,
        tool_calls: list[dict[str, Any]],
        step_index: int,
    ) -> dict[str, Any]:
        cleaned_text = str(ai_text or "").strip()
        model_action = self._resolve_model_action(
            ai_text=cleaned_text,
            tool_calls=tool_calls,
            step_index=step_index,
        )
        return {
            "clean_text": cleaned_text,
            "model_action": dict(model_action),
            "activity_context": self._activity_context_from_action(model_action),
        }

    def _build_revision_summary(
        self,
        *,
        prompt_message: str,
        raw_text: str,
        activity_context: dict[str, Any],
    ) -> dict[str, Any]:
        context = dict(activity_context or {})
        if not bool(context.get("prefer_change_summary")):
            return {}
        task_type = str(context.get("task_type") or "").strip()
        prefer_japanese = task_type == "japanese_grammar_review"
        original_excerpt = self._extract_activity_excerpt(prompt_message, prefer_japanese=prefer_japanese)
        result_excerpt = self._extract_activity_excerpt(raw_text, prefer_japanese=prefer_japanese)
        if prefer_japanese and result_excerpt == original_excerpt:
            fallback_excerpt = self._extract_activity_excerpt(raw_text, prefer_japanese=False)
            if fallback_excerpt:
                result_excerpt = fallback_excerpt
        if not original_excerpt or not result_excerpt:
            return {}
        return {
            "task_type": task_type,
            "output_mode": str(context.get("output_mode") or ""),
            "items": [
                {
                    "original_excerpt": original_excerpt,
                    "result_excerpt": result_excerpt,
                    "reason": str(context.get("summary_reason") or ""),
                }
            ],
        }

    @staticmethod
    def _write_authorization_state(message: str, *, collaboration_mode: str, project_root: str) -> dict[str, Any]:
        normalized = " ".join(str(message or "").split()).lower()
        has_write_intent = any(hint.lower() in normalized for hint in _WRITE_INTENT_HINTS)
        explicit_authorization = any(hint.lower() in normalized for hint in _EXPLICIT_WRITE_AUTH_HINTS)
        authorized = collaboration_mode in {"default", "execute"} and has_write_intent
        reasons: list[str] = []
        if has_write_intent:
            reasons.append("write_intent_detected")
        if explicit_authorization:
            reasons.append("explicit_user_authorization")
        return {
            "authorized": bool(authorized),
            "scope": "workspace" if authorized else "",
            "project_root": str(project_root or ""),
            "requires_structured_approval_for": [
                "project_outside_write",
                "large_delete_or_move",
                "dangerous_shell",
                "network_or_system_level_side_effect",
            ],
            "reason": ",".join(reasons),
        }

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

    def _build_attachment_tool_guidance(self, attachments: list[dict[str, Any]], *, locale: str) -> str:
        if not attachments:
            return ""
        lines: list[str] = [
            translate(locale, "runtime.attachment_guidance.intro"),
            translate(locale, "runtime.attachment_guidance.no_guess"),
        ]
        image_paths = self._attachment_paths(attachments, kind="image")
        if image_paths:
            lines.append(translate(locale, "runtime.attachment_guidance.image"))
            lines.append(
                translate(
                    locale,
                    "runtime.attachment_guidance.image_paths",
                    paths=json.dumps(image_paths[:2], ensure_ascii=False),
                )
            )
        document_paths = self._attachment_paths(attachments, kind="document")
        if document_paths:
            lines.append(translate(locale, "runtime.attachment_guidance.document"))
            lines.append(translate(locale, "runtime.attachment_guidance.msg"))
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
        locale: str,
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
        if self._callable_accepts_kwarg(setter, "locale"):
            kwargs["locale"] = locale
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
        elif tool_name in {
            "read_file",
            "list_dir",
            "glob_file_search",
            "search_contents_in_file",
            "search_contents_in_file_multi",
            "read_section",
            "table_extract",
            "fact_check_file",
        } and "path" in normalized:
            normalized["path"] = self._resolve_attachment_argument_path(normalized.get("path"), attachments)
        elif tool_name == "archive_extract" and "zip_path" in normalized:
            normalized["zip_path"] = self._resolve_attachment_argument_path(normalized.get("zip_path"), attachments)
        elif tool_name == "mail_extract_attachments" and "msg_path" in normalized:
            normalized["msg_path"] = self._resolve_attachment_argument_path(normalized.get("msg_path"), attachments)
        return normalized

    @staticmethod
    def _cancel_requested(context: dict[str, Any]) -> bool:
        event = context.get("cancel_event")
        return bool(event and hasattr(event, "is_set") and event.is_set())

    @staticmethod
    def _tool_cancelled_result(tool_name: str, call_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "kind": "tool_cancelled",
                "tool": str(tool_name or ""),
                "tool_call_id": str(call_id or ""),
                "message": "Tool execution was cancelled before this call was run.",
            },
            "summary": "cancelled",
        }

    @staticmethod
    def _tool_skipped_result(tool_name: str, call_id: str, *, reason: str) -> dict[str, Any]:
        reason_text = str(reason or "Tool execution was skipped after the turn reached a terminal state.")
        return {
            "ok": False,
            "error": {
                "kind": "tool_skipped",
                "tool": str(tool_name or ""),
                "tool_call_id": str(call_id or ""),
                "message": reason_text,
            },
            "summary": reason_text,
        }

    @staticmethod
    def _message_role(msg: Any) -> str:
        kwargs = getattr(msg, "kwargs", None)
        if isinstance(kwargs, dict) and str(kwargs.get("tool_call_id") or "").strip():
            return "tool"
        if str(getattr(msg, "tool_call_id", "") or "").strip():
            return "tool"
        role = str(getattr(msg, "type", "") or getattr(msg, "role", "") or "").strip().lower()
        if role:
            if role == "assistant":
                return "ai"
            if role == "user":
                return "human"
            return role
        class_name = msg.__class__.__name__.lower()
        if "tool" in class_name:
            return "tool"
        if "ai" in class_name or "assistant" in class_name:
            return "ai"
        if "human" in class_name or "user" in class_name:
            return "human"
        if "system" in class_name:
            return "system"
        if list(getattr(msg, "tool_calls", None) or []):
            return "ai"
        return ""

    @staticmethod
    def _tool_call_ids_from_ai_message(msg: Any) -> list[str]:
        ids: list[str] = []
        for call in list(getattr(msg, "tool_calls", None) or []):
            if isinstance(call, dict):
                call_id = str(call.get("id") or "").strip()
                if call_id:
                    ids.append(call_id)
        return ids

    @staticmethod
    def _tool_message_call_id(msg: Any) -> str:
        kwargs = getattr(msg, "kwargs", None)
        if isinstance(kwargs, dict):
            value = str(kwargs.get("tool_call_id") or "").strip()
            if value:
                return value
        return str(getattr(msg, "tool_call_id", "") or "").strip()

    def _messages_at_tool_boundary(self, messages: list[Any]) -> bool:
        pending: list[str] = []
        for msg in list(messages or []):
            role = self._message_role(msg)
            if pending:
                if role != "tool":
                    return False
                tool_call_id = self._tool_message_call_id(msg)
                if tool_call_id not in pending:
                    return False
                pending.remove(tool_call_id)
                continue
            if role == "tool":
                return False
            if role in {"ai", "assistant"}:
                pending.extend(self._tool_call_ids_from_ai_message(msg))
        return not pending

    def _tool_boundary_diagnostics(self, messages: list[Any]) -> dict[str, Any]:
        pending: list[str] = []
        orphan_tool_message_ids: list[str] = []
        first_error = ""
        for index, msg in enumerate(list(messages or [])):
            role = self._message_role(msg)
            if pending:
                if role != "tool":
                    first_error = first_error or f"non_tool_message_before_pending_closed:{index}:{role}"
                    break
                tool_call_id = self._tool_message_call_id(msg)
                if tool_call_id not in pending:
                    orphan_tool_message_ids.append(tool_call_id)
                    first_error = first_error or f"unexpected_tool_call_id:{tool_call_id}"
                    break
                pending.remove(tool_call_id)
                continue
            if role == "tool":
                orphan_tool_message_ids.append(self._tool_message_call_id(msg))
                first_error = first_error or f"orphan_tool_message:{index}"
                break
            if role in {"ai", "assistant"}:
                pending.extend(self._tool_call_ids_from_ai_message(msg))
        return {
            "ok": not pending and not orphan_tool_message_ids and not first_error,
            "pending_tool_call_ids": list(pending),
            "orphan_tool_message_ids": list(orphan_tool_message_ids),
            "message_count": len(list(messages or [])),
            "error": first_error,
        }

    def _assert_tool_message_invariants(
        self,
        messages: list[Any],
        *,
        phase: str,
        trace_events: list[dict[str, Any]] | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        run_id: str = "",
        locale: str = "",
    ) -> None:
        if self._messages_at_tool_boundary(messages):
            return
        diagnostics = self._tool_boundary_diagnostics(messages)
        self._emit_trace(
            progress_cb,
            run_id=run_id,
            type="tool_invariant.failed",
            title="Tool message invariant failed",
            detail=str(diagnostics.get("error") or phase),
            status="failed",
            payload={"phase": phase, **diagnostics},
            trace_events=trace_events,
        )
        _ = locale
        raise RuntimeError(f"tool message invariant failed at {phase}: {diagnostics}")

    @staticmethod
    def _ensure_model_tool_call_ids(
        ai_msg: Any,
        tool_calls: list[dict[str, Any]],
        *,
        agent_id: str,
        round_idx: int,
    ) -> list[dict[str, Any]]:
        ensured: list[dict[str, Any]] = []
        raw_ai_calls = list(getattr(ai_msg, "tool_calls", None) or [])
        for index, call in enumerate(list(tool_calls or []), start=1):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip() or f"{agent_id}_{round_idx}_{index}"
            call["id"] = call_id
            if index <= len(raw_ai_calls) and isinstance(raw_ai_calls[index - 1], dict):
                raw_ai_calls[index - 1]["id"] = call_id
            ensured.append(call)
        try:
            ai_msg.tool_calls = raw_ai_calls if raw_ai_calls else ensured
        except Exception:
            pass
        return ensured

    def _tool_message_for_result(self, *, result: dict[str, Any], call_id: str, name: str) -> Any:
        result_json = json.dumps(result, ensure_ascii=False)
        return self._backend._ToolMessage(
            content=self._backend._shorten(result_json, 60000),
            tool_call_id=str(call_id or ""),
            name=name or "unknown_tool",
        )

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
        model: str | None,
        auto_compact_token_limit: int,
        context_window_known: bool,
    ) -> tuple[list[Any], int, bool, int]:
        if not self._messages_at_tool_boundary(messages):
            return messages, compacted_until, False, 0
        estimated_tokens = 0
        try:
            estimated_tokens = count_tokens(
                "\n".join(
                    self._backend._shorten(str(getattr(item, "content", getattr(item, "text", item))), 3000)
                    for item in list(messages)
                ),
                model,
            )
        except Exception:
            estimated_tokens = 0
        if auto_compact_token_limit > 0 and estimated_tokens < auto_compact_token_limit:
            return messages, compacted_until, False, estimated_tokens
        if auto_compact_token_limit <= 0 and len(tool_events) - compacted_until < _DEFAULT_COMPACT_AFTER_TOOL_CALLS:
            return messages, compacted_until, False, estimated_tokens
        if (
            auto_compact_token_limit > 0
            and not context_window_known
            and len(tool_events) - compacted_until < _DEFAULT_COMPACT_AFTER_TOOL_CALLS
        ):
            return messages, compacted_until, False, estimated_tokens
        if len(messages) <= base_message_count + _DEFAULT_COMPACT_KEEP_LAST_MESSAGES:
            return messages, compacted_until, False, estimated_tokens

        end_index = max(compacted_until, len(tool_events) - 4)
        if end_index <= compacted_until:
            return messages, compacted_until, False, estimated_tokens

        summary = self._build_live_compaction_summary(
            tool_events=tool_events,
            start_index=compacted_until,
            end_index=end_index,
            plan_state=plan_state,
        )
        if not summary:
            return messages, compacted_until, False, estimated_tokens

        base_messages = list(messages[:base_message_count])
        tail_messages = list(messages[-_DEFAULT_COMPACT_KEEP_LAST_MESSAGES:])
        compacted_messages = [
            *base_messages,
            self._backend._SystemMessage(content=summary),
            *tail_messages,
        ]
        if not self._messages_at_tool_boundary(compacted_messages):
            return messages, compacted_until, False, estimated_tokens
        return compacted_messages, end_index, True, estimated_tokens

    @staticmethod
    def _invoke_backend_method(
        method: Callable[..., Any],
        *,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        if event_cb is not None:
            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                signature = None
            if signature is not None and "event_cb" in signature.parameters:
                kwargs["event_cb"] = event_cb
        return method(**kwargs)

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

        context_payload = dict(context or {})
        phase_timer = PhaseTimer(
            offset_base_ms=max(0, int(context_payload.get("phase_timing_base_ms") or 0) or 0),
        )
        if self._require_runtime_auth:
            with phase_timer.measure("runtime_auth_summary_ms"):
                auth_summary = OpenAIAuthManager(self._config).auth_summary()
            if not bool(auth_summary.get("available")):
                raise RuntimeError(str(auth_summary.get("reason") or "LLM credentials are required"))

        locale = normalize_locale(getattr(settings, "locale", ""), self._config.default_locale)
        run_id = str(context_payload.get("run_id") or "")
        session_id = str(context_payload.get("session_id") or "")
        attachment_metas = [
            item for item in list(context_payload.get("attachments") or [])
            if isinstance(item, dict)
        ]
        attachment_guidance = self._build_attachment_tool_guidance(attachment_metas, locale=locale)
        has_image_attachments = has_image_attachments_helper(attachment_metas)
        with phase_timer.measure("agent_spec_load_ms"):
            spec = self._load_spec(locale=locale)
        with phase_timer.measure("skills_load_ms"):
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
        loop_safeguards = default_loop_safeguards() if selected_tools else {}
        runnable_tools = list(selected_tools if selected_tools else ())
        max_turn_seconds = int(loop_safeguards.get("max_turn_seconds") or 0)
        max_same_action_repeats = int(loop_safeguards.get("max_same_action_repeats") or 0)
        no_progress_threshold_before_replan = int(loop_safeguards.get("no_progress_threshold_before_replan") or 0)
        no_progress_threshold_after_replan = int(loop_safeguards.get("no_progress_threshold_after_replan") or 0)
        max_guard_rejections = int(loop_safeguards.get("max_guard_rejections") or 0)
        automatic_replan_enabled = bool(loop_safeguards.get("automatic_replan"))
        progress_signal_guard_enabled = bool(loop_safeguards.get("progress_signal_guard"))
        same_action_repeat_guard_enabled = bool(loop_safeguards.get("same_action_repeat_guard"))
        inline_document = _looks_like_inline_document_payload(prompt_message)
        attachment_evidence_pack = [
            item for item in list(context_payload.get("attachment_evidence_pack") or [])
            if isinstance(item, dict)
        ]
        runtime_contract = build_full_auto_runtime_contract(
            settings=settings,
            config=self._config,
            context=context_payload,
        )
        tools_available = bool(runnable_tools)
        tool_count = len(runnable_tools)
        project_context = dict(context_payload.get("project") or {})
        project_root = str(project_context.get("project_root") or "").strip()
        project_id = str(project_context.get("project_id") or "").strip()
        effective_cwd = str(project_context.get("cwd") or project_root or "").strip()
        compaction_status = dict(context_payload.get("compaction_status") or {})
        auto_compact_token_limit = max(0, int(compaction_status.get("auto_compact_token_limit") or 0))
        context_window_known = bool(compaction_status.get("context_window_known"))
        live_compaction_status = dict(compaction_status)
        route_state_input = dict(context_payload.get("route_state") or {})
        current_turn_context = dict(context_payload.get("current_turn") or {})
        revision_requested = self._looks_like_revision_request(prompt_message, route_state=route_state_input)
        japanese_review_requested = self._looks_like_japanese_review_request(prompt_message, route_state=route_state_input)
        active_task_focus = self._normalize_task_checkpoint(
            context_payload.get("active_task_focus")
            or context_payload.get("current_task_focus")
            or route_state_input.get("current_task_focus")
            or route_state_input.get("task_checkpoint")
        )
        current_task_focus = self._initial_task_checkpoint(
            route_state=route_state_input,
            project_root=project_root,
            cwd=effective_cwd,
            goal=str(current_turn_context.get("goal") or _truncate_goal(prompt_message)),
            attachments=attachment_metas,
            prefer_goal=bool(str(current_turn_context.get("goal") or "").strip()),
        )
        current_goal = str(current_task_focus.get("goal") or current_turn_context.get("goal") or _truncate_goal(prompt_message))
        current_task_focus["goal"] = current_goal
        if current_task_focus.get("cwd"):
            effective_cwd = str(current_task_focus.get("cwd") or effective_cwd)
        turn_runtime_boundary = build_turn_runtime_boundary(
            config=self._config,
            runtime_contract=runtime_contract,
            project_root=project_root or self._config.workspace_root,
            cwd=effective_cwd or project_root or self._config.workspace_root,
            attachments=attachment_metas,
        )
        write_authorization_state = self._write_authorization_state(
            prompt_message,
            collaboration_mode=collaboration_mode,
            project_root=project_root,
        )
        write_authorized = bool(write_authorization_state.get("authorized"))
        blocked_reason = ""
        project_contract_text = self._load_project_contract_text(project_root)

        messages: list[Any] = [
            self._backend._SystemMessage(
                content=self._render_system_prompt(
                    settings,
                    spec=spec,
                    loaded_skills=loaded_skills,
                    project_contract_text=project_contract_text,
                )
            ),
        ]
        if attachment_guidance:
            messages.append(self._backend._SystemMessage(content=attachment_guidance))
        messages.append(
            self._backend._HumanMessage(
                content=self._build_human_payload(
                    message=prompt_message,
                    context=context_payload,
                    runtime_boundary=turn_runtime_boundary,
                )
            )
        )

        usage_total = self._backend._empty_usage()
        notes: list[str] = [
            f"agent_id:{spec.agent_id}",
            f"tool_policy:{spec.tool_policy}",
            f"collaboration_mode:{collaboration_mode}",
        ]
        if inline_document:
            notes.append("inline_document_context")
        if attachment_evidence_pack:
            notes.append("attachment_evidence_pack_ready")
        if write_authorized:
            notes.append("write_authorized_workspace")
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
        model_action: dict[str, Any] = {}
        execution_trace: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = []
        run_started_at = time.monotonic()
        answer_stream_state = self._new_answer_stream_state(run_id=run_id, thread_id=session_id)
        turn_activity_context = {
            "task_type": "model_action",
            "primary_intent": "pending",
            "output_mode": "pending",
            "response_mode": "pending",
            "action_type": "pending",
            "source": "model_action",
        }
        activity_sequence = 0
        current_step_index = 0

        def emit_runtime_activity(
            activity_type: str,
            stage: str,
            detail: str,
            *,
            status: str = "running",
            payload: dict[str, Any] | None = None,
            visible: bool = True,
        ) -> str | None:
            nonlocal activity_sequence
            activity_sequence += 1
            return self._emit_activity_trace(
                progress_cb,
                run_id=run_id,
                locale=locale,
                type=activity_type,
                stage=stage,
                detail=detail,
                status=status,
                payload=payload,
                visible=visible,
                trace_events=trace_events,
                sequence=activity_sequence,
            )

        self._emit_trace(
            progress_cb,
            run_id=run_id,
            type="run.started",
            title=self._trace_label(locale, "run.started"),
            status="running",
            payload={"collaboration_mode": collaboration_mode},
            trace_events=trace_events,
        )
        emit_runtime_activity(
            "activity.started",
            "request_analysis",
            "Inspecting the request, restored task focus, attachment context, and runtime contract.",
            payload={
                "attachments": len(attachment_metas),
                "tools_available": tools_available,
                "tool_count": tool_count,
                "collaboration_mode": collaboration_mode,
                "context_pack": "current_turn/conversation_window/turn_memory/plan_state/compaction/runtime_boundary",
                "runtime_boundary": dump_model(turn_runtime_boundary),
            },
            visible=False,
        )
        self._emit_trace(
            progress_cb,
            run_id=run_id,
            type="runtime_contract.selected",
            title=self._trace_label(locale, "runtime_contract.selected"),
            detail=self._trace_label(locale, "runtime_contract.detail"),
            status="success",
            payload=runtime_contract.as_payload(),
            visible=False,
            trace_events=trace_events,
        )
        emit_runtime_activity(
            "activity.done",
            "request_analysis",
            self._activity_detail(
                task_type=turn_activity_context.get("task_type"),
                primary_intent=turn_activity_context.get("primary_intent"),
                execution_policy=turn_activity_context.get("execution_policy"),
                output_mode=turn_activity_context.get("output_mode"),
            ),
            status="success",
            payload={
                "attachments": len(attachment_metas),
                "tools_available": tools_available,
                "tool_count": tool_count,
                "collaboration_mode": collaboration_mode,
                "runtime_boundary": dump_model(turn_runtime_boundary),
            },
            visible=False,
        )
        emit_runtime_activity(
            "activity.started",
            "model_action",
            "Waiting for the model to choose the next action.",
            payload={
                "tools_available": tools_available,
                "tool_count": tool_count,
                "inline_document": inline_document,
                "runtime_boundary": dump_model(turn_runtime_boundary),
            },
        )

        def refresh_model_step(ai_msg: Any, *, event_type: str = "activity.done") -> None:
            nonlocal current_step_index
            nonlocal model_action
            nonlocal turn_activity_context
            nonlocal notes
            current_step_index += 1
            raw_ai_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
            current_tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
            step_state = self._resolve_model_step(
                ai_text=raw_ai_text,
                tool_calls=current_tool_calls,
                step_index=current_step_index,
            )
            cleaned_text = str(step_state.get("clean_text") or raw_ai_text).strip()
            model_action = dict(step_state.get("model_action") or {})
            turn_activity_context = dict(step_state.get("activity_context") or self._activity_context_from_action(model_action))
            try:
                ai_msg.content = cleaned_text
            except Exception:
                pass
            if model_action.get("normalization_notes"):
                notes.extend(f"model_action_normalized:{item}" for item in list(model_action.get("normalization_notes") or []))
            emit_runtime_activity(
                event_type,
                "model_action",
                str(model_action.get("reason") or "Model action resolved."),
                status="success" if bool(model_action.get("accepted")) else "blocked",
                payload={
                    "model_action": dict(model_action),
                    "revision_index": int(current_step_index),
                    "runtime_boundary": dump_model(turn_runtime_boundary),
                },
            )

        self._set_tools_runtime_context(
            execution_mode=settings.execution_mode,
            session_id=str(context_payload.get("session_id") or ""),
            project_id=project_id,
            project_root=project_root,
            cwd=effective_cwd,
            model=requested_model,
            locale=locale,
        )

        ai_msg: Any = None
        try:
            self._assert_tool_message_invariants(
                messages,
                phase="before_initial_llm",
                trace_events=trace_events,
                progress_cb=progress_cb,
                run_id=run_id,
                locale=locale,
            )
            self._emit_trace(
                progress_cb,
                run_id=run_id,
                type="llm.started",
                title=self._trace_label(locale, "llm.started"),
                status="running",
                payload={
                    "model": requested_model,
                    "tools_available": bool(runnable_tools),
                },
                trace_events=trace_events,
            )
            phase_timer.record_offset_ms("model_request_start_ms", if_missing=True)
            ai_msg, runner, effective_model, invoke_notes = self._invoke_backend_method(
                self._backend._invoke_chat_with_runner,
                messages=messages,
                model=requested_model,
                max_output_tokens=int(settings.max_output_tokens),
                enable_tools=bool(runnable_tools),
                tool_names=runnable_tools if runnable_tools else None,
                event_cb=self._make_model_stream_observer(
                    progress_cb=progress_cb,
                    run_id=run_id,
                    thread_id=session_id,
                    locale=locale,
                    trace_events=trace_events,
                    answer_stream_state=answer_stream_state,
                    stage="initial_model_response",
                    model=requested_model,
                    tool_round=0,
                    answer_context=turn_activity_context,
                    phase_timer=phase_timer,
                ),
            )
            self._emit_trace(
                progress_cb,
                run_id=run_id,
                type="llm.finished",
                title=self._trace_label(locale, "llm.finished"),
                status="success",
                payload={"model": effective_model or requested_model},
                trace_events=trace_events,
            )
            self._set_tools_runtime_context(
                execution_mode=settings.execution_mode,
                session_id=str(context_payload.get("session_id") or ""),
                project_id=project_id,
                project_root=project_root,
                cwd=effective_cwd,
                model=effective_model,
                locale=locale,
            )
            notes.extend(invoke_notes)
            usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
            refresh_model_step(ai_msg, event_type="activity.done")

            halt_for_user_input = False
            turn_started_at = time.monotonic()
            round_idx = 0
            tool_call_count = 0
            same_action_repeat_count = 0
            last_action_fingerprint = ""
            no_progress_cycles = 0
            post_replan_no_progress_cycles = 0
            guard_rejection_count = 0
            progress_tracker = self._new_progress_tracker()
            progress_signals: list[dict[str, Any]] = []
            replan_history: list[dict[str, Any]] = []
            replan_attempt_count = 0
            compacted_tool_events = 0
            base_message_count = len(messages)

            while True:
                if self._cancel_requested(context_payload):
                    turn_status = "cancelled"
                    forced_text = translate(locale, "runtime.cancelled.text")
                    notes.append("run_cancelled_by_user")
                    self._emit_stage(
                        progress_cb,
                        phase="report",
                        label=translate(locale, "runtime.cancelled.label"),
                        detail=translate(locale, "runtime.cancelled.detail"),
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
                    blocked_reason = blocked_reason or "turn_budget_wall_clock_exceeded"
                    forced_text = translate(locale, "runtime.budget.wall_clock")
                    notes.append("turn_budget_wall_clock_exceeded")
                    break

                ai_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
                tool_calls = list(model_action.get("tool_calls") or [])
                step_action_type = str(model_action.get("action_type") or "").strip() or "empty"
                step_accepted = bool(model_action.get("accepted"))
                if not tool_calls:
                    no_tool_response_kind = "final_answer" if step_accepted and ai_text else "empty_response"
                    if not step_accepted:
                        blocked_reason = blocked_reason or "model_action_empty"
                    execution_entry = ExecutionTraceEntry(
                        step_index=int(model_action.get("step_index") or current_step_index),
                        action_type=step_action_type,
                        status="completed" if step_accepted else "blocked",
                        title=translate(locale, "runtime.activity.execution_title.direct_answer"),
                        result_summary=safe_preview(ai_text, limit=240),
                        observation_summary=(
                            translate(locale, "runtime.activity.execution.direct_answer_prepared")
                            if step_accepted
                            else str(model_action.get("reason") or "Model produced no executable action.")
                        ),
                        detail=str(model_action.get("reason") or ""),
                        payload={
                            "model_action": dict(model_action),
                            "response_kind": no_tool_response_kind,
                        },
                    )
                    execution_trace = self._append_execution_trace(execution_trace, execution_entry)
                    emit_runtime_activity(
                        "activity.done" if round_idx == 0 else "activity.delta",
                        "execution",
                        self._execution_activity_detail(locale, dump_model(execution_entry)),
                        status="success" if step_accepted else "blocked",
                        payload={
                            "execution_trace": list(execution_trace),
                            "execution_trace_entry": dump_model(execution_entry),
                            "model_action": dict(model_action),
                            **turn_activity_context,
                        },
                    )
                    break

                round_idx += 1
                tool_calls = self._ensure_model_tool_call_ids(
                    ai_msg,
                    tool_calls,
                    agent_id=spec.agent_id,
                    round_idx=round_idx,
                )
                messages.append(ai_msg)
                round_success = False
                round_signature_parts: list[dict[str, Any]] = []
                round_progress_signals: list[dict[str, Any]] = []
                round_has_progress = False
                stop_after_tools = False
                needs_replan = False
                replan_trigger = ""
                replan_detail = ""
                emit_runtime_activity(
                    "activity.delta",
                    "execution",
                    translate(locale, "runtime.activity.execution.processing_tool_calls", count=len(tool_calls)),
                    payload={
                        "tool_names": [str(call.get("name") or "") for call in tool_calls[:8]],
                        "tool_count": len(tool_calls),
                        "tool_count_total": len(tool_calls),
                        "tool_drain_mode": "codex_style_all_calls",
                        "model_action": dict(model_action),
                        **turn_activity_context,
                    },
                )
                self._emit_trace(
                    progress_cb,
                    run_id=run_id,
                    type="tool_drain.started",
                    title="Tool drain started",
                    detail=f"Draining {len(tool_calls)} model tool call(s).",
                    status="running",
                    payload={
                        "tool_count_total": len(tool_calls),
                        "tool_drain_mode": "codex_style_all_calls",
                        "tool_boundary_clean": self._messages_at_tool_boundary(messages),
                    },
                    trace_events=trace_events,
                )
                for call_idx, call in enumerate(tool_calls, start=1):
                    raw_name = str(call.get("raw_name") or call.get("name") or "").strip()
                    raw_arguments = call.get("raw_args")
                    if raw_arguments is None:
                        raw_arguments = call.get("args")
                    call_id = str(call.get("id") or f"{spec.agent_id}_{round_idx}_{call_idx}")
                    preview_name = self._normalize_tool_name(str(call.get("name") or raw_name).strip())
                    preview_args = dict(raw_arguments) if isinstance(raw_arguments, dict) else {}
                    preview_schema = dict((self._tool_specs_by_name.get(preview_name) or {}).get("parameters") or {})
                    tool_audit = build_tool_argument_audit(preview_name or raw_name, preview_args, preview_schema, locale=locale)
                    raw_tool_call_payload = {
                        "id": call_id,
                        "name": raw_name or str(call.get("name") or ""),
                        "arguments": safe_preview(raw_arguments, limit=4000),
                    }
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="action.detected",
                        title=self._trace_label(locale, "action.detected", tool=preview_name or raw_name or "tool"),
                        detail=str(tool_audit.get("arguments_preview") or summarize_tool_args(preview_name or raw_name, preview_args)),
                        status="running",
                        payload={
                            "model_action": "tool_call",
                            "tool_name": preview_name or raw_name,
                            "raw_tool_call": raw_tool_call_payload,
                            **tool_audit,
                        },
                        trace_events=trace_events,
                    )
                    skip_reason = ""
                    skip_kind = ""
                    if self._cancel_requested(context_payload):
                        turn_status = "cancelled"
                        forced_text = translate(locale, "runtime.cancelled.text")
                        if "run_cancelled_by_user" not in notes:
                            notes.append("run_cancelled_by_user")
                        stop_after_tools = True
                        skip_kind = "cancelled"
                        skip_reason = "Tool execution was cancelled before this call was run."
                    elif halt_for_user_input:
                        skip_kind = "skipped"
                        skip_reason = "Tool execution skipped because structured user input is required."
                    elif stop_after_tools:
                        skip_kind = "skipped"
                        skip_reason = str(blocked_reason or "Tool execution skipped after the turn reached a stop condition.")
                    if skip_kind:
                        name = preview_name or raw_name or "unknown_tool"
                        arguments = preview_args
                        validation_payload = {
                            "allowed": False,
                            "code": "tool_cancelled" if skip_kind == "cancelled" else "tool_skipped",
                            "message": skip_reason,
                            "normalized_arguments": arguments,
                            "severity": "blocked",
                        }
                        result = (
                            self._tool_cancelled_result(name, call_id)
                            if skip_kind == "cancelled"
                            else self._tool_skipped_result(name, call_id, reason=skip_reason)
                        )
                        event = self._build_tool_event(
                            name=name,
                            arguments=arguments,
                            result=result,
                            locale=locale,
                            raw_tool_call=raw_tool_call_payload,
                            validation_result=validation_payload,
                            raw_arguments=raw_arguments,
                        )
                        tool_events.append(event)
                        self._emit_trace(
                            progress_cb,
                            run_id=run_id,
                            type="tool.failed",
                            title=self._trace_label(locale, "tool.failed", tool=name),
                            detail=summarize_tool_result(name, result, locale=locale),
                            status="cancelled" if skip_kind == "cancelled" else "blocked",
                            payload={
                                "tool_name": name,
                                "raw_tool_call": raw_tool_call_payload,
                                "validation_result": validation_payload,
                                "result_preview": safe_preview(result),
                            },
                            trace_events=trace_events,
                        )
                        self._emit_trace(
                            progress_cb,
                            run_id=run_id,
                            type="observation.returned",
                            title=self._trace_label(locale, "observation.returned", tool=name),
                            detail=str(result.get("summary") or skip_reason)[:280],
                            status="success",
                            payload={
                                "model_action": "tool_call",
                                "tool_name": name,
                                "observation": safe_preview(result, limit=4000),
                                "validation_result": validation_payload,
                            },
                            trace_events=trace_events,
                        )
                        if progress_cb is not None:
                            progress_cb(
                                {
                                    "event": "tool",
                                    "item": dump_model(event),
                                    "status": event.status,
                                    "summary": event.summary,
                                    "source_refs": list(event.source_refs),
                                    "tool_round": round_idx,
                                    "tool_index": call_idx,
                                    "group": event.group,
                                    "agent_id": spec.agent_id,
                                }
                            )
                        messages.append(self._tool_message_for_result(result=result, call_id=call_id, name=name))
                        tool_call_count += 1
                        action_fingerprint = self._action_fingerprint(name, arguments)
                        round_signature_parts.append(
                            {
                                "name": name,
                                "input": arguments,
                                "status": event.status,
                                "action_fingerprint": action_fingerprint,
                            }
                        )
                        continue
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="tool.call_detected",
                        title=self._trace_label(locale, "tool.call_detected", tool=preview_name or raw_name or "tool"),
                        detail=str(
                            tool_audit.get("arguments_preview")
                            or summarize_tool_args(preview_name or raw_name, preview_args)
                        ),
                        status="running",
                        payload={
                            "tool_name": preview_name or raw_name,
                            "raw_tool_call": raw_tool_call_payload,
                            **tool_audit,
                        },
                        trace_events=trace_events,
                    )
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="action.validating",
                        title=self._trace_label(locale, "action.validating", tool=preview_name or raw_name or "tool"),
                        detail="RuntimeBoundary",
                        status="running",
                        payload={
                            "model_action": "tool_call",
                            "tool_name": preview_name or raw_name,
                            "raw_tool_call": raw_tool_call_payload,
                        },
                        trace_events=trace_events,
                    )
                    validation = self._validate_model_tool_call(
                        call=call,
                        runnable_tools=runnable_tools,
                        locale=locale,
                        runtime_boundary=turn_runtime_boundary,
                        attachments=attachment_metas,
                    )
                    validation_payload = dump_model(validation)
                    name = str(validation.tool_name or preview_name or raw_name).strip()
                    arguments = dict(validation.normalized_arguments or {})
                    if raw_name and raw_name != name:
                        notes.append(f"tool_alias:{raw_name}->{name}")
                    if validation.normalization_notes:
                        notes.extend(f"tool_validation_normalized:{item}" for item in validation.normalization_notes)
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="action.allowed" if validation.allowed else "action.blocked",
                        title=self._trace_label(
                            locale,
                            "action.allowed" if validation.allowed else "action.blocked",
                            tool=name or raw_name or "tool",
                        ),
                        detail=self._validation_activity_detail(locale, validation_payload),
                        status="success" if validation.allowed else "blocked",
                        payload={
                            "model_action": "tool_call",
                            "tool_name": name or raw_name,
                            "raw_tool_call": raw_tool_call_payload,
                            "validation_result": validation_payload,
                            "normalized_arguments": safe_preview(arguments, limit=4000),
                            "runtime_boundary": dump_model(turn_runtime_boundary),
                        },
                        trace_events=trace_events,
                    )
                    emit_runtime_activity(
                        "activity.delta",
                        "action_validation",
                        self._validation_activity_detail(locale, validation_payload),
                        status="success" if validation.allowed else "blocked",
                        payload={
                            "model_action": dict(model_action),
                            "validation_result": validation_payload,
                            "raw_tool_call": raw_tool_call_payload,
                            "normalized_arguments": safe_preview(arguments, limit=4000),
                            "runtime_boundary": dump_model(turn_runtime_boundary),
                            **turn_activity_context,
                        },
                    )
                    plan_state_before = [dict(item) for item in list(plan_state or []) if isinstance(item, dict)]
                    if validation.allowed:
                        result, event = self._execute_tool_with_trace(
                            name=name,
                            arguments=arguments,
                            raw_tool_call=raw_tool_call_payload,
                            validation_result=validation_payload,
                            raw_arguments=raw_arguments,
                            run_id=run_id,
                            locale=locale,
                            progress_cb=progress_cb,
                            trace_events=trace_events,
                            tool_events=tool_events,
                            current_goal=current_goal,
                            current_task_focus=current_task_focus,
                            collaboration_mode=collaboration_mode,
                            turn_status=turn_status,
                            plan_state=plan_state,
                            pending_user_input=pending_user_input,
                            effective_cwd=effective_cwd,
                            spec=spec,
                            round_idx=round_idx,
                            call_idx=call_idx,
                        )
                    else:
                        guard_rejection_count += 1
                        result = validation_observation(validation, tool=name or raw_name)
                        event = self._build_tool_event(
                            name=name or raw_name,
                            arguments=arguments,
                            result=result,
                            locale=locale,
                            raw_tool_call=raw_tool_call_payload,
                            validation_result=validation_payload,
                            raw_arguments=raw_arguments,
                        )
                        tool_events.append(event)
                        self._emit_trace(
                            progress_cb,
                            run_id=run_id,
                            type="tool.failed",
                            title=self._trace_label(locale, "tool.failed", tool=name or raw_name or "tool"),
                            detail=summarize_tool_result(name or raw_name, result, locale=locale),
                            status="blocked",
                            payload={
                                "tool_name": name or raw_name,
                                "raw_tool_call": raw_tool_call_payload,
                                "validation_result": validation_payload,
                                "normalized_arguments": safe_preview(arguments, limit=4000),
                                **tool_audit,
                                "result_preview": safe_preview(result),
                            },
                            trace_events=trace_events,
                        )
                        self._emit_trace(
                            progress_cb,
                            run_id=run_id,
                            type="observation.returned",
                            title=self._trace_label(locale, "observation.returned", tool=name or raw_name or "tool"),
                            detail=str(result.get("summary") or result.get("message") or validation.message or "")[:280],
                            status="success",
                            payload={
                                "model_action": "tool_call",
                                "tool_name": name or raw_name,
                                "observation": safe_preview(result, limit=4000),
                                "validation_result": validation_payload,
                            },
                            trace_events=trace_events,
                        )
                        if progress_cb is not None:
                            progress_cb(
                                {
                                    "event": "tool",
                                    "item": dump_model(event),
                                    "status": event.status,
                                    "summary": event.summary,
                                    "source_refs": list(event.source_refs),
                                    "tool_round": round_idx,
                                    "tool_index": call_idx,
                                    "group": event.group,
                                    "agent_id": spec.agent_id,
                                }
                            )
                        notes.append("tool_validation_rejected")
                        if max_guard_rejections and guard_rejection_count > max_guard_rejections:
                            if automatic_replan_enabled and replan_attempt_count == 0:
                                needs_replan = True
                                replan_trigger = "validation_rejection_limit"
                                replan_detail = str(result.get("summary") or "")
                                notes.append("tool_validation_rejection_replan_requested")
                            else:
                                turn_status = "blocked"
                                blocked_reason = blocked_reason or "tool_validation_rejections_exceeded"
                                forced_text = str(result.get("summary") or translate(locale, "runtime.budget.guard_rejections"))
                                notes.append("tool_validation_rejections_exceeded")
                            stop_after_tools = True
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
                        locale=locale,
                    )
                    tool_call_count += 1
                    action_fingerprint = self._action_fingerprint(name, arguments)
                    round_signature_parts.append(
                        {
                            "name": name,
                            "input": arguments,
                            "status": event.status,
                            "action_fingerprint": action_fingerprint,
                        }
                    )
                    if event.status == "ok":
                        round_success = True
                    progress_signal = self._progress_signal_from_tool_result(
                        locale=locale,
                        tool_name=name,
                        arguments=arguments,
                        result=result,
                        event_status=event.status,
                        plan_state_before=plan_state_before,
                        tracker=progress_tracker,
                        action_fingerprint=action_fingerprint,
                    )
                    progress_signal_payload = dump_model(progress_signal)
                    round_progress_signals.append(progress_signal_payload)
                    progress_signals = [*progress_signals, progress_signal_payload][-48:]
                    round_has_progress = round_has_progress or bool(progress_signal.has_progress)
                    if progress_signal.has_progress or last_action_fingerprint != action_fingerprint:
                        same_action_repeat_count = 1
                    else:
                        same_action_repeat_count += 1
                    last_action_fingerprint = action_fingerprint
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
                            "summary": str(result.get("summary") or translate(locale, "runtime.pending_user_input.summary")),
                        }
                        turn_status = "needs_user_input"
                        halt_for_user_input = True
                        self._emit_trace(
                            progress_cb,
                            run_id=run_id,
                            type="approval.required",
                            title=self._trace_label(locale, "approval.required"),
                            detail=str(pending_user_input.get("summary") or ""),
                            status="blocked",
                            payload={"questions": safe_preview(pending_user_input.get("questions") or [])},
                            trace_events=trace_events,
                        )
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
                    messages.append(self._tool_message_for_result(result=result, call_id=call_id, name=name or "unknown_tool"))
                    if (
                        same_action_repeat_guard_enabled
                        and max_same_action_repeats
                        and same_action_repeat_count > max_same_action_repeats
                    ):
                        if automatic_replan_enabled and replan_attempt_count == 0:
                            needs_replan = True
                            replan_trigger = "same_action_repeat"
                            replan_detail = action_fingerprint
                            notes.append("turn_budget_same_action_repeat_replan_requested")
                        else:
                            turn_status = "blocked"
                            blocked_reason = blocked_reason or "turn_budget_same_action_repeats_exceeded"
                            forced_text = translate(locale, "runtime.budget.same_action_repeat")
                            notes.append("turn_budget_same_action_repeats_exceeded")
                        stop_after_tools = True

                tool_boundary_clean = self._messages_at_tool_boundary(messages)
                self._emit_trace(
                    progress_cb,
                    run_id=run_id,
                    type="tool_drain.finished" if tool_boundary_clean else "tool_invariant.failed",
                    title="Tool drain finished" if tool_boundary_clean else "Tool drain invariant failed",
                    detail=f"Drained {len(round_signature_parts)} of {len(tool_calls)} model tool call(s).",
                    status="success" if tool_boundary_clean else "failed",
                    payload={
                        "tool_count_total": len(tool_calls),
                        "tool_count_drained": len(round_signature_parts),
                        "tool_drain_mode": "codex_style_all_calls",
                        "tool_boundary_clean": tool_boundary_clean,
                    },
                    trace_events=trace_events,
                )
                self._assert_tool_message_invariants(
                    messages,
                    phase="after_tool_drain",
                    trace_events=trace_events,
                    progress_cb=progress_cb,
                    run_id=run_id,
                    locale=locale,
                )

                if round_signature_parts:
                    execution_entry = ExecutionTraceEntry(
                        step_index=int(model_action.get("step_index") or current_step_index),
                        action_type="tool_call",
                        status=(
                            "blocked"
                            if turn_status in {"blocked", "needs_user_input"}
                            else ("completed" if round_success else "failed")
                        ),
                        title=translate(locale, "runtime.activity.execution_title.tool_execution"),
                        tool_name=str((model_action.get("tool_name") or "")),
                        tool_names=[str(item.get("name") or "") for item in round_signature_parts if str(item.get("name") or "")],
                        result_summary="; ".join(
                            f"{str(item.get('name') or '')}:{str(item.get('status') or '')}"
                            for item in round_signature_parts[:8]
                        )[:280],
                        observation_summary=(
                            str(pending_user_input.get("summary") or "")
                            if halt_for_user_input
                            else (
                                translate(locale, "runtime.activity.execution.tool_output_collected")
                                if round_success
                                else translate(locale, "runtime.activity.execution.tool_result_returned")
                            )
                        ),
                        detail=str(model_action.get("reason") or ""),
                        payload={
                            "model_action": dict(model_action),
                            "completed_tool_calls": len(round_signature_parts),
                            "successful_tool_calls": sum(1 for item in round_signature_parts if str(item.get("status") or "") == "ok"),
                            "progress_signals": list(round_progress_signals),
                        },
                    )
                    execution_trace = self._append_execution_trace(execution_trace, execution_entry)
                    emit_runtime_activity(
                        "activity.delta",
                        "execution",
                        self._execution_activity_detail(locale, dump_model(execution_entry)),
                        status="blocked" if turn_status in {"blocked", "needs_user_input"} else ("success" if round_success else "failed"),
                        payload={
                            "execution_trace": list(execution_trace),
                            "execution_trace_entry": dump_model(execution_entry),
                            "model_action": dict(model_action),
                            "progress_signals": list(round_progress_signals),
                            **turn_activity_context,
                        },
                    )

                if progress_signal_guard_enabled and round_signature_parts:
                    if round_has_progress:
                        no_progress_cycles = 0
                        post_replan_no_progress_cycles = 0
                    else:
                        no_progress_cycles += 1
                        if replan_attempt_count > 0:
                            post_replan_no_progress_cycles += 1
                    if (
                        not needs_replan
                        and not halt_for_user_input
                        and automatic_replan_enabled
                        and replan_attempt_count == 0
                        and no_progress_threshold_before_replan > 0
                        and no_progress_cycles >= no_progress_threshold_before_replan
                    ):
                        needs_replan = True
                        replan_trigger = "no_progress"
                        replan_detail = ", ".join(self._recent_action_summaries(progress_signals, limit=3))
                    elif (
                        not needs_replan
                        and replan_attempt_count > 0
                        and no_progress_threshold_after_replan > 0
                        and post_replan_no_progress_cycles >= no_progress_threshold_after_replan
                    ):
                        turn_status = "blocked"
                        blocked_reason = blocked_reason or "turn_budget_no_progress_after_replan_exceeded"
                        forced_text = translate(locale, "runtime.budget.no_progress_after_replan")
                        notes.append("turn_budget_no_progress_after_replan_exceeded")
                        stop_after_tools = True

                if needs_replan and not halt_for_user_input and turn_status not in {"blocked", "cancelled"}:
                    replan_prompt = self._build_replan_checkpoint_prompt(
                        locale=locale,
                        current_goal=current_goal,
                        current_task_focus=current_task_focus,
                        progress_signals=progress_signals,
                        tool_events=tool_events,
                        trigger=replan_trigger or "no_progress",
                    )
                    replan_attempt_count += 1
                    post_replan_no_progress_cycles = 0
                    replan_payload = {
                        "trigger": replan_trigger or "no_progress",
                        "detail": replan_detail,
                        "known_facts": self._recent_action_summaries(progress_signals),
                        "failed_actions": self._recent_failed_action_summaries(tool_events),
                        "prompt": replan_prompt,
                        "round_index": round_idx,
                    }
                    replan_history = [*replan_history, replan_payload][-8:]
                    notes.append(f"replan_requested:{replan_trigger or 'no_progress'}")
                    messages.append(self._backend._SystemMessage(content=replan_prompt))
                    emit_runtime_activity(
                        "activity.delta",
                        "loop.safeguard",
                        translate(locale, "runtime.replan.requested", trigger=replan_trigger or "no_progress"),
                        payload={
                            "model_action": dict(model_action),
                            "progress_signals": list(progress_signals),
                            "replan_history": list(replan_history),
                            **turn_activity_context,
                        },
                    )
                    stop_after_tools = False
                    turn_status = "running"
                    blocked_reason = ""
                    forced_text = ""

                if halt_for_user_input or stop_after_tools:
                    break
                if self._cancel_requested(context_payload):
                    turn_status = "cancelled"
                    forced_text = translate(locale, "runtime.cancelled.text")
                    notes.append("run_cancelled_by_user")
                    break

                emit_runtime_activity(
                    "activity.delta",
                    "execution",
                    translate(locale, "runtime.activity.execution.requesting_next_model_turn"),
                    payload={
                        "execution_trace": list(execution_trace),
                        "completed_tool_calls": len(round_signature_parts),
                        "successful_tool_calls": sum(1 for item in round_signature_parts if str(item.get("status") or "") == "ok"),
                        "model_action": dict(model_action),
                        "progress_signals": list(progress_signals),
                        "replan_history": list(replan_history),
                        **turn_activity_context,
                    },
                )

                if not self._messages_at_tool_boundary(messages):
                    notes.append("compaction_skipped_not_at_tool_boundary")
                    compacted = False
                    live_estimated_tokens = 0
                else:
                    messages, compacted_tool_events, compacted, live_estimated_tokens = self._maybe_compact_live_messages(
                        messages=messages,
                        base_message_count=base_message_count,
                        tool_events=tool_events,
                        compacted_until=compacted_tool_events,
                        plan_state=plan_state,
                        model=effective_model,
                        auto_compact_token_limit=auto_compact_token_limit,
                        context_window_known=context_window_known,
                    )
                if live_estimated_tokens and auto_compact_token_limit > 0:
                    live_compaction_status["estimated_context_tokens"] = int(live_estimated_tokens)
                if compacted:
                    notes.append("turn_context_compacted")
                    before_tokens = int(live_estimated_tokens or 0)
                    after_tokens = 0
                    try:
                        after_tokens = count_tokens(
                            "\n".join(
                                self._backend._shorten(str(getattr(item, "content", getattr(item, "text", item))), 3000)
                                for item in list(messages)
                            ),
                            effective_model,
                        )
                    except Exception:
                        after_tokens = 0
                    live_compaction_status["last_compaction_phase"] = "mid_turn"
                    live_compaction_status["phase"] = "mid_turn"
                    live_compaction_status["last_compacted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    live_compaction_status["last_compaction_reason"] = (
                        f"context_limit:{before_tokens}/{int(auto_compact_token_limit or 0)}"
                    )
                    live_compaction_status["reason"] = "context_limit"
                    live_compaction_status["before_tokens"] = before_tokens
                    live_compaction_status["after_tokens"] = after_tokens
                    live_compaction_status["retained_turn_count"] = len(messages)
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="context.compacted",
                        title="Context compacted",
                        detail=translate(locale, "runtime.compaction.mid_turn"),
                        status="success",
                        payload={
                            "phase": "mid_turn",
                            "reason": "context_limit",
                            "before_tokens": before_tokens,
                            "after_tokens": after_tokens,
                            "retained_turn_count": len(messages),
                            "summary_tokens": 0,
                        },
                        trace_events=trace_events,
                    )
                    if progress_cb is not None:
                        progress_cb(
                            {
                                "event": "trace",
                                "message": translate(locale, "runtime.compaction.mid_turn"),
                                "run_snapshot": {
                                    "compaction_status": dict(live_compaction_status),
                                },
                            }
                        )

                self._emit_trace(
                    progress_cb,
                    run_id=run_id,
                    type="llm.started",
                    title=self._trace_label(locale, "llm.started"),
                    status="running",
                    payload={"model": effective_model or requested_model},
                    trace_events=trace_events,
                )
                phase_timer.record_offset_ms("model_request_start_ms", if_missing=True)
                self._assert_tool_message_invariants(
                    messages,
                    phase="before_followup_llm",
                    trace_events=trace_events,
                    progress_cb=progress_cb,
                    run_id=run_id,
                    locale=locale,
                )
                try:
                    ai_msg, runner, effective_model, invoke_notes = self._invoke_backend_method(
                        self._backend._invoke_with_runner_recovery,
                        runner=runner,
                        messages=messages,
                        model=effective_model,
                        max_output_tokens=int(settings.max_output_tokens),
                        enable_tools=True,
                        tool_names=runnable_tools,
                        event_cb=self._make_model_stream_observer(
                            progress_cb=progress_cb,
                            run_id=run_id,
                            thread_id=session_id,
                            locale=locale,
                            trace_events=trace_events,
                            answer_stream_state=answer_stream_state,
                            stage="post_tool_response",
                            model=effective_model,
                            tool_round=round_idx,
                            answer_context=turn_activity_context,
                            phase_timer=phase_timer,
                        ),
                    )
                except Exception as exc:
                    error_message = safe_error_message(exc)
                    turn_status = "blocked"
                    blocked_reason = blocked_reason or "llm_request_error"
                    forced_text = error_message
                    notes.append("llm_request_error")
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="llm.failed",
                        title="LLM request failed",
                        detail=error_message,
                        status="failed",
                        payload={
                            "kind": "llm_request_error",
                            "message": error_message,
                            "tool_boundary_clean": self._messages_at_tool_boundary(messages),
                        },
                        trace_events=trace_events,
                    )
                    break
                self._emit_trace(
                    progress_cb,
                    run_id=run_id,
                    type="llm.finished",
                    title=self._trace_label(locale, "llm.finished"),
                    status="success",
                    payload={"model": effective_model or requested_model},
                    trace_events=trace_events,
                )
                self._set_tools_runtime_context(
                    execution_mode=settings.execution_mode,
                    session_id=str(context_payload.get("session_id") or ""),
                    project_id=project_id,
                    project_root=project_root,
                    cwd=effective_cwd,
                    model=effective_model,
                    locale=locale,
                )
                notes.extend(invoke_notes)
                usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
                refresh_model_step(ai_msg, event_type="activity.delta")
        finally:
            if hasattr(self._backend.tools, "clear_runtime_context"):
                self._backend.tools.clear_runtime_context()

        raw_text = forced_text or (self._backend._content_to_text(getattr(ai_msg, "content", "")).strip() if ai_msg is not None else "")
        if not raw_text:
            raw_text = (
                translate(locale, "runtime.empty_response.pending_user_input")
                if pending_user_input
                else translate(locale, "runtime.empty_response.default")
            )
        has_successful_tool = any(item.status == "ok" for item in tool_events)
        evidence_status = "collected" if has_successful_tool else ("needs_evidence_review" if tool_events else "not_needed")
        if turn_status in {"cancelled", "blocked"}:
            pass
        elif pending_user_input:
            turn_status = "needs_user_input"
        else:
            turn_status = "completed"
        revision_summary = self._build_revision_summary(
            prompt_message=prompt_message,
            raw_text=raw_text,
            activity_context={
                **turn_activity_context,
                "prefer_change_summary": bool(revision_requested or japanese_review_requested),
                "task_type": (
                    "japanese_grammar_review"
                    if japanese_review_requested
                    else ("rewrite_review" if revision_requested else str(turn_activity_context.get("task_type") or ""))
                ),
            },
        )
        answer_stream = self._answer_stream_diagnostics(answer_stream_state)
        if raw_text and (turn_status not in {"blocked", "cancelled"} or answer_stream_state.get("item_started")):
            answer_stream = self._finalize_answer_stream(
                progress_cb,
                run_id=run_id,
                thread_id=session_id,
                locale=locale,
                trace_events=trace_events,
                answer_stream_state=answer_stream_state,
                final_text=raw_text,
                answer_context=turn_activity_context,
                revision_summary=revision_summary,
                phase_timer=phase_timer,
            )
        if answer_stream.get("streamed"):
            notes.append(f"answer_stream_deltas:{int(answer_stream.get('delta_count') or 0)}")
        elif raw_text and turn_status not in {"blocked", "cancelled"}:
            notes.append("answer_stream_not_observed")
        if turn_status == "blocked":
            self._emit_trace(
                progress_cb,
                run_id=run_id,
                type="blocked",
                title=self._trace_label(locale, "blocked"),
                detail=str(blocked_reason or raw_text or ""),
                status="blocked",
                trace_events=trace_events,
            )
        elif turn_status == "cancelled":
            self._emit_trace(
                progress_cb,
                run_id=run_id,
                type="cancelled",
                title=self._trace_label(locale, "cancelled"),
                detail=str(raw_text or ""),
                status="cancelled",
                trace_events=trace_events,
            )
        run_duration_ms = max(0, int((time.monotonic() - run_started_at) * 1000))
        phase_timings = phase_timer.snapshot(total_key="runtime_total_ms")
        run_trace_status = "success"
        if turn_status == "blocked":
            run_trace_status = "blocked"
        elif turn_status == "cancelled":
            run_trace_status = "cancelled"
        self._emit_trace(
            progress_cb,
            run_id=run_id,
            type="run.finished",
            title=self._trace_label(locale, "run.finished"),
            detail=str(turn_status or "completed"),
            status=run_trace_status,
            duration_ms=run_duration_ms,
            payload={"turn_status": turn_status},
            trace_events=trace_events,
        )
        current_task_focus["project_root"] = project_root
        current_task_focus["cwd"] = effective_cwd or project_root
        current_task_focus["active_attachments"] = self._attachment_refs(attachment_metas)
        if pending_user_input:
            current_task_focus["next_action"] = str(pending_user_input.get("summary") or translate(locale, "runtime.pending_user_input.summary"))
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
        if (
            model_action
            and turn_status in {"blocked", "cancelled"}
            and (
                not execution_trace
                or int((execution_trace[-1] or {}).get("step_index") or 0) != int(model_action.get("step_index") or 0)
            )
        ):
            final_execution_entry = ExecutionTraceEntry(
                step_index=int(model_action.get("step_index") or current_step_index),
                action_type=str(model_action.get("action_type") or "empty"),
                status=turn_status,
                title="Final execution state",
                tool_name=str(model_action.get("tool_name") or ""),
                tool_names=[str(item) for item in list(model_action.get("tool_names") or []) if str(item or "")],
                result_summary=safe_preview(raw_text, limit=240),
                observation_summary=str(blocked_reason or raw_text or ""),
                detail=str(model_action.get("reason") or ""),
                payload={"model_action": dict(model_action)},
            )
            execution_trace = self._append_execution_trace(execution_trace, final_execution_entry)

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
                "pending_approval": {},
                "write_authorization_state": dict(write_authorization_state),
                "blocked_reason": blocked_reason,
                "loop_safeguards": dict(loop_safeguards),
                "attachment_evidence_pack_preview": [
                    {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "kind": str(item.get("kind") or ""),
                        "summary": str(item.get("summary") or "")[:240],
                    }
                    for item in attachment_evidence_pack[:6]
                    if isinstance(item, dict)
                ],
                "tools_available": tools_available,
                "tool_count": tool_count,
                "runtime_contract": runtime_contract.as_payload(),
                "network_mode": spec.network_mode,
                "inline_document": inline_document,
                "thread_memory": dict(context_payload.get("thread_memory") or {}),
                "recent_tasks": list(context_payload.get("recent_tasks") or []),
                "artifact_memory_preview": list(context_payload.get("artifact_memory_preview") or []),
                "compaction_status": dict(live_compaction_status),
                "answer_stream": dict(answer_stream),
                "runtime_boundary": dump_model(turn_runtime_boundary),
                "current_turn": dict(current_turn_context),
                "active_task_focus": compat_task_checkpoint_from_focus(active_task_focus),
                "recent_user_messages": list(context_payload.get("recent_user_messages") or []),
                "model_action": dict(model_action),
                "execution_trace": list(execution_trace),
                "progress_signals": list(progress_signals),
                "replan_history": list(replan_history),
                "project_contract_loaded": bool(project_contract_text),
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
                "project_root": project_root,
                "cwd": effective_cwd,
                "phase_timings": dict(phase_timings),
            },
            "tool_timeline": [dump_model(item) for item in tool_events],
            "trace_events": [dict(item) for item in trace_events],
            "evidence": {
                "status": evidence_status,
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
                "current_turn": dict(current_turn_context),
                "active_task_focus": compat_task_checkpoint_from_focus(active_task_focus),
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
                "recent_user_messages": list(context_payload.get("recent_user_messages") or []),
                "thread_memory": dict(context_payload.get("thread_memory") or {}),
                "recent_tasks": list(context_payload.get("recent_tasks") or []),
                "artifact_memory_preview": list(context_payload.get("artifact_memory_preview") or []),
                "compaction_status": dict(live_compaction_status),
                "history_turn_count": len(list(context_payload.get("history_turns") or [])),
                "attachment_count": len(list(context_payload.get("attachments") or [])),
                "phase_timings": dict(phase_timings),
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
        activity_summary = " · ".join(
            [str(item.get("title") or "") for item in trace_events if str(item.get("title") or "").strip()][-5:]
        )[:400]

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
            "pending_approval": {},
            "write_authorization_state": dict(write_authorization_state),
            "blocked_reason": blocked_reason,
            "attachment_evidence_pack_preview": [
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or ""),
                    "summary": str(item.get("summary") or "")[:240],
                }
                for item in attachment_evidence_pack[:6]
                if isinstance(item, dict)
            ],
            "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
            "recent_tasks": list(context_payload.get("recent_tasks") or []),
            "runtime_boundary": dump_model(turn_runtime_boundary),
            "model_action": dict(model_action),
            "execution_trace": list(execution_trace),
            "progress_signals": list(progress_signals),
            "replan_history": list(replan_history),
            "activity": {
                "run_id": run_id,
                "status": turn_status,
                "started_at": trace_events[0]["timestamp"] if trace_events else 0.0,
                "finished_at": trace_events[-1]["timestamp"] if trace_events else 0.0,
                "run_duration_ms": run_duration_ms,
                "activity_summary": activity_summary,
                "current_turn_goal": current_goal,
                "current_turn_followup_type": str(current_turn_context.get("followup_type") or ""),
                "current_turn_goal_source": str(current_turn_context.get("source") or ""),
                "active_task_focus": compat_task_checkpoint_from_focus(active_task_focus),
                "recent_user_messages": list(context_payload.get("recent_user_messages") or []),
                "phase_timings": dict(phase_timings),
                "trace_events": [dict(item) for item in trace_events],
            },
            "compaction_status": dict(live_compaction_status),
            "answer_stream": dict(answer_stream),
            "tool_events": [dump_model(item) for item in tool_events],
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
                "route_state_input": dict(route_state_input),
                "model_action": dict(model_action),
                "execution_trace": list(execution_trace),
                "progress_signals": list(progress_signals),
                "replan_history": list(replan_history),
                "project_id": project_id,
                "project_root": project_root,
                "cwd": effective_cwd,
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
            },
        }
