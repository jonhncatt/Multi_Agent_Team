from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


_ATTACHMENT_CONTEXT_CLEAR_HINTS = (
    "忽略之前附件",
    "忽略附件",
    "不要参考附件",
    "别参考附件",
    "不要用附件",
    "不基于附件",
    "清空附件",
    "reset attachments",
    "clear attachments",
    "ignore previous attachment",
    "ignore previous attachments",
)
_ATTACHMENT_CONTEXT_FILE_HINTS = (
    "附件",
    "图片",
    "截图",
    "照片",
    "邮件",
    "邮箱",
    "msg",
    "email",
    "文档",
    "pdf",
    "docx",
    "xlsx",
    "pptx",
    "这个pdf",
    "这个文档",
    "这个文件",
    "上个pdf",
    "上个文档",
    "上个文件",
    "上一个附件",
    "上一个截图",
    "上一个图片",
    "this image",
    "this screenshot",
    "image",
    "screenshot",
)
_ATTACHMENT_CONTEXT_REFERENCE_HINTS = (
    "这个",
    "这份",
    "上个",
    "上一个",
    "刚才",
    "刚刚",
    "之前",
    "前面",
    "那个",
    "this",
    "that",
    "previous",
    "last",
)
_ATTACHMENT_CONTEXT_ACTION_HINTS = (
    "继续",
    "接着",
    "解析",
    "识别",
    "ocr",
    "转录",
    "抄录",
    "总结",
    "概括",
    "解读",
    "翻译",
    "提取",
    "原文",
    "文中",
    "出现",
    "用法",
    "语法",
    "什么意思",
    "查找",
    "看到",
    "看到了",
    "看一下",
    "继续看",
    "继续读",
    "continue",
    "transcribe",
    "extract text",
    "summarize",
    "analyze",
    "extract",
    "find",
)
_EXPLICIT_NEW_TASK_HINTS = (
    "新任务",
    "新问题",
    "另外",
    "另一个",
    "换个",
    "重新开始",
    "从头开始",
    "忽略上一个任务",
    "忽略刚才",
    "别看刚才",
    "new task",
    "another task",
    "different task",
    "ignore previous task",
    "start over",
)
_TASK_FOLLOWUP_HINTS = (
    "继续",
    "接着",
    "刚才",
    "刚刚",
    "前面",
    "上一步",
    "然后",
    "接下来",
    "这个文件",
    "这个附件",
    "这个图片",
    "这个截图",
    "这段代码",
    "该文件",
    "该图片",
    "当前文件夹",
    "当前目录",
    "当前项目",
    "当前仓库",
    "在当前文件夹",
    "在当前目录",
    "修改它",
    "修它",
    "改它",
    "让其修改",
    "continue",
    "same task",
    "current folder",
    "current directory",
    "this file",
    "that file",
    "it",
    "them",
)
_TASK_RECALL_HINTS = (
    "还记得",
    "记得吗",
    "我刚刚让你",
    "我之前让你",
    "我刚刚问你什么了",
    "我刚才问你什么了",
    "我刚刚问了什么",
    "我刚才问了什么",
    "刚刚我问你什么了",
    "刚才我问你什么了",
    "刚刚我问了什么",
    "刚才我问了什么",
    "我刚才问你的所有问题",
    "我问你的所有问题",
    "刚刚让你",
    "之前让你",
    "上一个任务",
    "上一条任务",
    "上一张",
    "上张图",
    "那张图",
    "那个截图",
    "那封邮件",
    "上一封邮件",
    "上个附件",
    "上一个附件",
    "what did i ask",
    "remember",
    "previous image",
    "previous email",
)
_TASK_SUBJECT_FOLLOWUP_HINTS = (
    "题目",
    "题目呢",
    "标题",
    "标题呢",
    "邮件题目",
    "邮件标题",
    "subject",
    "subject line",
    "email subject",
    "title",
    "title only",
    "件名",
    "メール件名",
)
_TASK_SHORT_ACTION_HINTS = (
    "修改",
    "修复",
    "实现",
    "继续",
    "解释",
    "分析",
    "看下",
    "看看",
    "读一下",
    "读取",
    "运行",
    "测试",
    "改一下",
    "修一下",
)
_IMAGE_HINTS = ("图片", "截图", "照片", "image", "screenshot", "photo", "png", "jpg", "jpeg", "gif", "webp", "heic")
_MAIL_HINTS = ("邮件", "邮箱", "msg", ".msg", "email", "mail", "outlook", "信件", "メール", "件名")
_DOCUMENT_HINTS = ("pdf", "文档", "docx", "xlsx", "pptx", "表格", "幻灯片", "文件")
_RESET_FOCUS_HINTS = (
    "忽略刚才",
    "忽略之前",
    "重新开始",
    "从头开始",
    "new task",
    "start over",
)
_RECENT_USER_LIST_HINTS = (
    "我刚才问你的所有问题",
    "我问你的所有问题",
    "list all my questions",
    "list my recent questions",
    "what were my recent questions",
)
_RECENT_USER_LAST_HINTS = (
    "我刚刚问你什么了",
    "我刚才问你什么了",
    "我刚刚问了什么",
    "我刚才问了什么",
    "刚刚我问你什么了",
    "刚才我问你什么了",
    "刚刚我问了什么",
    "刚才我问了什么",
    "what did i just ask",
    "what was my last question",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_attachment_ids(raw_ids: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids or []:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _dedupe_strings(values: list[Any] | None, *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _normalize_attachment_refs(raw: Any, *, limit: int = 8) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in list(raw or [])[:limit]:
        if not isinstance(item, dict):
            continue
        ref = {
            "id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "kind": str(item.get("kind") or "").strip(),
            "path": str(item.get("path") or "").strip(),
        }
        key = ref["id"] or ref["path"] or ref["name"]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def compat_task_checkpoint_from_focus(raw: Any) -> dict[str, Any]:
    focus = normalize_current_task_focus(raw)
    return {
        "task_id": focus["task_id"],
        "goal": focus["goal"],
        "project_root": focus["project_root"],
        "cwd": focus["cwd"],
        "active_files": list(focus["active_files"]),
        "active_attachments": [dict(item) for item in focus["active_attachments"]],
        "last_completed_step": focus["last_completed_step"],
        "next_action": focus["next_action"],
    }


def normalize_current_task_focus(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "task_id": str(raw.get("task_id") or "").strip(),
        "goal": str(raw.get("goal") or "").strip(),
        "project_root": str(raw.get("project_root") or "").strip(),
        "cwd": str(raw.get("cwd") or "").strip(),
        "active_files": _dedupe_strings(list(raw.get("active_files") or []), limit=8),
        "active_attachments": _normalize_attachment_refs(raw.get("active_attachments"), limit=8),
        "last_completed_step": str(raw.get("last_completed_step") or "").strip(),
        "next_action": str(raw.get("next_action") or "").strip(),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def normalize_work_cursor(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "project_root": str(raw.get("project_root") or "").strip(),
        "cwd": str(raw.get("cwd") or "").strip(),
        "active_files": _dedupe_strings(list(raw.get("active_files") or []), limit=8),
        "active_attachments": _normalize_attachment_refs(raw.get("active_attachments"), limit=8),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


_TASK_STEP_COMPLETED_STATUSES = {"completed", "complete", "done", "success", "succeeded"}
_TASK_STEP_FAILED_STATUSES = {"failed", "error", "blocked"}


def _stable_step_id(step: str, index: int) -> str:
    text = str(step or "").strip()
    if not text:
        return f"step-{index + 1}"
    digest = uuid.uuid5(uuid.NAMESPACE_URL, f"task-step:{text}").hex[:10]
    return f"step-{digest}"


def _as_text_list(raw: Any, *, limit: int = 8) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]
    return _dedupe_strings(values, limit=limit)


def _normalize_evidence_refs(raw: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    if raw is None:
        values: list[Any] = []
    elif isinstance(raw, (str, dict)):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            ref = {k: v for k, v in dict(value).items() if v not in (None, "", [], {})}
        else:
            label = str(value or "").strip()
            if not label:
                continue
            ref = {"ref": label}
        key = repr(sorted(ref.items()))
        if not ref or key in seen:
            continue
        seen.add(key)
        refs.append(ref)
        if len(refs) >= limit:
            break
    return refs


def _merge_text_lists(*collections: Any, limit: int = 8) -> list[str]:
    merged: list[Any] = []
    for collection in collections:
        merged.extend(_as_text_list(collection, limit=limit * 2))
    return _dedupe_strings(merged, limit=limit)


def _merge_evidence_refs(*collections: Any, limit: int = 12) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection in collections:
        for ref in _normalize_evidence_refs(collection, limit=limit * 2):
            key = repr(sorted(ref.items()))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
            if len(refs) >= limit:
                return refs
    return refs


def normalize_task_plan_items(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(list(raw or [])):
        if not isinstance(item, dict):
            continue
        raw_step = str(item.get("step") or item.get("title") or item.get("label") or "").strip()
        description = str(item.get("description") or item.get("content") or "").strip()
        step = raw_step
        if description and (
            not step
            or re.fullmatch(r"(?:step\s*)?\d+", step, flags=re.IGNORECASE)
            or re.fullmatch(r"(?:第\s*)?\d+\s*步", step)
            or re.fullmatch(r"步骤\s*\d+", step)
        ):
            step = description
        if not step:
            continue
        step_id = str(item.get("id") or item.get("step_id") or _stable_step_id(step, index)).strip()
        status = _normalize_step_status(item.get("status"), default="pending") or "pending"
        items.append(
            {
                **dict(item),
                "id": step_id,
                "step": step,
                "status": status,
                "progress_basis": _as_text_list(item.get("progress_basis"), limit=8),
                "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs"), limit=12),
                "completed_at": str(item.get("completed_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            }
        )
    return items


def _normalize_completed_steps(raw: Any) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(list(raw or [])):
        if isinstance(item, dict):
            step = str(item.get("step") or item.get("summary") or item.get("title") or "").strip()
            step_id = str(item.get("id") or item.get("step_id") or (_stable_step_id(step, index) if step else "")).strip()
            payload = dict(item)
        else:
            step = str(item or "").strip()
            step_id = _stable_step_id(step, index) if step else ""
            payload = {}
        key = step_id or step
        if not key or key in seen:
            continue
        seen.add(key)
        completed.append(
            {
                **payload,
                "id": step_id,
                "step": step,
                "progress_basis": _as_text_list(item.get("progress_basis"), limit=8),
                "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs"), limit=12),
                "completed_at": str((payload.get("completed_at") or payload.get("updated_at") or "")).strip(),
                "updated_at": str(payload.get("updated_at") or "").strip(),
            }
        )
    return completed


def _normalize_failed_attempts(raw: Any) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(raw or []):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or item.get("error") or "").strip()
        tool = str(item.get("tool") or item.get("name") or "").strip()
        step_id = str(item.get("step_id") or item.get("id") or "").strip()
        key = "|".join([tool, step_id, summary])
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        attempts.append(
            {
                **dict(item),
                "tool": tool,
                "summary": summary[:500],
                "step_id": step_id,
                "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs"), limit=12),
                "created_at": str(item.get("created_at") or item.get("updated_at") or "").strip(),
            }
        )
    return attempts


def _normalize_validation_warnings(raw: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(raw or [])[:24]:
        if isinstance(item, dict):
            code = str(item.get("code") or "task_state_validation").strip()
            message = str(item.get("message") or item.get("summary") or "").strip()
            step_id = str(item.get("step_id") or item.get("id") or "").strip()
            severity = str(item.get("severity") or "warning").strip() or "warning"
            created_at = str(item.get("created_at") or item.get("updated_at") or "").strip()
        else:
            code = "task_state_validation"
            message = str(item or "").strip()
            step_id = ""
            severity = "warning"
            created_at = ""
        key = "|".join([code, step_id, message])
        if not message or key in seen:
            continue
        seen.add(key)
        warnings.append(
            {
                "code": code[:120],
                "message": message[:500],
                "step_id": step_id[:120],
                "severity": severity[:40],
                "created_at": created_at,
            }
        )
    return warnings


def _task_warning(
    code: str,
    message: str,
    *,
    step_id: str = "",
    created_at: str = "",
    severity: str = "warning",
) -> dict[str, Any]:
    return {
        "code": str(code or "task_state_validation").strip()[:120],
        "message": str(message or "").strip()[:500],
        "step_id": str(step_id or "").strip()[:120],
        "severity": str(severity or "warning").strip()[:40],
        "created_at": str(created_at or "").strip(),
    }


def _normalize_step_status(value: Any, *, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "none"}:
        return default
    if raw in _TASK_STEP_COMPLETED_STATUSES:
        return "completed"
    if raw in {"in_progress", "in-progress", "active", "doing", "working"}:
        return "in_progress"
    if raw in {"pending", "todo", "not_started", "not-started"}:
        return "pending"
    if raw in {"failed", "error", "failure"}:
        return "failed"
    if raw in {"blocked", "waiting"}:
        return "blocked"
    return raw


def normalize_task_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    plan_items = normalize_task_plan_items(raw.get("plan_items") or raw.get("plan") or [])
    completed_steps = _derive_completed_steps(
        plan_items,
        raw.get("completed_steps") or [],
        str(raw.get("updated_at") or "").strip(),
    )
    raw_current_step_id = str(raw.get("current_step_id") or "").strip()
    known_step_ids = {str(item.get("id") or "").strip() for item in plan_items if str(item.get("id") or "").strip()}
    current_step_id = raw_current_step_id if raw_current_step_id in known_step_ids else derive_current_step_id(plan_items)
    raw_status = _normalize_step_status(raw.get("status"), default=str(raw.get("status") or "idle").strip() or "idle")
    if raw_status in {"blocked", "failed", "cancelled"}:
        status = raw_status
    elif plan_items and all(str(item.get("status") or "").strip() in _TASK_STEP_COMPLETED_STATUSES for item in plan_items):
        status = "completed"
    elif plan_items:
        status = raw_status if raw_status in {"in_progress", "pending"} else "in_progress"
    else:
        status = raw_status or "idle"
    return {
        "task_id": str(raw.get("task_id") or "").strip(),
        "goal": str(raw.get("goal") or "").strip(),
        "status": status,
        "plan_items": plan_items,
        "current_step_id": current_step_id,
        "completed_steps": completed_steps,
        "failed_attempts": _normalize_failed_attempts(raw.get("failed_attempts") or []),
        "blocked_reason": str(raw.get("blocked_reason") or "").strip(),
        "next_required_action": str(raw.get("next_required_action") or raw.get("next_action") or "").strip(),
        "progress_basis": _as_text_list(raw.get("progress_basis"), limit=8),
        "evidence_refs": _normalize_evidence_refs(raw.get("evidence_refs"), limit=12),
        "validation_warnings": _normalize_validation_warnings(raw.get("validation_warnings") or []),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def task_state_has_checkpoint(raw: Any) -> bool:
    task = normalize_task_state(raw)
    return bool(
        task.get("task_id")
        or task.get("goal")
        or list(task.get("plan_items") or [])
        or str(task.get("current_step_id") or "").strip()
        or list(task.get("completed_steps") or [])
        or list(task.get("failed_attempts") or [])
    )


def derive_current_step_id(plan_items: Any) -> str:
    items = normalize_task_plan_items(plan_items)
    for item in items:
        if str(item.get("status") or "").strip() == "in_progress":
            return str(item.get("id") or "").strip()
    for item in items:
        status = str(item.get("status") or "").strip()
        if status not in _TASK_STEP_COMPLETED_STATUSES and status not in _TASK_STEP_FAILED_STATUSES:
            return str(item.get("id") or "").strip()
    return ""


def _derive_completed_steps(plan_items: Any, previous_completed: Any, now: str = "") -> list[dict[str, Any]]:
    items = normalize_task_plan_items(plan_items)
    prior_items = _normalize_completed_steps(previous_completed or [])
    prior_by_id = {str(item.get("id") or "").strip(): item for item in prior_items if str(item.get("id") or "").strip()}
    prior_by_step = {
        str(item.get("step") or "").strip().lower(): item
        for item in prior_items
        if str(item.get("step") or "").strip()
    }
    completed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if str(item.get("status") or "").strip() not in _TASK_STEP_COMPLETED_STATUSES:
            continue
        step = str(item.get("step") or "").strip()
        step_id = str(item.get("id") or _stable_step_id(step, index)).strip()
        prior = prior_by_id.get(step_id) or prior_by_step.get(step.lower())
        completed.append(
            {
                "id": step_id,
                "step": step,
                "completed_at": str(item.get("completed_at") or ((prior or {}).get("completed_at")) or now or "").strip(),
                "updated_at": str(item.get("updated_at") or ((prior or {}).get("updated_at")) or now or "").strip(),
                "progress_basis": _as_text_list(item.get("progress_basis") or ((prior or {}).get("progress_basis")), limit=8),
                "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs") or ((prior or {}).get("evidence_refs")), limit=12),
            }
        )
    return completed


def _normalize_task_state_step_updates(raw: Any) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for item in list(raw or [])[:16]:
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("step_id") or item.get("id") or "").strip()
        if not step_id:
            continue
        updates.append(
            {
                "step_id": step_id,
                "status": _normalize_step_status(item.get("status"), default=""),
                "progress_basis": _as_text_list(item.get("progress_basis"), limit=8),
                "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs"), limit=12),
                "blocked_reason": str(item.get("blocked_reason") or "").strip()[:500],
                "summary": str(item.get("summary") or "").strip()[:500],
            }
        )
    return updates


