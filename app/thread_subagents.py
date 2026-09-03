from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any
import uuid


_ACTIVE_STATUSES = {"queued", "running"}
_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "interrupted_by_restart",
}
_PROCESS_RUNTIME_ID = str(uuid.uuid4())


def _record_status(record: dict[str, Any]) -> str:
    return str(record.get("status") or "").strip().lower()


class ThreadSubagentStateStore:
    """Atomic JSON persistence for one Thread's Subagent state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _file_key(thread_id: str) -> str:
        return hashlib.sha256(str(thread_id or "").encode("utf-8")).hexdigest()

    def _path(self, thread_id: str) -> Path:
        return self.root / f"{self._file_key(thread_id)}.json"

    def load(self, thread_id: str) -> dict[str, dict[str, Any]]:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return {}
        path = self._path(normalized_thread_id)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict) or str(payload.get("thread_id") or "") != normalized_thread_id:
            return {}
        records: dict[str, dict[str, Any]] = {}
        for raw_record in list(payload.get("records") or []):
            if not isinstance(raw_record, dict):
                continue
            subagent_id = str(raw_record.get("id") or "").strip()
            if not subagent_id:
                continue
            record = copy.deepcopy(raw_record)
            record["id"] = subagent_id
            record["thread_id"] = normalized_thread_id
            records[subagent_id] = record
        return records

    def save(self, thread_id: str, records: dict[str, dict[str, Any]]) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            raise ValueError("thread_id is required")
        path = self._path(normalized_thread_id)
        payload = {
            "schema_version": 1,
            "thread_id": normalized_thread_id,
            "updated_at": time.time(),
            "records": [
                copy.deepcopy(record)
                for record in records.values()
                if isinstance(record, dict)
            ],
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def delete_thread(self, thread_id: str) -> None:
        self._path(thread_id).unlink(missing_ok=True)


class ThreadSubagentManager:
    """Thread-scoped Subagent state with process-local execution handles."""

    def __init__(
        self,
        root: Path,
        *,
        runtime_id: str | None = None,
    ) -> None:
        self.runtime_id = str(runtime_id or _PROCESS_RUNTIME_ID)
        self.store = ThreadSubagentStateStore(root)
        self._condition = threading.Condition(threading.RLock())
        self._records_by_thread: dict[str, dict[str, dict[str, Any]]] = {}
        self._handles: dict[tuple[str, str], dict[str, Any]] = {}

    @staticmethod
    def _interrupted_result(record: dict[str, Any]) -> dict[str, Any]:
        subagent_id = str(record.get("id") or "")
        role = str(record.get("role") or "explorer")
        item = dict(record.get("item") or {})
        message = "Subagent execution was interrupted because Vintage Programmer restarted."
        return {
            "ok": False,
            "subagent_id": subagent_id,
            "role": role,
            "label": str(item.get("label") or ""),
            "status": "interrupted_by_restart",
            "error_kind": "subagent_interrupted_by_restart",
            "error": message,
            "summary": message,
            "token_usage": {},
        }

    def _load_thread_locked(self, thread_id: str) -> dict[str, dict[str, Any]]:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return {}
        existing = self._records_by_thread.get(normalized_thread_id)
        if existing is not None:
            return existing
        records = self.store.load(normalized_thread_id)
        changed = False
        now = time.time()
        for record in records.values():
            status = _record_status(record)
            if status not in _ACTIVE_STATUSES:
                continue
            if str(record.get("owner_runtime_id") or "") == self.runtime_id:
                continue
            result = self._interrupted_result(record)
            item = {
                **dict(record.get("item") or {}),
                "status": "interrupted_by_restart",
                "summary": result["summary"],
                "completed_at": now,
            }
            record.update(
                {
                    "status": "interrupted_by_restart",
                    "result": result,
                    "item": item,
                    "detached": True,
                    "updated_at": now,
                }
            )
            changed = True
        self._records_by_thread[normalized_thread_id] = records
        if changed:
            self.store.save(normalized_thread_id, records)
        return records

    def _save_thread_locked(self, thread_id: str) -> None:
        self.store.save(thread_id, self._records_by_thread.get(thread_id, {}))

    def create(
        self,
        *,
        thread_id: str,
        subagent_id: str,
        parent_run_id: str,
        role: str,
        item: dict[str, Any],
        cancel_event: threading.Event,
    ) -> dict[str, Any]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        if not normalized_thread_id or not normalized_id:
            raise ValueError("thread_id and subagent_id are required")
        now = time.time()
        with self._condition:
            records = self._load_thread_locked(normalized_thread_id)
            if normalized_id in records:
                raise ValueError(f"Duplicate Subagent id: {normalized_id}")
            record = {
                "id": normalized_id,
                "thread_id": normalized_thread_id,
                "parent_run_id": str(parent_run_id or ""),
                "owner_runtime_id": self.runtime_id,
                "role": str(role or "explorer"),
                "status": "queued",
                "item": copy.deepcopy(item),
                "result": None,
                "detached": False,
                "usage_reported": False,
                "collected": False,
                "published": False,
                "created_at": now,
                "updated_at": now,
            }
            records[normalized_id] = record
            self._handles[(normalized_thread_id, normalized_id)] = {
                "cancel_event": cancel_event,
                "future": None,
                "cancel_commands": None,
            }
            self._save_thread_locked(normalized_thread_id)
            self._condition.notify_all()
            return copy.deepcopy(record)

    def attach_handles(
        self,
        *,
        thread_id: str,
        subagent_id: str,
        future: Any | None = None,
        cancel_commands: Any | None = None,
    ) -> None:
        key = (str(thread_id or "").strip(), str(subagent_id or "").strip())
        with self._condition:
            handle = self._handles.get(key)
            if handle is None:
                return
            if future is not None:
                handle["future"] = future
            if cancel_commands is not None:
                handle["cancel_commands"] = cancel_commands
            self._condition.notify_all()

    def mark_running(
        self,
        *,
        thread_id: str,
        subagent_id: str,
        item: dict[str, Any],
    ) -> bool:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if not isinstance(record, dict) or _record_status(record) not in _ACTIVE_STATUSES:
                return False
            record["status"] = "running"
            record["item"] = copy.deepcopy(item)
            record["updated_at"] = time.time()
            self._save_thread_locked(normalized_thread_id)
            self._condition.notify_all()
            return True

    def finish(
        self,
        *,
        thread_id: str,
        subagent_id: str,
        status: str,
        item: dict[str, Any],
        result: dict[str, Any],
        detached: bool = False,
    ) -> bool:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        normalized_status = str(status or "failed").strip().lower()
        if normalized_status not in _TERMINAL_STATUSES:
            normalized_status = "failed"
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if not isinstance(record, dict) or _record_status(record) in _TERMINAL_STATUSES:
                return False
            record.update(
                {
                    "status": normalized_status,
                    "item": copy.deepcopy(item),
                    "result": copy.deepcopy(result),
                    "detached": bool(detached),
                    "updated_at": time.time(),
                }
            )
            self._handles.pop((normalized_thread_id, normalized_id), None)
            self._save_thread_locked(normalized_thread_id)
            self._condition.notify_all()
            return True

    def records(
        self,
        *,
        thread_id: str,
        subagent_ids: list[str],
        timeout_seconds: float = 0,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_ids = list(
            dict.fromkeys(
                str(item or "").strip()
                for item in subagent_ids
                if str(item or "").strip()
            )
        )
        deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
        with self._condition:
            records = self._load_thread_locked(normalized_thread_id)
            unknown_ids = [item for item in normalized_ids if item not in records]
            if unknown_ids:
                return [], unknown_ids
            while normalized_ids and any(
                _record_status(records[item]) in _ACTIVE_STATUSES
                for item in normalized_ids
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
                records = self._load_thread_locked(normalized_thread_id)
            return [copy.deepcopy(records[item]) for item in normalized_ids], []

    def default_wait_ids(self, *, thread_id: str, preferred_ids: list[str]) -> list[str]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_preferred = list(
            dict.fromkeys(str(item or "").strip() for item in preferred_ids if str(item or "").strip())
        )
        with self._condition:
            records = self._load_thread_locked(normalized_thread_id)
            if normalized_preferred:
                return [item for item in normalized_preferred if item in records]
            return [
                subagent_id
                for subagent_id, record in records.items()
                if _record_status(record) in _ACTIVE_STATUSES or not bool(record.get("collected"))
            ]

    def collect(self, *, thread_id: str, subagent_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if not isinstance(record, dict) or _record_status(record) in _ACTIVE_STATUSES:
                return None, {}
            result = record.get("result")
            if not isinstance(result, dict):
                return None, {}
            usage: dict[str, Any] = {}
            changed = False
            if not bool(record.get("collected")):
                record["collected"] = True
                changed = True
            if not bool(record.get("usage_reported")):
                usage = copy.deepcopy(dict(result.get("token_usage") or {}))
                record["usage_reported"] = True
                changed = True
            if changed:
                record["updated_at"] = time.time()
                self._save_thread_locked(normalized_thread_id)
            return copy.deepcopy(result), usage

    def claim_usage(self, *, thread_id: str, subagent_id: str) -> dict[str, Any]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if not isinstance(record, dict) or bool(record.get("usage_reported")):
                return {}
            result = record.get("result")
            if not isinstance(result, dict):
                return {}
            record["usage_reported"] = True
            record["updated_at"] = time.time()
            self._save_thread_locked(normalized_thread_id)
            return copy.deepcopy(dict(result.get("token_usage") or {}))

    def claim_publish(
        self,
        *,
        thread_id: str,
        subagent_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if (
                not isinstance(record, dict)
                or _record_status(record) in _ACTIVE_STATUSES
                or not isinstance(record.get("result"), dict)
                or bool(record.get("collected"))
                or bool(record.get("published"))
                or bool(record.get("detached"))
            ):
                return None
            record["published"] = True
            record["updated_at"] = time.time()
            self._save_thread_locked(normalized_thread_id)
            return copy.deepcopy(dict(record.get("item") or {})), copy.deepcopy(dict(record["result"]))

    def release_publish(self, *, thread_id: str, subagent_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_id = str(subagent_id or "").strip()
        with self._condition:
            record = self._load_thread_locked(normalized_thread_id).get(normalized_id)
            if not isinstance(record, dict) or not bool(record.get("published")):
                return
            record["published"] = False
            record["updated_at"] = time.time()
            self._save_thread_locked(normalized_thread_id)

    def live_handles(
        self,
        *,
        thread_id: str,
        subagent_ids: list[str],
    ) -> list[tuple[str, dict[str, Any]]]:
        normalized_thread_id = str(thread_id or "").strip()
        with self._condition:
            return [
                (subagent_id, dict(self._handles[(normalized_thread_id, subagent_id)]))
                for subagent_id in subagent_ids
                if (normalized_thread_id, subagent_id) in self._handles
            ]

    def cancel_parent_run(self, *, thread_id: str, parent_run_id: str) -> list[str]:
        """Cancel and persist every active Subagent owned by one parent Agent run."""

        normalized_thread_id = str(thread_id or "").strip()
        normalized_parent_run_id = str(parent_run_id or "").strip()
        if not normalized_thread_id or not normalized_parent_run_id:
            return []
        with self._condition:
            records = self._load_thread_locked(normalized_thread_id)
            target_ids = [
                subagent_id
                for subagent_id, record in records.items()
                if _record_status(record) in _ACTIVE_STATUSES
                and str(record.get("parent_run_id") or "").strip() == normalized_parent_run_id
            ]
            handles = [
                (subagent_id, dict(self._handles.get((normalized_thread_id, subagent_id)) or {}))
                for subagent_id in target_ids
            ]

        for subagent_id, handle in handles:
            cancel_event = handle.get("cancel_event")
            if cancel_event and hasattr(cancel_event, "set"):
                cancel_event.set()
            cancel_commands = handle.get("cancel_commands")
            if callable(cancel_commands):
                try:
                    cancel_commands(run_id=subagent_id)
                except Exception:
                    pass
            future = handle.get("future")
            if future is not None and hasattr(future, "cancel"):
                try:
                    future.cancel()
                except Exception:
                    pass

        cancelled_ids: list[str] = []
        now = time.time()
        with self._condition:
            records = self._load_thread_locked(normalized_thread_id)
            for subagent_id in target_ids:
                record = records.get(subagent_id)
                if not isinstance(record, dict) or _record_status(record) not in _ACTIVE_STATUSES:
                    continue
                item = dict(record.get("item") or {})
                message = "Subagent was cancelled because its parent run was stopped by the user."
                result = {
                    "ok": False,
                    "subagent_id": subagent_id,
                    "role": str(record.get("role") or "explorer"),
                    "label": str(item.get("label") or ""),
                    "status": "cancelled",
                    "error_kind": "subagent_cancelled",
                    "error": message,
                    "summary": message,
                    "token_usage": {},
                }
                record.update(
                    {
                        "status": "cancelled",
                        "result": result,
                        "item": {
                            **item,
                            "status": "cancelled",
                            "summary": message,
                            "completed_at": now,
                        },
                        "detached": True,
                        "updated_at": now,
                    }
                )
                self._handles.pop((normalized_thread_id, subagent_id), None)
                cancelled_ids.append(subagent_id)
            if cancelled_ids:
                self._save_thread_locked(normalized_thread_id)
                self._condition.notify_all()
        return cancelled_ids

    def delete_thread(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        with self._condition:
            self._records_by_thread.pop(normalized_thread_id, None)
            for key in [key for key in self._handles if key[0] == normalized_thread_id]:
                self._handles.pop(key, None)
            self.store.delete_thread(normalized_thread_id)
            self._condition.notify_all()


_MANAGERS_LOCK = threading.Lock()
_MANAGERS: dict[str, ThreadSubagentManager] = {}


def get_thread_subagent_manager(root: Path) -> ThreadSubagentManager:
    normalized_root = str(Path(root).resolve())
    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(normalized_root)
        if manager is None:
            manager = ThreadSubagentManager(Path(normalized_root))
            _MANAGERS[normalized_root] = manager
        return manager
