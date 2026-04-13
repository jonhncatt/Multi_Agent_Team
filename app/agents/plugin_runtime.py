from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.kernel.llm_router import LLMRouter
from app.models import ChatSettings, ToolEvent
from app.openai_auth import OpenAIAuthManager
from packages.office_modules.office_agent_runtime import create_office_runtime_backend

_PLUGIN_FILE_ORDER: tuple[str, ...] = (
    "router_agent",
    "coordinator_agent",
    "planner_agent",
    "researcher_agent",
    "file_reader_agent",
    "summarizer_agent",
    "fixer_agent",
    "worker_agent",
    "conflict_detector_agent",
    "reviewer_agent",
    "revision_agent",
    "structurer_agent",
)

_TOOL_PROFILE_PRESETS: dict[str, tuple[str, ...]] = {
    "none": (),
    "workspace": (
        "run_shell",
        "list_directory",
        "search_codebase",
        "copy_file",
        "extract_zip",
        "extract_msg_attachments",
    ),
    "file": (
        "read_text_file",
        "search_text_in_file",
        "multi_query_search",
        "doc_index_build",
        "read_section_by_heading",
        "table_extract",
        "fact_check_file",
    ),
    "web": (
        "search_web",
        "fetch_web",
        "download_web_file",
    ),
    "write": (
        "write_text_file",
        "append_text_file",
        "replace_in_file",
    ),
    "session": (
        "list_sessions",
        "read_session_history",
    ),
}

_PLUGIN_QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "router_agent": {
        "quality_profile": "router_gate_v2",
        "scope": "只做路由与分发，不直接执行任务。",
        "stop_rules": [
            "禁止工具调用。",
            "禁止输出思维链。",
            "禁止替代执行插件输出最终答案。",
        ],
        "response_contract": {"mode": "text", "keys": []},
        "tool_expectation": {"keywords": [], "min_tool_calls": 0, "nudge_prompt": ""},
    },
    "coordinator_agent": {
        "quality_profile": "coordination_contract_v2",
        "scope": "把任务拆成阶段、定义交接条件与回滚点。",
        "stop_rules": [
            "只输出计划与协作编排，不直接给最终答案。",
            "禁止工具调用。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["objective", "stages", "handoff", "rollback_points", "risks"],
            "max_items": 6,
        },
    },
    "planner_agent": {
        "quality_profile": "planning_contract_v2",
        "scope": "提炼目标、约束、计划与验收信号。",
        "stop_rules": [
            "只输出计划，不直接作答。",
            "禁止工具调用。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["objective", "constraints", "plan", "watchouts", "success_signals"],
            "max_items": 6,
        },
    },
    "researcher_agent": {
        "quality_profile": "evidence_first_v2",
        "scope": "联网取证、来源整理与不确定性标注。",
        "stop_rules": [
            "关键结论必须附来源线索。",
            "证据不足必须明确写出。",
            "禁止编造来源与事实。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["summary", "evidence", "sources", "open_questions", "next_steps"],
            "max_items": 8,
        },
        "tool_expectation": {
            "keywords": [
                "最新",
                "today",
                "news",
                "新闻",
                "网页",
                "web",
                "search",
                "查",
                "检索",
                "来源",
            ],
            "min_tool_calls": 1,
            "nudge_prompt": "当前任务应先联网取证。请至少调用一次允许工具（search_web/fetch_web/read_text_file）后再输出结论。",
        },
    },
    "file_reader_agent": {
        "quality_profile": "document_evidence_v2",
        "scope": "定位命中、提取证据、保留路径与章节信息。",
        "stop_rules": [
            "先定位命中再总结。",
            "输出中保留可复核线索（路径/章节/关键词）。",
            "禁止编造文档不存在内容。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["summary", "hits", "evidence", "gaps", "next_actions"],
            "max_items": 8,
        },
        "tool_expectation": {
            "keywords": [
                "文件",
                "文档",
                "附件",
                "pdf",
                "doc",
                "章节",
                "表格",
                "搜索",
                "定位",
            ],
            "min_tool_calls": 1,
            "nudge_prompt": "当前任务属于文档取证。请至少调用一次文件工具（read_text_file/search_text_in_file/read_section_by_heading/table_extract）后再输出。",
        },
    },
    "summarizer_agent": {
        "quality_profile": "high_signal_summary_v2",
        "scope": "高信息量摘要，不停留在能力确认。",
        "stop_rules": [
            "先给结论，再给关键点。",
            "禁止空泛表述。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["summary", "key_points", "action_items", "risks"],
            "max_items": 6,
        },
    },
    "fixer_agent": {
        "quality_profile": "repair_contract_v2",
        "scope": "定位根因、给最小修复方案、提供验证步骤。",
        "stop_rules": [
            "先根因后修复。",
            "必须包含验证与回滚建议。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["root_cause", "fix_plan", "patch_scope", "validation_steps", "risks"],
            "max_items": 8,
        },
        "tool_expectation": {
            "keywords": ["修复", "fix", "bug", "报错", "错误", "异常", "traceback", "失败"],
            "min_tool_calls": 1,
            "nudge_prompt": "修复任务需要先定位证据。请至少调用一次允许工具（search_codebase/read_text_file/run_shell）后再输出修复方案。",
        },
    },
    "worker_agent": {
        "quality_profile": "execution_contract_v2",
        "scope": "执行主任务并交付可复核结果。",
        "stop_rules": [
            "有证据需求时先调用工具。",
            "输出必须包含已做动作与下一步建议。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["summary", "actions_taken", "tool_findings", "deliverables", "next_steps"],
            "max_items": 10,
        },
        "tool_expectation": {
            "keywords": [
                "查",
                "search",
                "读取",
                "read",
                "运行",
                "run",
                "修复",
                "fix",
                "写入",
                "write",
                "下载",
                "download",
            ],
            "min_tool_calls": 1,
            "nudge_prompt": "该任务应先执行工具操作。请至少完成一次允许工具调用并基于结果输出。",
        },
    },
    "conflict_detector_agent": {
        "quality_profile": "consistency_guard_v2",
        "scope": "检测常识冲突、证据矛盾与高风险断言。",
        "stop_rules": [
            "只做冲突检测，不给最终业务结论。",
            "知识只用于报警，不替代证据。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["has_conflict", "confidence", "summary", "concerns", "suggested_checks"],
            "max_items": 6,
        },
    },
    "reviewer_agent": {
        "quality_profile": "review_gate_v2",
        "scope": "做最终质量审阅与风险门禁。",
        "stop_rules": [
            "verdict 仅可 pass/warn/block。",
            "需要证据时优先调用只读工具复核。",
            "不要全盘否定已确认事实。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["verdict", "confidence", "summary", "strengths", "risks", "followups"],
            "max_items": 8,
        },
        "tool_expectation": {
            "keywords": ["审核", "review", "校验", "verify", "风险", "证据", "正确性"],
            "min_tool_calls": 1,
            "nudge_prompt": "审阅任务需要独立复核。请至少调用一次允许工具后再输出 verdict。",
        },
    },
    "revision_agent": {
        "quality_profile": "revision_guard_v2",
        "scope": "基于审阅结论做最小必要修订。",
        "stop_rules": [
            "保留已确认事实。",
            "未证实信息必须标记不确定。",
            "禁止引入新事实。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["changed", "summary", "key_changes", "final_answer"],
            "max_items": 6,
        },
    },
    "structurer_agent": {
        "quality_profile": "structured_bundle_v2",
        "scope": "将内容整理成结构化交付格式。",
        "stop_rules": [
            "禁止改写事实本身。",
            "证据不足结论必须降级。",
            "禁止编造来源。",
            "禁止思维链。",
        ],
        "response_contract": {
            "mode": "json",
            "keys": ["summary", "claims", "warnings", "next_steps"],
            "max_items": 8,
        },
    },
}