def normalize_task_state_delta(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    step_updates = _normalize_task_state_step_updates(
        raw.get("step_updates")
        or raw.get("steps")
        or raw.get("updates")
        or []
    )
    if not step_updates:
        for item in _normalize_completed_steps(raw.get("completed_steps") or raw.get("completed") or []):
            step_id = str(item.get("id") or item.get("step_id") or "").strip()
            if not step_id:
                continue
            step_updates.append(
                {
                    "step_id": step_id,
                    "status": "completed",
                    "progress_basis": _as_text_list(item.get("progress_basis"), limit=8),
                    "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs"), limit=12),
                    "blocked_reason": "",
                    "summary": "",
                }
            )
    failed_attempts = _normalize_failed_attempts(raw.get("failed_attempts") or raw.get("failures") or [])
    return {
        "status": _normalize_step_status(raw.get("status"), default=""),
        "current_step_id": str(raw.get("current_step_id") or "").strip(),
        "step_updates": step_updates,
        "failed_attempts": failed_attempts,
        "blocked_reason": str(raw.get("blocked_reason") or "").strip()[:500],
        "next_required_action": str(raw.get("next_required_action") or raw.get("next_action") or "").strip()[:500],
        "progress_basis": _as_text_list(raw.get("progress_basis"), limit=8),
        "evidence_refs": _normalize_evidence_refs(raw.get("evidence_refs"), limit=12),
    }


