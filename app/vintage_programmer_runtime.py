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
from app.context_meter import count_tokens
from app.i18n import normalize_locale, response_style_hint, translate
from app.models import (
    ChatSettings,
    ExecutionTraceEntry,
    HighLevelProposal,
    ToolEvent,
    ToolGuardResult,
    ValidatedNextStep,
)
from app.openai_auth import OpenAIAuthManager
from app.runtime_contract import RuntimeContract, build_full_auto_runtime_contract
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
from packages.office_modules.intent_support import (
    has_image_attachments as has_image_attachments_helper,
    looks_like_image_capability_denial as looks_like_image_capability_denial_helper,
)
from packages.office_modules.office_agent_runtime import create_office_runtime_backend
from packages.office_modules.request_analysis import looks_like_permission_gate_text


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
_MODEL_PROPOSAL_OPEN_TAG = "<model_proposal>"
_MODEL_PROPOSAL_CLOSE_TAG = "</model_proposal>"

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

_DEFAULT_MAX_TOOL_CALLS_PER_TURN = 24
_DEFAULT_MAX_TURN_SECONDS = 1800
_DEFAULT_MAX_SAME_TOOL_REPEATS = 4
_DEFAULT_MAX_NO_PROGRESS_CYCLES = 4
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

    def descriptor(self, locale: str | None = None) -> dict[str, object]:
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
        return payload

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
    def _build_model_proposal_prompt() -> str:
        return (
            "[tool_loop_protocol]\n"
            "- Treat runtime_context_json.route_state and other harness hints as weak hints, not as the final task decision.\n"
            "- You may answer directly when the current context is sufficient.\n"
            "- When tools are needed, issue the current tool call directly instead of inventing a heavy upfront plan.\n"
            "- Tool results and tool-call errors will be returned to you. Use them to decide the next move and continue the turn.\n"
            "- Do not enumerate a full future tool list up front. Focus on the current objective and the immediate next action.\n"
            "- If it helps clarify the current objective, you may emit one concise operational proposal block in this exact wrapper format before the current step:\n"
            "  <model_proposal>{...json...}</model_proposal>\n"
            "- If you emit that block, keep it short and include: intent, task_type, current_goal, expects_tools, response_mode, user_stage, summary, next_step_hint, change_summary_requested.\n"
            "- This proposal is an operational note, not hidden chain-of-thought. Keep it concise, factual, and revisable.\n"
        )

    @staticmethod
    def _build_full_auto_tool_policy_prompt(*, locale: str, runtime_contract: RuntimeContract, model: str = "") -> str:
        model_label = str(model or "").strip().lower()
        coding_agent_like = any(token in model_label for token in ("codex", "claude", "coder", "devstral", "qwen3-coder"))
        strength = "standard" if coding_agent_like else "strict"
        return (
            "[full_auto_tool_policy]\n"
            f"enforcement_level: {strength}\n"
            f"- Current runtime mode is {runtime_contract.mode}. Tool policy is {runtime_contract.tool_policy}.\n"
            "- In default/execute mode, when the user asks to modify, fix, implement, update, complete, or patch workspace content, do the work now.\n"
            "- Use tools when needed.\n"
            "- Do not force tools for self-contained text tasks such as plain chat, explanation, translation, rewriting, meeting minutes, or summarization of text already provided by the user.\n"
            "- Use tools when the request requires external context, workspace inspection, file reading, code search, file modification, testing, command execution, or long-running task progress.\n"
            "- File edits use apply_patch. Workspace inspection uses read_file/list_dir/glob_file_search/search_codebase/exec_command. Attachment understanding uses read_file/image_read/search_contents_in_file/read_section/table_extract as appropriate.\n"
            "- Use update_plan for multi-step workspace tasks, debugging, code changes, release work, or long-running operations. Do not use update_plan for simple chat, translation, rewriting, meeting minutes, or summarizing text already provided by the user.\n"
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
    ) -> str:
        contract = runtime_contract or RuntimeContract()
        return "\n".join(
            [
                cls._build_runtime_contract_prompt(runtime_contract=contract),
                cls._build_anti_permission_gate_prompt(),
                cls._build_model_proposal_prompt(),
                cls._build_full_auto_tool_policy_prompt(locale=locale, runtime_contract=contract, model=model),
            ]
        )

    def _build_human_payload(self, *, message: str, context: dict[str, Any]) -> str:
        history_turns = list(context.get("history_turns") or [])
        recent_history = [
            {
                "role": str(item.get("role") or ""),
                "text": str(item.get("text") or "")[:1200],
            }
            for item in history_turns[:16]
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
        compaction_status = dict(context.get("compaction_status") or {})
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
            "compaction_status": {
                "generation": int(compaction_status.get("generation") or 0),
                "retained_turn_count": int(compaction_status.get("retained_turn_count") or 0),
                "last_compacted_at": str(compaction_status.get("last_compacted_at") or ""),
                "last_compaction_phase": str(compaction_status.get("last_compaction_phase") or ""),
                "replacement_history_mode": bool(compaction_status.get("replacement_history_mode")),
            },
            "recalled_context": dict(context.get("recalled_context") or {}),
            "user_input_response": dict(context.get("user_input_response") or {}),
            "attachments": attachments,
            "attachment_evidence_pack": list(context.get("attachment_evidence_pack") or [])[:8],
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
                "tool.call_detected": "检测到工具调用：{tool}",
                "tool.guard": "工具检查：{tool}",
                "tool.started": "调用工具：{tool}",
                "tool.finished": "工具完成：{tool}",
                "tool.failed": "工具失败：{tool}",
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
                "tool.call_detected": "ツール呼び出しを検出: {tool}",
                "tool.guard": "ツール検査: {tool}",
                "tool.started": "ツール呼び出し: {tool}",
                "tool.finished": "ツール完了: {tool}",
                "tool.failed": "ツール失敗: {tool}",
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
                "tool.call_detected": "Tool call detected: {tool}",
                "tool.guard": "Tool guard: {tool}",
                "tool.started": "Calling tool: {tool}",
                "tool.finished": "Tool finished: {tool}",
                "tool.failed": "Tool failed: {tool}",
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
            "proposal_filter_buffer": "",
            "proposal_filter_done": False,
            "proposal_text": "",
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
        if state.get("proposal_filter_done"):
            return delta
        buffer = f"{str(state.get('proposal_filter_buffer') or '')}{str(delta or '')}"
        state["proposal_filter_buffer"] = buffer
        stripped = buffer.lstrip()
        if stripped and not stripped.startswith("<"):
            state["proposal_filter_done"] = True
            state["proposal_filter_buffer"] = ""
            return buffer
        if stripped.startswith(_MODEL_PROPOSAL_OPEN_TAG):
            open_idx = buffer.find(_MODEL_PROPOSAL_OPEN_TAG)
            close_idx = buffer.find(_MODEL_PROPOSAL_CLOSE_TAG, open_idx + len(_MODEL_PROPOSAL_OPEN_TAG))
            if close_idx < 0:
                if len(buffer) > 4096:
                    state["proposal_filter_done"] = True
                    state["proposal_filter_buffer"] = ""
                    return buffer
                return ""
            state["proposal_text"] = buffer[open_idx + len(_MODEL_PROPOSAL_OPEN_TAG) : close_idx].strip()
            tail = buffer[close_idx + len(_MODEL_PROPOSAL_CLOSE_TAG):]
            state["proposal_filter_done"] = True
            state["proposal_filter_buffer"] = ""
            return tail
        if len(stripped) >= 32 or "\n" in stripped:
            state["proposal_filter_done"] = True
            state["proposal_filter_buffer"] = ""
            return buffer
        return ""

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
            call_state["event_count"] = int(call_state.get("event_count") or 0) + 1
            if not call_state["first_event_at"]:
                call_state["first_event_at"] = timestamp
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
        guard_result: dict[str, Any] | None = None,
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
        return ToolEvent(
            name=name or "(unknown)",
            input=arguments,
            raw_tool_call=safe_preview(raw_call_payload, limit=4000) if raw_call_payload else {},
            raw_arguments=safe_preview(raw_argument_payload, limit=4000),
            normalized_arguments=safe_preview(arguments, limit=4000) if isinstance(arguments, dict) else {},
            guard_result=dict(guard_result or {}),
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
        guard_result: dict[str, Any] | None,
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
                "guard_result": dict(guard_result or {}),
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
            guard_result=guard_result,
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
                "guard_result": dict(guard_result or {}),
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

    @staticmethod
    def _high_level_proposal_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "task_type": {"type": "string"},
                "current_goal": {"type": "string"},
                "expects_tools": {"type": "boolean"},
                "response_mode": {"type": "string"},
                "user_stage": {"type": "string"},
                "summary": {"type": "string"},
                "next_step_hint": {"type": "string"},
                "change_summary_requested": {"type": "boolean"},
                # Backward-compatible fields from the earlier turn-level proposal schema.
                "output_mode": {"type": "string"},
                "tool_decision": {"type": "string"},
                "needs_tools": {"type": "boolean"},
                "response_kind": {"type": "string"},
                "proposed_tools": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "intent",
                "task_type",
                "current_goal",
                "expects_tools",
                "response_mode",
                "user_stage",
                "summary",
                "next_step_hint",
                "change_summary_requested",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _string_list(raw_value: Any, *, limit: int = 8) -> list[str]:
        values = list(raw_value or []) if isinstance(raw_value, (list, tuple)) else []
        normalized: list[str] = []
        for item in values:
            text = str(item or "").strip()
            if text and text not in normalized:
                normalized.append(text)
            if len(normalized) >= limit:
                break
        return normalized

    def _build_runtime_guess(self, *, prompt_message: str, route_state: dict[str, Any], locale: str) -> dict[str, Any]:
        route = dict(route_state or {})
        task_checkpoint = dict(route.get("task_checkpoint") or route.get("current_task_focus") or {})
        route_task_type = str(route.get("task_type") or "").strip().lower()
        route_primary_intent = str(route.get("primary_intent") or "").strip().lower()
        execution_policy = str(route.get("execution_policy") or "").strip().lower()
        current_goal_hint = str(task_checkpoint.get("goal") or route.get("goal") or "").strip()
        next_action_hint = str(task_checkpoint.get("next_action") or "").strip()
        revision_requested = self._looks_like_revision_request(prompt_message, route_state=route)
        japanese_review = self._looks_like_japanese_review_request(prompt_message, route_state=route)
        if japanese_review:
            task_type = "japanese_grammar_review"
        elif revision_requested and route_task_type in {"", "standard", "simple_understanding", "simple_qa", "followup_transform"}:
            task_type = "rewrite_review"
        else:
            task_type = route_task_type or "standard"
        if route_primary_intent:
            primary_intent = route_primary_intent
        elif revision_requested:
            primary_intent = "transform"
        elif task_type in {"simple_understanding", "simple_qa", "understanding"}:
            primary_intent = "understanding"
        else:
            primary_intent = "standard"
        output_mode = "revision_with_change_summary" if revision_requested else "direct_answer"
        summary_reason = (
            translate(locale, "runtime.activity.summary.japanese_cleanup_requested")
            if japanese_review
            else (
                translate(locale, "runtime.activity.summary.rewrite_requested")
                if revision_requested
                else translate(locale, "runtime.activity.summary.direct_answer_path")
            )
        )
        return {
            "task_type": task_type,
            "route_task_type": route_task_type or "",
            "primary_intent": primary_intent,
            "execution_policy": execution_policy,
            "output_mode": output_mode,
            "prefer_change_summary": revision_requested,
            "summary_reason": summary_reason,
            "current_goal_hint": current_goal_hint,
            "next_action_hint": next_action_hint,
            "source": "runtime_guess",
        }

    @staticmethod
    def _extract_model_proposal_block(text: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        raw = str(text or "")
        open_idx = raw.find(_MODEL_PROPOSAL_OPEN_TAG)
        if open_idx < 0:
            return (
                {},
                raw.strip(),
                {
                    "status": "missing",
                    "checked": False,
                    "summary": "proposal block missing",
                    "errors": [],
                },
            )
        close_idx = raw.find(_MODEL_PROPOSAL_CLOSE_TAG, open_idx + len(_MODEL_PROPOSAL_OPEN_TAG))
        if close_idx < 0:
            return (
                {},
                raw.replace(_MODEL_PROPOSAL_OPEN_TAG, "").strip(),
                {
                    "status": "invalid",
                    "checked": False,
                    "summary": "proposal block not closed",
                    "errors": ["proposal block not closed"],
                },
            )
        proposal_text = raw[open_idx + len(_MODEL_PROPOSAL_OPEN_TAG) : close_idx].strip()
        cleaned_text = f"{raw[:open_idx]}{raw[close_idx + len(_MODEL_PROPOSAL_CLOSE_TAG):]}".strip()
        try:
            payload = json.loads(proposal_text) if proposal_text else {}
        except Exception as exc:
            message = safe_error_message(exc)
            return (
                {},
                cleaned_text,
                {
                    "status": "invalid",
                    "checked": False,
                    "summary": message,
                    "errors": [message],
                },
            )
        if not isinstance(payload, dict):
            return (
                {},
                cleaned_text,
                {
                    "status": "invalid",
                    "checked": False,
                    "summary": "proposal block must decode to a JSON object",
                    "errors": ["proposal block must decode to a JSON object"],
                },
            )
        return (
            dict(payload),
            cleaned_text,
            {
                "status": "parsed",
                "checked": True,
                "summary": "proposal block parsed",
                "errors": [],
            },
        )

    def _fallback_high_level_proposal(
        self,
        *,
        prompt_message: str,
        runtime_hint: dict[str, Any],
        previous_proposal: dict[str, Any] | None,
        tool_calls: list[dict[str, Any]],
        expects_tools: bool,
    ) -> HighLevelProposal:
        previous = dict(previous_proposal or {})
        has_tool_calls = bool(tool_calls)
        needs_tools = bool(has_tool_calls or expects_tools)
        response_mode = str(previous.get("response_mode") or runtime_hint.get("output_mode") or "direct_answer").strip() or "direct_answer"
        hinted_goal = str(runtime_hint.get("current_goal_hint") or "").strip()
        current_goal = hinted_goal or str(previous.get("current_goal") or "").strip() or safe_preview(prompt_message, limit=280) or (
            "Gather the required tool evidence before answering." if needs_tools else "Answer the user directly."
        )
        summary = str(previous.get("summary") or runtime_hint.get("summary_reason") or "").strip() or (
            "Use the next observed tool result to continue." if needs_tools else "Answer directly from the provided context."
        )
        next_step_hint = str(runtime_hint.get("next_action_hint") or previous.get("next_step_hint") or "").strip() or (
            "Use the returned tool result to revise the next proposal."
            if needs_tools
            else "Prepare the user-facing answer directly."
        )
        return HighLevelProposal(
            intent=str(previous.get("intent") or runtime_hint.get("primary_intent") or "standard"),
            task_type=str(previous.get("task_type") or runtime_hint.get("task_type") or "standard"),
            current_goal=current_goal,
            expects_tools=needs_tools,
            response_mode=response_mode,
            user_stage=str(previous.get("user_stage") or "").strip()
            or ("Direct answer generation" if not needs_tools else "Gather evidence for the current step"),
            summary=summary,
            next_step_hint=next_step_hint,
            change_summary_requested=bool(previous.get("change_summary_requested"))
            or bool(runtime_hint.get("prefer_change_summary")),
            source="proposal_carry_forward" if previous else "runtime_fallback",
        )

    def _normalize_high_level_proposal(
        self,
        *,
        raw_proposal: dict[str, Any],
        prompt_message: str,
        runtime_hint: dict[str, Any],
        previous_proposal: dict[str, Any] | None,
        tool_calls: list[dict[str, Any]],
        expects_tools: bool,
    ) -> tuple[HighLevelProposal, dict[str, Any]]:
        if not raw_proposal:
            fallback = self._fallback_high_level_proposal(
                prompt_message=prompt_message,
                runtime_hint=runtime_hint,
                previous_proposal=previous_proposal,
                tool_calls=tool_calls,
                expects_tools=expects_tools,
            )
            return fallback, {
                "status": "missing",
                "checked": False,
                "summary": "proposal block missing",
                "errors": [],
            }
        validation = validate_tool_arguments(raw_proposal, self._high_level_proposal_schema())
        fallback = self._fallback_high_level_proposal(
            prompt_message=prompt_message,
            runtime_hint=runtime_hint,
            previous_proposal=previous_proposal,
            tool_calls=tool_calls,
            expects_tools=expects_tools,
        )
        legacy_tool_decision = str(raw_proposal.get("tool_decision") or "").strip().lower()
        expects_tools_value = raw_proposal.get("expects_tools")
        if expects_tools_value is None:
            expects_tools_value = raw_proposal.get("needs_tools")
        proposal_expects_tools = bool(expects_tools_value)
        if tool_calls:
            proposal_expects_tools = True
        elif not proposal_expects_tools and legacy_tool_decision in {"tool_loop", "tool_if_needed", "use_tools", "tools", "needs_tools"}:
            proposal_expects_tools = True
        elif not proposal_expects_tools and expects_tools:
            proposal_expects_tools = True
        response_mode = str(
            raw_proposal.get("response_mode")
            or raw_proposal.get("output_mode")
            or fallback.response_mode
        ).strip() or fallback.response_mode
        current_goal = str(raw_proposal.get("current_goal") or "").strip() or fallback.current_goal
        summary = str(raw_proposal.get("summary") or "").strip() or fallback.summary
        next_step_hint = str(raw_proposal.get("next_step_hint") or "").strip()
        if not next_step_hint:
            next_step_hint = (
                "Use the current tool result to decide the next move."
                if proposal_expects_tools
                else "Prepare the user-facing answer directly."
            )
        return (
            HighLevelProposal(
                intent=str(raw_proposal.get("intent") or fallback.intent).strip() or fallback.intent,
                task_type=str(raw_proposal.get("task_type") or fallback.task_type).strip() or fallback.task_type,
                current_goal=current_goal,
                expects_tools=proposal_expects_tools,
                response_mode=response_mode,
                user_stage=str(raw_proposal.get("user_stage") or fallback.user_stage).strip() or fallback.user_stage,
                summary=summary,
                next_step_hint=next_step_hint,
                change_summary_requested=bool(raw_proposal.get("change_summary_requested"))
                or response_mode == "revision_with_change_summary",
                source="model",
            ),
            validation,
        )

    def _validate_next_step(
        self,
        *,
        proposal: HighLevelProposal,
        proposal_validation: dict[str, Any],
        runtime_hint: dict[str, Any],
        runnable_tools: list[str],
        tool_calls: list[dict[str, Any]],
        ai_text: str,
        expects_tools: bool,
        observed_tool_output: bool,
        step_index: int,
    ) -> ValidatedNextStep:
        proposed_tool_calls: list[dict[str, Any]] = []
        normalized_tool_names: list[str] = []
        normalization_notes: list[str] = []
        for call in tool_calls[:8]:
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
            if name:
                normalized_tool_names.append(name)
            if raw_name and raw_name != name:
                normalization_notes.append(f"{raw_name}->{name}")
            proposed_tool_calls.append(normalized_call)

        action_type = "inspect_context"
        accepted = True
        reason = ""
        if proposed_tool_calls:
            action_type = "tool_call"
            accepted = True
            reason = (
                f"Model proposed {len(proposed_tool_calls)} tool call(s); guard will validate each call before execution."
                if len(proposed_tool_calls) > 1
                else f"Model proposed {proposed_tool_calls[0].get('name') or proposed_tool_calls[0].get('raw_name') or 'a tool'}; guard will validate it before execution."
            )
        elif ai_text:
            action_type = "direct_answer"
            accepted = True
            reason = "Answer directly from the available context."
        else:
            action_type = "inspect_context"
            accepted = False
            reason = "The model did not emit an executable current step."

        validation = {
            "proposal_schema": str(proposal_validation.get("status") or "missing"),
            "permission": "allowed" if accepted else "needs_revision",
            "mode": "compatible",
            "expects_tools": bool(expects_tools or proposal.expects_tools),
            "proposed_tool_count": len(proposed_tool_calls),
            "guarded_at_execution": bool(proposed_tool_calls),
            "tool_count": len(proposed_tool_calls),
        }
        normalization = " · ".join(normalization_notes[:6])
        return ValidatedNextStep(
            step_index=max(1, int(step_index)),
            action_type=action_type,
            tool_name=(
                str(proposed_tool_calls[0].get("name") or proposed_tool_calls[0].get("raw_name") or "")
                if proposed_tool_calls
                else ""
            ),
            tool_args=(
                dict(proposed_tool_calls[0].get("args") or {})
                if proposed_tool_calls
                else {}
            ),
            tool_names=normalized_tool_names,
            approved_tool_calls=proposed_tool_calls,
            blocked_tool_calls=[],
            accepted=accepted,
            normalization=normalization,
            validation=validation,
            reason=reason,
            response_mode=proposal.response_mode or str(runtime_hint.get("output_mode") or "direct_answer"),
            task_type=proposal.task_type or str(runtime_hint.get("task_type") or "standard"),
            current_goal=proposal.current_goal,
            change_summary_requested=bool(proposal.change_summary_requested),
            source="harness",
        )

    def _guard_tool_call(
        self,
        *,
        call: dict[str, Any],
        runnable_tools: list[str],
        attachments: list[dict[str, Any]],
        locale: str,
    ) -> ToolGuardResult:
        raw_tool_name = str(call.get("raw_name") or call.get("name") or "").strip()
        tool_name = self._normalize_tool_name(str(call.get("name") or raw_tool_name).strip())
        raw_arguments = call.get("raw_args")
        if raw_arguments is None:
            raw_arguments = call.get("args")
        checks = {
            "json": "passed" if isinstance(raw_arguments, dict) else "failed",
            "tool_exists": "pending",
            "schema": "pending",
            "policy": "pending",
            "permission": "pending",
        }
        if not isinstance(raw_arguments, dict):
            invalid_args_message = translate(locale, "runtime.tool.guard.arguments_not_object")
            checks.update(
                {
                    "tool_exists": "skipped",
                    "schema": "failed",
                    "policy": "skipped",
                    "permission": "skipped",
                }
            )
            return ToolGuardResult(
                status="rejected",
                call_id=str(call.get("id") or ""),
                raw_tool_name=raw_tool_name,
                tool_name=tool_name,
                raw_arguments=safe_preview(raw_arguments, limit=4000),
                normalized_arguments={},
                normalization_notes=[],
                checks=checks,
                schema_validation={
                    "status": "invalid",
                    "checked": False,
                    "summary": invalid_args_message,
                    "errors": [invalid_args_message],
                },
                reason=invalid_args_message,
            )

        tool_exists = bool(tool_name and tool_name in self._tool_specs_by_name)
        checks["tool_exists"] = "passed" if tool_exists else "failed"
        if not tool_exists:
            checks.update({"schema": "skipped", "policy": "failed", "permission": "failed"})
            allowed_preview = ", ".join(runnable_tools[:8])
            return ToolGuardResult(
                status="rejected",
                call_id=str(call.get("id") or ""),
                raw_tool_name=raw_tool_name,
                tool_name=tool_name or raw_tool_name,
                raw_arguments=safe_preview(raw_arguments, limit=4000),
                normalized_arguments={},
                normalization_notes=[],
                checks=checks,
                schema_validation={
                    "status": "missing",
                    "checked": False,
                    "summary": translate(locale, "runtime.tool.validation.tool_unavailable"),
                    "errors": [],
                },
                reason=(
                    translate(
                        locale,
                        "runtime.tool.guard.unknown_tool",
                        tool=raw_tool_name or tool_name or "(empty)",
                        allowed_tools=allowed_preview,
                    )
                    if allowed_preview
                    else translate(locale, "runtime.tool.guard.rejected_call", tool=raw_tool_name or tool_name or "(empty)")
                ),
            )

        tool_schema = dict((self._tool_specs_by_name.get(tool_name) or {}).get("parameters") or {})
        normalization = normalize_tool_arguments(tool_name, raw_arguments, tool_schema)
        normalized_arguments = dict(normalization.get("arguments") or {})
        rewrite_arguments = self._rewrite_attachment_tool_arguments(
            name=tool_name,
            arguments=normalized_arguments,
            attachments=attachments,
        )
        normalization_notes = [str(item) for item in list(normalization.get("notes") or []) if str(item or "")]
        if rewrite_arguments != normalized_arguments:
            normalization_notes.append("attachment_ref_resolved")
        normalized_arguments = rewrite_arguments

        tool_allowed = bool(tool_name and tool_name in runnable_tools)
        checks["policy"] = "passed" if tool_allowed else "failed"
        checks["permission"] = "passed" if tool_allowed else "failed"
        schema_validation = validate_tool_arguments(normalized_arguments, tool_schema, locale=locale)
        schema_status = str(schema_validation.get("status") or "")
        if schema_status == "valid":
            checks["schema"] = "normalized" if normalization_notes else "passed"
        elif schema_status == "missing":
            checks["schema"] = "missing"
        else:
            checks["schema"] = "failed"

        if not tool_allowed:
            return ToolGuardResult(
                status="rejected",
                call_id=str(call.get("id") or ""),
                raw_tool_name=raw_tool_name,
                tool_name=tool_name,
                raw_arguments=safe_preview(raw_arguments, limit=4000),
                normalized_arguments=normalized_arguments,
                normalization_notes=normalization_notes,
                checks=checks,
                schema_validation=schema_validation,
                reason=translate(
                    locale,
                    "runtime.tool.guard.outside_boundary",
                    tool=tool_name or raw_tool_name or "(empty)",
                ),
            )

        if schema_status not in {"valid", "missing"}:
            return ToolGuardResult(
                status="rejected",
                call_id=str(call.get("id") or ""),
                raw_tool_name=raw_tool_name,
                tool_name=tool_name,
                raw_arguments=safe_preview(raw_arguments, limit=4000),
                normalized_arguments=normalized_arguments,
                normalization_notes=normalization_notes,
                checks=checks,
                schema_validation=schema_validation,
                reason=str(schema_validation.get("summary") or translate(locale, "runtime.tool.guard.arguments_invalid")),
            )

        guard_status = "normalized" if normalization_notes or raw_tool_name != tool_name else "accepted"
        if guard_status == "normalized":
            reason = translate(locale, "runtime.activity.guard.normalized_approved", tool=tool_name or "tool")
        else:
            reason = translate(locale, "runtime.activity.guard.accepted", tool=tool_name or "tool")
        return ToolGuardResult(
            status=guard_status,
            call_id=str(call.get("id") or ""),
            raw_tool_name=raw_tool_name,
            tool_name=tool_name,
            raw_arguments=safe_preview(raw_arguments, limit=4000),
            normalized_arguments=normalized_arguments,
            normalization_notes=normalization_notes,
            checks=checks,
            schema_validation=schema_validation,
            reason=reason,
        )

    @staticmethod
    def _tool_guard_activity_detail(locale: str, guard_result: dict[str, Any]) -> str:
        guard = dict(guard_result or {})
        status = str(guard.get("status") or "").strip()
        tool_name = str(guard.get("tool_name") or guard.get("raw_tool_name") or "tool").strip() or "tool"
        if status == "normalized":
            notes = [str(item) for item in list(guard.get("normalization_notes") or []) if str(item or "")]
            suffix = f" ({', '.join(notes[:3])})" if notes else ""
            return translate(locale, "runtime.activity.guard.normalized_continued", tool=tool_name, suffix=suffix)
        if status == "rejected":
            return str(guard.get("reason") or translate(locale, "runtime.activity.guard.rejected", tool=tool_name))[:280]
        return translate(locale, "runtime.activity.guard.accepted_execution", tool=tool_name)

    @staticmethod
    def _structured_tool_guard_rejection_result(
        *,
        locale: str,
        guard_result: ToolGuardResult,
        runnable_tools: list[str],
    ) -> dict[str, Any]:
        guard_payload = guard_result.model_dump()
        tool_name = str(guard_result.tool_name or guard_result.raw_tool_name or "")
        allowed_tools = [str(item) for item in list(runnable_tools or []) if str(item or "").strip()]
        message = str(guard_result.reason or "").strip()
        if not message:
            message = translate(locale, "runtime.tool.guard.rejected_call", tool=tool_name or "(empty)")
        if str((guard_result.checks or {}).get("tool_exists") or "") == "failed":
            allowed_preview = ", ".join(allowed_tools[:8])
            if allowed_preview:
                message = translate(
                    locale,
                    "runtime.tool.guard.unknown_tool",
                    tool=tool_name or "(empty)",
                    allowed_tools=allowed_preview,
                )
        elif str((guard_result.checks or {}).get("policy") or "") == "failed":
            message = translate(locale, "runtime.tool.guard.policy_blocked", tool=tool_name or "(empty)")
        elif str((guard_result.checks or {}).get("schema") or "") == "failed":
            schema_summary = str((guard_result.schema_validation or {}).get("summary") or "").strip()
            if schema_summary:
                message = translate(
                    locale,
                    "runtime.tool.guard.schema_invalid",
                    tool=tool_name or "(empty)",
                    summary=schema_summary,
                )
        return {
            "ok": False,
            "error": {
                "kind": "tool_call_rejected",
                "tool": tool_name,
                "message": message,
                "guard_status": str(guard_result.status or ""),
            },
            "guard_result": guard_payload,
            "allowed_tools": allowed_tools,
            "summary": message,
        }

    @staticmethod
    def _proposal_activity_detail(locale: str, proposal: dict[str, Any]) -> str:
        summary = str((proposal or {}).get("summary") or "").strip()
        if summary:
            return summary
        return str((proposal or {}).get("current_goal") or "").strip() or translate(locale, "runtime.activity.proposal.current_understanding_recorded")

    @staticmethod
    def _validation_activity_detail(locale: str, validated_next_step: dict[str, Any]) -> str:
        step = dict(validated_next_step or {})
        action_type = str(step.get("action_type") or "").strip()
        accepted = bool(step.get("accepted"))
        if not accepted:
            return str(step.get("reason") or translate(locale, "runtime.activity.validation.rejected_current_step"))[:280]
        if action_type == "tool_call":
            tool_names = VintageProgrammerRuntime._string_list(step.get("tool_names"), limit=4)
            if tool_names:
                return translate(locale, "runtime.activity.validation.tool_call_queued_named", tools=", ".join(tool_names))
            return translate(locale, "runtime.activity.validation.tool_call_queued")
        if action_type == "direct_answer":
            return translate(locale, "runtime.activity.validation.direct_answer")
        if action_type == "ask_user":
            return translate(locale, "runtime.activity.validation.user_input_step")
        return translate(locale, "runtime.activity.validation.current_step_accepted")

    @staticmethod
    def _execution_activity_detail(locale: str, entry: dict[str, Any]) -> str:
        item = dict(entry or {})
        observation = str(item.get("observation_summary") or "").strip()
        if observation:
            return observation
        return str(item.get("result_summary") or "").strip() or translate(locale, "runtime.activity.execution.recorded")

    @staticmethod
    def _activity_context_from_step(
        proposal: dict[str, Any],
        validated_next_step: dict[str, Any],
        runtime_hint: dict[str, Any],
    ) -> dict[str, Any]:
        step = dict(validated_next_step or {})
        hint = dict(runtime_hint or {})
        item = dict(proposal or {})
        response_mode = str(step.get("response_mode") or item.get("response_mode") or hint.get("output_mode") or "direct_answer").strip() or "direct_answer"
        return {
            "task_type": str(step.get("task_type") or item.get("task_type") or hint.get("task_type") or "standard").strip() or "standard",
            "route_task_type": str(hint.get("route_task_type") or ""),
            "primary_intent": str(item.get("intent") or hint.get("primary_intent") or "standard").strip() or "standard",
            "execution_policy": str(hint.get("execution_policy") or ""),
            "output_mode": response_mode,
            "prefer_change_summary": bool(step.get("change_summary_requested"))
            or response_mode == "revision_with_change_summary"
            or bool(hint.get("prefer_change_summary")),
            "summary_reason": str(item.get("summary") or hint.get("summary_reason") or "").strip(),
            "response_mode": response_mode,
            "current_goal": str(item.get("current_goal") or ""),
            "action_type": str(step.get("action_type") or ""),
            "user_stage": str(item.get("user_stage") or ""),
            "source": str(item.get("source") or hint.get("source") or ""),
        }

    @staticmethod
    def _append_execution_trace(
        execution_trace: list[dict[str, Any]],
        entry: ExecutionTraceEntry,
    ) -> list[dict[str, Any]]:
        next_trace = [*list(execution_trace or []), entry.model_dump()]
        return next_trace[-24:]

    def _resolve_step_state(
        self,
        *,
        prompt_message: str,
        ai_text: str,
        runtime_hint: dict[str, Any],
        previous_proposal: dict[str, Any] | None,
        runnable_tools: list[str],
        tool_calls: list[dict[str, Any]],
        expects_tools: bool,
        observed_tool_output: bool,
        step_index: int,
    ) -> dict[str, Any]:
        raw_proposal, cleaned_text, block_meta = self._extract_model_proposal_block(ai_text)
        proposal, proposal_validation = self._normalize_high_level_proposal(
            raw_proposal=raw_proposal,
            prompt_message=prompt_message,
            runtime_hint=runtime_hint,
            previous_proposal=previous_proposal,
            tool_calls=tool_calls,
            expects_tools=expects_tools,
        )
        validated_next_step = self._validate_next_step(
            proposal=proposal,
            proposal_validation=proposal_validation,
            runtime_hint=runtime_hint,
            runnable_tools=runnable_tools,
            tool_calls=tool_calls,
            ai_text=cleaned_text,
            expects_tools=expects_tools,
            observed_tool_output=observed_tool_output,
            step_index=step_index,
        )
        return {
            "clean_text": cleaned_text,
            "high_level_proposal": proposal.model_dump(),
            "validated_next_step": validated_next_step.model_dump(),
            "proposal_diagnostics": {
                **dict(block_meta or {}),
                "schema_validation": dict(proposal_validation or {}),
            },
            "runtime_hint": dict(runtime_hint or {}),
            "activity_context": self._activity_context_from_step(
                proposal.model_dump(),
                validated_next_step.model_dump(),
                runtime_hint,
            ),
        }

    def _strip_model_proposal_from_message(self, ai_msg: Any) -> dict[str, Any]:
        raw_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
        _proposal, cleaned_text, block_meta = self._extract_model_proposal_block(raw_text)
        try:
            ai_msg.content = cleaned_text
        except Exception:
            pass
        return dict(block_meta or {})

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
    def _has_write_tool_event(tool_events: list[ToolEvent]) -> bool:
        for item in tool_events:
            if str(getattr(item, "name", "") or "").strip() in _WRITE_TOOL_NAMES and str(getattr(item, "status", "") or "") == "ok":
                return True
        return False

    @staticmethod
    def _looks_like_invalid_permission_gate(text: str, *, request_requires_tools: bool) -> bool:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return False
        if looks_like_permission_gate_text(normalized, request_requires_tools=request_requires_tools):
            return True
        lowered = normalized.lower()
        extra_markers = (
            "要不要我",
            "是否需要我",
            "请确认",
            "你确认",
            "回一句",
            "回复“补”",
            "回复\"补\"",
            "我再 patch",
            "我再修改",
            "shall i",
            "should i apply",
            "confirm before",
            "reply yes",
            "please confirm",
            "確認してください",
            "確認して",
            "実行してよいですか",
        )
        return any(marker.lower() in lowered for marker in extra_markers)

    def _build_invalid_final_steer(
        self,
        *,
        locale: str,
        write_authorization_state: dict[str, Any],
        attachment_evidence_pack: list[dict[str, Any]],
    ) -> str:
        lines = [
            translate(locale, "runtime.invalid_final_guard.steer"),
            f"write_authorization_state: {json.dumps(write_authorization_state, ensure_ascii=False)}",
            "Required behavior: call apply_patch/exec_command/read_file/list_dir/glob_file_search/search_codebase or another appropriate tool now; do not ask for confirmation in prose.",
        ]
        if attachment_evidence_pack:
            lines.append(
                "attachment_evidence_pack_available: "
                + json.dumps(
                    [
                        {
                            "id": str(item.get("id") or ""),
                            "name": str(item.get("name") or ""),
                            "kind": str(item.get("kind") or ""),
                            "summary": str(item.get("summary") or "")[:240],
                        }
                        for item in attachment_evidence_pack[:4]
                        if isinstance(item, dict)
                    ],
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines)

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

    def _build_act_now_steer(self, attachments: list[dict[str, Any]], *, locale: str) -> str:
        lines = [translate(locale, "runtime.act_now.default")]
        image_paths = self._attachment_paths(attachments, kind="image")
        if image_paths:
            lines.append(translate(locale, "runtime.act_now.image"))
            lines.append(
                translate(
                    locale,
                    "runtime.act_now.image_paths",
                    paths=json.dumps(image_paths[:2], ensure_ascii=False),
                )
            )
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

    def _auto_rescue_image_read(
        self,
        *,
        attachments: list[dict[str, Any]],
        tool_events: list[ToolEvent],
        trace_events: list[dict[str, Any]],
        messages: list[Any],
        runner: Any,
        effective_model: str,
        settings: ChatSettings,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        spec: VintageProgrammerSpec,
        round_idx: int,
        run_id: str,
        locale: str,
        current_goal: str,
        current_task_focus: dict[str, Any],
        collaboration_mode: str,
        turn_status: str,
        plan_state: list[dict[str, Any]],
        pending_user_input: dict[str, Any],
        effective_cwd: str,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Any, Any, str, bool, list[str]]:
        image_path = self._first_attachment_path(attachments, kind="image")
        if not image_path:
            return runner, effective_model, "", False, []

        arguments = {"path": image_path}
        result, _event = self._execute_tool_with_trace(
            name="image_read",
            arguments=arguments,
            raw_tool_call={"id": "auto_image_read_rescue", "name": "image_read", "arguments": safe_preview(arguments, limit=4000)},
            guard_result={
                "status": "accepted",
                "tool_name": "image_read",
                "raw_tool_name": "image_read",
                "normalized_arguments": safe_preview(arguments, limit=4000),
                "normalization_notes": [],
                "checks": {
                    "json": "passed",
                    "tool_exists": "passed",
                    "schema": "missing",
                    "policy": "passed",
                    "permission": "passed",
                },
                "reason": "Auto image rescue executed image_read directly.",
            },
            raw_arguments=arguments,
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
            call_idx=1,
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
        ai_msg, runner, effective_model, invoke_notes = self._invoke_backend_method(
            self._backend._invoke_with_runner_recovery,
            runner=runner,
            messages=messages,
            model=effective_model,
            max_output_tokens=int(settings.max_output_tokens),
            enable_tools=True,
            tool_names=list(spec.allowed_tools),
            event_cb=event_cb,
        )
        return ai_msg, runner, effective_model, bool(result.get("ok")), invoke_notes

    @staticmethod
    def _build_image_read_fallback_answer(result: dict[str, Any], *, locale: str) -> str:
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

        lines: list[str] = [translate(locale, "runtime.image_read.intro")]
        if visible_text:
            lines.append(translate(locale, "runtime.image_read.visible_text"))
            lines.append("")
            lines.append("```text")
            lines.append(visible_text)
            lines.append("```")
        if analysis and analysis.lower() != "extracted visible text from the image using local ocr.":
            lines.append(translate(locale, "runtime.image_read.analysis", analysis=analysis))
        elif not visible_text and analysis:
            lines.append(translate(locale, "runtime.image_read.analysis", analysis=analysis))
        meta_bits = [str(item) for item in (width, height) if item not in (None, "")]
        if mime or meta_bits:
            detail = " · ".join(
                [item for item in [mime.upper() if mime else "", "x".join(meta_bits) if len(meta_bits) == 2 else ""] if item]
            )
            if detail:
                lines.append(translate(locale, "runtime.image_read.basic_info", detail=detail))
        if warning:
            lines.append(translate(locale, "runtime.image_read.warning", warning=warning))
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
        model: str | None,
        auto_compact_token_limit: int,
        context_window_known: bool,
    ) -> tuple[list[Any], int, bool, int]:
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

        if self._require_runtime_auth:
            auth_summary = OpenAIAuthManager(self._config).auth_summary()
            if not bool(auth_summary.get("available")):
                raise RuntimeError(str(auth_summary.get("reason") or "LLM credentials are required"))

        context_payload = dict(context or {})
        locale = normalize_locale(getattr(settings, "locale", ""), self._config.default_locale)
        run_id = str(context_payload.get("run_id") or "")
        session_id = str(context_payload.get("session_id") or "")
        attachment_metas = [
            item for item in list(context_payload.get("attachments") or [])
            if isinstance(item, dict)
        ]
        attachment_guidance = self._build_attachment_tool_guidance(attachment_metas, locale=locale)
        has_image_attachments = has_image_attachments_helper(attachment_metas)
        spec = self._load_spec(locale=locale)
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
        attachment_evidence_pack = [
            item for item in list(context_payload.get("attachment_evidence_pack") or [])
            if isinstance(item, dict)
        ]
        requires_tools_hint = bool(
            _looks_like_explicit_tool_request(prompt_message)
            or attachment_requires_tools
            or bool(attachment_evidence_pack)
        )
        runtime_contract = build_full_auto_runtime_contract(
            settings=settings,
            config=self._config,
            context=context_payload,
            requires_tools_hint=requires_tools_hint,
        )
        expects_tools = (
            collaboration_mode in {"default", "execute"}
            and bool(runnable_tools)
            and not inline_document
            and (_looks_like_explicit_tool_request(prompt_message) or attachment_requires_tools or bool(attachment_evidence_pack))
        )
        project_context = dict(context_payload.get("project") or {})
        project_root = str(project_context.get("project_root") or "").strip()
        project_id = str(project_context.get("project_id") or "").strip()
        effective_cwd = str(project_context.get("cwd") or project_root or "").strip()
        compaction_status = dict(context_payload.get("compaction_status") or {})
        auto_compact_token_limit = max(0, int(compaction_status.get("auto_compact_token_limit") or 0))
        context_window_known = bool(compaction_status.get("context_window_known"))
        live_compaction_status = dict(compaction_status)
        route_state_input = dict(context_payload.get("route_state") or {})
        runtime_hint = self._build_runtime_guess(
            prompt_message=prompt_message,
            route_state=route_state_input,
            locale=locale,
        )
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
        write_authorization_state = self._write_authorization_state(
            prompt_message,
            collaboration_mode=collaboration_mode,
            project_root=project_root,
        )
        write_authorized = bool(write_authorization_state.get("authorized"))
        invalid_final_guard = {
            "enabled": bool(write_authorized and collaboration_mode in {"default", "execute"} and bool(runnable_tools)),
            "triggered": False,
            "attempts": 0,
            "reason": "",
        }
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
        last_image_read_result: dict[str, Any] | None = None
        high_level_proposal: dict[str, Any] = {}
        validated_next_step: dict[str, Any] = {}
        execution_trace: list[dict[str, Any]] = []
        proposal_diagnostics: dict[str, Any] = {}
        trace_events: list[dict[str, Any]] = []
        run_started_at = time.monotonic()
        answer_stream_state = self._new_answer_stream_state(run_id=run_id, thread_id=session_id)
        turn_activity_context = dict(runtime_hint)
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
                "expects_tools": expects_tools,
                "collaboration_mode": collaboration_mode,
                "runtime_hint": dict(runtime_hint),
                "runtime_guess": dict(runtime_hint),
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
                "expects_tools": expects_tools,
                "collaboration_mode": collaboration_mode,
                "runtime_hint": dict(runtime_hint),
                "runtime_guess": dict(runtime_hint),
            },
            visible=False,
        )
        emit_runtime_activity(
            "activity.started",
            "high_level_proposal",
            "Requesting the current objective and next move from the model.",
            payload={
                "tool_count": len(runnable_tools),
                "expects_tools": expects_tools,
                "inline_document": inline_document,
                "runtime_hint": dict(runtime_hint),
                "runtime_guess": dict(runtime_hint),
            },
        )

        def refresh_model_step(ai_msg: Any, *, event_type: str = "activity.done") -> None:
            nonlocal current_step_index
            nonlocal high_level_proposal
            nonlocal validated_next_step
            nonlocal proposal_diagnostics
            nonlocal turn_activity_context
            nonlocal current_goal
            nonlocal current_task_focus
            nonlocal notes
            current_step_index += 1
            raw_ai_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
            current_tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
            step_state = self._resolve_step_state(
                prompt_message=prompt_message,
                ai_text=raw_ai_text,
                runtime_hint=runtime_hint,
                previous_proposal=high_level_proposal,
                runnable_tools=runnable_tools,
                tool_calls=current_tool_calls,
                expects_tools=expects_tools,
                observed_tool_output=any(item.status == "ok" for item in tool_events),
                step_index=current_step_index,
            )
            cleaned_text = str(step_state.get("clean_text") or raw_ai_text).strip()
            high_level_proposal = dict(step_state.get("high_level_proposal") or {})
            validated_next_step = dict(step_state.get("validated_next_step") or {})
            proposal_diagnostics = dict(step_state.get("proposal_diagnostics") or {})
            turn_activity_context = dict(step_state.get("activity_context") or runtime_hint)
            proposal_goal = str(high_level_proposal.get("current_goal") or "").strip()
            if proposal_goal:
                current_goal = proposal_goal
                current_task_focus["goal"] = current_goal
            try:
                ai_msg.content = cleaned_text
            except Exception:
                pass
            if cleaned_text != raw_ai_text:
                notes.append("model_turn_proposal_stripped_from_answer_text")
            if str(((proposal_diagnostics.get("schema_validation") or {}).get("status")) or "") not in {"", "valid"}:
                notes.append("high_level_proposal_schema_adjusted")
            emit_runtime_activity(
                event_type,
                "high_level_proposal",
                self._proposal_activity_detail(locale, high_level_proposal),
                status="success",
                payload={
                    "high_level_proposal": dict(high_level_proposal),
                    "runtime_hint": dict(runtime_hint),
                    "runtime_guess": dict(runtime_hint),
                    "proposal_diagnostics": dict(proposal_diagnostics),
                    "revision_index": int(current_step_index),
                },
            )
            emit_runtime_activity(
                event_type,
                "step_validation",
                self._validation_activity_detail(locale, validated_next_step),
                status="success" if bool(validated_next_step.get("accepted")) else "blocked",
                payload={
                    "validated_next_step": dict(validated_next_step),
                    "high_level_proposal": dict(high_level_proposal),
                    "runtime_hint": dict(runtime_hint),
                    "runtime_guess": dict(runtime_hint),
                    "proposal_diagnostics": dict(proposal_diagnostics),
                    "revision_index": int(current_step_index),
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

            act_now_budget = 1 if collaboration_mode in {"default", "execute"} and max_tool_calls_per_turn > 0 else 0
            invalid_final_guard_budget = 1 if bool(invalid_final_guard.get("enabled")) else 0
            auto_image_rescue_budget = 1 if has_image_attachments and "image_read" in runnable_tools else 0
            halt_for_user_input = False
            turn_started_at = time.monotonic()
            round_idx = 0
            tool_call_count = 0
            same_tool_repeat_count = 0
            last_tool_name = ""
            no_progress_cycles = 0
            last_round_signature = ""
            guard_rejection_count = 0
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
                    forced_text = translate(locale, "runtime.budget.wall_clock")
                    notes.append("turn_budget_wall_clock_exceeded")
                    break

                ai_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
                tool_calls = list(validated_next_step.get("approved_tool_calls") or [])
                step_action_type = str(validated_next_step.get("action_type") or "").strip() or "inspect_context"
                step_accepted = bool(validated_next_step.get("accepted"))
                if not tool_calls:
                    invalid_permission_gate = (
                        bool(invalid_final_guard.get("enabled"))
                        and not self._has_write_tool_event(tool_events)
                        and self._looks_like_invalid_permission_gate(
                            ai_text,
                            request_requires_tools=bool(expects_tools or write_authorized or tool_events),
                        )
                    )
                    if invalid_permission_gate:
                        invalid_final_guard["triggered"] = True
                        invalid_final_guard["attempts"] = int(invalid_final_guard.get("attempts") or 0) + 1
                        invalid_final_guard["reason"] = "natural_language_confirmation_after_write_authorization"
                        if invalid_final_guard_budget > 0:
                            invalid_final_guard_budget -= 1
                            self._emit_trace(
                                progress_cb,
                                run_id=run_id,
                                type="repair.started",
                                title=self._trace_label(locale, "repair.started"),
                                detail="invalid_final_guard",
                                status="running",
                                trace_events=trace_events,
                            )
                            messages.append(ai_msg)
                            messages.append(
                                self._backend._SystemMessage(
                                    content=self._build_invalid_final_steer(
                                        locale=locale,
                                        write_authorization_state=write_authorization_state,
                                        attachment_evidence_pack=attachment_evidence_pack,
                                    )
                                )
                            )
                            notes.append("invalid_final_guard_steer")
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
                                    stage="repair_invalid_final_guard",
                                    model=effective_model,
                                    tool_round=round_idx,
                                    answer_context=turn_activity_context,
                                ),
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
                            self._emit_trace(
                                progress_cb,
                                run_id=run_id,
                                type="repair.finished",
                                title=self._trace_label(locale, "repair.finished"),
                                detail="invalid_final_guard",
                                status="success",
                                trace_events=trace_events,
                            )
                            continue
                        turn_status = "blocked"
                        blocked_reason = "model_refused_to_act_after_authorization"
                        forced_text = translate(locale, "runtime.invalid_final_guard.blocked")
                        notes.append(blocked_reason)
                        break
                    should_steer = (
                        act_now_budget > 0
                        and not tool_events
                        and collaboration_mode in {"default", "execute"}
                        and (
                            (not step_accepted)
                            or expects_tools
                            or self._looks_like_plan_only_response(ai_text)
                            or (has_image_attachments and looks_like_image_capability_denial_helper(ai_text))
                        )
                    )
                    if should_steer:
                        act_now_budget -= 1
                        messages.append(ai_msg)
                        messages.append(
                            self._backend._SystemMessage(
                                content=self._build_act_now_steer(attachment_metas, locale=locale)
                            )
                        )
                        notes.append("strict_agentic_act_now_steer")
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
                                stage="repair_act_now",
                                model=effective_model,
                                tool_round=round_idx,
                                answer_context=turn_activity_context,
                            ),
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
                            trace_events=trace_events,
                            messages=messages,
                            runner=runner,
                            effective_model=effective_model,
                            settings=settings,
                            progress_cb=progress_cb,
                            spec=spec,
                            round_idx=round_idx + 1,
                            run_id=run_id,
                            locale=locale,
                            current_goal=current_goal,
                            current_task_focus=current_task_focus,
                            collaboration_mode=collaboration_mode,
                            turn_status=turn_status,
                            plan_state=plan_state,
                            pending_user_input=pending_user_input,
                            effective_cwd=effective_cwd,
                            event_cb=self._make_model_stream_observer(
                                progress_cb=progress_cb,
                                run_id=run_id,
                                thread_id=session_id,
                                locale=locale,
                                trace_events=trace_events,
                                answer_stream_state=answer_stream_state,
                                stage="image_rescue_response",
                                model=effective_model,
                                tool_round=round_idx + 1,
                                answer_context=turn_activity_context,
                            ),
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
                        notes.extend(rescue_notes)
                        usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))
                        refresh_model_step(ai_msg, event_type="activity.delta")
                        tool_call_count += 1
                        if last_tool_name == "image_read":
                            same_tool_repeat_count += 1
                        else:
                            last_tool_name = "image_read"
                            same_tool_repeat_count = 1
                        if rescue_ok:
                            no_progress_cycles = 0
                        continue
                    no_tool_response_kind = "direct_answer" if ai_text else "empty_response"
                    if self._looks_like_plan_only_response(ai_text):
                        no_tool_response_kind = "plan_only"
                    if not step_accepted:
                        blocked_reason = blocked_reason or "validated_next_step_rejected"
                    execution_entry = ExecutionTraceEntry(
                        step_index=int(validated_next_step.get("step_index") or current_step_index),
                        action_type=step_action_type,
                        status="completed" if step_accepted else "blocked",
                        title=translate(locale, "runtime.activity.execution_title.direct_answer"),
                        result_summary=safe_preview(ai_text, limit=240),
                        observation_summary=(
                            translate(locale, "runtime.activity.execution.direct_answer_prepared")
                            if step_accepted
                            else str(validated_next_step.get("reason") or translate(locale, "runtime.activity.validation.rejected_current_step"))
                        ),
                        detail=str(validated_next_step.get("reason") or ""),
                        payload={
                            "validated_next_step": dict(validated_next_step),
                            "response_kind": no_tool_response_kind,
                        },
                    )
                    execution_trace = self._append_execution_trace(execution_trace, execution_entry)
                    emit_runtime_activity(
                        "activity.done" if round_idx == 0 else "activity.delta",
                        "execution",
                        self._execution_activity_detail(locale, execution_entry.model_dump()),
                        status="success" if step_accepted else "blocked",
                        payload={
                            "execution_trace": list(execution_trace),
                            "execution_trace_entry": execution_entry.model_dump(),
                            "validated_next_step": dict(validated_next_step),
                            "high_level_proposal": dict(high_level_proposal),
                            "runtime_hint": dict(runtime_hint),
                            "runtime_guess": dict(runtime_hint),
                            **turn_activity_context,
                        },
                    )
                    break

                messages.append(ai_msg)
                round_idx += 1
                round_success = False
                round_signature_parts: list[dict[str, Any]] = []
                stop_after_tools = False
                emit_runtime_activity(
                    "activity.delta",
                    "execution",
                    translate(locale, "runtime.activity.execution.processing_tool_calls", count=len(tool_calls[:8])),
                    payload={
                        "tool_names": [str(call.get("name") or "") for call in tool_calls[:8]],
                        "tool_count": len(tool_calls[:8]),
                        "validated_next_step": dict(validated_next_step),
                        "high_level_proposal": dict(high_level_proposal),
                        "runtime_hint": dict(runtime_hint),
                        "runtime_guess": dict(runtime_hint),
                        **turn_activity_context,
                    },
                )
                for call_idx, call in enumerate(tool_calls[:8], start=1):
                    if self._cancel_requested(context_payload):
                        turn_status = "cancelled"
                        forced_text = translate(locale, "runtime.cancelled.text")
                        notes.append("run_cancelled_by_user")
                        stop_after_tools = True
                        break
                    if max_tool_calls_per_turn and tool_call_count >= max_tool_calls_per_turn:
                        turn_status = "blocked"
                        forced_text = translate(locale, "runtime.budget.tool_calls")
                        notes.append("turn_budget_tool_calls_exceeded")
                        stop_after_tools = True
                        break
                    raw_name = str(call.get("raw_name") or call.get("name") or "").strip()
                    raw_arguments = call.get("raw_args")
                    if raw_arguments is None:
                        raw_arguments = call.get("args")
                    preview_name = self._normalize_tool_name(str(call.get("name") or raw_name).strip())
                    preview_args = dict(raw_arguments) if isinstance(raw_arguments, dict) else {}
                    preview_schema = dict((self._tool_specs_by_name.get(preview_name) or {}).get("parameters") or {})
                    tool_audit = build_tool_argument_audit(preview_name or raw_name, preview_args, preview_schema, locale=locale)
                    raw_tool_call_payload = {
                        "id": str(call.get("id") or ""),
                        "name": raw_name or str(call.get("name") or ""),
                        "arguments": safe_preview(raw_arguments, limit=4000),
                    }
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
                    guard_result = self._guard_tool_call(
                        call=call,
                        runnable_tools=runnable_tools,
                        attachments=attachment_metas,
                        locale=locale,
                    )
                    guard_payload = guard_result.model_dump()
                    name = str(guard_result.tool_name or preview_name or raw_name).strip()
                    arguments = dict(guard_result.normalized_arguments or {})
                    if raw_name and raw_name != name:
                        notes.append(f"tool_alias:{raw_name}->{name}")
                    if guard_result.normalization_notes:
                        notes.extend(f"tool_guard_normalized:{item}" for item in guard_result.normalization_notes)
                    self._emit_trace(
                        progress_cb,
                        run_id=run_id,
                        type="tool.guard",
                        title=self._trace_label(locale, "tool.guard", tool=name or raw_name or "tool"),
                        detail=self._tool_guard_activity_detail(locale, guard_payload),
                        status="success" if guard_result.status in {"accepted", "normalized"} else "blocked",
                        payload={
                            "tool_name": name or raw_name,
                            "raw_tool_call": raw_tool_call_payload,
                            "guard_result": guard_payload,
                            "normalized_arguments": safe_preview(arguments, limit=4000),
                        },
                        trace_events=trace_events,
                    )
                    emit_runtime_activity(
                        "activity.delta",
                        "step_validation",
                        self._tool_guard_activity_detail(locale, guard_payload),
                        status="success" if guard_result.status in {"accepted", "normalized"} else "blocked",
                        payload={
                            "validated_next_step": dict(validated_next_step),
                            "high_level_proposal": dict(high_level_proposal),
                            "runtime_hint": dict(runtime_hint),
                            "runtime_guess": dict(runtime_hint),
                            "guard_result": guard_payload,
                            "raw_tool_call": raw_tool_call_payload,
                            "normalized_arguments": safe_preview(arguments, limit=4000),
                            **turn_activity_context,
                        },
                    )
                    if guard_result.status in {"accepted", "normalized"}:
                        result, event = self._execute_tool_with_trace(
                            name=name,
                            arguments=arguments,
                            raw_tool_call=raw_tool_call_payload,
                            guard_result=guard_payload,
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
                        result = self._structured_tool_guard_rejection_result(
                            locale=locale,
                            guard_result=guard_result,
                            runnable_tools=runnable_tools,
                        )
                        event = self._build_tool_event(
                            name=name or raw_name,
                            arguments=arguments,
                            result=result,
                            locale=locale,
                            raw_tool_call=raw_tool_call_payload,
                            guard_result=guard_payload,
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
                                "guard_result": guard_payload,
                                "normalized_arguments": safe_preview(arguments, limit=4000),
                                **tool_audit,
                                "result_preview": safe_preview(result),
                            },
                            trace_events=trace_events,
                        )
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
                                }
                            )
                        notes.append("tool_guard_rejected")
                        if guard_rejection_count > _DEFAULT_MAX_GUARD_REJECTIONS:
                            turn_status = "blocked"
                            blocked_reason = blocked_reason or "tool_guard_rejections_exceeded"
                            forced_text = str(result.get("summary") or translate(locale, "runtime.budget.no_progress"))
                            stop_after_tools = True
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
                        locale=locale,
                    )
                    tool_call_count += 1
                    if name == last_tool_name:
                        same_tool_repeat_count += 1
                    else:
                        last_tool_name = name
                        same_tool_repeat_count = 1
                    round_signature_parts.append(
                        {
                            "name": name,
                            "input": arguments,
                            "status": event.status,
                        }
                    )
                    if event.status == "ok":
                        round_success = True
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
                            fallback_answer = self._build_image_read_fallback_answer(last_image_read_result, locale=locale)
                            if fallback_answer:
                                turn_status = "completed"
                                forced_text = fallback_answer
                                notes.append("image_read_repeat_fallback_answer")
                            else:
                                turn_status = "blocked"
                                forced_text = translate(locale, "runtime.budget.same_tool_repeat")
                                notes.append("turn_budget_same_tool_repeats_exceeded")
                        else:
                            turn_status = "blocked"
                            forced_text = translate(locale, "runtime.budget.same_tool_repeat")
                            notes.append("turn_budget_same_tool_repeats_exceeded")
                        stop_after_tools = True
                        break

                if round_signature_parts:
                    execution_entry = ExecutionTraceEntry(
                        step_index=int(validated_next_step.get("step_index") or current_step_index),
                        action_type="tool_call",
                        status=(
                            "blocked"
                            if turn_status in {"blocked", "needs_user_input"}
                            else ("completed" if round_success else "failed")
                        ),
                        title=translate(locale, "runtime.activity.execution_title.tool_execution"),
                        tool_name=str((validated_next_step.get("tool_name") or "")),
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
                        detail=str(validated_next_step.get("reason") or ""),
                        payload={
                            "validated_next_step": dict(validated_next_step),
                            "completed_tool_calls": len(round_signature_parts),
                            "successful_tool_calls": sum(1 for item in round_signature_parts if str(item.get("status") or "") == "ok"),
                        },
                    )
                    execution_trace = self._append_execution_trace(execution_trace, execution_entry)
                    emit_runtime_activity(
                        "activity.delta",
                        "execution",
                        self._execution_activity_detail(locale, execution_entry.model_dump()),
                        status="blocked" if turn_status in {"blocked", "needs_user_input"} else ("success" if round_success else "failed"),
                        payload={
                            "execution_trace": list(execution_trace),
                            "execution_trace_entry": execution_entry.model_dump(),
                            "validated_next_step": dict(validated_next_step),
                            "high_level_proposal": dict(high_level_proposal),
                            "runtime_hint": dict(runtime_hint),
                            "runtime_guess": dict(runtime_hint),
                            **turn_activity_context,
                        },
                    )

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
                        "validated_next_step": dict(validated_next_step),
                        "high_level_proposal": dict(high_level_proposal),
                        "runtime_hint": dict(runtime_hint),
                        "runtime_guess": dict(runtime_hint),
                        **turn_activity_context,
                    },
                )

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
                    forced_text = translate(locale, "runtime.budget.no_progress")
                    notes.append("turn_budget_no_progress_exceeded")
                    break

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
                    live_compaction_status["last_compaction_phase"] = "mid_turn"
                    live_compaction_status["last_compacted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    live_compaction_status["last_compaction_reason"] = (
                        f"mid_turn_context_budget_exceeded:{int(live_estimated_tokens or 0)}/{int(auto_compact_token_limit or 0)}"
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
        if (
            has_image_attachments
            and last_image_read_result
            and self._looks_like_generic_image_read_request(prompt_message)
        ):
            fallback_answer = self._build_image_read_fallback_answer(last_image_read_result, locale=locale)
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
            blocked_reason = blocked_reason or "required_tooling_not_used"
            if has_image_attachments and looks_like_image_capability_denial_helper(raw_text):
                notes.append("image_attachment_tooling_not_used")
            else:
                notes.append("strict_agentic_blocked_without_required_tools")
        elif collaboration_mode in {"default", "execute"} and not tool_events and self._looks_like_plan_only_response(raw_text):
            turn_status = "blocked"
            blocked_reason = blocked_reason or "plan_only_response_after_steer"
            notes.append("strict_agentic_blocked_after_steer")
        else:
            turn_status = "completed"
        revision_summary = self._build_revision_summary(
            prompt_message=prompt_message,
            raw_text=raw_text,
            activity_context=turn_activity_context,
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
            validated_next_step
            and turn_status in {"blocked", "cancelled"}
            and (
                not execution_trace
                or int((execution_trace[-1] or {}).get("step_index") or 0) != int(validated_next_step.get("step_index") or 0)
            )
        ):
            final_execution_entry = ExecutionTraceEntry(
                step_index=int(validated_next_step.get("step_index") or current_step_index),
                action_type=str(validated_next_step.get("action_type") or "inspect_context"),
                status=turn_status,
                title="Final execution state",
                tool_name=str(validated_next_step.get("tool_name") or ""),
                tool_names=[str(item) for item in list(validated_next_step.get("tool_names") or []) if str(item or "")],
                result_summary=safe_preview(raw_text, limit=240),
                observation_summary=str(blocked_reason or raw_text or ""),
                detail=str(validated_next_step.get("reason") or ""),
                payload={"validated_next_step": dict(validated_next_step)},
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
                "invalid_final_guard": dict(invalid_final_guard),
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
                "requires_tools": expects_tools,
                "runtime_contract": runtime_contract.as_payload(),
                "tool_round_limit": tool_round_limit,
                "network_mode": spec.network_mode,
                "inline_document": inline_document,
                "thread_memory": dict(context_payload.get("thread_memory") or {}),
                "recent_tasks": list(context_payload.get("recent_tasks") or []),
                "artifact_memory_preview": list(context_payload.get("artifact_memory_preview") or []),
                "compaction_status": dict(live_compaction_status),
                "answer_stream": dict(answer_stream),
                "runtime_hint": dict(runtime_hint),
                "runtime_guess": dict(runtime_hint),
                "high_level_proposal": dict(high_level_proposal),
                "model_proposal": dict(high_level_proposal),
                "validated_next_step": dict(validated_next_step),
                "validated_plan": dict(validated_next_step),
                "execution_trace": list(execution_trace),
                "proposal_diagnostics": dict(proposal_diagnostics),
                "project_contract_loaded": bool(project_contract_text),
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
                "project_root": project_root,
                "cwd": effective_cwd,
            },
            "tool_timeline": [item.model_dump() for item in tool_events],
            "trace_events": [dict(item) for item in trace_events],
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
                "compaction_status": dict(live_compaction_status),
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
            "invalid_final_guard": dict(invalid_final_guard),
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
            "runtime_hint": dict(runtime_hint),
            "runtime_guess": dict(runtime_hint),
            "high_level_proposal": dict(high_level_proposal),
            "model_proposal": dict(high_level_proposal),
            "validated_next_step": dict(validated_next_step),
            "validated_plan": dict(validated_next_step),
            "execution_trace": list(execution_trace),
            "proposal_diagnostics": dict(proposal_diagnostics),
            "activity": {
                "run_id": run_id,
                "status": turn_status,
                "started_at": trace_events[0]["timestamp"] if trace_events else 0.0,
                "finished_at": trace_events[-1]["timestamp"] if trace_events else 0.0,
                "run_duration_ms": run_duration_ms,
                "activity_summary": activity_summary,
                "trace_events": [dict(item) for item in trace_events],
            },
            "compaction_status": dict(live_compaction_status),
            "answer_stream": dict(answer_stream),
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
                "runtime_hint": dict(runtime_hint),
                "model_proposal": dict(high_level_proposal),
                "high_level_proposal": dict(high_level_proposal),
                "validated_plan": dict(validated_next_step),
                "validated_next_step": dict(validated_next_step),
                "execution_trace": list(execution_trace),
                "project_id": project_id,
                "project_root": project_root,
                "cwd": effective_cwd,
                "current_task_focus": compat_task_checkpoint_from_focus(current_task_focus),
                "task_checkpoint": compat_task_checkpoint_from_focus(current_task_focus),
            },
        }
