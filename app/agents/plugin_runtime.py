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
            "capability_tags": list(self.capability_tags),
            "summary": self.description,
            "tool_profile": self.tool_profile,
            "allowed_tools": list(self.allowed_tools),
            "max_tool_rounds": self.max_tool_rounds,
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
            "capability_tags": list(self.capability_tags),
            "tool_profile": self.tool_profile,
            "allowed_tools": list(self.allowed_tools),
            "max_tool_rounds": self.max_tool_rounds,
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
        title = str(payload.get("title") or plugin_id).strip() or plugin_id
        description = str(payload.get("description") or "").strip()
        sprite_role = str(payload.get("sprite_role") or plugin_id.replace("_agent", "")).strip() or "worker"
        supports_swarm = bool(payload.get("supports_swarm"))
        swarm_mode = str(payload.get("swarm_mode") or ("generic-swarm" if supports_swarm else "none")).strip() or "none"
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
            source_path=str(path.relative_to(self._manifest_dir.parent)),
        )

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
        return {
            "profiles": profile_map,
            "tools": tools,
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
                    "capability_tags": [],
                    "summary": "插件未配置",
                    "tool_profile": "none",
                    "allowed_tools": [],
                    "max_tool_rounds": 0,
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
                "notes": [],
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
            self._backend._SystemMessage(content=manifest.system_prompt),
            self._backend._HumanMessage(content=human_payload),
        ]

        selected_tools = list(manifest.allowed_tools)
        if not bool(settings.enable_tools):
            selected_tools = []
        tool_round_limit = manifest.max_tool_rounds if max_tool_rounds is None else int(max_tool_rounds)
        tool_round_limit = max(0, min(12, tool_round_limit))
        if not selected_tools:
            tool_round_limit = 0

        usage_total = self._backend._empty_usage()
        notes: list[str] = []
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

        for round_idx in range(tool_round_limit):
            tool_calls = list(getattr(ai_msg, "tool_calls", None) or [])
            if not tool_calls:
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

        text = self._backend._content_to_text(getattr(ai_msg, "content", "")).strip()
        if not text:
            text = "(empty response)"

        return {
            "ok": True,
            "plugin_id": manifest.plugin_id,
            "text": text,
            "effective_model": effective_model or requested_model,
            "tool_events": [item.model_dump() for item in tool_events],
            "token_usage": usage_total,
            "notes": notes,
            "decision": {},
        }
