from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.serialization import dump_model
from app.session_context import normalize_task_state, normalize_work_cursor


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
    status: str = ""
    current_step_id: str = ""
    current_step: str = ""
    next_action: str = ""
    blocked_reason: str = ""
    completed_steps: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


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
    status: Literal["pending", "in_progress", "completed", "failed", "blocked"] = "pending"


class PlanContext(BaseModel):
    items: list[PlanItem] = Field(default_factory=list)


class CompactionSummary(BaseModel):
    confirmed_facts: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    current_state: str = ""
    next_steps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    do_not_repeat: list[str] = Field(default_factory=list)


class PermissionsContext(BaseModel):
    profile: str = "auto"
    label: str = "Auto"
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


def _summary_strings(values: Any, *, limit: int = 8, max_chars: int = 500) -> list[str]:
    if isinstance(values, str):
        raw_values: list[Any] = [
            line.strip(" -\t")
            for line in values.splitlines()
            if line.strip(" -\t")
        ] or [values]
    else:
        raw_values = list(values or [])
    out: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            value = (
                item.get("summary")
                or item.get("step")
                or item.get("title")
                or item.get("text")
                or item.get("message")
                or item.get("error")
            )
            if not value:
                value = json.dumps(dump_model(item), ensure_ascii=False, default=str)
        else:
            value = item
        text = _truncate(value, max_chars)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return _unique_strings(out, limit=limit, max_chars=max_chars)


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


def _compact_turn_for_compaction(turn: Any) -> dict[str, Any] | None:
    if not isinstance(turn, dict):
        return None
    role = _truncate(turn.get("role") or "unknown", 40)
    text = _clean_text(turn.get("text") or turn.get("content"), limit=1200)
    if not text:
        return None
    payload: dict[str, Any] = {
        "id": _truncate(turn.get("id"), 120),
        "role": role,
        "text": text,
        "created_at": _truncate(turn.get("created_at"), 80),
    }
    attachments = []
    for item in list(turn.get("attachments") or [])[:6]:
        if not isinstance(item, dict):
            continue
        label = _truncate(item.get("name") or item.get("path") or item.get("id"), 160)
        if label:
            attachments.append(label)
    if attachments:
        payload["attachments"] = attachments
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


def _tool_evidence_for_compaction(event: Any) -> dict[str, Any] | None:
    observation = _tool_event_observation(event)
    if not observation:
        return None
    payload = dump_model(event)
    if not isinstance(payload, dict):
        payload = {}
    evidence = {
        "tool": _truncate(observation.get("tool"), 120),
        "target": _truncate(observation.get("target"), 240),
        "status": _truncate(observation.get("status"), 80),
        "summary": _truncate(observation.get("summary"), 500),
        "source_refs": [
            _truncate(item, 240)
            for item in list(payload.get("source_refs") or [])[:6]
            if str(item or "").strip()
        ],
    }
    return {key: value for key, value in evidence.items() if value not in ("", [], {})}


def _normalize_compaction_tool_evidence(raw_values: Any) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in list(raw_values or []):
        normalized = _tool_evidence_for_compaction(item)
        if normalized:
            evidence.append(normalized)
        if len(evidence) >= 24:
            break
    return evidence


