from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.serialization import dump_model


_VALID_PLAN_STATUS = {"pending", "in_progress", "completed"}
_DRAFT_PREFIXES = (
    "we need to",
    "let's ",
    "lets ",
    "maybe ",
    "actually ",
    "we are stuck",
    "i need to",
    "i should ",
    "how to ",
)


class TaskContext(BaseModel):
    user_request: str = ""
    goal: str = ""
    current_step: str = ""
    next_action: str = ""


class WorkspaceContext(BaseModel):
    project_root: str = ""
    cwd: str = ""
    model_visible_paths: list[str] = Field(default_factory=list)


class RecentObservation(BaseModel):
    source: str = ""
    tool: str = ""
    target: str = ""
    status: str = ""
    summary: str = ""


class MemoryContext(BaseModel):
    clean_summary: str = ""
    active_files: list[str] = Field(default_factory=list)
    recent_observations: list[RecentObservation] = Field(default_factory=list)


class PlanItem(BaseModel):
    step: str = ""
    status: Literal["pending", "in_progress", "completed"] = "pending"


class PlanContext(BaseModel):
    items: list[PlanItem] = Field(default_factory=list)


class PermissionsContext(BaseModel):
    profile: str = "code"
    read: str = ""
    write: str = ""
    shell: str = ""
    network: str = "disabled"


class ConversationContext(BaseModel):
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)


class ModelContext(BaseModel):
    task: TaskContext = Field(default_factory=TaskContext)
    workspace: WorkspaceContext = Field(default_factory=WorkspaceContext)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    plan: PlanContext = Field(default_factory=PlanContext)
    permissions: PermissionsContext = Field(default_factory=PermissionsContext)
    conversation: ConversationContext = Field(default_factory=ConversationContext)


# Backward-compatible name for older tests/imports. The runtime now treats this
# object as ModelContext, not as the previous broad ContextPack envelope.
ContextPack = ModelContext


