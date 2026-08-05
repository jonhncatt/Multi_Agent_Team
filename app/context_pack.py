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


class RecentObservation(BaseModel):
    source: str = ""
    tool: str = ""
    target: str = ""
    status: str = ""
    summary: str = ""
    source_refs: list[str] = Field(default_factory=list)


class VerifiedFact(BaseModel):
    text: str = ""
    source: str = ""
    source_ref: str = ""


class PlanItem(BaseModel):
    step: str = ""
    status: Literal["pending", "in_progress", "completed", "failed", "blocked"] = "pending"


class CompactionSummary(BaseModel):
    user_requirements: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    current_state: str = ""
    next_steps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    do_not_repeat: list[str] = Field(default_factory=list)


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
        for separator in ("/", "\\"):
            prefix = root + separator
            if value.startswith(prefix):
                # Whole path values become stable model-facing paths on every
                # host. Embedded prose keeps its original punctuation below.
                return value[len(prefix) :].replace("\\", "/")
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


def _file_strings(values: Any, *, limit: int = 10) -> list[str]:
    return _unique_strings(
        [
            item
            for item in list(values or [])
            if not re.match(r"^[a-z][a-z0-9+.-]*://", str(item or "").strip(), flags=re.IGNORECASE)
        ],
        limit=limit,
        max_chars=500,
    )


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
    if isinstance(raw_turns, (list, tuple)):
        iterator = reversed(raw_turns)
    else:
        iterator = reversed(list(raw_turns or []))
    for item in iterator:
        if not isinstance(item, dict):
            continue
        role = _truncate(item.get("role"), 40)
        if not _is_clean_role(role):
            continue
        original_text = str(item.get("text") or item.get("content") or "")
        raw_text = _clean_text(original_text, limit=20000)
        was_truncated = bool(item.get("truncated")) or len(original_text) > 1200
        if role == "user" and (
            raw_text == current_text
            or (was_truncated and len(raw_text) >= 1200 and current_text.startswith(raw_text))
        ):
            continue
        text = raw_text[:1200]
        if not text:
            continue
        if role == "assistant" and is_model_draft(text):
            continue
        turn: dict[str, Any] = {"role": role, "text": text}
        if was_truncated:
            turn["truncated"] = True
        selected.append(turn)
        if len(selected) >= limit:
            break
    return list(reversed(selected))


def _source_ref_text(value: Any) -> str:
    if isinstance(value, dict):
        direct = str(value.get("path") or value.get("file") or value.get("url") or value.get("ref") or "").strip()
        if direct:
            return direct[:500]
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:500]
    return str(value or "").strip()[:500]


def _normalize_source_refs(raw_values: Any, *, limit: int = 6) -> list[str]:
    return _unique_strings(
        [_source_ref_text(item) for item in list(raw_values or [])],
        limit=limit,
        max_chars=500,
    )


def _normalize_recent_observations(raw_values: Any) -> list[RecentObservation]:
    observations: list[RecentObservation] = []
    iterable = raw_values if isinstance(raw_values, (list, tuple)) else list(raw_values or [])
    for item in iterable:
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
                source_refs=_normalize_source_refs(item.get("source_refs"), limit=6),
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
    args = payload.get("arguments") or payload.get("args") or payload.get("normalized_arguments") or payload.get("input")
    if isinstance(args, dict):
        target = _truncate(args.get("path") or args.get("root") or args.get("cwd") or args.get("query"), 240)
    return {
        "source": "tool",
        "tool": tool,
        "target": target,
        "status": status,
        "summary": summary or f"{tool}:{status}",
        "source_refs": _normalize_source_refs(payload.get("source_refs"), limit=6),
    }


