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
_MAIL_HINTS = ("邮件", "邮箱", "msg", ".msg", "email", "outlook", "信件")
_DOCUMENT_HINTS = ("pdf", "文档", "docx", "xlsx", "pptx", "表格", "幻灯片", "文件")
_RESET_FOCUS_HINTS = (
    "忽略刚才",
    "忽略之前",
    "重新开始",
    "从头开始",
    "new task",
    "start over",
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
    return any(hint in text for hint in _TASK_RECALL_HINTS)


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
    agent_state = session.get("agent_state")
    if isinstance(agent_state, dict):
        fallback = normalize_thread_memory(agent_state.get("thread_memory"))
        if not thread_memory["summary"] and fallback["summary"]:
            thread_memory["summary"] = fallback["summary"]
        if not thread_memory["recent_tasks"] and fallback["recent_tasks"]:
            thread_memory["recent_tasks"] = list(fallback["recent_tasks"])
    if not thread_memory["summary"]:
        thread_memory["summary"] = str(session.get("summary") or "").strip()
    return thread_memory


def _session_artifact_memory(session: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = normalize_artifact_memory(session.get("artifact_memory"), limit=48)
    if artifacts:
        return artifacts
    agent_state = session.get("agent_state")
    if isinstance(agent_state, dict):
        return normalize_artifact_memory(agent_state.get("artifact_memory_preview"), limit=48)
    return []


def _session_task_checkpoint(session: dict[str, Any]) -> dict[str, Any]:
    return compat_task_checkpoint_from_focus(_session_current_task_focus(session))


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
) -> dict[str, Any]:
    requested = normalize_attachment_ids(requested_attachment_ids)
    remembered = infer_session_active_attachment_ids(session)
    recalled_entries = select_recalled_artifacts(session, message=message, limit=4)
    recalled_ids = normalize_attachment_ids([str(item.get("artifact_id") or "") for item in recalled_entries])
    clear_context = message_clears_attachment_context(message)
    attachment_context_mode = "none"
    auto_linked_attachment_ids: list[str] = []

    if clear_context:
        effective_attachment_ids = requested
        attachment_context_mode = "cleared" if not requested else "explicit"
    elif requested:
        effective_attachment_ids = requested
        attachment_context_mode = "explicit"
    elif recalled_ids:
        effective_attachment_ids = recalled_ids
        attachment_context_mode = "auto_linked"
        auto_linked_attachment_ids = list(recalled_ids)
    elif remembered and message_requests_attachment_context(message):
        effective_attachment_ids = remembered
        attachment_context_mode = "auto_linked"
        auto_linked_attachment_ids = list(remembered)
    else:
        effective_attachment_ids = []

    recalled_task = select_recalled_task(session, message=message, artifact_ids=effective_attachment_ids)
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
        "recalled_task": recalled_task,
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
    thread_memory = _session_thread_memory(session)
    artifact_memory = _session_artifact_memory(session)
    if not thread_memory["summary"]:
        thread_memory["summary"] = str(session.get("summary") or "").strip()
    if focus["cwd"] and focus["cwd"] not in thread_memory["recent_cwds"]:
        thread_memory["recent_cwds"] = [focus["cwd"], *thread_memory["recent_cwds"]][:8]
    if focus["active_files"]:
        thread_memory["recent_files"] = _dedupe_strings(list(focus["active_files"]) + list(thread_memory["recent_files"]), limit=12)
    if not thread_memory["updated_at"]:
        thread_memory["updated_at"] = agent_state.get("updated_at") if isinstance(agent_state, dict) else ""

    if session.get("current_task_focus") != focus:
        session["current_task_focus"] = dict(focus)
        changed = True
    if session.get("thread_memory") != thread_memory:
        session["thread_memory"] = dict(thread_memory)
        changed = True
    if session.get("artifact_memory") != artifact_memory:
        session["artifact_memory"] = list(artifact_memory)
        changed = True

    if agent_state.get("current_task_focus") != focus:
        agent_state["current_task_focus"] = dict(focus)
        changed = True
    compat_checkpoint = compat_task_checkpoint_from_focus(focus)
    if agent_state.get("task_checkpoint") != compat_checkpoint:
        agent_state["task_checkpoint"] = compat_checkpoint
        changed = True
    if agent_state.get("thread_memory") != thread_memory:
        agent_state["thread_memory"] = dict(thread_memory)
        changed = True
    if agent_state.get("recent_tasks") != thread_memory["recent_tasks"]:
        agent_state["recent_tasks"] = list(thread_memory["recent_tasks"])
        changed = True
    artifact_preview = artifact_memory[:8]
    if agent_state.get("artifact_memory_preview") != artifact_preview:
        agent_state["artifact_memory_preview"] = artifact_preview
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
) -> None:
    now = _now_iso()
    session["route_state"] = dict(route_state or {})
    focus = normalize_current_task_focus(
        ((route_state or {}).get("current_task_focus") if isinstance(route_state, dict) else None)
        or ((route_state or {}).get("task_checkpoint") if isinstance(route_state, dict) else None)
    )
    if not focus["task_id"]:
        focus["task_id"] = str(uuid.uuid4())
    if not focus["goal"]:
        focus["goal"] = str(user_message or "").strip()[:240]
    focus["updated_at"] = now

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
            if name in {"image_read", "read", "read_section", "table_extract", "fact_check_file"}:
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

    artifact_refs = normalize_attachment_ids([str(item.get("artifact_id") or "") for item in artifact_memory[:8]])
    active_artifact_refs = normalize_attachment_ids([str(item.get("id") or "") for item in focus["active_attachments"]])
    task = normalize_recent_task(
        {
            "task_id": focus["task_id"],
            "turn_id": user_turn_id,
            "user_request": str(user_message or "").strip(),
            "goal": focus["goal"],
            "cwd": focus["cwd"],
            "artifact_refs": active_artifact_refs or artifact_refs,
            "active_files": list(focus["active_files"]),
            "result_digest": result_digest,
            "updated_at": now,
        }
    )

    thread_memory = _session_thread_memory(session)
    next_recent_tasks = [task]
    for item in thread_memory["recent_tasks"]:
        if str(item.get("task_id") or "") == task["task_id"]:
            continue
        next_recent_tasks.append(normalize_recent_task(item))
    thread_memory["recent_tasks"] = next_recent_tasks[:12]
    thread_memory["summary"] = str(session.get("summary") or thread_memory.get("summary") or "").strip()
    thread_memory["recent_cwds"] = _dedupe_strings([focus["cwd"], *thread_memory["recent_cwds"]], limit=8)
    thread_memory["recent_files"] = _dedupe_strings(list(focus["active_files"]) + list(thread_memory["recent_files"]), limit=12)
    thread_memory["updated_at"] = now

    session["current_task_focus"] = dict(focus)
    session["thread_memory"] = dict(thread_memory)
    session["artifact_memory"] = list(artifact_memory)
    sync_session_memory_state(session)