def _tool_event_evidence(event: dict[str, Any]) -> list[dict[str, Any]]:
    tool = str(event.get("name") or event.get("tool") or "").strip()
    refs = _normalize_evidence_refs(event.get("evidence_refs") or event.get("source_refs"), limit=12)
    evidence: list[dict[str, Any]] = []
    for ref in refs:
        evidence.append({"source": "tool", "tool": tool, **dict(ref)})
    if not evidence:
        summary = str(event.get("summary") or event.get("output_preview") or event.get("result_summary") or "").strip()
        if summary or tool:
            evidence.append({"source": "tool", "tool": tool, "summary": summary[:240]})
    return evidence


def _tool_event_progress(event: dict[str, Any]) -> str:
    tool = str(event.get("name") or event.get("tool") or "").strip() or "tool"
    summary = str(event.get("summary") or event.get("output_preview") or event.get("result_summary") or "").strip()
    if not summary:
        summary = str(event.get("status") or "").strip()
    return f"{tool}: {summary}"[:500] if summary else tool[:500]


def _runtime_error_summary(runtime_error: Any) -> str:
    if isinstance(runtime_error, dict):
        message = str(runtime_error.get("message") or runtime_error.get("kind") or runtime_error.get("exception_type") or "").strip()
    else:
        message = str(runtime_error or "").strip()
    return message[:500]


def _pending_user_action(pending_user_input: Any) -> str:
    if not isinstance(pending_user_input, dict):
        return ""
    return str(
        pending_user_input.get("summary")
        or pending_user_input.get("question")
        or pending_user_input.get("prompt")
        or pending_user_input.get("message")
        or ""
    ).strip()[:500]