_SWARM_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "swarm",
    "并行",
    "父子",
    "分支",
    "协同",
    "协作",
    "multi-agent",
    "multi agent",
)

_PLUGIN_SWARM_PRESETS: dict[str, dict[str, Any]] = {
    "router_agent": {
        "role": "root-router",
        "enabled_by_default": False,
        "max_depth": 3,
        "max_children": 4,
        "join_policy": "route_merge",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "coordinator_agent",
                "label": "Coordinator Branch",
                "objective": "组织阶段、依赖和协作顺序。",
                "required": True,
                "propagate": True,
            },
            {
                "plugin_id": "planner_agent",
                "label": "Planner Branch",
                "objective": "拆解任务，给出可执行计划和验收标准。",
                "keywords": ["计划", "plan", "步骤"],
                "propagate": True,
            },
            {
                "plugin_id": "researcher_agent",
                "label": "Research Branch",
                "objective": "补齐外部证据与事实来源。",
                "keywords": ["research", "搜索", "证据", "来源", "最新"],
                "propagate": True,
            },
            {
                "plugin_id": "worker_agent",
                "label": "Execution Branch",
                "objective": "执行主动作并返回可交付结果。",
                "keywords": ["执行", "run", "实现", "修复", "fix"],
                "propagate": True,
            },
            {
                "plugin_id": "reviewer_agent",
                "label": "Review Branch",
                "objective": "最终质量门禁与风险复核。",
                "keywords": ["审核", "review", "校验", "风险"],
                "propagate": True,
            },
        ],
    },
    "coordinator_agent": {
        "role": "supervisor",
        "enabled_by_default": False,
        "max_depth": 3,
        "max_children": 4,
        "join_policy": "stage_join",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "planner_agent",
                "label": "Planning Branch",
                "objective": "产出阶段计划、约束和交接条件。",
                "required": True,
                "propagate": True,
            },
            {
                "plugin_id": "researcher_agent",
                "label": "Evidence Branch",
                "objective": "补齐关键证据与来源清单。",
                "keywords": ["research", "调研", "证据", "来源", "外部"],
                "propagate": True,
            },
            {
                "plugin_id": "worker_agent",
                "label": "Execution Branch",
                "objective": "执行关键动作并提供落地结果。",
                "required": True,
                "propagate": True,
            },
            {
                "plugin_id": "reviewer_agent",
                "label": "Gate Branch",
                "objective": "做阶段结果审阅与风险评级。",
                "keywords": ["review", "审核", "风险"],
                "propagate": True,
            },
        ],
    },
    "planner_agent": {
        "role": "planner-parent",
        "enabled_by_default": False,
        "max_depth": 2,
        "max_children": 3,
        "join_policy": "plan_merge",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "researcher_agent",
                "label": "Research Sub-Plan",
                "objective": "为计划中的关键假设补齐证据。",
                "required": True,
                "propagate": True,
            },
            {
                "plugin_id": "file_reader_agent",
                "label": "Document Sub-Plan",
                "objective": "提取文档/附件里的约束和输入信息。",
                "keywords": ["文件", "文档", "附件", "pdf", "doc"],
                "propagate": False,
            },
            {
                "plugin_id": "worker_agent",
                "label": "Execution Sub-Plan",
                "objective": "验证计划步骤是否具备可执行性。",
                "keywords": ["实现", "执行", "run", "fix"],
                "propagate": False,
            },
        ],
    },
    "researcher_agent": {
        "role": "research-parent",
        "enabled_by_default": False,
        "max_depth": 2,
        "max_children": 3,
        "join_policy": "evidence_merge",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "file_reader_agent",
                "label": "Doc Evidence Branch",
                "objective": "在本地文档中补齐可复核证据。",
                "required": True,
                "propagate": False,
            },
            {
                "plugin_id": "conflict_detector_agent",
                "label": "Conflict Branch",
                "objective": "识别证据冲突或高风险断言。",
                "propagate": False,
            },
            {
                "plugin_id": "summarizer_agent",
                "label": "Compression Branch",
                "objective": "对证据集合做高密度压缩。",
                "propagate": False,
            },
        ],
    },
    "worker_agent": {
        "role": "executor-parent",
        "enabled_by_default": False,
        "max_depth": 2,
        "max_children": 4,
        "join_policy": "execution_merge",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "file_reader_agent",
                "label": "Read Branch",
                "objective": "补齐文件取证和上下文定位。",
                "keywords": ["文件", "文档", "read", "附件"],
                "propagate": False,
            },
            {
                "plugin_id": "fixer_agent",
                "label": "Fix Branch",
                "objective": "定位问题并给出最小修复路径。",
                "keywords": ["修复", "fix", "bug", "错误", "异常"],
                "propagate": False,
            },
            {
                "plugin_id": "reviewer_agent",
                "label": "Review Branch",
                "objective": "对执行结果进行质量复核。",
                "keywords": ["review", "审核", "校验", "风险"],
                "propagate": True,
            },
            {
                "plugin_id": "structurer_agent",
                "label": "Structure Branch",
                "objective": "把执行产物整理成结构化交付。",
                "keywords": ["结构化", "格式", "输出"],
                "propagate": False,
            },
        ],
    },
    "conflict_detector_agent": {
        "role": "consensus-parent",
        "enabled_by_default": False,
        "max_depth": 2,
        "max_children": 2,
        "join_policy": "consensus_vote",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "researcher_agent",
                "label": "Re-Check Branch",
                "objective": "复查争议点的来源证据。",
                "propagate": False,
            },
            {
                "plugin_id": "reviewer_agent",
                "label": "Risk Gate Branch",
                "objective": "对冲突结论做风险门禁评级。",
                "required": True,
                "propagate": False,
            },
        ],
    },
    "reviewer_agent": {
        "role": "review-parent",
        "enabled_by_default": False,
        "max_depth": 2,
        "max_children": 3,
        "join_policy": "review_gate",
        "failure_policy": "serial_replay",
        "children": [
            {
                "plugin_id": "conflict_detector_agent",
                "label": "Consistency Branch",
                "objective": "检查事实一致性与潜在冲突。",
                "required": True,
                "propagate": False,
            },
            {
                "plugin_id": "revision_agent",
                "label": "Revision Branch",
                "objective": "根据审阅意见生成最小修订。",
                "propagate": False,
            },
            {
                "plugin_id": "structurer_agent",
                "label": "Packaging Branch",
                "objective": "整理最终交付结构并标注风险。",
                "propagate": False,
            },
        ],
    },
}

_JSON_LIST_HINT_KEYS: set[str] = {
    "stages",
    "handoff",
    "rollback_points",
    "constraints",
    "plan",
    "watchouts",
    "success_signals",
    "evidence",
    "sources",
    "open_questions",
    "next_steps",
    "hits",
    "gaps",
    "next_actions",
    "key_points",
    "action_items",
    "risks",
    "fix_plan",
    "patch_scope",
    "validation_steps",
    "actions_taken",
    "tool_findings",
    "deliverables",
    "concerns",
    "suggested_checks",
    "strengths",
    "followups",
    "key_changes",
    "claims",
    "warnings",
}

_JSON_BOOL_HINT_KEYS: set[str] = {
    "has_conflict",
    "changed",
}