def build_compaction_input(
    *,
    old_messages: Any = None,
    tool_evidence: Any = None,
    task_state: dict[str, Any] | None = None,
    work_cursor: dict[str, Any] | None = None,
    modified_files: Any = None,
    failed_attempts: Any = None,
    current_status: str = "",
) -> dict[str, Any]:
    task_payload = dict(task_state or {})
    cursor_payload = dict(work_cursor or {})
    messages = []
    for item in list(old_messages or []):
        turn = _compact_turn_for_compaction(item)
        if turn:
            messages.append(turn)
        if len(messages) >= 24:
            break
    evidence = _normalize_compaction_tool_evidence(tool_evidence)
    files_from_evidence: list[str] = []
    for item in evidence:
        files_from_evidence.append(str(item.get("target") or ""))
    files = _unique_strings(
        [
            *list(modified_files or []),
            *list(cursor_payload.get("active_files") or []),
            *files_from_evidence,
        ],
        limit=16,
        max_chars=500,
    )
    failures = _summary_strings(
        [
            *list(failed_attempts or []),
            *list(task_payload.get("failed_attempts") or []),
            *[
                item
                for item in evidence
                if str(item.get("status") or "").strip().lower() not in {"", "ok", "success", "completed"}
            ],
        ],
        limit=12,
        max_chars=500,
    )
    return {
        "old_messages": messages,
        "tool_evidence": evidence,
        "task_state": {
            "task_id": _truncate(task_payload.get("task_id"), 120),
            "goal": _truncate(task_payload.get("goal"), 500),
            "status": _truncate(task_payload.get("status"), 80),
            "plan_items": [
                {
                    "id": _truncate(item.get("id") or item.get("step_id"), 120),
                    "step": _truncate(item.get("step") or item.get("title"), 500),
                    "status": _truncate(item.get("status"), 80),
                }
                for item in list(task_payload.get("plan_items") or task_payload.get("plan") or [])[:12]
                if isinstance(item, dict) and _truncate(item.get("step") or item.get("title"), 500)
            ],
            "current_step_id": _truncate(task_payload.get("current_step_id"), 120),
            "completed_steps": _summary_strings(task_payload.get("completed_steps"), limit=8, max_chars=500),
            "blocked_reason": _truncate(task_payload.get("blocked_reason"), 500),
            "next_required_action": _truncate(task_payload.get("next_required_action") or task_payload.get("next_action"), 500),
            "failed_attempts": failures,
        },
        "work_cursor": {
            "project_root": _truncate(cursor_payload.get("project_root"), 500),
            "cwd": _truncate(cursor_payload.get("cwd"), 500),
            "active_files": _unique_strings(cursor_payload.get("active_files"), limit=12, max_chars=500),
            "active_attachments": [
                {
                    "id": _truncate(item.get("id"), 120),
                    "name": _truncate(item.get("name"), 160),
                    "kind": _truncate(item.get("kind"), 80),
                    "path": _truncate(item.get("path"), 500),
                }
                for item in list(cursor_payload.get("active_attachments") or [])[:8]
                if isinstance(item, dict)
            ],
        },
        "modified_files": files,
        "failed_attempts": failures,
        "current_status": _truncate(current_status or task_payload.get("status"), 120),
    }


def normalize_compaction_summary(raw: Any) -> CompactionSummary:
    if isinstance(raw, CompactionSummary):
        return raw
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    return CompactionSummary(
        confirmed_facts=_summary_strings(payload.get("confirmed_facts"), limit=12, max_chars=500),
        files_touched=_unique_strings(payload.get("files_touched"), limit=16, max_chars=500),
        decisions=_summary_strings(payload.get("decisions"), limit=10, max_chars=500),
        failed_attempts=_summary_strings(payload.get("failed_attempts"), limit=12, max_chars=500),
        current_state=_truncate(payload.get("current_state"), 1000),
        next_steps=_summary_strings(payload.get("next_steps"), limit=12, max_chars=500),
        open_questions=_summary_strings(payload.get("open_questions"), limit=8, max_chars=500),
        do_not_repeat=_summary_strings(payload.get("do_not_repeat"), limit=8, max_chars=500),
    )


def parse_compaction_summary_text(text: str) -> CompactionSummary | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1))
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidates.insert(0, raw[first : last + 1])
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(decoded, dict):
            return normalize_compaction_summary(decoded)
    return None


