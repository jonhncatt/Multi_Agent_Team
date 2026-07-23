from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_RESULT_REF_PATTERN = re.compile(r"^tr_[a-f0-9]{32}$")


def _safe_name(value: str) -> str:
    return _SAFE_NAME_PATTERN.sub("_", str(value or "")).strip("._") or "anonymous"


class ToolResultStore:
    """Thread-scoped storage for tool output omitted from model context.

    Only results that are actually truncated need to be written. References are
    opaque and can be opened only while the caller is in the same Thread.
    """

    def __init__(self, root: Path, *, max_results_per_thread: int = 64) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_results_per_thread = max(8, int(max_results_per_thread or 64))
        self._lock = threading.RLock()

    def _thread_dir(self, thread_id: str) -> Path:
        return self.root / _safe_name(thread_id)

    def _path(self, thread_id: str, result_ref: str) -> Path:
        if not _RESULT_REF_PATTERN.fullmatch(str(result_ref or "")):
            raise ValueError("invalid_tool_result_ref")
        return self._thread_dir(thread_id) / f"{result_ref}.json"

    def save(
        self,
        *,
        thread_id: str,
        run_id: str,
        call_id: str,
        tool_name: str,
        content: str,
        token_count: int,
    ) -> str:
        result_ref = f"tr_{uuid.uuid4().hex}"
        target = self._path(thread_id, result_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "result_ref": result_ref,
            "thread_id": str(thread_id or ""),
            "run_id": str(run_id or ""),
            "call_id": str(call_id or ""),
            "tool_name": str(tool_name or "unknown_tool"),
            "content": str(content or ""),
            "token_count": max(0, int(token_count or 0)),
            "created_at": time.time(),
        }
        temporary = target.with_suffix(".json.tmp")
        with self._lock:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
            self._prune_locked(thread_id)
        return result_ref

    def load(self, *, thread_id: str, result_ref: str) -> dict[str, Any] | None:
        try:
            target = self._path(thread_id, result_ref)
        except ValueError:
            return None
        if not target.is_file():
            return None
        try:
            with self._lock:
                payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if str(payload.get("thread_id") or "") != str(thread_id or ""):
            return None
        if str(payload.get("result_ref") or "") != str(result_ref or ""):
            return None
        return payload

    def delete_thread(self, thread_id: str) -> None:
        target = self._thread_dir(thread_id)
        if not target.exists():
            return
        with self._lock:
            shutil.rmtree(target, ignore_errors=True)

    def _prune_locked(self, thread_id: str) -> None:
        paths = sorted(
            self._thread_dir(thread_id).glob("tr_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in paths[self.max_results_per_thread :]:
            path.unlink(missing_ok=True)


__all__ = ["ToolResultStore"]