_JSON_ENUM_HINTS: dict[str, set[str]] = {
    "verdict": {"pass", "warn", "block"},
    "confidence": {"high", "medium", "low"},
}


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _split_profile_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    merged = raw.replace(",", "+")
    parts = [item.strip().lower() for item in merged.split("+")]
    return [item for item in parts if item]


def _resolve_profile_tools(profile: str) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for token in _split_profile_tokens(profile):
        preset = _TOOL_PROFILE_PRESETS.get(token, ())
        for name in preset:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
    return tuple(names)


def _as_int(value: Any, *, default: int = 0, min_value: int = 0, max_value: int = 99) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for item in keywords:
        key = str(item or "").strip().lower()
        if key and key in lowered:
            return True
    return False


@dataclass(slots=True, frozen=True)
class AgentSwarmChild:
    plugin_id: str
    label: str
    objective: str
    keywords: tuple[str, ...]
    required: bool
    propagate: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "label": self.label,
            "objective": self.objective,
            "keywords": list(self.keywords),
            "required": self.required,
            "propagate": self.propagate,
        }


@dataclass(slots=True, frozen=True)
class AgentPluginManifest:
    plugin_id: str
    title: str
    description: str
    sprite_role: str
    supports_swarm: bool
    swarm_mode: str
    capability_tags: tuple[str, ...]
    tool_profile: str
    allowed_tools: tuple[str, ...]
    max_tool_rounds: int
    system_prompt: str
    scope: str
    stop_rules: tuple[str, ...]
    quality_profile: str
    response_mode: str
    response_keys: tuple[str, ...]
    response_max_items: int
    tool_expect_keywords: tuple[str, ...]
    tool_expect_min_calls: int
    tool_expect_nudge: str
    swarm_role: str
    swarm_enabled_by_default: bool
    swarm_max_depth: int
    swarm_max_children: int
    swarm_join_policy: str
    swarm_failure_policy: str
    swarm_children: tuple[AgentSwarmChild, ...]
    source_path: str

    def to_control_panel_descriptor(self) -> dict[str, object]:
        return {
            "key": self.plugin_id,
            "title": self.title,
            "path": self.source_path,
            "exists": True,
            "sprite_role": self.sprite_role,
            "supports_swarm": self.supports_swarm,
            "swarm_mode": self.swarm_mode,
            "swarm_role": self.swarm_role,
            "swarm_enabled_by_default": self.swarm_enabled_by_default,
            "swarm_max_depth": self.swarm_max_depth,
            "swarm_max_children": self.swarm_max_children,
            "swarm_join_policy": self.swarm_join_policy,
            "swarm_failure_policy": self.swarm_failure_policy,
            "swarm_children": [item.to_payload() for item in self.swarm_children],
            "capability_tags": list(self.capability_tags),
            "summary": self.description,
            "tool_profile": self.tool_profile,
            "allowed_tools": list(self.allowed_tools),
            "max_tool_rounds": self.max_tool_rounds,
            "quality_profile": self.quality_profile,
            "response_mode": self.response_mode,
            "response_keys": list(self.response_keys),
            "response_max_items": self.response_max_items,
            "stop_rules": list(self.stop_rules),
            "scope": self.scope,
            "tool_expect_keywords": list(self.tool_expect_keywords),
            "tool_expect_min_calls": self.tool_expect_min_calls,
            "independent_runnable": True,
        }

    def to_api_payload(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "title": self.title,
            "description": self.description,
            "sprite_role": self.sprite_role,
            "supports_swarm": self.supports_swarm,
            "swarm_mode": self.swarm_mode,
            "swarm_role": self.swarm_role,
            "swarm_enabled_by_default": self.swarm_enabled_by_default,
            "swarm_max_depth": self.swarm_max_depth,
            "swarm_max_children": self.swarm_max_children,
            "swarm_join_policy": self.swarm_join_policy,
            "swarm_failure_policy": self.swarm_failure_policy,
            "swarm_children": [item.to_payload() for item in self.swarm_children],
            "capability_tags": list(self.capability_tags),
            "tool_profile": self.tool_profile,
            "allowed_tools": list(self.allowed_tools),
            "max_tool_rounds": self.max_tool_rounds,
            "quality_profile": self.quality_profile,
            "scope": self.scope,
            "stop_rules": list(self.stop_rules),
            "response_mode": self.response_mode,
            "response_keys": list(self.response_keys),
            "response_max_items": self.response_max_items,
            "tool_expect_keywords": list(self.tool_expect_keywords),
            "tool_expect_min_calls": self.tool_expect_min_calls,
            "source_path": self.source_path,
            "independent_runnable": True,
        }