def _merge_plan_items_with_history(previous_items: Any, incoming_plan: Any) -> list[dict[str, Any]]:
    prior_items = normalize_task_plan_items(previous_items or [])
    next_items = normalize_task_plan_items(incoming_plan if incoming_plan else prior_items)
    prior_by_id = {str(item.get("id") or ""): item for item in prior_items if str(item.get("id") or "").strip()}
    prior_by_step = {str(item.get("step") or "").strip().lower(): item for item in prior_items if str(item.get("step") or "").strip()}
    merged_items: list[dict[str, Any]] = []
    for item in next_items:
        prior = prior_by_id.get(str(item.get("id") or "")) or prior_by_step.get(str(item.get("step") or "").strip().lower())
        if not prior:
            merged_items.append(dict(item))
            continue
        merged_items.append(
            {
                **dict(prior),
                **dict(item),
                "id": str(prior.get("id") or item.get("id") or "").strip(),
                "progress_basis": _merge_text_lists(prior.get("progress_basis"), item.get("progress_basis"), limit=8),
                "evidence_refs": _merge_evidence_refs(prior.get("evidence_refs"), item.get("evidence_refs"), limit=12),
                "completed_at": str(item.get("completed_at") or prior.get("completed_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or prior.get("updated_at") or "").strip(),
            }
        )
    return merged_items


def _step_kind(step: str) -> str:
    text = str(step or "").strip().lower()
    if not text:
        return "generic"
    modify_hints = (
        "modify",
        "patch",
        "edit",
        "write",
        "implement",
        "fix",
        "change",
        "update",
        "refactor",
        "rename",
        "修改",
        "修复",
        "实现",
        "编辑",
        "改动",
        "补",
    )
    verify_hints = (
        "test",
        "verify",
        "validation",
        "validate",
        "check",
        "compile",
        "lint",
        "smoke",
        "run tests",
        "测试",
        "验证",
        "检查",
        "编译",
        "回归",
    )
    inspect_hints = (
        "inspect",
        "read",
        "search",
        "review",
        "look",
        "analyze",
        "trace",
        "find",
        "survey",
        "browse",
        "看",
        "读",
        "搜",
        "检查现状",
        "分析",
        "定位",
        "查找",
    )
    if any(hint in text for hint in modify_hints):
        return "modify"
    if any(hint in text for hint in verify_hints):
        return "verify"
    if any(hint in text for hint in inspect_hints):
        return "inspect"
    return "generic"


def _event_tool_name(event: dict[str, Any]) -> str:
    return str(event.get("name") or event.get("tool") or "").strip().lower()


def _event_status(event: dict[str, Any]) -> str:
    return str(event.get("status") or "").strip().lower()


def _event_returncode(event: dict[str, Any]) -> int | None:
    diagnostics = dict(event.get("diagnostics") or {}) if isinstance(event.get("diagnostics"), dict) else {}
    if diagnostics.get("returncode") not in (None, ""):
        try:
            return int(diagnostics.get("returncode"))
        except Exception:
            return None
    preview = dict(event.get("result_preview") or {}) if isinstance(event.get("result_preview"), dict) else {}
    if preview.get("returncode") not in (None, ""):
        try:
            return int(preview.get("returncode"))
        except Exception:
            return None
    return None


def _event_command(event: dict[str, Any]) -> str:
    for key in ("normalized_arguments", "input"):
        payload = dict(event.get(key) or {}) if isinstance(event.get(key), dict) else {}
        command = str(payload.get("cmd") or payload.get("command") or "").strip()
        if command:
            return command
    return ""


def _event_has_file_change(event: dict[str, Any]) -> bool:
    tool_name = _event_tool_name(event)
    if tool_name == "apply_patch":
        return True
    preview = dict(event.get("result_preview") or {}) if isinstance(event.get("result_preview"), dict) else {}
    files = list(preview.get("files") or [])
    if any(str(item or "").strip() for item in files):
        return True
    summary = str(event.get("summary") or "").strip().lower()
    return any(token in summary for token in ("patched", "updated", "modified", "created", "edited", "rewrote"))


def _event_matches_ref(event: dict[str, Any], ref: dict[str, Any]) -> bool:
    if not isinstance(ref, dict):
        return False
    expected_tool = str(ref.get("tool") or "").strip().lower()
    event_tool = _event_tool_name(event)
    if expected_tool and expected_tool != event_tool:
        return False
    haystacks = [
        event_tool,
        str(event.get("summary") or "").strip(),
        str(event.get("output_preview") or "").strip(),
        str(event.get("cwd") or "").strip(),
        _event_command(event),
    ]
    haystacks.extend(str(item or "").strip() for item in list(event.get("source_refs") or [])[:12])
    preview = dict(event.get("result_preview") or {}) if isinstance(event.get("result_preview"), dict) else {}
    haystacks.extend(
        str(preview.get(key) or "").strip()
        for key in ("path", "url", "summary", "command")
    )
    for key in ("ref", "path", "summary", "cmd", "command"):
        expected = str(ref.get(key) or "").strip()
        if not expected:
            continue
        expected_lower = expected.lower()
        if not any(expected_lower in str(item or "").lower() for item in haystacks if str(item or "").strip()):
            return False
    return True


def _resolve_evidence_events(tool_events: Any, evidence_refs: Any) -> list[dict[str, Any]]:
    events = [dict(item) for item in list(tool_events or []) if isinstance(item, dict)]
    refs = _normalize_evidence_refs(evidence_refs, limit=12)
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        for event in events:
            if not _event_matches_ref(event, ref):
                continue
            key = repr(sorted(event.items()))
            if key in seen:
                continue
            seen.add(key)
            matched.append(event)
    return matched


def _events_support_step(step_kind: str, events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    if step_kind == "inspect":
        return any(
            _event_status(event) in {"ok", "success", "completed", "complete", "done"}
            and _event_tool_name(event)
            in {
                "read_file",
                "read_section",
                "search_contents_in_file",
                "search_contents_in_file_multi",
                "search_codebase",
                "list_dir",
                "glob_file_search",
                "table_extract",
                "fact_check_file",
                "sessions_list",
                "sessions_history",
                "web_search",
                "web_fetch",
                "image_read",
                "image_inspect",
            }
            for event in events
        )
    if step_kind == "modify":
        return any(
            _event_status(event) in {"ok", "success", "completed", "complete", "done"}
            and _event_has_file_change(event)
            for event in events
        )
    if step_kind == "verify":
        return any(
            _event_tool_name(event) == "exec_command"
            and _event_status(event) in {"ok", "success", "completed", "complete", "done"}
            and _event_returncode(event) == 0
            for event in events
        )
    return any(_event_status(event) in {"ok", "success", "completed", "complete", "done"} for event in events)


def _events_include_failure(events: list[dict[str, Any]]) -> bool:
    return any(_event_status(event) in {"error", "failed", "failure", "blocked"} for event in events)


def _fallback_next_required_action(plan_items: Any, current_step_id: str) -> str:
    items = normalize_task_plan_items(plan_items)
    target = next((item for item in items if str(item.get("id") or "") == str(current_step_id or "").strip()), None)
    step = str((target or {}).get("step") or "").strip()
    return f"Continue current step: {step}"[:500] if step else ""


def _looks_generic_next_action(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    generic_values = {
        "continue",
        "continue current step",
        "keep going",
        "proceed",
        "next",
        "继续",
        "继续当前步骤",
        "继续当前任务",
        "接着做",
        "往下做",
    }
    return text in generic_values


def merge_task_state_delta(
    previous: Any,
    plan: Any,
    delta: Any,
    tool_events: Any,
    turn_status: Any,
    runtime_error: Any,
    pending_user_input: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = _now_iso()
    state = normalize_task_state(previous)
    merged_items = _merge_plan_items_with_history(state.get("plan_items") or [], plan or state.get("plan_items") or [])
    delta_payload = normalize_task_state_delta(delta)
    completed_steps = _derive_completed_steps(merged_items, state.get("completed_steps") or [], now)
    failed_attempts = _normalize_failed_attempts(
        list(state.get("failed_attempts") or []) + list(delta_payload.get("failed_attempts") or [])
    )
    progress_basis = _merge_text_lists(state.get("progress_basis"), delta_payload.get("progress_basis"), limit=8)
    evidence_refs = _merge_evidence_refs(state.get("evidence_refs"), delta_payload.get("evidence_refs"), limit=12)
    current_step_id = str(delta_payload.get("current_step_id") or "").strip()
    known_step_ids = {str(item.get("id") or "").strip() for item in merged_items if str(item.get("id") or "").strip()}
    if current_step_id and current_step_id not in known_step_ids:
        current_step_id = ""
    if not current_step_id:
        current_step_id = derive_current_step_id(merged_items)

    next_required_action = str(delta_payload.get("next_required_action") or "").strip()
    if not next_required_action:
        next_required_action = _pending_user_action(pending_user_input) or _fallback_next_required_action(merged_items, current_step_id)
    blocked_reason = str(delta_payload.get("blocked_reason") or "").strip()
    turn_status_text = str(turn_status or "").strip()
    runtime_summary = _runtime_error_summary(runtime_error)
    normalized_delta_status = str(delta_payload.get("status") or "").strip()
    if normalized_delta_status in {"blocked", "failed", "cancelled"}:
        status = normalized_delta_status
    elif turn_status_text in {"blocked", "needs_user_input"} and blocked_reason:
        status = "blocked"
    elif turn_status_text == "failed" and (blocked_reason or runtime_summary or failed_attempts):
        status = "failed"
    elif turn_status_text == "cancelled":
        status = "cancelled"
    elif merged_items and all(str(item.get("status") or "").strip() in _TASK_STEP_COMPLETED_STATUSES for item in merged_items):
        status = "completed"
    elif merged_items or state.get("goal"):
        status = "in_progress"
    else:
        status = state.get("status") or "idle"

    if status in {"blocked", "failed"} and not blocked_reason:
        blocked_reason = runtime_summary
    if runtime_summary and status in {"blocked", "failed"} and not failed_attempts:
        failed_attempts = _normalize_failed_attempts(
            list(failed_attempts)
            + [{
                "tool": "runtime",
                "summary": runtime_summary,
                "step_id": current_step_id,
                "evidence_refs": [{"source": "runtime_error"}],
                "created_at": now,
            }]
        )

    next_state = normalize_task_state(
        {
            **state,
            "status": status,
            "plan_items": merged_items,
            "current_step_id": current_step_id,
            "completed_steps": completed_steps,
            "failed_attempts": failed_attempts,
            "blocked_reason": blocked_reason,
            "next_required_action": next_required_action,
            "progress_basis": progress_basis,
            "evidence_refs": evidence_refs,
            "validation_warnings": [],
            "updated_at": now,
        }
    )
    return next_state, {}


def merge_task_state_after_turn(
    previous: Any,
    plan: Any,
    tool_events: Any,
    progress_signals: Any,
    turn_status: Any,
    runtime_error: Any,
    pending_user_input: Any,
) -> dict[str, Any]:
    now = _now_iso()
    state = normalize_task_state(previous)
    merged_items = _merge_plan_items_with_history(state.get("plan_items") or [], plan)
    current_step_id = derive_current_step_id(merged_items)
    completed_steps = _derive_completed_steps(merged_items, state.get("completed_steps") or [], now)
    events = [dict(item) for item in list(tool_events or []) if isinstance(item, dict)]
    signals = [dict(item) for item in list(progress_signals or []) if isinstance(item, dict)]
    progress_basis = _merge_text_lists(
        state.get("progress_basis"),
        [
            str(item.get("summary") or "").strip()
            for item in signals
            if bool(item.get("has_progress")) and str(item.get("summary") or "").strip()
        ],
        limit=8,
    )
    event_refs = [
        {"tool": _event_tool_name(event), "ref": str(ref or "").strip()}
        for event in events
        for ref in list(event.get("source_refs") or [])
        if str(ref or "").strip()
    ]
    evidence_refs = _merge_evidence_refs(state.get("evidence_refs"), event_refs, limit=12)
    event_failures = [
        {
            "tool": _event_tool_name(event),
            "summary": str(event.get("summary") or event.get("output_preview") or "").strip()[:500],
            "created_at": now,
        }
        for event in events
        if _event_tool_name(event) != "update_plan"
        and _event_status(event) in {"error", "failed", "failure", "blocked"}
    ]
    failed_attempts = _normalize_failed_attempts(
        [*list(state.get("failed_attempts") or []), *event_failures]
    )

    turn_status_text = str(turn_status or "").strip()
    runtime_summary = _runtime_error_summary(runtime_error)
    pending_action = _pending_user_action(pending_user_input)
    if turn_status_text == "failed" or runtime_summary:
        status = "failed"
    elif turn_status_text == "cancelled":
        status = "cancelled"
    elif turn_status_text in {"blocked", "needs_user_input"} or pending_action:
        status = "blocked"
    elif merged_items and all(str(item.get("status") or "").strip() in _TASK_STEP_COMPLETED_STATUSES for item in merged_items):
        status = "completed"
    elif merged_items or state.get("goal"):
        status = "in_progress"
    else:
        status = state.get("status") or "idle"

    next_item = next(
        (
            item
            for item in merged_items
            if str(item.get("status") or "").strip() not in _TASK_STEP_COMPLETED_STATUSES
            and str(item.get("status") or "").strip() not in _TASK_STEP_FAILED_STATUSES
        ),
        None,
    )
    next_required_action = pending_action or (str(next_item.get("step") or "").strip() if next_item else "")

    return normalize_task_state(
        {
            **state,
            "status": status,
            "plan_items": merged_items,
            "current_step_id": current_step_id,
            "completed_steps": completed_steps,
            "failed_attempts": failed_attempts,
            "blocked_reason": (
                pending_action
                or runtime_summary
                or (str(state.get("blocked_reason") or "") if status in {"blocked", "failed"} else "")
            ),
            "next_required_action": next_required_action,
            "progress_basis": progress_basis,
            "evidence_refs": evidence_refs,
            "validation_warnings": [],
            "updated_at": now,
        }
    )


def focus_from_work_cursor_task_state(work_cursor: Any, task_state: Any) -> dict[str, Any]:
    cursor = normalize_work_cursor(work_cursor)
    task = normalize_task_state(task_state)
    completed_steps = list(task.get("completed_steps") or [])
    last_completed = ""
    if completed_steps:
        latest = completed_steps[-1]
        if isinstance(latest, dict):
            last_completed = str(latest.get("step") or latest.get("summary") or latest.get("id") or "").strip()
    return normalize_current_task_focus(
        {
            "task_id": task.get("task_id") or "",
            "goal": task.get("goal") or "",
            "project_root": cursor.get("project_root") or "",
            "cwd": cursor.get("cwd") or "",
            "active_files": cursor.get("active_files") or [],
            "active_attachments": cursor.get("active_attachments") or [],
            "last_completed_step": last_completed,
            "next_action": task.get("next_required_action") or "",
            "updated_at": task.get("updated_at") or cursor.get("updated_at") or "",
        }
    )


def normalize_recent_task(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "task_id": str(raw.get("task_id") or "").strip(),
        "turn_id": str(raw.get("turn_id") or "").strip(),
        "user_request": str(raw.get("user_request") or "").strip(),
        "goal": str(raw.get("goal") or "").strip(),
        "cwd": str(raw.get("cwd") or "").strip(),
        "artifact_refs": _dedupe_strings(list(raw.get("artifact_refs") or []), limit=8),
        "active_files": _dedupe_strings(list(raw.get("active_files") or []), limit=8),
        "result_digest": str(raw.get("result_digest") or "").strip(),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def normalize_recent_tasks(raw: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(raw or [])[:limit]:
        normalized = normalize_recent_task(item)
        key = normalized["task_id"] or normalized["turn_id"] or normalized["updated_at"]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out[:limit]


def normalize_artifact_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "artifact_id": str(raw.get("artifact_id") or raw.get("id") or "").strip(),
        "kind": str(raw.get("kind") or "").strip(),
        "name": str(raw.get("name") or "").strip(),
        "path": str(raw.get("path") or "").strip(),
        "mime": str(raw.get("mime") or "").strip(),
        "turn_id": str(raw.get("turn_id") or "").strip(),
        "source_tool": str(raw.get("source_tool") or "").strip(),
        "summary_digest": str(raw.get("summary_digest") or "").strip(),
        "created_at": str(raw.get("created_at") or "").strip(),
    }


def normalize_artifact_memory(raw: Any, *, limit: int = 48) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = sorted(
        [normalize_artifact_entry(item) for item in list(raw or [])],
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )
    for item in items:
        key = item["artifact_id"] or item["path"] or item["name"]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def normalize_thread_memory(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "summary": str(raw.get("summary") or "").strip(),
        "recent_tasks": normalize_recent_tasks(raw.get("recent_tasks"), limit=12),
        "recent_cwds": _dedupe_strings(list(raw.get("recent_cwds") or []), limit=8),
        "recent_files": _dedupe_strings(list(raw.get("recent_files") or []), limit=12),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def message_clears_attachment_context(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(hint in text for hint in _ATTACHMENT_CONTEXT_CLEAR_HINTS)


def message_explicitly_starts_new_task(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(hint in text for hint in _EXPLICIT_NEW_TASK_HINTS)


def message_requests_task_recall(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return (
        any(hint in text for hint in _TASK_RECALL_HINTS)
        or message_requests_latest_user_question(message)
        or message_requests_recent_user_list(message)
    )


def message_requests_latest_user_question(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(hint in text for hint in _RECENT_USER_LAST_HINTS)


def message_requests_recent_user_list(message: str) -> bool:
    raw = str(message or "").strip()
    text = raw.lower()
    if not text:
        return False
    if any(hint in text for hint in _RECENT_USER_LIST_HINTS):
        return True
    return any(token in text for token in ("all my questions", "所有问题")) and any(
        token in text for token in ("list", "罗列", "列", "show")
    )


def message_requests_subject_followup(message: str) -> bool:
    raw = str(message or "").strip()
    text = raw.lower()
    if not text:
        return False
    if any(hint == text for hint in _TASK_SUBJECT_FOLLOWUP_HINTS):
        return True
    if len(raw) <= 24 and any(hint in text for hint in _TASK_SUBJECT_FOLLOWUP_HINTS):
        return True
    return False


def message_requests_attachment_context(message: str) -> bool:
    raw = str(message or "").strip()
    if not raw:
        return False
    text = raw.lower()
    if any(hint in text for hint in _ATTACHMENT_CONTEXT_FILE_HINTS):
        return True
    has_ref = any(hint in text for hint in _ATTACHMENT_CONTEXT_REFERENCE_HINTS)
    has_action = any(hint in text for hint in _ATTACHMENT_CONTEXT_ACTION_HINTS)
    if has_ref and has_action:
        return True
    if len(raw) <= 40 and (
        any(token in text for token in ("什么意思", "怎么用", "用法", "语法", "在文中", "有没有出现", "是否出现"))
        or bool(re.search(r"[\"'“”‘’「『].{1,24}[\"'“”‘’」』]", raw))
    ):
        return True
    if message_requests_task_recall(raw) and any(hint in text for hint in _ATTACHMENT_CONTEXT_FILE_HINTS):
        return True
    if len(raw) <= 12 and any(token in text for token in ("继续", "接着", "然后呢", "继续吧", "接着说")):
        return True
    if len(raw) <= 24 and re.search(r"\b(continue|go on|next)\b", text):
        return True
    return False


def _session_current_task_focus(session: dict[str, Any]) -> dict[str, Any]:
    canonical_focus = focus_from_work_cursor_task_state(
        session.get("work_cursor"),
        session.get("task_state"),
    )
    if (
        canonical_focus["task_id"]
        or canonical_focus["goal"]
        or canonical_focus["active_files"]
        or canonical_focus["active_attachments"]
    ):
        return canonical_focus
    agent_state = session.get("agent_state")
    if isinstance(agent_state, dict):
        focus = agent_state.get("current_task_focus")
        if isinstance(focus, dict) and focus:
            return normalize_current_task_focus(focus)
        checkpoint = agent_state.get("task_checkpoint")
        if isinstance(checkpoint, dict) and checkpoint:
            return normalize_current_task_focus(checkpoint)
    current_focus = session.get("current_task_focus")
    if isinstance(current_focus, dict) and current_focus:
        return normalize_current_task_focus(current_focus)
    route_state = session.get("route_state")
    if isinstance(route_state, dict):
        focus = route_state.get("current_task_focus")
        if isinstance(focus, dict) and focus:
            return normalize_current_task_focus(focus)
        checkpoint = route_state.get("task_checkpoint")
        if isinstance(checkpoint, dict) and checkpoint:
            return normalize_current_task_focus(checkpoint)
    return normalize_current_task_focus({})


def _session_thread_memory(session: dict[str, Any]) -> dict[str, Any]:
    thread_memory = normalize_thread_memory(session.get("thread_memory"))
    legacy_recent_tasks = normalize_recent_tasks(session.get("recent_tasks"), limit=12)
    agent_state = session.get("agent_state")
    if isinstance(agent_state, dict):
        fallback = normalize_thread_memory(agent_state.get("thread_memory"))
        if not thread_memory["summary"] and fallback["summary"]:
            thread_memory["summary"] = fallback["summary"]
        legacy_recent_tasks = normalize_recent_tasks(
            [*legacy_recent_tasks, *list(fallback.get("recent_tasks") or [])],
            limit=12,
        )
    if legacy_recent_tasks:
        thread_memory["recent_tasks"] = normalize_recent_tasks(
            [*list(thread_memory.get("recent_tasks") or []), *legacy_recent_tasks],
            limit=12,
        )
    if not thread_memory["summary"]:
        thread_memory["summary"] = str(session.get("summary") or "").strip()
    return thread_memory


def _session_artifact_memory(session: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_candidates: list[dict[str, Any]] = []
    artifact_candidates.extend(normalize_artifact_memory(session.get("artifact_memory"), limit=48))
    artifact_candidates.extend(normalize_artifact_memory(session.get("artifact_memory_preview"), limit=48))
    agent_state = session.get("agent_state")
    if isinstance(agent_state, dict):
        artifact_candidates.extend(normalize_artifact_memory(agent_state.get("artifact_memory_preview"), limit=48))
    return normalize_artifact_memory(artifact_candidates, limit=48)


def _session_task_checkpoint(session: dict[str, Any]) -> dict[str, Any]:
    return compat_task_checkpoint_from_focus(_session_current_task_focus(session))


def _recent_user_messages_from_turns(
    turns: list[dict[str, Any]] | None,
    *,
    limit: int = 8,
) -> list[str]:
    collected: list[str] = []
    for item in list(turns or []):
        if not isinstance(item, dict) or str(item.get("role") or "") != "user":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            collected.append(text)
    return collected[-max(1, limit) :]


def get_recent_user_messages(
    session: dict[str, Any],
    *,
    limit: int = 8,
) -> list[str]:
    turns = session.get("turns", [])
    if isinstance(turns, list) and turns:
        return _recent_user_messages_from_turns(turns, limit=limit)
    return []


def _message_mentions_email_context(message: str) -> bool:
    raw = str(message or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    return any(token in raw for token in ("邮件", "邮箱", "信件", "メール", "件名")) or any(
        token in lowered for token in ("email", "mail", "subject")
    )


def _recent_assistant_messages_from_turns(
    turns: list[dict[str, Any]] | None,
    *,
    limit: int = 4,
) -> list[str]:
    collected: list[str] = []
    for item in list(turns or []):
        if not isinstance(item, dict) or str(item.get("role") or "") != "assistant":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            collected.append(text)
    return collected[-max(1, limit) :]


def _has_email_followup_context(
    session: dict[str, Any],
    *,
    history_turns: list[dict[str, Any]] | None = None,
) -> bool:
    focus = _session_current_task_focus(session)
    candidates = [str(focus.get("goal") or "").strip()]
    candidates.extend(_recent_user_messages_from_turns(history_turns or session.get("turns") or [], limit=4))
    candidates.extend(_recent_assistant_messages_from_turns(history_turns or session.get("turns") or [], limit=3))
    return any(_message_mentions_email_context(item) for item in candidates if str(item or "").strip())


def derive_current_turn_context(
    session: dict[str, Any],
    *,
    message: str,
    history_turns: list[dict[str, Any]] | None = None,
    recent_user_messages: list[str] | None = None,
) -> dict[str, Any]:
    raw = str(message or "").strip()
    history = list(history_turns or [])
    prior_user_messages = list(recent_user_messages or _recent_user_messages_from_turns(history, limit=8))
    followup_type = ""
    goal_source = "latest_user_message"
    is_followup = False
    goal = raw[:240]
    prior_focus_goal = str(_session_current_task_focus(session).get("goal") or "").strip()
    prior_task_goal = str(normalize_task_state(session.get("task_state")).get("goal") or "").strip()
    inherited_goal = prior_task_goal or prior_focus_goal

    if message_requests_recent_user_list(raw):
        goal = "List the recent user questions from this thread in order."
        followup_type = "recent_user_messages_list"
        goal_source = "recent_user_messages"
        is_followup = True
    elif message_requests_latest_user_question(raw):
        goal = "Answer what the previous user message was in this thread."
        followup_type = "recent_user_message_recall"
        goal_source = "recent_user_messages"
        is_followup = True
    elif message_requests_subject_followup(raw) and _has_email_followup_context(session, history_turns=history):
        goal = "Provide only a subject/title for the previous email or draft."
        followup_type = "subject_request"
        goal_source = "followup_classifier"
        is_followup = True
    elif message_likely_continues_task(raw, session=session):
        if inherited_goal:
            goal = inherited_goal
        followup_type = "task_followup"
        goal_source = "existing_task_goal" if inherited_goal else "latest_user_message"
        is_followup = True

    return {
        "user_message": raw,
        "goal": goal,
        "is_followup": bool(is_followup),
        "followup_type": followup_type,
        "source": goal_source,
        "recent_user_messages": prior_user_messages[-8:],
    }


def message_likely_continues_task(message: str, *, session: dict[str, Any] | None = None) -> bool:
    raw = str(message or "").strip()
    if not raw:
        return False
    text = raw.lower()
    if message_explicitly_starts_new_task(raw):
        return False
    if any(hint in text for hint in _TASK_FOLLOWUP_HINTS):
        return True
    if message_requests_task_recall(raw):
        return True

    focus = _session_current_task_focus(session or {})
    has_active_context = bool(focus.get("active_files") or focus.get("active_attachments") or focus.get("cwd"))
    if has_active_context and len(raw) <= 24 and any(hint in text for hint in ("修", "改", "继续", "实现")):
        return True
    if has_active_context and len(raw) <= 40 and any(hint in text for hint in _TASK_SHORT_ACTION_HINTS):
        if any(token in text for token in ("它", "其", "这", "该", "当前", "这里", "文件", "目录", "文件夹", "附件", "图片", "截图", "代码")):
            return True
    if has_active_context and len(raw) <= 80 and any(hint in text for hint in _TASK_SHORT_ACTION_HINTS):
        if re.search(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]+", raw):
            return True
    return False


def infer_focus_shift(
    session: dict[str, Any],
    *,
    message: str,
    requested_attachment_ids: list[str] | None = None,
) -> bool:
    requested = normalize_attachment_ids(requested_attachment_ids)
    text = str(message or "").strip().lower()
    if any(hint in text for hint in _RESET_FOCUS_HINTS):
        return True
    if message_clears_attachment_context(message):
        return True
    if requested and not message_likely_continues_task(message, session=session):
        return True
    return False


def should_start_new_task(
    session: dict[str, Any],
    *,
    message: str,
    requested_attachment_ids: list[str] | None = None,
) -> bool:
    checkpoint = _session_task_checkpoint(session)
    if not checkpoint:
        return False
    requested = normalize_attachment_ids(requested_attachment_ids)
    text = str(message or "").strip().lower()
    if message_requests_task_recall(message):
        return False
    if message_explicitly_starts_new_task(message):
        return True
    if message_clears_attachment_context(message):
        return True
    if requested:
        return not any(hint in text for hint in _TASK_FOLLOWUP_HINTS)
    if message_likely_continues_task(message, session=session):
        return False
    return True


def prepare_route_state_for_turn(
    route_state: dict[str, Any] | None,
    *,
    reset_focus: bool = False,
) -> dict[str, Any]:
    state = dict(route_state or {})
    if not reset_focus:
        return state
    state.pop("current_task_focus", None)
    state.pop("task_checkpoint", None)
    state.pop("work_cursor", None)
    state.pop("task_state", None)
    return state


def infer_session_active_attachment_ids(session: dict[str, Any]) -> list[str]:
    if bool(session.get("attachment_context_cleared")):
        return []
    from_state = session.get("active_attachment_ids")
    if isinstance(from_state, list):
        normalized = normalize_attachment_ids([str(item or "") for item in from_state])
        if normalized:
            return normalized

    focus = _session_current_task_focus(session)
    if focus["active_attachments"]:
        normalized = normalize_attachment_ids([str(item.get("id") or "") for item in focus["active_attachments"]])
        if normalized:
            return normalized

    turns_raw = session.get("turns", [])
    if not isinstance(turns_raw, list):
        return []
    for turn in reversed(turns_raw):
        if not isinstance(turn, dict) or str(turn.get("role") or "") != "user":
            continue
        attachments = turn.get("attachments", [])
        if not isinstance(attachments, list) or not attachments:
            continue
        normalized = normalize_attachment_ids(
            [str(item.get("id") or "") for item in attachments if isinstance(item, dict)]
        )
        if normalized:
            return normalized
    return []


def attachment_context_key(attachment_ids: list[str] | None) -> str:
    normalized = normalize_attachment_ids(attachment_ids)
    if not normalized:
        return ""
    return "|".join(normalized)


def _artifact_kind(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind") or "").strip().lower()
    name = str(entry.get("name") or "").strip().lower()
    path = str(entry.get("path") or "").strip().lower()
    mime = str(entry.get("mime") or "").strip().lower()
    blob = " ".join([kind, name, path, mime])
    if any(token in blob for token in (".msg", "outlook", "message/rfc822", "application/vnd.ms-outlook", " email ")):
        return "mail"
    if kind == "image" or any(token in blob for token in _IMAGE_HINTS):
        return "image"
    if any(token in blob for token in (".pdf", ".docx", ".xlsx", ".pptx", "application/pdf")):
        return "document"
    return kind or "other"


def _artifact_matches_message(entry: dict[str, Any], message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    kind = _artifact_kind(entry)
    if any(token in text for token in _IMAGE_HINTS):
        return kind == "image"
    if any(token in text for token in _MAIL_HINTS):
        return kind == "mail"
    if any(token in text for token in _DOCUMENT_HINTS):
        return kind in {"document", "mail"}
    return True


def _wanted_artifact_kind(message: str) -> str:
    text = str(message or "").strip().lower()
    if any(token in text for token in _IMAGE_HINTS):
        return "image"
    if any(token in text for token in _MAIL_HINTS):
        return "mail"
    if any(token in text for token in _DOCUMENT_HINTS):
        return "document"
    return ""


def _artifact_rank(entry: dict[str, Any], message: str) -> tuple[int, str]:
    score = 0
    if _artifact_matches_message(entry, message):
        score += 100
    name = str(entry.get("name") or "").strip().lower()
    path = str(entry.get("path") or "").strip().lower()
    text = str(message or "").strip().lower()
    if name and name in text:
        score += 40
    if path and path in text:
        score += 40
    if message_requests_task_recall(message):
        score += 10
    return score, str(entry.get("created_at") or "")


def select_recalled_artifacts(session: dict[str, Any], *, message: str, limit: int = 4) -> list[dict[str, Any]]:
    if not message_requests_attachment_context(message):
        return []
    artifacts = _session_artifact_memory(session)
    if not artifacts:
        return []
    wanted_kind = _wanted_artifact_kind(message)
    if wanted_kind:
        matching_kind = [item for item in artifacts if _artifact_kind(item) == wanted_kind]
        if matching_kind:
            artifacts = matching_kind
    ranked = sorted(
        artifacts,
        key=lambda item: _artifact_rank(item, message),
        reverse=True,
    )
    selected = [item for item in ranked if _artifact_rank(item, message)[0] > 0]
    if not selected and message_requests_task_recall(message):
        selected = ranked
    return selected[:limit]


def select_recalled_task(session: dict[str, Any], *, message: str, artifact_ids: list[str] | None = None) -> dict[str, Any]:
    recent_tasks = _session_thread_memory(session).get("recent_tasks") or []
    if not recent_tasks:
        return {}
    wanted_ids = set(normalize_attachment_ids(artifact_ids))
    if wanted_ids:
        for item in recent_tasks:
            refs = set(_dedupe_strings(list(item.get("artifact_refs") or []), limit=8))
            if refs & wanted_ids:
                return dict(item)
    if message_requests_task_recall(message):
        return dict(recent_tasks[0])
    return {}


def resolve_recalled_context(
    session: dict[str, Any],
    *,
    message: str,
    attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    recalled_artifacts = select_recalled_artifacts(session, message=message, limit=4)
    if attachment_ids:
        wanted = set(normalize_attachment_ids(attachment_ids))
        if wanted:
            recalled_artifacts = [item for item in _session_artifact_memory(session) if str(item.get("artifact_id") or "") in wanted]
    recalled_artifact_ids = normalize_attachment_ids([str(item.get("artifact_id") or "") for item in recalled_artifacts])
    recalled_task = select_recalled_task(session, message=message, artifact_ids=recalled_artifact_ids)
    return {
        "recalled_task": recalled_task,
        "recalled_artifacts": recalled_artifacts,
        "recalled_artifact_ids": recalled_artifact_ids,
    }


def resolve_attachment_context(
    session: dict[str, Any],
    *,
    message: str,
    requested_attachment_ids: list[str] | None,
    clear_attachment_context: bool = False,
) -> dict[str, Any]:
    requested = normalize_attachment_ids(requested_attachment_ids)
    remembered = infer_session_active_attachment_ids(session)
    recalled_entries: list[dict[str, Any]] = []
    recalled_ids: list[str] = []
    clear_context = bool(clear_attachment_context)
    attachment_context_mode = "none"
    auto_linked_attachment_ids: list[str] = []

    if clear_context:
        effective_attachment_ids = requested
        attachment_context_mode = "cleared" if not requested else "explicit"
    elif requested:
        effective_attachment_ids = requested
        attachment_context_mode = "explicit"
    elif remembered:
        effective_attachment_ids = remembered
        attachment_context_mode = "auto_linked"
        auto_linked_attachment_ids = list(remembered)
    else:
        effective_attachment_ids = []

    return {
        "requested_attachment_ids": requested,
        "remembered_attachment_ids": remembered,
        "recalled_attachment_ids": recalled_ids,
        "effective_attachment_ids": effective_attachment_ids,
        "attachment_context_mode": attachment_context_mode,
        "auto_linked_attachment_ids": auto_linked_attachment_ids,
        "clear_attachment_context": clear_context,
        "attachment_context_key": attachment_context_key(effective_attachment_ids),
        "recalled_artifacts": recalled_entries,
        "recalled_task": {},
    }


def apply_attachment_context_result(
    session: dict[str, Any],
    *,
    resolved_attachment_ids: list[str] | None,
    attachment_context_mode: str,
    clear_attachment_context: bool = False,
    requested_attachment_ids: list[str] | None = None,
) -> None:
    resolved = normalize_attachment_ids(resolved_attachment_ids)
    requested = normalize_attachment_ids(requested_attachment_ids)
    if attachment_context_mode in {"explicit", "auto_linked"}:
        session["active_attachment_ids"] = resolved
        session["attachment_context_cleared"] = False
    elif clear_attachment_context and not requested:
        session["active_attachment_ids"] = []
        session["attachment_context_cleared"] = True


def _coerce_route_state_map(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or not isinstance(value, dict):
            continue
        out[normalized_key] = dict(value)
    return out


def resolve_scoped_route_state(
    session: dict[str, Any],
    *,
    attachment_ids: list[str] | None,
) -> tuple[dict[str, Any], str]:
    context_key = attachment_context_key(attachment_ids)
    if context_key:
        scoped = _coerce_route_state_map(session.get("attachment_route_states")).get(context_key)
        if isinstance(scoped, dict) and scoped:
            return dict(scoped), "attachment"
        return {}, "attachment_miss"
    route_state = session.get("route_state")
    if isinstance(route_state, dict) and route_state:
        return dict(route_state), "session"
    return {}, "none"


def store_scoped_route_state(
    session: dict[str, Any],
    *,
    attachment_ids: list[str] | None,
    route_state: dict[str, Any] | None,
) -> None:
    normalized_state = dict(route_state or {})
    session["route_state"] = normalized_state

    context_key = attachment_context_key(attachment_ids)
    if not context_key:
        return

    scoped_states = _coerce_route_state_map(session.get("attachment_route_states"))
    if normalized_state:
        scoped_states[context_key] = normalized_state
    else:
        scoped_states.pop(context_key, None)
    session["attachment_route_states"] = scoped_states


def get_thread_memory(session: dict[str, Any]) -> dict[str, Any]:
    return _session_thread_memory(session)


def get_current_task_focus(session: dict[str, Any]) -> dict[str, Any]:
    return _session_current_task_focus(session)


def get_artifact_memory_preview(session: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    return _session_artifact_memory(session)[:limit]


def sync_session_memory_state(session: dict[str, Any]) -> bool:
    changed = False
    agent_state = session.get("agent_state")
    if not isinstance(agent_state, dict):
        agent_state = {}
        session["agent_state"] = agent_state
        changed = True

    focus = _session_current_task_focus(session)
    if focus["task_id"] and not focus["updated_at"]:
        focus["updated_at"] = _now_iso()
    work_cursor = normalize_work_cursor(session.get("work_cursor"))
    task_state = normalize_task_state(session.get("task_state"))
    task_checkpoint_exists = task_state_has_checkpoint(task_state)
    if focus["project_root"] and work_cursor["project_root"] != focus["project_root"]:
        work_cursor["project_root"] = focus["project_root"]
    if focus["cwd"] and work_cursor["cwd"] != focus["cwd"]:
        work_cursor["cwd"] = focus["cwd"]
    if focus["active_files"] and work_cursor["active_files"] != focus["active_files"]:
        work_cursor["active_files"] = list(focus["active_files"])
    if focus["active_attachments"] and work_cursor["active_attachments"] != focus["active_attachments"]:
        work_cursor["active_attachments"] = [dict(item) for item in focus["active_attachments"]]
    if focus["updated_at"] and not work_cursor["updated_at"]:
        work_cursor["updated_at"] = focus["updated_at"]
    if task_checkpoint_exists and focus["task_id"] and task_state["task_id"] != focus["task_id"]:
        task_state["task_id"] = focus["task_id"]
    if task_checkpoint_exists and focus["goal"] and task_state["goal"] != focus["goal"]:
        task_state["goal"] = focus["goal"]
    if task_checkpoint_exists and focus["next_action"] and not task_state["next_required_action"]:
        task_state["next_required_action"] = focus["next_action"]
    if task_checkpoint_exists and focus["updated_at"] and not task_state["updated_at"]:
        task_state["updated_at"] = focus["updated_at"]
    if task_checkpoint_exists and task_state["status"] == "idle" and (task_state["goal"] or task_state["plan_items"]):
        task_state["status"] = "in_progress"
    thread_memory = _session_thread_memory(session)
    artifact_memory = _session_artifact_memory(session)
    compaction_state = dict(session.get("compaction_state") or {}) if isinstance(session.get("compaction_state"), dict) else {}
    legacy_compaction_status = (
        dict(session.get("compaction_status") or {})
        if isinstance(session.get("compaction_status"), dict)
        else {}
    )
    legacy_context_meter = (
        dict(session.get("context_meter") or {})
        if isinstance(session.get("context_meter"), dict)
        else {}
    )
    for key in (
        "generation",
        "compacted_until_turn_id",
        "retained_turn_ids",
        "last_compacted_at",
        "last_compaction_reason",
        "last_compaction_phase",
        "phase",
        "reason",
        "before_tokens",
        "after_tokens",
        "estimated_context_tokens",
        "effective_context_window",
        "auto_compact_token_limit",
        "threshold_source",
        "retained_turn_count",
    ):
        if key in legacy_compaction_status and compaction_state.get(key) in (None, "", [], {}, 0):
            compaction_state[key] = legacy_compaction_status.get(key)
    meter_mapping = {
        "estimated_tokens": "estimated_context_tokens",
        "context_window": "effective_context_window",
        "auto_compact_token_limit": "auto_compact_token_limit",
        "threshold_source": "threshold_source",
    }
    for source_key, state_key in meter_mapping.items():
        if source_key in legacy_context_meter and compaction_state.get(state_key) in (None, "", [], {}, 0):
            compaction_state[state_key] = legacy_context_meter.get(source_key)
    if not thread_memory["summary"]:
        thread_memory["summary"] = str(session.get("summary") or "").strip()
    if focus["cwd"] and focus["cwd"] not in thread_memory["recent_cwds"]:
        thread_memory["recent_cwds"] = [focus["cwd"], *thread_memory["recent_cwds"]][:8]
    if focus["active_files"]:
        thread_memory["recent_files"] = _dedupe_strings(list(focus["active_files"]) + list(thread_memory["recent_files"]), limit=12)
    if not thread_memory["updated_at"]:
        thread_memory["updated_at"] = agent_state.get("updated_at") if isinstance(agent_state, dict) else ""

    if session.get("work_cursor") != work_cursor:
        session["work_cursor"] = dict(work_cursor)
        changed = True
    if session.get("task_state") != task_state:
        session["task_state"] = dict(task_state)
        changed = True
    if session.get("thread_memory") != thread_memory:
        session["thread_memory"] = dict(thread_memory)
        changed = True
    if session.get("artifact_memory") != artifact_memory:
        session["artifact_memory"] = list(artifact_memory)
        changed = True
    if compaction_state and session.get("compaction_state") != compaction_state:
        session["compaction_state"] = dict(compaction_state)
        changed = True
    for derived_key in ("recent_tasks", "artifact_memory_preview", "context_meter", "compaction_status"):
        if derived_key in session:
            session.pop(derived_key, None)
            changed = True
    if "current_task_focus" in session:
        session.pop("current_task_focus", None)
        changed = True

    for legacy_key in (
        "current_task_focus",
        "task_checkpoint",
        "thread_memory",
        "recent_tasks",
        "artifact_memory_preview",
        "tool_hits",
        "tool_names",
        "goal",
        "current_goal",
    ):
        if legacy_key in agent_state:
            agent_state.pop(legacy_key, None)
            changed = True
    pending_turn = agent_state.get("pending_turn")
    if not (isinstance(pending_turn, dict) and pending_turn) and "plan" in agent_state:
        agent_state.pop("plan", None)
        changed = True
    return changed


def record_turn_memory(
    session: dict[str, Any],
    *,
    user_message: str,
    assistant_text: str,
    attachments: list[dict[str, Any]] | None,
    route_state: dict[str, Any] | None,
    tool_events: list[dict[str, Any]] | None,
    answer_bundle: dict[str, Any] | None,
    touch_task_checkpoint: bool = True,
) -> None:
    now = _now_iso()
    session["route_state"] = dict(route_state or {})
    work_cursor = normalize_work_cursor(session.get("work_cursor"))
    task_state = normalize_task_state(session.get("task_state"))
    has_task_checkpoint = task_state_has_checkpoint(task_state)
    focus = (
        focus_from_work_cursor_task_state(work_cursor, task_state)
        if has_task_checkpoint
        else normalize_current_task_focus({})
    )
    if has_task_checkpoint and touch_task_checkpoint:
        if not task_state["task_id"]:
            task_state["task_id"] = str(uuid.uuid4())
        task_state["updated_at"] = now
        focus = normalize_current_task_focus(
            {
                "task_id": task_state["task_id"],
                "goal": task_state["goal"],
                "project_root": work_cursor["project_root"],
                "cwd": work_cursor["cwd"],
                "active_files": list(work_cursor["active_files"]),
                "active_attachments": [dict(item) for item in list(work_cursor["active_attachments"])],
                "last_completed_step": focus.get("last_completed_step") or "",
                "next_action": task_state.get("next_required_action") or focus.get("next_action") or "",
                "updated_at": now,
            }
        )
        work_cursor["project_root"] = focus["project_root"] or work_cursor["project_root"]
        work_cursor["cwd"] = focus["cwd"] or work_cursor["cwd"]
        work_cursor["active_files"] = list(focus["active_files"] or work_cursor["active_files"])
        work_cursor["active_attachments"] = [dict(item) for item in list(focus["active_attachments"] or work_cursor["active_attachments"])]
        work_cursor["updated_at"] = now

    turns = session.get("turns", [])
    user_turn_id = ""
    for item in reversed(list(turns or [])):
        if isinstance(item, dict) and str(item.get("role") or "") == "user":
            user_turn_id = str(item.get("id") or "").strip()
            if user_turn_id:
                break

    result_digest = str(((answer_bundle or {}).get("summary")) or "").strip() or str(assistant_text or "").strip()[:240]
    source_tool = ""
    for item in list(tool_events or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            source_tool = name
            if name in {"image_read", "read_file", "read_section", "table_extract", "fact_check_file"}:
                break

    artifact_memory = _session_artifact_memory(session)
    artifact_index = {
        (str(item.get("artifact_id") or "").strip() or str(item.get("path") or "").strip() or str(item.get("name") or "").strip()): dict(item)
        for item in artifact_memory
    }
    for meta in attachments or []:
        if not isinstance(meta, dict):
            continue
        artifact_id = str(meta.get("id") or meta.get("artifact_id") or "").strip()
        path = str(meta.get("path") or "").strip()
        name = str(meta.get("original_name") or meta.get("name") or "").strip()
        key = artifact_id or path or name
        if not key:
            continue
        entry = normalize_artifact_entry(
            {
                "artifact_id": artifact_id or path or name,
                "kind": str(meta.get("kind") or "").strip(),
                "name": name,
                "path": path,
                "mime": str(meta.get("mime") or meta.get("content_type") or "").strip(),
                "turn_id": user_turn_id,
                "source_tool": source_tool,
                "summary_digest": result_digest,
                "created_at": now,
            }
        )
        artifact_index[key] = entry
    artifact_memory = normalize_artifact_memory(list(artifact_index.values()), limit=48)

    thread_memory = _session_thread_memory(session)
    thread_memory["summary"] = str(session.get("summary") or thread_memory.get("summary") or "").strip()
    if has_task_checkpoint and touch_task_checkpoint:
        artifact_refs = normalize_attachment_ids([str(item.get("artifact_id") or "") for item in artifact_memory[:8]])
        active_artifact_refs = normalize_attachment_ids([str(item.get("id") or "") for item in focus["active_attachments"]])
        task = normalize_recent_task(
            {
                "task_id": task_state["task_id"],
                "turn_id": user_turn_id,
                "user_request": str(user_message or "").strip(),
                "goal": task_state["goal"],
                "cwd": work_cursor["cwd"],
                "artifact_refs": active_artifact_refs or artifact_refs,
                "active_files": list(work_cursor["active_files"]),
                "result_digest": result_digest,
                "updated_at": now,
            }
        )
        next_recent_tasks = [task]
        for item in thread_memory["recent_tasks"]:
            if str(item.get("task_id") or "") == task["task_id"]:
                continue
            next_recent_tasks.append(normalize_recent_task(item))
        thread_memory["recent_tasks"] = next_recent_tasks[:12]
    thread_memory["recent_cwds"] = _dedupe_strings([work_cursor["cwd"], *thread_memory["recent_cwds"]], limit=8)
    thread_memory["recent_files"] = _dedupe_strings(list(work_cursor["active_files"]) + list(thread_memory["recent_files"]), limit=12)
    thread_memory["updated_at"] = now

    session["work_cursor"] = dict(work_cursor)
    session["task_state"] = dict(task_state)
    session["thread_memory"] = dict(thread_memory)
    session["artifact_memory"] = list(artifact_memory)
    sync_session_memory_state(session)