def _extract_active_files_from_events(tool_events: Any) -> list[str]:
    files: list[str] = []
    for event in list(tool_events or []):
        payload = dump_model(event)
        if not isinstance(payload, dict):
            continue
        tool = str(payload.get("name") or payload.get("tool") or payload.get("tool_name") or "").strip().lower()
        project_root = str(payload.get("project_root") or "").strip()
        if tool in _FILE_CONTEXT_TOOL_NAMES:
            for ref in list(payload.get("source_refs") or []):
                value = (
                    str(ref.get("path") or ref.get("file") or "")
                    if isinstance(ref, dict)
                    else str(ref or "")
                )
                if value and not re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE):
                    files.append(
                        _rebase_text_paths_for_model(value, project_root=project_root) if project_root else value
                    )
            args = payload.get("arguments") or payload.get("args") or payload.get("normalized_arguments") or payload.get("input")
            if isinstance(args, dict):
                value = str(args.get("path") or args.get("file") or args.get("dst_path") or "")
                if value:
                    files.append(_rebase_text_paths_for_model(value, project_root=project_root) if project_root else value)
    return _unique_strings(files, limit=10, max_chars=500)


_WRITE_TOOL_NAMES = {
    "apply_patch",
    "write_file",
    "save_skill",
    "archive_extract",
    "mail_extract_attachments",
    "web_download",
    "browser_screenshot",
}

_FILE_CONTEXT_TOOL_NAMES = {
    "read_file",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "read_section",
    "table_extract",
    "fact_check_file",
    "search_codebase",
    "image_inspect",
    "image_read",
    "apply_patch",
    "archive_extract",
    "mail_extract_attachments",
    "web_download",
    "browser_screenshot",
    "save_skill",
}

_NON_FACT_TOOL_NAMES = {
    "update_plan",
    "request_user_input",
    "load_skill",
    "save_skill",
    "sessions_list",
    "sessions_history",
}


def _extract_modified_files_from_events(tool_events: Any) -> list[str]:
    files: list[str] = []
    for event in list(tool_events or []):
        payload = dump_model(event)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"ok", "success", "completed", "complete", "done"}:
            continue
        tool = str(payload.get("name") or payload.get("tool") or payload.get("tool_name") or "").strip().lower()
        if tool not in _WRITE_TOOL_NAMES:
            continue
        args = payload.get("arguments") or payload.get("args") or payload.get("normalized_arguments") or payload.get("input")
        if tool == "apply_patch" and isinstance(args, dict) and bool(args.get("check")):
            continue
        project_root = str(payload.get("project_root") or "").strip()
        for ref in list(payload.get("source_refs") or []):
            if isinstance(ref, dict):
                value = str(ref.get("path") or ref.get("file") or "")
            else:
                value = str(ref or "")
            if value and not re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE):
                files.append(_rebase_text_paths_for_model(value, project_root=project_root) if project_root else value)
        if isinstance(args, dict):
            value = str(args.get("path") or args.get("file") or args.get("dst_path") or "")
            if value:
                files.append(_rebase_text_paths_for_model(value, project_root=project_root) if project_root else value)
        result_preview = payload.get("result_preview")
        if isinstance(result_preview, dict):
            files.extend(
                _rebase_text_paths_for_model(str(item or ""), project_root=project_root) if project_root else str(item or "")
                for item in list(result_preview.get("files") or [])
            )
    return _unique_strings(files, limit=10, max_chars=500)


def extract_modified_files_from_events(tool_events: Any) -> list[str]:
    """Return files changed by successful write tools using the real ToolEvent wire shape."""

    return _extract_modified_files_from_events(tool_events)


def _verified_facts_from_events(tool_events: Any) -> list[VerifiedFact]:
    facts: list[VerifiedFact] = []
    for event in list(tool_events or []):
        payload = dump_model(event)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"ok", "success", "completed", "complete", "done"}:
            continue
        text = _truncate(payload.get("summary") or payload.get("message"), 500)
        tool = _truncate(payload.get("name") or payload.get("tool") or payload.get("tool_name"), 120)
        if not text or tool.lower() in _NON_FACT_TOOL_NAMES:
            continue
        refs = _normalize_source_refs(payload.get("source_refs"), limit=6)
        args = payload.get("arguments") or payload.get("args") or payload.get("normalized_arguments") or payload.get("input")
        argument_ref = ""
        if isinstance(args, dict):
            argument_ref = _truncate(
                args.get("path")
                or args.get("file")
                or args.get("url")
                or args.get("cmd")
                or args.get("query"),
                400,
            )
        source_ref = refs[0] if refs else (
            f"{tool}:{argument_ref}" if argument_ref else f"tool:{tool or 'runtime'}"
        )
        project_root = str(payload.get("project_root") or "").strip()
        if project_root and source_ref and not re.match(r"^[a-z][a-z0-9+.-]*://", source_ref, flags=re.IGNORECASE):
            source_ref = _rebase_text_paths_for_model(source_ref, project_root=project_root)
        facts.append(VerifiedFact(text=text, source=tool or "runtime", source_ref=source_ref))
        if len(facts) >= 12:
            break
    return facts