class AgentPluginRuntime:
    def __init__(
        self,
        *,
        config: AppConfig,
        kernel_runtime: Any,
        manifest_dir: Path,
    ) -> None:
        self._config = config
        self._router = LLMRouter(default_agent="worker_agent")
        self._manifest_dir = manifest_dir.resolve()
        self._backend = create_office_runtime_backend(
            config,
            kernel_runtime=kernel_runtime,
        )
        self._manifests = self._load_manifests()
        self._manifest_map = {item.plugin_id: item for item in self._manifests}
        self._tool_specs_by_name = self._build_tool_spec_index()

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

    def _load_manifests(self) -> list[AgentPluginManifest]:
        manifests: list[AgentPluginManifest] = []
        if not self._manifest_dir.is_dir():
            return manifests

        available_by_stem = {
            item.stem: item
            for item in self._manifest_dir.glob("*.json")
            if item.is_file()
        }
        ordered_stems = [stem for stem in _PLUGIN_FILE_ORDER if stem in available_by_stem]
        ordered_stems.extend(sorted(stem for stem in available_by_stem.keys() if stem not in ordered_stems))

        for stem in ordered_stems:
            path = available_by_stem[stem]
            loaded = self._parse_manifest(path)
            if loaded is not None:
                manifests.append(loaded)
        return manifests

    def _parse_swarm_children(
        self,
        *,
        plugin_id: str,
        children_raw: Any,
    ) -> tuple[AgentSwarmChild, ...]:
        if not isinstance(children_raw, list):
            return ()
        out: list[AgentSwarmChild] = []
        seen: set[str] = set()
        for item in children_raw:
            if not isinstance(item, dict):
                continue
            child_plugin_id = str(item.get("plugin_id") or item.get("target") or "").strip()
            if not child_plugin_id or child_plugin_id == plugin_id:
                continue
            lowered = child_plugin_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            label = str(item.get("label") or child_plugin_id).strip() or child_plugin_id
            objective = str(item.get("objective") or item.get("instruction") or f"完成 {label} 子任务。").strip()
            if not objective:
                objective = f"完成 {label} 子任务。"
            keywords = tuple(
                _normalize_str_list(
                    item.get("keywords")
                    or item.get("when_keywords")
                    or []
                )
            )
            out.append(
                AgentSwarmChild(
                    plugin_id=child_plugin_id,
                    label=label,
                    objective=objective,
                    keywords=keywords,
                    required=_as_bool(item.get("required"), default=False),
                    propagate=_as_bool(item.get("propagate"), default=False),
                )
            )
        return tuple(out)

    def _parse_manifest(self, path: Path) -> AgentPluginManifest | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        plugin_id = str(payload.get("plugin_id") or "").strip()
        if not plugin_id:
            return None
        preset = dict(_PLUGIN_QUALITY_PRESETS.get(plugin_id) or {})
        swarm_preset = dict(_PLUGIN_SWARM_PRESETS.get(plugin_id) or {})

        title = str(payload.get("title") or plugin_id).strip() or plugin_id
        description = str(payload.get("description") or "").strip()
        sprite_role = str(payload.get("sprite_role") or plugin_id.replace("_agent", "")).strip() or "worker"

        raw_swarm = payload.get("swarm") if isinstance(payload.get("swarm"), dict) else {}
        supports_swarm = bool(payload.get("supports_swarm")) or bool(raw_swarm or swarm_preset)
        swarm_mode = str(payload.get("swarm_mode") or raw_swarm.get("mode") or ("generic-swarm" if supports_swarm else "none")).strip() or "none"
        capability_tags = tuple(_normalize_str_list(payload.get("capability_tags")))

        raw_profile = str(payload.get("tool_profile") or "none").strip().lower() or "none"
        profile_tools = list(_resolve_profile_tools(raw_profile))
        explicit_tools = _normalize_str_list(payload.get("allowed_tools"))
        allowed_tools = tuple(explicit_tools if explicit_tools else profile_tools)
        max_tool_rounds = int(payload.get("max_tool_rounds") or 0)
        if not allowed_tools:
            max_tool_rounds = 0
        max_tool_rounds = max(0, min(12, max_tool_rounds))

        system_prompt = str(payload.get("system_prompt") or "").strip()
        if not system_prompt:
            system_prompt = (
                f"你是 {title}。"
                "请严格围绕用户问题给出可执行结论。"
                "不要输出思维链。"
            )

        scope = str(payload.get("scope") or preset.get("scope") or description or title).strip()
        stop_rules = tuple(_normalize_str_list(payload.get("stop_rules") or preset.get("stop_rules") or []))
        quality_profile = str(payload.get("quality_profile") or preset.get("quality_profile") or "legacy_plus").strip() or "legacy_plus"

        preset_contract = preset.get("response_contract") if isinstance(preset.get("response_contract"), dict) else {}
        raw_contract = payload.get("response_contract") if isinstance(payload.get("response_contract"), dict) else {}
        response_mode = str(
            raw_contract.get("mode")
            or payload.get("response_mode")
            or preset_contract.get("mode")
            or "text"
        ).strip().lower() or "text"
        if response_mode not in {"text", "json"}:
            response_mode = "text"

        response_keys = _normalize_str_list(
            raw_contract.get("keys")
            or payload.get("response_keys")
            or preset_contract.get("keys")
            or []
        )
        if response_mode == "json" and not response_keys:
            response_keys = ["summary"]
        response_max_items = _as_int(
            raw_contract.get("max_items")
            if isinstance(raw_contract, dict)
            else None,
            default=_as_int(
                payload.get("response_max_items"),
                default=_as_int(preset_contract.get("max_items"), default=6, min_value=1, max_value=20),
                min_value=1,
                max_value=20,
            ),
            min_value=1,
            max_value=20,
        )

        preset_expect = preset.get("tool_expectation") if isinstance(preset.get("tool_expectation"), dict) else {}
        raw_expect = payload.get("tool_expectation") if isinstance(payload.get("tool_expectation"), dict) else {}
        tool_expect_keywords = tuple(
            _normalize_str_list(
                raw_expect.get("keywords")
                or payload.get("tool_expect_keywords")
                or preset_expect.get("keywords")
                or []
            )
        )
        tool_expect_min_calls = _as_int(
            raw_expect.get("min_tool_calls")
            if isinstance(raw_expect, dict)
            else None,
            default=_as_int(
                payload.get("tool_expect_min_calls"),
                default=_as_int(preset_expect.get("min_tool_calls"), default=0, min_value=0, max_value=6),
                min_value=0,
                max_value=6,
            ),
            min_value=0,
            max_value=6,
        )
        if not allowed_tools:
            tool_expect_min_calls = 0
        tool_expect_nudge = str(
            raw_expect.get("nudge_prompt")
            or payload.get("tool_expect_nudge")
            or preset_expect.get("nudge_prompt")
            or ""
        ).strip()

        swarm_role = str(
            raw_swarm.get("role")
            or payload.get("swarm_role")
            or swarm_preset.get("role")
            or ("leaf" if not supports_swarm else "parent")
        ).strip() or "leaf"
        swarm_enabled_by_default = _as_bool(
            raw_swarm.get("enabled_by_default")
            if isinstance(raw_swarm, dict)
            else None,
            default=_as_bool(payload.get("swarm_enabled_by_default"), default=_as_bool(swarm_preset.get("enabled_by_default"), default=False)),
        )
        swarm_max_depth = _as_int(
            raw_swarm.get("max_depth")
            if isinstance(raw_swarm, dict)
            else None,
            default=_as_int(payload.get("swarm_max_depth"), default=_as_int(swarm_preset.get("max_depth"), default=2, min_value=1, max_value=4), min_value=1, max_value=4),
            min_value=1,
            max_value=4,
        )
        swarm_max_children = _as_int(
            raw_swarm.get("max_children")
            if isinstance(raw_swarm, dict)
            else None,
            default=_as_int(payload.get("swarm_max_children"), default=_as_int(swarm_preset.get("max_children"), default=3, min_value=1, max_value=6), min_value=1, max_value=6),
            min_value=1,
            max_value=6,
        )
        swarm_join_policy = str(
            raw_swarm.get("join_policy")
            or payload.get("swarm_join_policy")
            or swarm_preset.get("join_policy")
            or "merge"
        ).strip() or "merge"
        swarm_failure_policy = str(
            raw_swarm.get("failure_policy")
            or payload.get("swarm_failure_policy")
            or swarm_preset.get("failure_policy")
            or "serial_replay"
        ).strip() or "serial_replay"
        swarm_children = self._parse_swarm_children(
            plugin_id=plugin_id,
            children_raw=(
                raw_swarm.get("children")
                if isinstance(raw_swarm, dict)
                else None
            )
            or payload.get("swarm_children")
            or swarm_preset.get("children")
            or [],
        )
        if not supports_swarm:
            swarm_children = ()
            swarm_mode = "none"
            swarm_role = "leaf"
            swarm_enabled_by_default = False
            swarm_max_depth = 1
            swarm_max_children = 1

        return AgentPluginManifest(
            plugin_id=plugin_id,
            title=title,
            description=description,
            sprite_role=sprite_role,
            supports_swarm=supports_swarm,
            swarm_mode=swarm_mode,
            capability_tags=capability_tags,
            tool_profile=raw_profile,
            allowed_tools=allowed_tools,
            max_tool_rounds=max_tool_rounds,
            system_prompt=system_prompt,
            scope=scope,
            stop_rules=stop_rules,
            quality_profile=quality_profile,
            response_mode=response_mode,
            response_keys=tuple(response_keys),
            response_max_items=response_max_items,
            tool_expect_keywords=tool_expect_keywords,
            tool_expect_min_calls=tool_expect_min_calls,
            tool_expect_nudge=tool_expect_nudge,
            swarm_role=swarm_role,
            swarm_enabled_by_default=swarm_enabled_by_default,
            swarm_max_depth=swarm_max_depth,
            swarm_max_children=swarm_max_children,
            swarm_join_policy=swarm_join_policy,
            swarm_failure_policy=swarm_failure_policy,
            swarm_children=swarm_children,
            source_path=str(path.relative_to(self._manifest_dir.parent)),
        )

    def _render_runtime_system_prompt(self, manifest: AgentPluginManifest) -> str:
        parts: list[str] = [manifest.system_prompt]
        if manifest.scope:
            parts.append(f"工作范围: {manifest.scope}")
        if manifest.stop_rules:
            parts.append("硬性约束:\n" + "\n".join(f"- {item}" for item in manifest.stop_rules))
        parts.append(f"质量档位: {manifest.quality_profile}")
        if manifest.response_mode == "json" and manifest.response_keys:
            parts.append(
                "输出契约:\n"
                "- 只返回 JSON 对象。\n"
                f"- 固定字段: {', '.join(manifest.response_keys)}。\n"
                "- 字段不可省略，缺失时返回空值。"
            )
        if manifest.tool_expect_min_calls > 0 and manifest.tool_expect_keywords:
            parts.append(
                "工具策略:\n"
                f"- 当用户请求包含关键词 {', '.join(manifest.tool_expect_keywords[:8])} 时，"
                f"至少调用 {manifest.tool_expect_min_calls} 次允许工具后再下结论。"
            )
        if manifest.supports_swarm:
            parts.append(
                "Swarm 协作策略:\n"
                f"- 当前模式: {manifest.swarm_mode}。\n"
                f"- 角色: {manifest.swarm_role}。\n"
                f"- 分支上限: depth={manifest.swarm_max_depth}, children={manifest.swarm_max_children}。"
            )
        parts.append("通用要求: 禁止输出思维链；禁止编造未验证事实；证据不足时必须明确标注。")
        return "\n\n".join(item for item in parts if str(item).strip())

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            candidate = raw[start : end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
        return None

    def _default_value_for_key(self, key: str) -> Any:
        normalized = str(key or "").strip().lower()
        if normalized in _JSON_BOOL_HINT_KEYS:
            return False
        if normalized in _JSON_LIST_HINT_KEYS or normalized.endswith("s"):
            return []
        if normalized in _JSON_ENUM_HINTS:
            if normalized == "verdict":
                return "warn"
            return "medium"
        return ""

    def _normalize_contract_value(self, key: str, value: Any, *, max_items: int) -> Any:
        normalized = str(key or "").strip().lower()
        if normalized in _JSON_BOOL_HINT_KEYS:
            return _as_bool(value, default=False)

        if normalized in _JSON_ENUM_HINTS:
            allowed = _JSON_ENUM_HINTS[normalized]
            text = str(value or "").strip().lower()
            if text in allowed:
                return text
            if normalized == "verdict":
                return "warn"
            return "medium"

        if normalized in _JSON_LIST_HINT_KEYS or normalized.endswith("s"):
            raw_items = value if isinstance(value, list) else [value]
            out: list[str] = []
            for raw in raw_items:
                text = str(raw or "").strip()
                if not text:
                    continue
                out.append(text)
                if len(out) >= max_items:
                    break
            return out

        if isinstance(value, (dict, list)):
            return value
        return str(value or "").strip()

    def _coerce_response_contract(
        self,
        *,
        manifest: AgentPluginManifest,
        text: str,
    ) -> tuple[str, list[str]]:
        notes: list[str] = []
        raw_text = str(text or "").strip()
        if manifest.response_mode != "json":
            return raw_text or "(empty response)", notes

        parsed = self._extract_json_object(raw_text)
        if parsed is None:
            parsed = {}
            notes.append("response_contract_json_fallback")
            for key in manifest.response_keys:
                parsed[key] = self._default_value_for_key(key)
            primary_key = manifest.response_keys[0] if manifest.response_keys else "summary"
            parsed[primary_key] = raw_text or "(empty response)"

        for key in manifest.response_keys:
            if key not in parsed:
                parsed[key] = self._default_value_for_key(key)
                notes.append(f"response_contract_missing_key:{key}")
            parsed[key] = self._normalize_contract_value(
                key,
                parsed.get(key),
                max_items=manifest.response_max_items,
            )

        return json.dumps(parsed, ensure_ascii=False, indent=2), notes

    def _quality_audit_notes(
        self,
        *,
        manifest: AgentPluginManifest,
        message: str,
        text: str,
        tool_events: list[ToolEvent],
    ) -> list[str]:
        notes: list[str] = []
        lowered = str(text or "").lower()
        if "思维链" in lowered or "chain-of-thought" in lowered:
            notes.append("quality_warning:chain_of_thought_leak")

        should_expect_tooling = (
            manifest.tool_expect_min_calls > 0
            and len(manifest.allowed_tools) > 0
            and _contains_any(str(message or ""), manifest.tool_expect_keywords)
        )
        if should_expect_tooling and len(tool_events) < manifest.tool_expect_min_calls:
            notes.append(
                f"quality_warning:tool_evidence_insufficient(min={manifest.tool_expect_min_calls},actual={len(tool_events)})"
            )
        return notes

    def _default_tooling_nudge(self, manifest: AgentPluginManifest) -> str:
        if manifest.tool_expect_nudge:
            return manifest.tool_expect_nudge
        names = ", ".join(list(manifest.allowed_tools)[:4]) or "allowed tools"
        return (
            "当前任务需要先进行工具取证。"
            f"请先调用至少一项允许工具（例如: {names}），再给出结论。"
        )

    def _dedup_notes(self, notes: list[str]) -> list[str]:
        deduped: list[str] = []
        seen_notes: set[str] = set()
        for item in notes:
            text_note = str(item or "").strip()
            if not text_note:
                continue
            if text_note in seen_notes:
                continue
            seen_notes.add(text_note)
            deduped.append(text_note)
        return deduped

    def _merge_usage_totals(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = dict(left or {})
        right_payload = dict(right or {})
        for key in ("input_tokens", "output_tokens", "total_tokens", "llm_calls"):
            merged[key] = int(merged.get(key, 0) or 0) + int(right_payload.get(key, 0) or 0)
        merged["estimated_cost_usd"] = float(merged.get("estimated_cost_usd", 0.0) or 0.0) + float(
            right_payload.get("estimated_cost_usd", 0.0) or 0.0
        )
        if "pricing_known" in merged or "pricing_known" in right_payload:
            merged["pricing_known"] = bool(merged.get("pricing_known")) or bool(right_payload.get("pricing_known"))
        for key in ("pricing_model", "input_price_per_1m", "output_price_per_1m"):
            if merged.get(key) in {"", None} and right_payload.get(key) not in {"", None}:
                merged[key] = right_payload.get(key)
        return merged

    def _tool_events_for_module(
        self,
        *,
        module_id: str,
        module_title: str,
        events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for raw in list(events or []):
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item["module_id"] = str(item.get("module_id") or module_id)
            item["module_title"] = str(item.get("module_title") or module_title)
            item["module_group"] = str(item.get("module_group") or "agent_plugin")
            out.append(item)
        return out

    def _safe_preview(self, text: Any, *, limit: int = 260) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        compact = " ".join(raw.split())
        if len(compact) <= limit:
            return compact
        return compact[: max(12, limit - 3)] + "..."

    def _resolve_swarm_run_options(
        self,
        *,
        manifest: AgentPluginManifest,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raw_swarm = context.get("swarm") if isinstance(context.get("swarm"), dict) else {}
        raw_inputs = context.get("swarm_inputs")
        has_legacy_swarm_inputs = isinstance(raw_inputs, list) and len(raw_inputs) >= 2
        trigger_by_message = _contains_any(str(message or ""), _SWARM_TRIGGER_KEYWORDS)
        default_enabled = manifest.supports_swarm and (
            manifest.swarm_enabled_by_default or has_legacy_swarm_inputs or trigger_by_message
        )
        enabled = _as_bool(raw_swarm.get("enabled"), default=default_enabled)
        if not manifest.supports_swarm:
            enabled = False

        max_depth = _as_int(
            raw_swarm.get("max_depth"),
            default=manifest.swarm_max_depth,
            min_value=1,
            max_value=4,
        )
        max_children = _as_int(
            raw_swarm.get("max_children"),
            default=manifest.swarm_max_children,
            min_value=1,
            max_value=6,
        )
        return {
            "enabled": enabled,
            "max_depth": max_depth,
            "max_children": max_children,
            "join_policy": str(raw_swarm.get("join_policy") or manifest.swarm_join_policy or "merge").strip() or "merge",
            "failure_policy": str(raw_swarm.get("failure_policy") or manifest.swarm_failure_policy or "serial_replay").strip() or "serial_replay",
            "expand_children": _as_bool(raw_swarm.get("expand_children"), default=True),
            "force_all_children": _as_bool(raw_swarm.get("force_all_children"), default=False),
            "allow_serial_replay": _as_bool(raw_swarm.get("allow_serial_replay"), default=True),
        }

    def _select_swarm_children(
        self,
        *,
        manifest: AgentPluginManifest,
        message: str,
        ancestry: tuple[str, ...],
        max_children: int,
        force_all_children: bool,
    ) -> list[AgentSwarmChild]:
        available = [
            item
            for item in manifest.swarm_children
            if item.plugin_id not in ancestry and item.plugin_id in self._manifest_map
        ]
        if not available:
            return []
        if force_all_children:
            return available[:max_children]

        selected: list[AgentSwarmChild] = []
        selected_ids: set[str] = set()

        for item in available:
            if not item.required:
                continue
            selected.append(item)
            selected_ids.add(item.plugin_id)
            if len(selected) >= max_children:
                return selected

        for item in available:
            if item.plugin_id in selected_ids:
                continue
            if item.keywords and _contains_any(message, item.keywords):
                selected.append(item)
                selected_ids.add(item.plugin_id)
                if len(selected) >= max_children:
                    return selected

        if not selected:
            return available[:max_children]

        for item in available:
            if len(selected) >= max_children:
                break
            if item.plugin_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item.plugin_id)
        return selected

    def _compose_swarm_child_message(
        self,
        *,
        parent_manifest: AgentPluginManifest,
        child_rule: AgentSwarmChild,
        root_message: str,
        parent_text: str,
    ) -> str:
        lines: list[str] = [
            f"swarm_parent_plugin: {parent_manifest.plugin_id}",
            f"swarm_branch_label: {child_rule.label}",
            f"swarm_branch_objective: {child_rule.objective}",
            "",
            "root_user_message:",
            str(root_message or "").strip(),
        ]
        parent_preview = self._safe_preview(parent_text, limit=1200)
        if parent_preview:
            lines.extend(
                [
                    "",
                    "parent_output_preview:",
                    parent_preview,
                ]
            )
        return "\n".join(lines).strip()

    def _run_plugin_once(
        self,
        *,
        manifest: AgentPluginManifest,
        message: str,
        settings: ChatSettings,
        context: dict[str, Any] | None = None,
        max_tool_rounds: int | None = None,
    ) -> dict[str, Any]:
        prompt_message = str(message or "").strip()
        if not prompt_message:
            raise ValueError("message cannot be empty")

        if manifest.plugin_id == "router_agent":
            decision = self._router.route(
                prompt_message,
                candidate_agents=[item.plugin_id for item in self._manifests],
                context=context or {},
            )
            return {
                "ok": True,
                "plugin_id": manifest.plugin_id,
                "text": (
                    f"route={decision.target_agent}\n"
                    f"reason={decision.reason}\n"
                    f"confidence={decision.confidence:.2f}"
                ),
                "effective_model": "rule_router",
                "tool_events": [],
                "token_usage": self._backend._empty_usage(),
                "notes": [f"quality_profile:{manifest.quality_profile}"],
                "decision": {
                    "target_agent": decision.target_agent,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "metadata": dict(decision.metadata or {}),
                },
            }

        resolved = OpenAIAuthManager(self._config).auth_summary()
        if not bool(resolved.get("available")):
            raise RuntimeError(str(resolved.get("reason") or "LLM credentials are required"))

        requested_model = str(settings.model or self._config.default_model).strip() or self._config.default_model
        human_payload = "\n".join(
            [
                "user_message:",
                prompt_message,
                "",
                "runtime_context_json:",
                json.dumps(context or {}, ensure_ascii=False),
            ]
        )
        messages: list[Any] = [
            self._backend._SystemMessage(content=self._render_runtime_system_prompt(manifest)),
            self._backend._HumanMessage(content=human_payload),
        ]

        selected_tools = list(manifest.allowed_tools)
        if not bool(settings.enable_tools):
            selected_tools = []
        tool_round_limit = manifest.max_tool_rounds if max_tool_rounds is None else int(max_tool_rounds)
        tool_round_limit = max(0, min(12, tool_round_limit))
        if not selected_tools:
            tool_round_limit = 0

        expects_tooling = (
            bool(selected_tools)
            and manifest.tool_expect_min_calls > 0
            and _contains_any(prompt_message, manifest.tool_expect_keywords)
        )

        usage_total = self._backend._empty_usage()
        notes: list[str] = [f"quality_profile:{manifest.quality_profile}"]
        tool_events: list[ToolEvent] = []

        ai_msg, runner, effective_model, invoke_notes = self._backend._invoke_chat_with_runner(
            messages=messages,
            model=requested_model,
            max_output_tokens=int(settings.max_output_tokens),
            enable_tools=bool(selected_tools),
            tool_names=selected_tools if selected_tools else None,
        )
        notes.extend(invoke_notes)
        usage_total = self._backend._merge_usage(usage_total, self._backend._extract_usage_from_message(ai_msg))

        tooling_nudge_budget = 1 if expects_tooling and tool_round_limit > 0 else 0

        for round_idx in range(tool_round_limit):
            tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
            if not tool_calls:
                if tooling_nudge_budget > 0 and len(tool_events) < manifest.tool_expect_min_calls:
                    tooling_nudge_budget -= 1
                    messages.append(ai_msg)
                    messages.append(self._backend._SystemMessage(content=self._default_tooling_nudge(manifest)))
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
                args = call.get("args")
                if not isinstance(args, dict):
                    args = {}
                if name and name in selected_tools:
                    result = self._backend.tools.execute(name, args)
                else:
                    result = {
                        "ok": False,
                        "error": f"Tool not allowed for plugin {manifest.plugin_id}: {name or '(empty)'}",
                        "allowed_tools": selected_tools,
                    }
                result_json = json.dumps(result, ensure_ascii=False)
                tool_events.append(
                    ToolEvent(
                        name=name or "(unknown)",
                        input=args,
                        output_preview=self._backend._shorten(result_json, 1000),
                    )
                )
                messages.append(
                    self._backend._ToolMessage(
                        content=self._backend._shorten(result_json, 60000),
                        tool_call_id=str(call.get("id") or f"{manifest.plugin_id}_{round_idx}_{call_idx}"),
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

        if expects_tooling and len(tool_events) < manifest.tool_expect_min_calls:
            notes.append(
                f"tool_expectation_not_met(min={manifest.tool_expect_min_calls},actual={len(tool_events)})"
            )

        raw_text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
        if not raw_text:
            raw_text = "(empty response)"

        text, contract_notes = self._coerce_response_contract(
            manifest=manifest,
            text=raw_text,
        )
        notes.extend(contract_notes)
        notes.extend(
            self._quality_audit_notes(
                manifest=manifest,
                message=prompt_message,
                text=text,
                tool_events=tool_events,
            )
        )

        return {
            "ok": True,
            "plugin_id": manifest.plugin_id,
            "text": text,
            "effective_model": effective_model or requested_model,
            "tool_events": [item.model_dump() for item in tool_events],
            "token_usage": usage_total,
            "notes": self._dedup_notes(notes),
            "decision": {},
        }

    def _run_swarm_node(
        self,
        *,
        manifest: AgentPluginManifest,
        message: str,
        root_message: str,
        settings: ChatSettings,
        context: dict[str, Any],
        max_tool_rounds: int | None,
        depth: int,
        ancestry: tuple[str, ...],
        branch_label: str,
        parent_plugin_id: str,
        allow_expand: bool,
        options: dict[str, Any],
        collector: list[dict[str, Any]],
    ) -> dict[str, Any]:
        run_context = dict(context or {})
        swarm_context = run_context.get("swarm") if isinstance(run_context.get("swarm"), dict) else {}
        swarm_context = dict(swarm_context or {})
        swarm_context.update(
            {
                "enabled": False,
                "depth": depth,
                "parent_plugin": parent_plugin_id,
                "branch_label": branch_label,
                "ancestry": list(ancestry),
            }
        )
        run_context["swarm"] = swarm_context

        degraded = False
        run_result: dict[str, Any]
        try:
            run_result = self._run_plugin_once(
                manifest=manifest,
                message=message,
                settings=settings,
                context=run_context,
                max_tool_rounds=max_tool_rounds,
            )
        except Exception as exc:
            run_result = {
                "ok": False,
                "plugin_id": manifest.plugin_id,
                "text": "",
                "effective_model": "",
                "tool_events": [],
                "token_usage": self._backend._empty_usage(),
                "notes": [f"plugin_run_failed:{exc}"],
                "decision": {},
                "error": str(exc),
            }

        if (
            not bool(run_result.get("ok"))
            and options.get("allow_serial_replay")
            and options.get("failure_policy") == "serial_replay"
        ):
            replay_context = dict(run_context)
            replay_swarm = replay_context.get("swarm") if isinstance(replay_context.get("swarm"), dict) else {}
            replay_swarm = dict(replay_swarm or {})
            replay_swarm["serial_replay"] = True
            replay_context["swarm"] = replay_swarm
            try:
                replay_result = self._run_plugin_once(
                    manifest=manifest,
                    message=message,
                    settings=settings,
                    context=replay_context,
                    max_tool_rounds=max_tool_rounds,
                )
                if bool(replay_result.get("ok")):
                    replay_notes = list(replay_result.get("notes") or [])
                    replay_notes.append("swarm_serial_replay_recovered")
                    replay_result["notes"] = self._dedup_notes(replay_notes)
                    run_result = replay_result
                    degraded = True
                else:
                    fail_notes = list(run_result.get("notes") or [])
                    fail_notes.append("swarm_serial_replay_failed")
                    run_result["notes"] = self._dedup_notes(fail_notes)
            except Exception as replay_exc:
                fail_notes = list(run_result.get("notes") or [])
                fail_notes.append(f"swarm_serial_replay_failed:{replay_exc}")
                run_result["notes"] = self._dedup_notes(fail_notes)

        children_nodes: list[dict[str, Any]] = []
        can_expand = (
            allow_expand
            and options.get("expand_children")
            and manifest.supports_swarm
            and bool(manifest.swarm_children)
            and depth < int(options.get("max_depth") or 1)
        )
        if can_expand:
            child_rules = self._select_swarm_children(
                manifest=manifest,
                message=message,
                ancestry=ancestry,
                max_children=int(options.get("max_children") or 1),
                force_all_children=bool(options.get("force_all_children")),
            )
            for child_rule in child_rules:
                child_manifest = self._manifest_map.get(child_rule.plugin_id)
                if child_manifest is None:
                    children_nodes.append(
                        {
                            "plugin_id": child_rule.plugin_id,
                            "title": child_rule.label,
                            "depth": depth + 1,
                            "branch_label": child_rule.label,
                            "parent_plugin_id": manifest.plugin_id,
                            "ok": False,
                            "effective_model": "",
                            "text_preview": "missing manifest",
                            "tool_event_count": 0,
                            "token_usage": self._backend._empty_usage(),
                            "notes": [f"missing_manifest:{child_rule.plugin_id}"],
                            "children": [],
                            "degraded": False,
                            "swarm_mode": "none",
                            "swarm_role": "leaf",
                        }
                    )
                    continue
                child_message = self._compose_swarm_child_message(
                    parent_manifest=manifest,
                    child_rule=child_rule,
                    root_message=root_message,
                    parent_text=str(run_result.get("text") or ""),
                )
                child_context = dict(run_context)
                child_context.update(
                    {
                        "swarm_parent_output": str(run_result.get("text") or ""),
                        "swarm_parent_plugin": manifest.plugin_id,
                        "swarm_branch_objective": child_rule.objective,
                    }
                )
                child_node = self._run_swarm_node(
                    manifest=child_manifest,
                    message=child_message,
                    root_message=root_message,
                    settings=settings,
                    context=child_context,
                    max_tool_rounds=max_tool_rounds,
                    depth=depth + 1,
                    ancestry=ancestry + (child_manifest.plugin_id,),
                    branch_label=child_rule.label,
                    parent_plugin_id=manifest.plugin_id,
                    allow_expand=child_rule.propagate,
                    options=options,
                    collector=collector,
                )
                children_nodes.append(child_node)

        node = {
            "plugin_id": manifest.plugin_id,
            "title": manifest.title,
            "depth": depth,
            "branch_label": branch_label,
            "parent_plugin_id": parent_plugin_id,
            "ok": bool(run_result.get("ok")),
            "effective_model": str(run_result.get("effective_model") or ""),
            "text_preview": self._safe_preview(run_result.get("text"), limit=320),
            "tool_event_count": len(run_result.get("tool_events") or []),
            "token_usage": dict(run_result.get("token_usage") or {}),
            "notes": list(run_result.get("notes") or []),
            "children": children_nodes,
            "degraded": degraded,
            "swarm_mode": manifest.swarm_mode,
            "swarm_role": manifest.swarm_role,
        }
        collector.append(
            {
                "plugin_id": manifest.plugin_id,
                "title": manifest.title,
                "depth": depth,
                "branch_label": branch_label,
                "parent_plugin_id": parent_plugin_id,
                "degraded": degraded,
                "result": run_result,
                "swarm_mode": manifest.swarm_mode,
                "swarm_role": manifest.swarm_role,
            }
        )
        return node

    def _summarize_swarm_tree(
        self,
        *,
        root_manifest: AgentPluginManifest,
        root_result: dict[str, Any],
        root_node: dict[str, Any],
        options: dict[str, Any],
        collector: list[dict[str, Any]],
    ) -> dict[str, Any]:
        usage_total = self._backend._empty_usage()
        aggregated_tool_events: list[dict[str, Any]] = []
        notes: list[str] = []
        highlights: list[str] = []
        failed_count = 0
        degraded_count = 0

        for item in collector:
            result = dict(item.get("result") or {})
            usage_total = self._merge_usage_totals(usage_total, dict(result.get("token_usage") or {}))
            aggregated_tool_events.extend(
                self._tool_events_for_module(
                    module_id=str(item.get("plugin_id") or ""),
                    module_title=str(item.get("title") or ""),
                    events=list(result.get("tool_events") or []),
                )
            )
            item_notes = [str(note or "").strip() for note in list(result.get("notes") or []) if str(note or "").strip()]
            if str(item.get("plugin_id") or "") == root_manifest.plugin_id:
                notes.extend(item_notes)
            else:
                notes.extend([f"{item.get('plugin_id')}:{note}" for note in item_notes])
            if not bool(result.get("ok")):
                failed_count += 1
            if bool(item.get("degraded")):
                degraded_count += 1
            highlights.append(
                f"d{int(item.get('depth') or 0)} · {item.get('plugin_id')} · {self._safe_preview(result.get('text'), limit=120) or '(empty)'}"
            )

        notes.extend(
            [
                f"swarm_enabled:{root_manifest.plugin_id}",
                f"swarm_join_policy:{options.get('join_policy')}",
                f"swarm_failure_policy:{options.get('failure_policy')}",
                f"swarm_nodes:{len(collector)}",
                f"swarm_branches:{max(0, len(collector) - 1)}",
            ]
        )
        if failed_count:
            notes.append(f"swarm_failed_nodes:{failed_count}")
        if degraded_count:
            notes.append(f"swarm_degraded_nodes:{degraded_count}")

        decision_payload = dict(root_result.get("decision") or {})
        decision_payload["swarm"] = {
            "enabled": True,
            "root_plugin": root_manifest.plugin_id,
            "swarm_mode": root_manifest.swarm_mode,
            "swarm_role": root_manifest.swarm_role,
            "join_policy": options.get("join_policy"),
            "failure_policy": options.get("failure_policy"),
            "max_depth": int(options.get("max_depth") or 1),
            "max_children": int(options.get("max_children") or 1),
            "node_count": len(collector),
            "branch_count": max(0, len(collector) - 1),
            "failed_node_count": failed_count,
            "degraded_node_count": degraded_count,
            "tree": root_node,
            "highlights": highlights[:24],
        }

        text = str(root_result.get("text") or "").strip()
        if not text:
            text = (
                f"swarm root={root_manifest.plugin_id} "
                f"nodes={len(collector)} "
                f"failed={failed_count} "
                f"degraded={degraded_count}"
            )

        return {
            "ok": bool(root_result.get("ok")),
            "plugin_id": root_manifest.plugin_id,
            "text": text,
            "effective_model": str(root_result.get("effective_model") or "swarm"),
            "tool_events": aggregated_tool_events,
            "token_usage": usage_total,
            "notes": self._dedup_notes(notes),
            "decision": decision_payload,
        }

    def list_manifests(self) -> list[AgentPluginManifest]:
        return list(self._manifests)

    def list_api_payload(self) -> list[dict[str, object]]:
        return [item.to_api_payload() for item in self._manifests]

    def tool_model_payload(self) -> dict[str, object]:
        profile_map = {
            key: list(value)
            for key, value in _TOOL_PROFILE_PRESETS.items()
        }
        tools: list[dict[str, object]] = []
        for name in sorted(self._tool_specs_by_name.keys()):
            spec = self._tool_specs_by_name.get(name) or {}
            tools.append(
                {
                    "name": name,
                    "description": str(spec.get("description") or "").strip(),
                    "parameters": dict(spec.get("parameters") or {}),
                }
            )
        quality_presets = {
            key: {
                "quality_profile": str((payload or {}).get("quality_profile") or ""),
                "scope": str((payload or {}).get("scope") or ""),
                "response_contract": dict((payload or {}).get("response_contract") or {}),
                "tool_expectation": dict((payload or {}).get("tool_expectation") or {}),
            }
            for key, payload in _PLUGIN_QUALITY_PRESETS.items()
        }
        swarm_presets = {}
        for key, payload in _PLUGIN_SWARM_PRESETS.items():
            data = dict(payload or {})
            swarm_presets[key] = {
                "role": str(data.get("role") or ""),
                "enabled_by_default": _as_bool(data.get("enabled_by_default"), default=False),
                "max_depth": _as_int(data.get("max_depth"), default=2, min_value=1, max_value=4),
                "max_children": _as_int(data.get("max_children"), default=3, min_value=1, max_value=6),
                "join_policy": str(data.get("join_policy") or ""),
                "failure_policy": str(data.get("failure_policy") or ""),
                "children": list(data.get("children") or []),
            }
        return {
            "profiles": profile_map,
            "tools": tools,
            "quality_presets": quality_presets,
            "swarm_presets": swarm_presets,
        }

    def control_panel_plugin_descriptors(self, slot_count: int = 12) -> list[dict[str, object]]:
        active = [item.to_control_panel_descriptor() for item in self._manifests[:slot_count]]
        while len(active) < slot_count:
            slot = str(len(active) + 1).zfill(2)
            active.append(
                {
                    "key": f"llm_module_{slot}",
                    "title": f"LLM 模块 {slot}",
                    "path": "",
                    "exists": False,
                    "sprite_role": "worker",
                    "supports_swarm": False,
                    "swarm_mode": "none",
                    "swarm_role": "leaf",
                    "swarm_enabled_by_default": False,
                    "swarm_max_depth": 1,
                    "swarm_max_children": 1,
                    "swarm_join_policy": "none",
                    "swarm_failure_policy": "none",
                    "swarm_children": [],
                    "capability_tags": [],
                    "summary": "插件未配置",
                    "tool_profile": "none",
                    "allowed_tools": [],
                    "max_tool_rounds": 0,
                    "quality_profile": "unconfigured",
                    "response_mode": "text",
                    "response_keys": [],
                    "response_max_items": 0,
                    "stop_rules": [],
                    "scope": "",
                    "tool_expect_keywords": [],
                    "tool_expect_min_calls": 0,
                    "independent_runnable": False,
                }
            )
        return active

    def run_plugin(
        self,
        *,
        plugin_id: str,
        message: str,
        settings: ChatSettings,
        context: dict[str, Any] | None = None,
        max_tool_rounds: int | None = None,
    ) -> dict[str, Any]:
        manifest = self._manifest_map.get(str(plugin_id or "").strip())
        if manifest is None:
            raise ValueError(f"Unknown plugin_id: {plugin_id}")
        prompt_message = str(message or "").strip()
        if not prompt_message:
            raise ValueError("message cannot be empty")
        context_payload = dict(context or {})

        swarm_options = self._resolve_swarm_run_options(
            manifest=manifest,
            message=prompt_message,
            context=context_payload,
        )
        if bool(swarm_options.get("enabled")) and manifest.supports_swarm and manifest.swarm_children:
            collector: list[dict[str, Any]] = []
            root_node = self._run_swarm_node(
                manifest=manifest,
                message=prompt_message,
                root_message=prompt_message,
                settings=settings,
                context=context_payload,
                max_tool_rounds=max_tool_rounds,
                depth=0,
                ancestry=(manifest.plugin_id,),
                branch_label="root",
                parent_plugin_id="",
                allow_expand=True,
                options=swarm_options,
                collector=collector,
            )
            root_result = dict(collector[-1].get("result") or {}) if collector else self._run_plugin_once(
                manifest=manifest,
                message=prompt_message,
                settings=settings,
                context=context_payload,
                max_tool_rounds=max_tool_rounds,
            )
            return self._summarize_swarm_tree(
                root_manifest=manifest,
                root_result=root_result,
                root_node=root_node,
                options=swarm_options,
                collector=collector,
            )

        return self._run_plugin_once(
            manifest=manifest,
            message=prompt_message,
            settings=settings,
            context=context_payload,
            max_tool_rounds=max_tool_rounds,
        )
