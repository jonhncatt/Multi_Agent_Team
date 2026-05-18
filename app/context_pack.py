from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


_VALID_PLAN_STATUS = {"pending", "in_progress", "completed"}


class CurrentTurn(BaseModel):
    user_message_preview: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    attachment_evidence: list[dict[str, Any]] = Field(default_factory=list)
    current_files: list[str] = Field(default_factory=list)


class ConversationWindow(BaseModel):
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)


class ActiveTask(BaseModel):
    goal: str = ""
    cwd: str = ""
    active_files: list[str] = Field(default_factory=list)
    last_observation: str = ""


class RecentObservation(BaseModel):
    source: str = ""
    tool: str = ""
    target: str = ""
    status: str = ""
    summary: str = ""


class TurnMemory(BaseModel):
    active_task: ActiveTask = Field(default_factory=ActiveTask)
    summary: str = ""
    recent_observations: list[RecentObservation] = Field(default_factory=list)


class PlanItem(BaseModel):
    step: str = ""
    status: Literal["pending", "in_progress", "completed"] = "pending"


class PlanState(BaseModel):
    active: bool = False
    items: list[PlanItem] = Field(default_factory=list)
    updated_at_turn: str | None = None


class CompactionView(BaseModel):
    active: bool = False
    phase: str = ""
    reason: str = ""
    summary_available: bool = False


class RuntimeBoundaryModelView(BaseModel):
    workspace_read_allowed: bool = True
    workspace_write_allowed: bool = True
    shell_allowed: bool = False
    network_allowed: bool = False
    approval_policy: str = ""
    cwd: str = ""
    project_root: str = ""


class ContextPack(BaseModel):
    current_turn: CurrentTurn = Field(default_factory=CurrentTurn)
    conversation_window: ConversationWindow = Field(default_factory=ConversationWindow)
    turn_memory: TurnMemory = Field(default_factory=TurnMemory)
    plan_state: PlanState = Field(default_factory=PlanState)
    compaction: CompactionView = Field(default_factory=CompactionView)
    runtime_boundary: RuntimeBoundaryModelView = Field(default_factory=RuntimeBoundaryModelView)


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