def normalize_user_message_preview(message: Any, *, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _truncate(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _candidate_root_strings(root: Any) -> list[str]:
    raw = str(root or "").strip()
    if not raw:
        return []
    candidates = {raw.rstrip("/\\")}
    try:
        candidates.add(str(Path(raw).expanduser().resolve()).rstrip("/\\"))
    except Exception:
        pass
    return [item for item in candidates if item and len(item) > 1]


def _rebase_text_paths_for_model(
    text: str,
    *,
    project_root: Path | str,
    previous_roots: list[Path | str] | None = None,
) -> str:
    """Convert known project-root absolute paths in historical text to portable model paths."""

    value = str(text or "")
    roots: list[str] = []
    for raw_root in [project_root, *(previous_roots or [])]:
        roots.extend(_candidate_root_strings(raw_root))
    for root in sorted(set(roots), key=len, reverse=True):
        if value == root:
            return "."
        value = value.replace(root + "/", "")
        value = value.replace(root + "\\", "")
    return value


def _rebase_value_paths_for_model(
    value: Any,
    *,
    project_root: Path | str,
    previous_roots: list[Path | str] | None = None,
) -> Any:
    if isinstance(value, str):
        return _rebase_text_paths_for_model(value, project_root=project_root, previous_roots=previous_roots)
    if isinstance(value, list):
        return [
            _rebase_value_paths_for_model(item, project_root=project_root, previous_roots=previous_roots)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _rebase_value_paths_for_model(item, project_root=project_root, previous_roots=previous_roots)
            for key, item in value.items()
        }
    return value


def _known_previous_project_roots(context: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for key in ("previous_project_roots", "previous_roots"):
        roots.extend(str(item) for item in list(context.get(key) or []) if str(item or "").strip())
    project = context.get("project")
    if isinstance(project, dict):
        roots.extend(str(item) for item in list(project.get("previous_project_roots") or []) if str(item or "").strip())
    return roots


def _unique_strings(values: Any, *, limit: int, max_chars: int = 240) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(values or []):
        value = _truncate(item, max_chars)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _normalize_plan_items(raw_items: Any) -> list[PlanItem]:
    items: list[PlanItem] = []
    for item in list(raw_items or []):
        if not isinstance(item, dict):
            continue
        step = _truncate(item.get("step") or item.get("title") or item.get("content"), 500)
        if not step:
            continue
        status = str(item.get("status") or "pending").strip()
        if status not in _VALID_PLAN_STATUS:
            status = "pending"
        items.append(PlanItem(step=step, status=status))  # type: ignore[arg-type]
        if len(items) >= 12:
            break
    return items


def _normalize_plan_context(raw_plan_state: Any, raw_plan: Any = None) -> PlanContext:
    raw_items: Any = raw_plan
    if isinstance(raw_plan_state, dict):
        raw_items = raw_plan_state.get("items") or raw_plan_state.get("plan") or raw_items
    elif raw_plan_state:
        raw_items = raw_plan_state
    return PlanContext(items=_normalize_plan_items(raw_items))


def _is_clean_role(role: str) -> bool:
    return role in {"user", "assistant"}


def is_model_draft(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in _DRAFT_PREFIXES):
        return True
    if normalized.startswith(("plan:", "todo:", "analysis:")):
        return True
    # A strategy-only assistant message without a user-facing conclusion should
    # not become clean memory.
    if normalized.count("we need to") >= 2 or normalized.count("let's") >= 2:
        return True
    return False


def classify_assistant_output(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "empty"
    return "model_draft" if is_model_draft(raw) else "final_answer"


def _clean_text(text: Any, *, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _normalize_clean_turns(raw_turns: Any, *, current_message: Any, limit: int = 8) -> list[dict[str, Any]]:
    current_text = _clean_text(current_message, limit=20000)
    selected: list[dict[str, Any]] = []
    for item in reversed(list(raw_turns or [])):
        if not isinstance(item, dict):
            continue
        role = _truncate(item.get("role"), 40)
        if not _is_clean_role(role):
            continue
        text = _clean_text(item.get("text") or item.get("content"), limit=1200)
        if not text:
            continue
        if role == "user" and text == current_text:
            continue
        if role == "assistant" and is_model_draft(text):
            continue
        turn: dict[str, Any] = {"role": role, "text": text}
        if len(str(item.get("text") or item.get("content") or "")) > 1200:
            turn["truncated"] = True
        selected.append(turn)
        if len(selected) >= limit:
            break
    return list(reversed(selected))


def _normalize_recent_observations(raw_values: Any) -> list[RecentObservation]:
    observations: list[RecentObservation] = []
    for item in list(raw_values or []):
        if not isinstance(item, dict):
            continue
        summary = _truncate(item.get("summary") or item.get("message") or item.get("text") or item.get("error"), 500)
        if not summary:
            continue
        observations.append(
            RecentObservation(
                source=_truncate(item.get("source") or ("tool" if item.get("tool") else ""), 80),
                tool=_truncate(item.get("tool") or item.get("name"), 120),
                target=_truncate(item.get("target") or item.get("path") or item.get("file"), 240),
                status=_truncate(item.get("status") or ("error" if item.get("error") else ""), 80),
                summary=summary,
            )
        )
        if len(observations) >= 5:
            break
    return observations


def _tool_event_observation(event: Any) -> dict[str, Any] | None:
    payload = dump_model(event)
    if not isinstance(payload, dict):
        return None
    tool = _truncate(payload.get("name") or payload.get("tool") or payload.get("tool_name"), 120)
    status = _truncate(payload.get("status") or "", 80)
    summary = _truncate(payload.get("summary") or payload.get("message") or payload.get("error"), 500)
    if not summary and not tool:
        return None
    target = ""
    args = payload.get("arguments") or payload.get("args")
    if isinstance(args, dict):
        target = _truncate(args.get("path") or args.get("root") or args.get("cwd") or args.get("query"), 240)
    return {
        "source": "tool",
        "tool": tool,
        "target": target,
        "status": status,
        "summary": summary or f"{tool}:{status}",
    }


def _extract_active_files_from_events(tool_events: Any) -> list[str]:
    files: list[str] = []
    for event in list(tool_events or []):
        payload = dump_model(event)
        if not isinstance(payload, dict):
            continue
        for ref in list(payload.get("source_refs") or []):
            if isinstance(ref, dict):
                files.append(str(ref.get("path") or ref.get("file") or ""))
        args = payload.get("arguments") or payload.get("args")
        if isinstance(args, dict):
            files.append(str(args.get("path") or args.get("file") or ""))
    return _unique_strings(files, limit=10, max_chars=500)


def _permission_text(value: Any, *, enabled: str, disabled: str) -> str:
    return enabled if bool(value) else disabled


def _has_context_manager_data(payload: dict[str, Any]) -> bool:
    try:
        context_version = int(payload.get("context_version") or 0)
    except Exception:
        context_version = 0
    return bool(
        str(payload.get("clean_summary") or "").strip()
        or list(payload.get("clean_turns") or [])
        or list(payload.get("recent_observations") or [])
        or list(payload.get("active_files") or [])
        or list(payload.get("plan") or [])
        or context_version > 0
    )


class ContextManager(BaseModel):
    clean_summary: str = ""
    clean_turns: list[dict[str, Any]] = Field(default_factory=list)
    recent_observations: list[RecentObservation] = Field(default_factory=list)
    active_files: list[str] = Field(default_factory=list)
    plan: list[PlanItem] = Field(default_factory=list)
    context_version: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ContextManager":
        raw = dict(payload or {})
        try:
            context_version = max(0, int(raw.get("context_version") or 0))
        except Exception:
            context_version = 0
        return cls(
            clean_summary=_truncate(raw.get("clean_summary"), 4000),
            clean_turns=_normalize_clean_turns(raw.get("clean_turns"), current_message="", limit=16),
            recent_observations=_normalize_recent_observations(raw.get("recent_observations")),
            active_files=_unique_strings(raw.get("active_files"), limit=10, max_chars=500),
            plan=_normalize_plan_items(raw.get("plan")),
            context_version=context_version,
        )

    @classmethod
    def from_context_payload(cls, context: dict[str, Any]) -> "ContextManager":
        raw_observations: list[Any] = []
        raw_observations.extend(list(context.get("recent_observations") or []))
        raw_observations.extend(list(context.get("recent_tool_results") or []))
        raw_observations.extend(list(context.get("recent_errors") or []))
        raw_observations.extend(
            {
                "source": "attachment_evidence",
                "tool": str(item.get("tool") or item.get("kind") or ""),
                "target": str(item.get("name") or item.get("path") or ""),
                "status": str(item.get("status") or "ready"),
                "summary": str(item.get("summary") or ""),
            }
            for item in list(context.get("attachment_evidence_pack") or [])
            if isinstance(item, dict)
        )
        raw_manager = context.get("context_manager")
        if isinstance(raw_manager, dict) and _has_context_manager_data(raw_manager):
            manager = cls.from_payload(raw_manager)
        else:
            thread_memory = dict(context.get("thread_memory") or {})
            compaction_status = dict(context.get("compaction_status") or {})
            manager = cls(
                clean_summary=_truncate(context.get("summary") or thread_memory.get("summary") or compaction_status.get("summary"), 4000),
                clean_turns=_normalize_clean_turns(context.get("history_turns"), current_message="", limit=16),
                recent_observations=_normalize_recent_observations(raw_observations),
                active_files=_unique_strings((context.get("current_task_focus") or {}).get("active_files"), limit=10, max_chars=500),
                plan=_normalize_plan_context(context.get("plan_state"), context.get("plan")).items,
                context_version=0,
            )
        if raw_observations:
            manager.recent_observations = _normalize_recent_observations(
                [*raw_observations, *[dump_model(item) for item in manager.recent_observations]]
            )

        project_payload = dict(context.get("project") or {})
        project_root = str(project_payload.get("project_root") or project_payload.get("root") or "").strip()
        previous_roots = _known_previous_project_roots(context)
        if project_root:
            manager.clean_summary = _rebase_text_paths_for_model(
                manager.clean_summary,
                project_root=project_root,
                previous_roots=previous_roots,
            )
            manager.clean_turns = _rebase_value_paths_for_model(
                manager.clean_turns,
                project_root=project_root,
                previous_roots=previous_roots,
            )
            manager.recent_observations = [
                RecentObservation(**_rebase_value_paths_for_model(dump_model(item), project_root=project_root, previous_roots=previous_roots))
                for item in manager.recent_observations
            ]
            manager.active_files = _unique_strings(
                _rebase_value_paths_for_model(manager.active_files, project_root=project_root, previous_roots=previous_roots),
                limit=10,
                max_chars=500,
            )
        return manager

    def to_session_payload(self) -> dict[str, Any]:
        return {
            "clean_summary": self.clean_summary,
            "clean_turns": [dict(item) for item in self.clean_turns],
            "recent_observations": [dump_model(item) for item in self.recent_observations[:5]],
            "active_files": list(self.active_files[:10]),
            "plan": [dump_model(item) for item in self.plan[:12]],
            "context_version": int(self.context_version),
        }

    def _touch(self) -> None:
        self.context_version += 1

    def update_after_turn(
        self,
        *,
        user_request: str,
        clean_final_answer: str | None,
        runtime_trace: dict[str, Any] | None = None,
        plan_updates: list[dict[str, Any]] | None = None,
    ) -> None:
        user_text = _clean_text(user_request, limit=4000)
        if user_text:
            self.clean_turns.append({"role": "user", "text": user_text})
            self._touch()

        answer_text = _clean_text(clean_final_answer, limit=4000)
        if answer_text and classify_assistant_output(answer_text) == "final_answer":
            self.clean_turns.append({"role": "assistant", "text": answer_text})
            self._touch()

        trace = dict(runtime_trace or {})
        observations = []
        for event in list(trace.get("tool_events") or []):
            observation = _tool_event_observation(event)
            if observation:
                observations.append(observation)
        if observations:
            merged = [*observations, *[dump_model(item) for item in self.recent_observations]]
            self.recent_observations = _normalize_recent_observations(merged)
            self._touch()

        active_files = _extract_active_files_from_events(trace.get("tool_events") or [])
        if active_files:
            self.active_files = _unique_strings([*active_files, *self.active_files], limit=10, max_chars=500)
            self._touch()

        if plan_updates is not None:
            self.plan = _normalize_plan_items(plan_updates)
            self._touch()

        self.recent_observations = self.recent_observations[:5]
        self.active_files = self.active_files[:10]

    def compact_if_needed(self, *, max_clean_turns: int = 16) -> bool:
        if len(self.clean_turns) <= max_clean_turns:
            return False
        keep_count = min(8, max(4, max_clean_turns // 2))
        old_turns = self.clean_turns[:-keep_count]
        retained = self.clean_turns[-keep_count:]
        summary_parts = [self.clean_summary] if self.clean_summary.strip() else []
        if old_turns:
            summary_parts.append(
                "Older conversation summary: "
                + " ".join(f"{turn.get('role')}: {_clean_text(turn.get('text'), limit=240)}" for turn in old_turns)
            )
        if self.recent_observations:
            summary_parts.append(
                "Recent observations: "
                + " ".join(_clean_text(item.summary, limit=160) for item in self.recent_observations[:5])
            )
        self.clean_summary = _clean_text(" ".join(summary_parts), limit=2000)
        self.clean_turns = retained
        self.recent_observations = self.recent_observations[:5]
        self._touch()
        return True


def _permissions_from_boundary(runtime_boundary_model_view: dict[str, Any], *, permission_profile: str) -> PermissionsContext:
    return PermissionsContext(
        profile=str(permission_profile or runtime_boundary_model_view.get("permission_profile") or "code"),
        read=str(runtime_boundary_model_view.get("file_read_scope") or _permission_text(
            runtime_boundary_model_view.get("workspace_read_allowed"),
            enabled="current project + imported files",
            disabled="none",
        )),
        write=str(runtime_boundary_model_view.get("file_write_scope") or _permission_text(
            runtime_boundary_model_view.get("workspace_write_allowed"),
            enabled="current project",
            disabled="none",
        )),
        shell=str(runtime_boundary_model_view.get("command_scope") or _permission_text(
            runtime_boundary_model_view.get("shell_allowed"),
            enabled="current project",
            disabled="none",
        )),
        network="enabled" if bool(runtime_boundary_model_view.get("network_allowed")) else "disabled",
    )


def build_model_context(
    *,
    user_request: str,
    runtime_boundary_model_view: dict[str, Any],
    permission_profile: str = "",
    project_root: Path | str | None = None,
    cwd: Path | str | None = None,
    context: dict[str, Any] | None = None,
    current_task_focus: dict[str, Any] | None = None,
) -> ModelContext:
    raw_context = dict(context or {})
    focus = dict(current_task_focus or raw_context.get("current_task_focus") or {})
    manager = ContextManager.from_context_payload(raw_context)

    project_payload = dict(raw_context.get("project") or {})
    resolved_project_root = str(
        project_root
        or runtime_boundary_model_view.get("project_root")
        or project_payload.get("project_root")
        or project_payload.get("root")
        or ""
    )
    resolved_cwd = str(cwd or runtime_boundary_model_view.get("cwd") or project_payload.get("cwd") or resolved_project_root)
    previous_roots = _known_previous_project_roots(raw_context)
    if resolved_project_root:
        focus = _rebase_value_paths_for_model(focus, project_root=resolved_project_root, previous_roots=previous_roots)

    current_turn = dict(raw_context.get("current_turn") or {})
    goal = _truncate(focus.get("goal") or current_turn.get("goal") or normalize_user_message_preview(user_request, limit=140), 500)
    current_step = _truncate(focus.get("last_completed_step") or focus.get("last_observation"), 500)
    if not current_step and manager.recent_observations:
        current_step = _truncate(manager.recent_observations[0].summary, 500)
    next_action = _truncate(focus.get("next_action"), 500)

    active_files = _unique_strings([*manager.active_files, *list(focus.get("active_files") or [])], limit=10, max_chars=500)
    if resolved_project_root:
        active_files = _unique_strings(
            _rebase_value_paths_for_model(active_files, project_root=resolved_project_root, previous_roots=previous_roots),
            limit=10,
            max_chars=500,
        )
    conversation = _normalize_clean_turns(manager.clean_turns, current_message=user_request, limit=8)
    return ModelContext(
        task=TaskContext(
            user_request=_clean_text(user_request, limit=4000),
            goal=goal,
            current_step=current_step,
            next_action=next_action,
        ),
        workspace=WorkspaceContext(
            project_root=str(resolved_project_root),
            cwd=str(resolved_cwd),
            model_visible_paths=active_files,
        ),
        memory=MemoryContext(
            clean_summary=_truncate(manager.clean_summary, 2000),
            active_files=active_files,
            recent_observations=manager.recent_observations[:5],
        ),
        plan=PlanContext(items=manager.plan[:12]),
        permissions=_permissions_from_boundary(runtime_boundary_model_view, permission_profile=permission_profile),
        conversation=ConversationContext(recent_turns=conversation),
    )


def build_context_pack(
    *,
    message: str,
    context: dict[str, Any],
    current_task_focus: dict[str, Any],
    runtime_boundary_model_view: dict[str, Any],
) -> ModelContext:
    return build_model_context(
        user_request=message,
        context=context,
        current_task_focus=current_task_focus,
        runtime_boundary_model_view=runtime_boundary_model_view,
        permission_profile=str(runtime_boundary_model_view.get("permission_profile") or ""),
    )


def render_model_context(model_context: ModelContext) -> str:
    payload = {"model_context": dump_model(model_context)}
    return "model_context_json:\n" + json.dumps(payload, ensure_ascii=False)