def _normalize_verified_facts(raw_values: Any) -> list[VerifiedFact]:
    facts: list[VerifiedFact] = []
    seen: set[tuple[str, str]] = set()
    for item in list(raw_values or []):
        if not isinstance(item, dict):
            continue
        text = _truncate(item.get("text") or item.get("summary"), 500)
        source = _truncate(item.get("source") or item.get("tool"), 120)
        raw_source_ref = item.get("source_ref")
        source_ref = _source_ref_text(raw_source_ref)
        if not source_ref:
            refs = _normalize_source_refs(item.get("source_refs"), limit=6)
            source_ref = refs[0] if refs else (f"tool:{source}" if source else "")
        key = (text, source_ref)
        if not text or not source_ref or key in seen:
            continue
        seen.add(key)
        facts.append(VerifiedFact(text=text, source=source or "runtime", source_ref=source_ref))
        if len(facts) >= 12:
            break
    return facts


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
    # ``task_state``/``work_cursor`` remain accepted for source compatibility
    # with older callers, but compaction memory is intentionally derived from
    # the thread transcript and tool evidence only. Harness state is not model
    # history and must not be smuggled back into a Session=Thread summary.
    _ = task_state, work_cursor, current_status
    messages = []
    raw_old_messages = list(old_messages or [])
    for item in raw_old_messages[-24:]:
        turn = _compact_turn_for_compaction(item)
        if turn:
            messages.append(turn)
    evidence = _normalize_compaction_tool_evidence(tool_evidence)
    files = _unique_strings(
        list(modified_files or []),
        limit=16,
        max_chars=500,
    )
    failures = _summary_strings(
        [
            *list(failed_attempts or []),
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
        "modified_files": files,
        "failed_attempts": failures,
    }


def normalize_compaction_summary(raw: Any) -> CompactionSummary:
    if isinstance(raw, CompactionSummary):
        return raw
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    return CompactionSummary(
        user_requirements=_summary_strings(payload.get("user_requirements"), limit=12, max_chars=500),
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
    evidence = [dict(item) for item in list(payload.get("tool_evidence") or []) if isinstance(item, dict)]
    confirmed: list[str] = []
    user_requirements: list[str] = []
    decisions: list[str] = []
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    evidence_files: list[str] = []
    for item in evidence:
        status = str(item.get("status") or "").strip().lower()
        summary = _truncate(item.get("summary"), 500)
        if not summary:
            continue
        if status in {"ok", "success", "completed", "complete", "done"}:
            confirmed.append(summary)
        target = _truncate(item.get("target"), 500)
        if target:
            evidence_files.append(target)
        evidence_files.extend(_file_strings(item.get("source_refs"), limit=6))
    for item in list(payload.get("old_messages") or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        text = _truncate(item.get("text"), 500)
        if not text:
            continue
        if role == "assistant":
            assistant_messages.append(text)
            continue
        if role != "user":
            continue
        user_messages.append(text)
        normalized_text = text.lower()
        requirement_markers = (
            "必须", "不要", "不能", "只", "禁止", "要求", "需要", "务必",
            "must", "should", "only", "do not", "don't", "never", "require",
        )
        if text and any(marker in normalized_text for marker in requirement_markers):
            user_requirements.append(text)
    # Always preserve the most recent earlier user request. It is the most
    # useful continuation anchor even when it contains no requirement keyword.
    if user_messages:
        user_requirements.append(user_messages[-1])
    failed = _summary_strings(payload.get("failed_attempts"), limit=12, max_chars=500)
    do_not_repeat = []
    for item in failed[:6]:
        do_not_repeat.append(f"Avoid repeating without new evidence: {item}")
    current_state = ""
    if assistant_messages:
        current_state = "Earlier assistant response (unverified): " + assistant_messages[-1]
    return CompactionSummary(
        user_requirements=_unique_strings(user_requirements, limit=12, max_chars=500),
        confirmed_facts=_unique_strings(confirmed, limit=12, max_chars=500),
        files_touched=_unique_strings(
            [*list(payload.get("modified_files") or []), *evidence_files],
            limit=16,
            max_chars=500,
        ),
        decisions=_unique_strings(decisions, limit=10, max_chars=500),
        failed_attempts=failed,
        current_state=current_state,
        next_steps=[],
        open_questions=[],
        do_not_repeat=_unique_strings(do_not_repeat, limit=8, max_chars=500),
    )


def render_compaction_prompt(compaction_input: dict[str, Any]) -> str:
    payload = dict(compaction_input or {})
    schema = {
        "user_requirements": ["explicit user requirements and constraints"],
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
        "The result is unverified continuation memory, not Harness task state.\n"
        "Use only the supplied transcript and source-marked tool evidence. Never invent plan status, completion, or verification.\n"
        "Use only concise durable facts needed to continue the task.\n\n"
        "schema:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\ncompaction_input:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )


def render_compaction_summary(summary: CompactionSummary | dict[str, Any], *, generation: int | None = None) -> str:
    payload = normalize_compaction_summary(summary)
    sections: list[tuple[str, list[str] | str]] = [
        ("user_requirements", payload.user_requirements),
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


def _has_context_manager_data(payload: dict[str, Any]) -> bool:
    try:
        context_version = int(payload.get("context_version") or 0)
    except Exception:
        context_version = 0
    try:
        schema_version = int(payload.get("schema_version") or 0)
    except Exception:
        schema_version = 0
    return bool(
        str(payload.get("working_summary") or payload.get("clean_summary") or "").strip()
        or list(payload.get("recent_turns") or payload.get("clean_turns") or [])
        or list(payload.get("recent_tool_results") or payload.get("recent_observations") or [])
        or list(payload.get("relevant_files") or payload.get("active_files") or [])
        or list(payload.get("modified_files") or [])
        or list(payload.get("verified_facts") or [])
        or list(payload.get("plan") or [])
        or schema_version >= 2
        or context_version > 0
    )


class ContextManager(BaseModel):
    schema_version: Literal[2] = 2
    working_summary: str = ""
    recent_turns: list[dict[str, Any]] = Field(default_factory=list)
    recent_tool_results: list[RecentObservation] = Field(default_factory=list)
    verified_facts: list[VerifiedFact] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    user_requirements: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    context_version: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ContextManager":
        raw = dict(payload or {})
        try:
            context_version = max(0, int(raw.get("context_version") or 0))
        except Exception:
            context_version = 0
        return cls(
            working_summary=_truncate(raw.get("working_summary") or raw.get("clean_summary"), 4000),
            recent_turns=_normalize_clean_turns(raw.get("recent_turns") or raw.get("clean_turns"), current_message="", limit=16),
            recent_tool_results=_normalize_recent_observations(
                raw.get("recent_tool_results") or raw.get("recent_observations")
            ),
            verified_facts=_normalize_verified_facts(raw.get("verified_facts")),
            relevant_files=_file_strings(raw.get("relevant_files") or raw.get("active_files"), limit=10),
            modified_files=_file_strings(raw.get("modified_files"), limit=10),
            user_requirements=_summary_strings(raw.get("user_requirements"), limit=12, max_chars=500),
            decisions=_summary_strings(raw.get("decisions"), limit=10, max_chars=500),
            open_questions=_summary_strings(raw.get("open_questions"), limit=8, max_chars=500),
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
            "schema_version": 2,
            "working_summary": self.working_summary,
            "recent_turns": [dict(item) for item in self.recent_turns],
            "recent_tool_results": [dump_model(item) for item in self.recent_tool_results[:5]],
            "verified_facts": [dump_model(item) for item in self.verified_facts[:12]],
            "relevant_files": list(self.relevant_files[:10]),
            "modified_files": list(self.modified_files[:10]),
            "user_requirements": list(self.user_requirements[:12]),
            "decisions": list(self.decisions[:10]),
            "open_questions": list(self.open_questions[:8]),
            "context_version": int(self.context_version),
        }
