from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_SCHEMA_VERSION = 1
TASK_STATUSES = {"active", "blocked", "completed", "archived"}
_SAFE_TASK_ID = re.compile(r"^[a-zA-Z0-9._-]{1,160}$")
_TASK_DIR_LOCKS: dict[str, threading.RLock] = {}
_TASK_DIR_LOCKS_GUARD = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _string_list(value: Any, *, limit: int = 24, item_limit: int = 800) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for raw in list(value or []):
        item = _text(raw, limit=item_limit)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def normalize_task(raw: Any) -> dict[str, Any]:
    payload = dict(raw or {}) if isinstance(raw, dict) else {}
    status = _text(payload.get("status"), limit=32).lower()
    if status not in TASK_STATUSES:
        status = "active"
    task_id = _text(payload.get("task_id") or payload.get("id"), limit=160)
    created_at = _text(payload.get("created_at"), limit=80) or _now_iso()
    updated_at = _text(payload.get("updated_at"), limit=80) or created_at
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "project_id": _text(payload.get("project_id"), limit=160),
        "project_title": _text(payload.get("project_title"), limit=240),
        "project_root": _text(payload.get("project_root"), limit=2000),
        "title": _text(payload.get("title"), limit=120),
        "status": status,
        "goal": _text(payload.get("goal"), limit=4000),
        "summary": _text(payload.get("summary"), limit=12000),
        "progress": _string_list(payload.get("progress"), limit=32),
        "next_steps": _string_list(payload.get("next_steps"), limit=24),
        "decisions": _string_list(payload.get("decisions"), limit=24),
        "blockers": _string_list(payload.get("blockers"), limit=16),
        "artifacts": _string_list(payload.get("artifacts"), limit=32, item_limit=2000),
        "source_thread_id": _text(payload.get("source_thread_id"), limit=160),
        "last_loaded_thread_id": _text(payload.get("last_loaded_thread_id"), limit=160),
        "last_loaded_at": _text(payload.get("last_loaded_at"), limit=80),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def task_context_snapshot(task: Any) -> dict[str, Any]:
    normalized = normalize_task(task)
    return {
        key: normalized[key]
        for key in (
            "task_id",
            "project_id",
            "project_title",
            "title",
            "status",
            "goal",
            "summary",
            "progress",
            "next_steps",
            "decisions",
            "blockers",
            "artifacts",
            "updated_at",
        )
    }


class TaskStore:
    """Durable task snapshots that are independent of any one Thread."""

    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir.expanduser().resolve()
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        lock_key = str(self.tasks_dir)
        with _TASK_DIR_LOCKS_GUARD:
            self._lock = _TASK_DIR_LOCKS.setdefault(lock_key, threading.RLock())

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        normalized = str(task_id or "").strip()
        if not _SAFE_TASK_ID.fullmatch(normalized):
            raise ValueError("Invalid task id")
        return normalized

    def _path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{self._validate_task_id(task_id)}.json"

    def get(self, task_id: str) -> dict[str, Any] | None:
        path = self._path(task_id)
        if not path.is_file():
            return None
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        normalized = normalize_task(payload)
        return normalized if normalized.get("task_id") else None

    def list(self, *, project_id: str | None = None, include_archived: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        wanted_project_id = str(project_id or "").strip()
        tasks: list[dict[str, Any]] = []
        for path in self.tasks_dir.glob("*.json"):
            task = self.get(path.stem)
            if not task:
                continue
            if wanted_project_id and str(task.get("project_id") or "") != wanted_project_id:
                continue
            if not include_archived and str(task.get("status") or "") == "archived":
                continue
            tasks.append(task)
        grouped: list[dict[str, Any]] = []
        for status in ("active", "blocked", "completed", "archived"):
            status_tasks = [item for item in tasks if str(item.get("status") or "") == status]
            status_tasks.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            grouped.extend(status_tasks)
        return grouped[: max(1, min(500, int(limit)))]

    def save(
        self,
        *,
        project_id: str,
        project_title: str,
        project_root: str,
        title: str,
        goal: str,
        summary: str,
        progress: list[str] | None = None,
        next_steps: list[str] | None = None,
        decisions: list[str] | None = None,
        blockers: list[str] | None = None,
        artifacts: list[str] | None = None,
        status: str = "active",
        task_id: str = "",
        source_thread_id: str = "",
    ) -> dict[str, Any]:
        normalized_project_id = _text(project_id, limit=160)
        normalized_title = _text(title, limit=120)
        normalized_goal = _text(goal, limit=4000)
        normalized_summary = _text(summary, limit=12000)
        if not normalized_project_id:
            raise ValueError("project_id is required")
        if not normalized_title:
            raise ValueError("task title is required")
        if not normalized_goal:
            raise ValueError("task goal is required")
        if not normalized_summary:
            raise ValueError("task summary is required")

        now = _now_iso()
        requested_task_id = str(task_id or "").strip()
        existing: dict[str, Any] = {}
        if requested_task_id:
            requested_task_id = self._validate_task_id(requested_task_id)
            existing = self.get(requested_task_id) or {}
            if not existing:
                raise FileNotFoundError(f"Task not found: {requested_task_id}")
            if str(existing.get("project_id") or "") != normalized_project_id:
                raise PermissionError("Task belongs to a different project")
        else:
            requested_task_id = str(uuid.uuid4())

        task = normalize_task(
            {
                **existing,
                "task_id": requested_task_id,
                "project_id": normalized_project_id,
                "project_title": project_title,
                "project_root": project_root,
                "title": normalized_title,
                "goal": normalized_goal,
                "summary": normalized_summary,
                "progress": progress or [],
                "next_steps": next_steps or [],
                "decisions": decisions or [],
                "blockers": blockers or [],
                "artifacts": artifacts or [],
                "status": status,
                "source_thread_id": str(existing.get("source_thread_id") or source_thread_id or ""),
                "created_at": str(existing.get("created_at") or now),
                "updated_at": now,
            }
        )
        self._write(task)
        return task

    def mark_loaded(self, task_id: str, *, thread_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")
        task["last_loaded_thread_id"] = _text(thread_id, limit=160)
        task["last_loaded_at"] = _now_iso()
        self._write(task)
        return task

    def delete(self, task_id: str) -> bool:
        path = self._path(task_id)
        if not path.is_file():
            return False
        with self._lock:
            path.unlink()
        return True

    def _write(self, task: dict[str, Any]) -> None:
        normalized = normalize_task(task)
        if not normalized.get("task_id"):
            raise ValueError("task_id is required")
        path = self._path(str(normalized["task_id"]))
        tmp_path = path.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