def build_structured_compaction_summary(compaction_input: dict[str, Any] | None) -> CompactionSummary:
    payload = dict(compaction_input or {})
    task_state = dict(payload.get("task_state") or {})
    evidence = [dict(item) for item in list(payload.get("tool_evidence") or []) if isinstance(item, dict)]
    messages = [dict(item) for item in list(payload.get("old_messages") or []) if isinstance(item, dict)]
    confirmed: list[str] = []
    decisions: list[str] = []
    for item in evidence:
        status = str(item.get("status") or "").strip().lower()
        summary = _truncate(item.get("summary"), 500)
        if not summary:
            continue
        if status in {"", "ok", "success", "completed"}:
            confirmed.append(summary)
    for item in messages:
        role = str(item.get("role") or "").strip()
        text = _truncate(item.get("text"), 320)
        if role == "assistant" and text:
            confirmed.append(text)
    plan_items = [dict(item) for item in list(task_state.get("plan_items") or []) if isinstance(item, dict)]
    for item in plan_items:
        if str(item.get("status") or "").strip() == "completed":
            step = _truncate(item.get("step"), 500)
            if step:
                decisions.append(step)
    next_steps = []
    next_required = _truncate(task_state.get("next_required_action"), 500)
    if next_required:
        next_steps.append(next_required)
    for item in plan_items:
        status = str(item.get("status") or "").strip()
        if status in {"pending", "in_progress"}:
            step = _truncate(item.get("step"), 500)
            if step:
                next_steps.append(step)
    failed = _summary_strings(payload.get("failed_attempts"), limit=12, max_chars=500)
    do_not_repeat = []
    for item in failed[:6]:
        do_not_repeat.append(f"Avoid repeating without new evidence: {item}")
    status = _truncate(task_state.get("status") or payload.get("current_status"), 80)
    goal = _truncate(task_state.get("goal"), 500)
    blocked = _truncate(task_state.get("blocked_reason"), 500)
    state_parts = []
    if status:
        state_parts.append(f"status={status}")
    if goal:
        state_parts.append(f"goal={goal}")
    if next_required:
        state_parts.append(f"next={next_required}")
    if blocked:
        state_parts.append(f"blocked={blocked}")
    return CompactionSummary(
        confirmed_facts=_unique_strings(confirmed, limit=12, max_chars=500),
        files_touched=_unique_strings(payload.get("modified_files"), limit=16, max_chars=500),
        decisions=_unique_strings(decisions, limit=10, max_chars=500),
        failed_attempts=failed,
        current_state="; ".join(state_parts),
        next_steps=_unique_strings(next_steps, limit=12, max_chars=500),
        open_questions=[],
        do_not_repeat=_unique_strings(do_not_repeat, limit=8, max_chars=500),
    )