def _attachment_kind(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip()
    if kind:
        return kind
    mime = str(item.get("mime_type") or item.get("mime") or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime in {"application/pdf"}:
        return "pdf"
    if "spreadsheet" in mime or "excel" in mime or mime.endswith("/csv"):
        return "spreadsheet"
    if mime.startswith("text/"):
        return "text"
    return "unknown"


def _normalize_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for item in list(raw_attachments or []):
        if not isinstance(item, dict):
            continue
        reference = _truncate(item.get("reference") or item.get("path") or item.get("id"), 500)
        attachment = {
            "name": _truncate(item.get("name") or item.get("original_name"), 200),
            "mime_type": _truncate(item.get("mime_type") or item.get("mime"), 120),
            "kind": _attachment_kind(item),
            "reference": reference,
        }
        if any(attachment.values()):
            attachments.append(attachment)
        if len(attachments) >= 8:
            break
    return attachments


def _normalize_attachment_evidence(raw_evidence: Any) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in list(raw_evidence or []):
        if not isinstance(item, dict):
            continue
        compact: dict[str, Any] = {}
        for key in ("name", "kind", "summary", "status", "tool"):
            if key in item:
                compact[key] = _truncate(item.get(key), 500 if key == "summary" else 160)
        if compact:
            evidence.append(compact)
        if len(evidence) >= 5:
            break
    return evidence


def _normalize_recent_turns(raw_turns: Any, *, current_message: Any) -> list[dict[str, Any]]:
    current_text = re.sub(r"\s+", " ", str(current_message or "")).strip()
    selected: list[dict[str, Any]] = []
    for item in reversed(list(raw_turns or [])):
        if not isinstance(item, dict):
            continue
        role = _truncate(item.get("role"), 40)
        text = re.sub(r"\s+", " ", str(item.get("text") or item.get("content") or "")).strip()
        if role == "user" and text == current_text:
            continue
        turn: dict[str, Any] = {"role": role}
        if role == "tool":
            turn["tool"] = _truncate(item.get("tool") or item.get("name"), 120)
            if len(text) > 1200:
                turn["summary"] = text[:1200]
                turn["truncated"] = True
            else:
                turn["text"] = text[:1200]
        else:
            turn["text"] = text[:1200]
            if len(text) > 1200:
                turn["truncated"] = True
        selected.append(turn)
        if len(selected) >= 12:
            break
    return list(reversed(selected))


def _normalize_recent_observations(context: dict[str, Any]) -> list[RecentObservation]:
    raw_values: list[Any] = []
    raw_values.extend(list(context.get("recent_observations") or []))
    raw_values.extend(list(context.get("recent_tool_results") or []))
    raw_values.extend(list(context.get("recent_errors") or []))
    observations: list[RecentObservation] = []
    for item in raw_values:
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


def _normalize_plan_state(raw_plan_state: Any, raw_plan: Any = None) -> PlanState:
    updated_at_turn: str | None = None
    raw_items: Any = raw_plan
    if isinstance(raw_plan_state, dict):
        raw_items = raw_plan_state.get("items") or raw_plan_state.get("plan") or raw_items
        raw_updated_at = raw_plan_state.get("updated_at_turn")
        updated_at_turn = str(raw_updated_at) if raw_updated_at is not None else None
    elif raw_plan_state:
        raw_items = raw_plan_state

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
    return PlanState(
        active=bool(items and any(item.status != "completed" for item in items)),
        items=items,
        updated_at_turn=updated_at_turn,
    )


def _normalize_compaction_view(compaction_status: dict[str, Any], *, summary: str) -> CompactionView:
    phase = _truncate(compaction_status.get("phase") or compaction_status.get("last_compaction_phase"), 80)
    raw_reason = _truncate(compaction_status.get("reason") or compaction_status.get("last_compaction_reason"), 120)
    reason = raw_reason.split(":", 1)[0] if raw_reason else ""
    return CompactionView(
        active=bool(phase or reason or compaction_status.get("enabled")),
        phase=phase,
        reason=reason,
        summary_available=bool(summary.strip()),
    )


def build_context_pack(
    *,
    message: str,
    context: dict[str, Any],
    current_task_focus: dict[str, Any],
    runtime_boundary_model_view: dict[str, Any],
) -> ContextPack:
    project_payload = dict(context.get("project") or {})
    project_root = (
        runtime_boundary_model_view.get("project_root")
        or project_payload.get("project_root")
        or project_payload.get("root")
        or ""
    )
    previous_roots = _known_previous_project_roots(context)
    if project_root:
        context = _rebase_value_paths_for_model(
            context,
            project_root=project_root,
            previous_roots=previous_roots,
        )
        current_task_focus = _rebase_value_paths_for_model(
            current_task_focus,
            project_root=project_root,
            previous_roots=previous_roots,
        )
    thread_memory = dict(context.get("thread_memory") or {})
    compaction_status = dict(context.get("compaction_status") or {})
    summary = _truncate(context.get("summary") or thread_memory.get("summary") or compaction_status.get("summary"), 2000)
    active_task = ActiveTask(
        goal=_truncate(current_task_focus.get("goal"), 500),
        cwd=_truncate(current_task_focus.get("cwd") or runtime_boundary_model_view.get("cwd"), 500),
        active_files=_unique_strings(current_task_focus.get("active_files"), limit=10, max_chars=500),
        last_observation=_truncate(
            current_task_focus.get("last_completed_step") or current_task_focus.get("last_observation"),
            500,
        ),
    )
    return ContextPack(
        current_turn=CurrentTurn(
            user_message_preview=normalize_user_message_preview(message),
            attachments=_normalize_attachments(context.get("attachments")),
            attachment_evidence=_normalize_attachment_evidence(context.get("attachment_evidence_pack")),
            current_files=_unique_strings(context.get("current_files"), limit=10, max_chars=500),
        ),
        conversation_window=ConversationWindow(
            recent_turns=_normalize_recent_turns(context.get("history_turns"), current_message=message)
        ),
        turn_memory=TurnMemory(
            active_task=active_task,
            summary=summary,
            recent_observations=_normalize_recent_observations(context),
        ),
        plan_state=_normalize_plan_state(context.get("plan_state"), context.get("plan")),
        compaction=_normalize_compaction_view(compaction_status, summary=summary),
        runtime_boundary=RuntimeBoundaryModelView(**runtime_boundary_model_view),
    )