def render_compaction_prompt(compaction_input: dict[str, Any]) -> str:
    payload = dict(compaction_input or {})
    schema = {
        "confirmed_facts": ["facts that are already verified"],
        "files_touched": ["paths that are relevant or changed"],
        "decisions": ["decisions already made"],
        "failed_attempts": ["attempts that failed and why"],
        "current_state": "one concise description of current status",
        "next_steps": ["specific next actions"],
        "open_questions": ["questions that still need user/model resolution"],
        "do_not_repeat": ["actions that should not be repeated without new evidence"],
    }
    return (
        "You are compacting a coding-agent thread. Return only strict JSON matching this schema.\n"
        "Do not include raw tool output, raw traces, provider payloads, secrets, or stack traces.\n"
        "Use only concise durable facts needed to continue the task.\n\n"
        "schema:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\ncompaction_input:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )


def render_compaction_summary(summary: CompactionSummary | dict[str, Any], *, generation: int | None = None) -> str:
    payload = normalize_compaction_summary(summary)
    sections: list[tuple[str, list[str] | str]] = [
        ("confirmed_facts", payload.confirmed_facts),
        ("files_touched", payload.files_touched),
        ("decisions", payload.decisions),
        ("failed_attempts", payload.failed_attempts),
        ("current_state", payload.current_state),
        ("next_steps", payload.next_steps),
        ("open_questions", payload.open_questions),
        ("do_not_repeat", payload.do_not_repeat),
    ]
    lines = ["Compacted thread history."]
    if generation is not None:
        lines.append(f"generation: {max(0, int(generation))}")
    for title, values in sections:
        if isinstance(values, str):
            text = _truncate(values, 1000)
            if text:
                lines.append(f"{title}: {text}")
            continue
        clean_values = _summary_strings(values, limit=16, max_chars=500)
        if not clean_values:
            continue
        lines.append(f"{title}:")
        lines.extend(f"- {item}" for item in clean_values)
    return _clean_text("\n".join(lines), limit=4000)


def apply_compaction_summary_to_state(
    *,
    context_manager: "ContextManager",
    summary: CompactionSummary | dict[str, Any],
    task_state: dict[str, Any] | None = None,
    work_cursor: dict[str, Any] | None = None,
    generation: int | None = None,
) -> tuple["ContextManager", dict[str, Any], dict[str, Any]]:
    normalized = normalize_compaction_summary(summary)
    manager = ContextManager.from_payload(context_manager.to_session_payload())
    manager.clean_summary = render_compaction_summary(normalized, generation=generation)
    observations = [
        {
            "source": "compaction",
            "tool": "llm_compaction",
            "status": "ok",
            "summary": item,
        }
        for item in [*normalized.confirmed_facts[:4], *normalized.decisions[:2], normalized.current_state]
        if str(item or "").strip()
    ]
    manager.recent_observations = _normalize_recent_observations(
        [*observations, *[dump_model(item) for item in manager.recent_observations]]
    )
    if normalized.files_touched:
        manager.active_files = _unique_strings(
            [*normalized.files_touched, *manager.active_files],
            limit=10,
            max_chars=500,
        )
    if normalized.next_steps:
        manager.plan = [
            PlanItem(step=step, status=("in_progress" if index == 0 else "pending"))
            for index, step in enumerate(normalized.next_steps[:12])
        ]
    manager.clean_turns = manager.clean_turns[-8:]
    manager._touch()

    task_payload = dict(task_state or {})
    existing_failures = [
        dict(item)
        for item in list(task_payload.get("failed_attempts") or [])
        if isinstance(item, dict)
    ]
    for item in normalized.failed_attempts:
        existing_failures.append({"summary": item, "source": "compaction"})
    if normalized.failed_attempts:
        task_payload["failed_attempts"] = existing_failures[-12:]
    if normalized.next_steps:
        task_payload["next_required_action"] = normalized.next_steps[0]
        task_payload["plan_items"] = [
            {
                "id": f"compaction-step-{index + 1}",
                "step": step,
                "status": "in_progress" if index == 0 else "pending",
            }
            for index, step in enumerate(normalized.next_steps[:12])
        ]
    if normalized.current_state and not str(task_payload.get("blocked_reason") or "").strip():
        if normalized.failed_attempts and str(task_payload.get("status") or "") in {"blocked", "failed"}:
            task_payload["blocked_reason"] = normalized.current_state[:500]

    cursor_payload = dict(work_cursor or {})
    if normalized.files_touched:
        cursor_payload["active_files"] = _unique_strings(
            [*normalized.files_touched, *list(cursor_payload.get("active_files") or [])],
            limit=8,
            max_chars=500,
        )
    return manager, task_payload, cursor_payload


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
        raw_manager = context.get("context_manager")
        if not isinstance(raw_manager, dict) or not _has_context_manager_data(raw_manager):
            return cls()
        return cls.from_payload(raw_manager)

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
        compaction_messages = [*old_turns]
        if self.clean_summary.strip():
            compaction_messages.insert(0, {"role": "assistant", "text": self.clean_summary})
        compaction_input = build_compaction_input(
            old_messages=compaction_messages,
            tool_evidence=[dump_model(item) for item in self.recent_observations],
            task_state={"plan_items": [dump_model(item) for item in self.plan]},
            work_cursor={"active_files": list(self.active_files)},
            modified_files=list(self.active_files),
        )
        summary = build_structured_compaction_summary(compaction_input)
        self.clean_summary = render_compaction_summary(summary)
        self.clean_turns = retained
        self.recent_observations = self.recent_observations[:5]
        self.active_files = _unique_strings(
            [*summary.files_touched, *self.active_files],
            limit=10,
            max_chars=500,
        )
        if summary.next_steps:
            self.plan = [
                PlanItem(step=step, status=("in_progress" if index == 0 else "pending"))
                for index, step in enumerate(summary.next_steps[:12])
            ]
        self._touch()
        return True


def _permissions_from_boundary(runtime_boundary_model_view: dict[str, Any], *, permission_profile: str) -> PermissionsContext:
    profile = str(permission_profile or runtime_boundary_model_view.get("permission_profile") or "auto")
    return PermissionsContext(
        profile=profile,
        label=str(runtime_boundary_model_view.get("permission_label") or profile.replace("_", " ").title()),
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
        network=(
            "enabled"
            if bool(runtime_boundary_model_view.get("network_allowed"))
            else str(runtime_boundary_model_view.get("network_reason") or "disabled")
        ),
    )


def _current_step_from_context_manager(context_manager: ContextManager) -> str:
    for item in context_manager.recent_observations:
        summary = _truncate(item.summary, 500)
        if summary:
            return summary
    return ""


def _next_action_from_context_manager(context_manager: ContextManager) -> str:
    for item in context_manager.plan:
        if item.status in {"pending", "in_progress"}:
            step = _truncate(item.step, 500)
            if step:
                return step
    return ""


def _task_context_from_state(
    *,
    user_request: str,
    context_manager: ContextManager,
    task_state: dict[str, Any] | None = None,
) -> TaskContext:
    normalized_task = normalize_task_state(task_state or {})
    plan_items = [dict(item) for item in list(normalized_task.get("plan_items") or []) if isinstance(item, dict)]
    current_step_id = str(normalized_task.get("current_step_id") or "").strip()
    current_step = ""
    if current_step_id:
        current_step = next(
            (
                _truncate(item.get("step"), 500)
                for item in plan_items
                if str(item.get("id") or "").strip() == current_step_id and _truncate(item.get("step"), 500)
            ),
            "",
        )
    if not current_step:
        current_step = _truncate(
            normalized_task.get("next_required_action") or _current_step_from_context_manager(context_manager),
            500,
        )
    return TaskContext(
        user_request=_clean_text(user_request, limit=max(4000, len(str(user_request or "")))),
        goal=_truncate(normalized_task.get("goal") or normalize_user_message_preview(user_request, limit=140), 500),
        status=_truncate(normalized_task.get("status"), 80),
        current_step_id=_truncate(current_step_id, 120),
        current_step=current_step,
        next_action=_truncate(
            normalized_task.get("next_required_action") or _next_action_from_context_manager(context_manager),
            500,
        ),
        blocked_reason=_truncate(normalized_task.get("blocked_reason"), 500),
        completed_steps=_summary_strings(normalized_task.get("completed_steps"), limit=6, max_chars=240),
        failed_attempts=_summary_strings(normalized_task.get("failed_attempts"), limit=6, max_chars=240),
        validation_warnings=_summary_strings(normalized_task.get("validation_warnings"), limit=6, max_chars=240),
    )


def build_model_context(
    *,
    user_request: str,
    context_manager: ContextManager,
    runtime_boundary: Any,
    project_root: Path | str | None = None,
    cwd: Path | str | None = None,
    task_state: dict[str, Any] | None = None,
    work_cursor: dict[str, Any] | None = None,
    user_request_char_limit: int | None = None,
) -> ModelContext:
    boundary_model_view = runtime_boundary.to_model_view() if hasattr(runtime_boundary, "to_model_view") else dict(runtime_boundary or {})
    normalized_task = normalize_task_state(task_state or {})
    normalized_cursor = normalize_work_cursor(work_cursor or {})
    resolved_project_root = str(
        project_root
        or normalized_cursor.get("project_root")
        or boundary_model_view.get("project_root")
        or ""
    )
    resolved_cwd = str(
        cwd
        or normalized_cursor.get("cwd")
        or boundary_model_view.get("cwd")
        or resolved_project_root
    )
    clean_user_request = _clean_text(
        user_request,
        limit=max(4000, int(user_request_char_limit or 4000)),
    )
    active_files = _unique_strings(
        [*list(normalized_cursor.get("active_files") or []), *context_manager.active_files],
        limit=10,
        max_chars=500,
    )
    conversation = _normalize_clean_turns(context_manager.clean_turns, current_message=clean_user_request, limit=8)
    task_context = _task_context_from_state(
        user_request=clean_user_request,
        context_manager=context_manager,
        task_state=normalized_task,
    )
    plan_items = (
        [
            PlanItem(step=_truncate(item.get("step"), 500), status=str(item.get("status") or "pending"))
            for item in list(normalized_task.get("plan_items") or [])[:12]
            if isinstance(item, dict) and _truncate(item.get("step"), 500)
        ]
        if list(normalized_task.get("plan_items") or [])
        else context_manager.plan[:12]
    )
    return ModelContext(
        task=task_context,
        workspace=WorkspaceContext(
            project_root=str(resolved_project_root),
            cwd=str(resolved_cwd),
            model_visible_paths=active_files,
        ),
        memory=MemoryContext(
            clean_summary=_truncate(context_manager.clean_summary, 2000),
            active_files=active_files,
            recent_observations=context_manager.recent_observations[:5],
        ),
        plan=PlanContext(items=plan_items),
        permissions=_permissions_from_boundary(
            boundary_model_view,
            permission_profile=str(getattr(runtime_boundary, "permission_profile", "") or boundary_model_view.get("permission_profile") or ""),
        ),
        conversation=ConversationContext(recent_turns=conversation),
    )


def render_model_context(model_context: ModelContext) -> str:
    payload = {"model_context": dump_model(model_context)}
    return "model_context_json:\n" + json.dumps(payload, ensure_ascii=False)
