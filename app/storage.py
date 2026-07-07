from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.serialization import dump_model
from app.session_migration import CONTEXT_SCHEMA_VERSION, migrate_legacy_session_to_context_manager


_SAFE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_ACTIVITY_HEAVY_KEYS = {
    "llm_exchanges",
    "trace_events",
    "tool_events",
    "tool_items",
    "live_items",
    "model_draft",
    "final_answer",
    "runtime_error",
    "inspector",
    "answer_stream",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return _SAFE_NAME_PATTERN.sub("_", name).strip("._") or "file"


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _activity_has_sidecar_payload(activity: dict[str, Any]) -> bool:
    return any(_is_non_empty(activity.get(key)) for key in _ACTIVITY_HEAVY_KEYS)


def _coerce_turns(raw: Any) -> list[dict[str, Any]]:
    return [item for item in list(raw or []) if isinstance(item, dict)]


def _new_repair_stats() -> dict[str, Any]:
    return {
        "scanned_sessions": 0,
        "migrated_sessions": 0,
        "migrated_turns": 0,
        "backfilled_turns": 0,
        "rebuilt_meta": 0,
        "skipped": 0,
        "errors": [],
    }


class RunArtifactStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _session_dir(self, session_id: str) -> Path:
        return self.runs_dir / _safe_name(str(session_id or ""))

    def _path(self, session_id: str, run_id: str) -> Path:
        return self._session_dir(session_id) / f"{_safe_name(str(run_id or 'run'))}.json"

    def trace_ref(self, session_id: str, run_id: str) -> str:
        return f"{_safe_name(str(session_id or ''))}/{_safe_name(str(run_id or 'run'))}"

    def save(self, *, session_id: str, run_id: str, artifact: dict[str, Any]) -> str:
        sid = str(session_id or "").strip()
        rid = str(run_id or "").strip() or str(uuid.uuid4())
        trace_ref = self.trace_ref(sid, rid)
        payload = dump_model(dict(artifact or {}))
        payload["session_id"] = sid
        payload["run_id"] = rid
        payload["trace_ref"] = trace_ref
        payload["updated_at"] = now_iso()
        payload.setdefault("created_at", payload["updated_at"])
        target = self._path(sid, rid)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(target)
        return trace_ref

    def load(self, *, session_id: str, run_id: str) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        rid = str(run_id or "").strip()
        if not sid or not rid:
            return None
        path = self._path(sid, rid)
        if not path.exists():
            return None
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else None
        except Exception:
            return None

    def load_by_ref(self, trace_ref: str) -> dict[str, Any] | None:
        raw = str(trace_ref or "").strip()
        if not raw:
            return None
        parts = [part for part in raw.split("/") if part]
        if len(parts) < 2:
            return None
        return self.load(session_id=parts[-2], run_id=parts[-1])

    def delete_session(self, session_id: str) -> None:
        target = self._session_dir(session_id)
        if not target.exists():
            return
        with self._lock:
            shutil.rmtree(target, ignore_errors=True)


class SessionMetaStore:
    def __init__(self, meta_dir: Path) -> None:
        self.meta_dir = meta_dir
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        return self.meta_dir / f"{_safe_name(str(session_id or ''))}.json"

    @staticmethod
    def metadata_from_session(session: dict[str, Any]) -> dict[str, Any]:
        payload = dict(session or {})
        sid = str(payload.get("id") or "").strip()
        turns = _coerce_turns(payload.get("turns"))
        custom_title = str(payload.get("title") or "").strip()
        title = custom_title
        if not title:
            title = "新会话"
            for turn in turns:
                if str(turn.get("role") or "") != "user":
                    continue
                text = str(turn.get("text") or "").replace("\n", " ").strip()
                if text:
                    title = text[:48]
                    break
        preview = ""
        if turns:
            preview = str(turns[-1].get("text") or "").replace("\n", " ").strip()[:80]
        agent_state = payload.get("agent_state")
        if not isinstance(agent_state, dict):
            agent_state = {}
        return {
            "session_id": sid,
            "title": title,
            "has_custom_title": bool(custom_title),
            "preview": preview,
            "turn_count": len(turns),
            "project_id": str(payload.get("project_id") or ""),
            "project_title": str(payload.get("project_title") or ""),
            "project_root": str(payload.get("project_root") or ""),
            "git_branch": str(payload.get("git_branch") or ""),
            "cwd": str(payload.get("cwd") or ""),
            "created_at": str(payload.get("created_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "status": str(agent_state.get("turn_status") or "idle"),
        }

    @staticmethod
    def display_title_for_session(session: dict[str, Any]) -> str:
        return str(SessionMetaStore.metadata_from_session(session).get("title") or "").strip()

    def save_session(self, session: dict[str, Any]) -> dict[str, Any]:
        meta = self.metadata_from_session(session)
        sid = str(meta.get("session_id") or "").strip()
        if not sid:
            return meta
        target = self._path(sid)
        tmp_path = target.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(target)
        return meta

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else None
        except Exception:
            return None

    def list_recent(self, limit: int = 50, *, project_id: str | None = None) -> list[dict[str, Any]]:
        max_items = max(1, min(500, int(limit)))
        wanted_project_id = str(project_id or "").strip()
        rows: list[dict[str, Any]] = []
        for path in sorted(self.meta_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if wanted_project_id and str(payload.get("project_id") or "").strip() != wanted_project_id:
                continue
            rows.append(dict(payload))
            if len(rows) >= max_items:
                break
        return sorted(rows, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:max_items]

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        try:
            with self._lock:
                path.unlink(missing_ok=True)
        except Exception:
            pass


class SessionStore:
    def __init__(
        self,
        sessions_dir: Path,
        *,
        runs_dir: Path | None = None,
        session_meta_dir: Path | None = None,
        run_artifact_store: RunArtifactStore | None = None,
        session_meta_store: SessionMetaStore | None = None,
    ) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        data_root = self.sessions_dir.parent
        self.run_artifact_store = run_artifact_store or RunArtifactStore(runs_dir or data_root / "runs")
        self.session_meta_store = session_meta_store or SessionMetaStore(session_meta_dir or data_root / "session_meta")
        self._lock = threading.Lock()

    def _default_agent_state(self) -> dict[str, Any]:
        return {
            "agent_id": "vintage_programmer",
            "phase": "idle",
            "turn_status": "idle",
            "last_run_id": "",
            "last_model": "",
            "last_provider": "",
            "last_compacted_at": "",
            "tool_count": 0,
            "evidence_status": "not_needed",
            "enabled_skill_ids": [],
            "final_answer_preview": "",
            "runtime_error": {},
            "updated_at": now_iso(),
        }

    def _default_context_manager(self) -> dict[str, Any]:
        return {
            "clean_summary": "",
            "clean_turns": [],
            "recent_observations": [],
            "active_files": [],
            "plan": [],
            "context_version": 0,
        }

    def _default_work_cursor(self) -> dict[str, Any]:
        return {
            "project_root": "",
            "cwd": "",
            "active_files": [],
            "active_attachments": [],
            "updated_at": "",
        }

    def _default_task_state(self) -> dict[str, Any]:
        return {
            "task_id": "",
            "goal": "",
            "status": "idle",
            "plan_items": [],
            "current_step_id": "",
            "completed_steps": [],
            "blocked_reason": "",
            "next_required_action": "",
            "failed_attempts": [],
            "progress_basis": [],
            "evidence_refs": [],
            "validation_warnings": [],
            "updated_at": "",
        }

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _activity_tool_count(self, activity: dict[str, Any], artifact: dict[str, Any] | None = None) -> int:
        for source in (artifact or {}, activity or {}):
            try:
                explicit = int(source.get("tool_count") or 0)
            except Exception:
                explicit = 0
            if explicit > 0:
                return explicit
        tool_events = (artifact or {}).get("tool_events")
        if isinstance(tool_events, list) and tool_events:
            return len(tool_events)
        for key in ("tool_items", "live_items"):
            items = activity.get(key)
            if isinstance(items, list) and items:
                return len(items)
        trace_events = activity.get("trace_events")
        if isinstance(trace_events, list):
            call_ids: set[str] = set()
            tool_like = 0
            for trace in trace_events:
                if not isinstance(trace, dict):
                    continue
                trace_type = str(trace.get("type") or "")
                if not trace_type.startswith("tool."):
                    continue
                payload = trace.get("payload")
                if not isinstance(payload, dict):
                    payload = {}
                call_id = str(payload.get("call_id") or payload.get("tool_call_id") or "").strip()
                if call_id:
                    call_ids.add(call_id)
                else:
                    tool_like += 1
            return len(call_ids) or tool_like
        return 0

    def _activity_summary(
        self,
        activity: dict[str, Any] | None,
        *,
        run_id: str,
        trace_ref: str,
        tool_count: int | None = None,
    ) -> dict[str, Any]:
        source = dict(activity or {})
        summary: dict[str, Any] = {}
        normalized_run_id = str(run_id or source.get("run_id") or "").strip()
        normalized_trace_ref = str(trace_ref or source.get("trace_ref") or "").strip()
        if normalized_run_id:
            summary["run_id"] = normalized_run_id
        if normalized_trace_ref:
            summary["trace_ref"] = normalized_trace_ref
        normalized_tool_count = tool_count
        if normalized_tool_count is None:
            try:
                normalized_tool_count = int(source.get("tool_count") or 0)
            except Exception:
                normalized_tool_count = 0
        summary["tool_count"] = max(0, int(normalized_tool_count or 0))
        summary["status"] = str(source.get("status") or "idle").strip() or "idle"
        summary_text = str(source.get("summary") or source.get("activity_summary") or "").strip()
        activity_summary = str(source.get("activity_summary") or summary_text).strip()
        if summary_text:
            summary["summary"] = summary_text
        if activity_summary:
            summary["activity_summary"] = activity_summary
        if "run_duration_ms" in source and source.get("run_duration_ms") not in (None, ""):
            try:
                summary["run_duration_ms"] = max(0, int(source.get("run_duration_ms") or 0))
            except Exception:
                pass
        return summary

    def _run_id_for_turn(self, turn: dict[str, Any]) -> str:
        activity = turn.get("activity")
        if not isinstance(activity, dict):
            activity = {}
        return (
            str(activity.get("run_id") or "").strip()
            or str(turn.get("run_id") or "").strip()
            or str(turn.get("id") or "").strip()
            or str(uuid.uuid4())
        )

    def _artifact_for_turn(
        self,
        *,
        session_id: str,
        turn: dict[str, Any],
        run_id: str,
        activity: dict[str, Any] | None = None,
        answer_bundle: dict[str, Any] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        inspector: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        activity_payload = dict(activity if isinstance(activity, dict) else (turn.get("activity") or {}))
        answer_payload = dict(answer_bundle if isinstance(answer_bundle, dict) else (turn.get("answer_bundle") or {}))
        artifact = {
            "session_id": str(session_id or ""),
            "thread_id": str(session_id or ""),
            "run_id": str(run_id or ""),
            "turn_id": str(turn.get("id") or ""),
            "turn_created_at": str(turn.get("created_at") or ""),
            "activity": activity_payload,
            "answer_bundle": answer_payload,
        }
        if tool_events is not None:
            artifact["tool_events"] = [dump_model(item) for item in list(tool_events or []) if item is not None]
        elif isinstance(activity_payload.get("tool_events"), list):
            artifact["tool_events"] = list(activity_payload.get("tool_events") or [])
        if inspector is not None:
            artifact["inspector"] = dict(inspector or {})
        elif isinstance(activity_payload.get("inspector"), dict):
            artifact["inspector"] = dict(activity_payload.get("inspector") or {})
        for key in ("model_draft", "final_answer", "runtime_error", "llm_exchanges", "trace_events", "tool_items", "live_items"):
            if key in activity_payload:
                artifact[key] = activity_payload.get(key)
        for key, value in dict(extra or {}).items():
            artifact[key] = value
        return artifact

    def persist_turn_artifact(
        self,
        session: dict[str, Any],
        *,
        turn_id: str,
        run_id: str | None = None,
        activity: dict[str, Any] | None = None,
        answer_bundle: dict[str, Any] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        inspector: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        session_id = str((session or {}).get("id") or "").strip()
        if not session_id:
            return None
        wanted_turn_id = str(turn_id or "").strip()
        if not wanted_turn_id:
            return None
        turns = _coerce_turns((session or {}).get("turns"))
        turn = next((item for item in turns if str(item.get("id") or "") == wanted_turn_id), None)
        if not turn:
            return None
        rid = str(run_id or "").strip() or self._run_id_for_turn(turn)
        artifact = self._artifact_for_turn(
            session_id=session_id,
            turn=turn,
            run_id=rid,
            activity=activity,
            answer_bundle=answer_bundle,
            tool_events=tool_events,
            inspector=inspector,
            extra=extra,
        )
        trace_ref = self.run_artifact_store.save(session_id=session_id, run_id=rid, artifact=artifact)
        artifact_activity = artifact.get("activity") if isinstance(artifact.get("activity"), dict) else {}
        turn["activity"] = self._activity_summary(
            artifact_activity,
            run_id=rid,
            trace_ref=trace_ref,
            tool_count=self._activity_tool_count(artifact_activity, artifact),
        )
        turn["answer_bundle"] = {}
        turn["run_artifact"] = {}
        return artifact

    def _load_turn_artifact(
        self,
        *,
        session_id: str,
        run_id: str,
        trace_ref: str,
    ) -> dict[str, Any] | None:
        artifact = self.run_artifact_store.load_by_ref(trace_ref) if trace_ref else None
        if artifact is None and run_id:
            artifact = self.run_artifact_store.load(session_id=session_id, run_id=run_id)
        return artifact

    def _turn_needs_summary_enrichment(self, activity: dict[str, Any], *, run_id: str, trace_ref: str) -> bool:
        if not (run_id or trace_ref):
            return False
        if not str(activity.get("status") or "").strip():
            return True
        return "tool_count" not in activity

    def _backfill_turn_activity_summaries(
        self,
        session: dict[str, Any],
        *,
        repair_stats: dict[str, Any] | None = None,
    ) -> bool:
        session_id = str((session or {}).get("id") or "").strip()
        if not session_id:
            return False
        changed = False
        for turn in _coerce_turns(session.get("turns")):
            if str(turn.get("role") or "") != "assistant":
                continue
            activity = turn.get("activity")
            if not isinstance(activity, dict):
                activity = {}
            run_id = self._run_id_for_turn(turn)
            trace_ref = str(activity.get("trace_ref") or "").strip()
            next_activity = self._activity_summary(
                activity,
                run_id=run_id,
                trace_ref=trace_ref,
            )
            if self._turn_needs_summary_enrichment(activity, run_id=run_id, trace_ref=trace_ref):
                artifact = self._load_turn_artifact(session_id=session_id, run_id=run_id, trace_ref=trace_ref)
                if artifact:
                    artifact_activity = artifact.get("activity") if isinstance(artifact.get("activity"), dict) else {}
                    next_activity = self._activity_summary(
                        artifact_activity,
                        run_id=str(artifact.get("run_id") or run_id or ""),
                        trace_ref=str(artifact.get("trace_ref") or trace_ref or ""),
                        tool_count=self._activity_tool_count(artifact_activity, artifact),
                    )
            if turn.get("activity") != next_activity:
                turn["activity"] = next_activity
                changed = True
                if repair_stats is not None:
                    repair_stats["backfilled_turns"] = int(repair_stats.get("backfilled_turns") or 0) + 1
        return changed

    def _migrate_turn_artifacts(
        self,
        session: dict[str, Any],
        *,
        repair_stats: dict[str, Any] | None = None,
    ) -> bool:
        session_id = str((session or {}).get("id") or "").strip()
        if not session_id:
            return False
        changed = False
        for turn in _coerce_turns(session.get("turns")):
            if str(turn.get("role") or "") != "assistant":
                continue
            activity = turn.get("activity")
            if not isinstance(activity, dict):
                activity = {}
            answer_bundle = turn.get("answer_bundle")
            if not isinstance(answer_bundle, dict):
                answer_bundle = {}
            embedded_artifact = turn.get("run_artifact")
            if not isinstance(embedded_artifact, dict):
                embedded_artifact = {}
            needs_sidecar = (
                _activity_has_sidecar_payload(activity)
                or bool(answer_bundle)
                or bool(embedded_artifact)
            )
            if not needs_sidecar:
                continue
            run_id = self._run_id_for_turn(turn)
            existing_trace_ref = str(activity.get("trace_ref") or "").strip()
            existing_artifact = self.run_artifact_store.load_by_ref(existing_trace_ref) if existing_trace_ref else None
            if existing_artifact is None:
                self.persist_turn_artifact(
                    session,
                    turn_id=str(turn.get("id") or ""),
                    run_id=run_id,
                    activity=activity,
                    answer_bundle=answer_bundle,
                    extra=embedded_artifact,
                )
            else:
                trace_ref = str(existing_artifact.get("trace_ref") or existing_trace_ref)
                artifact_activity = existing_artifact.get("activity") if isinstance(existing_artifact.get("activity"), dict) else {}
                turn["activity"] = self._activity_summary(
                    artifact_activity,
                    run_id=run_id,
                    trace_ref=trace_ref,
                    tool_count=self._activity_tool_count(artifact_activity, existing_artifact),
                )
                turn["answer_bundle"] = {}
                turn["run_artifact"] = {}
            changed = True
            if repair_stats is not None:
                repair_stats["migrated_turns"] = int(repair_stats.get("migrated_turns") or 0) + 1
        return changed

    def expand_turn_for_view(self, session_id: str, turn: dict[str, Any], *, view: str = "summary") -> dict[str, Any]:
        payload = dict(turn or {})
        if str(payload.get("role") or "") != "assistant":
            payload.setdefault("answer_bundle", {})
            payload.setdefault("activity", {})
            payload["run_artifact"] = {}
            return payload
        requested_view = str(view or "summary").strip().lower()
        activity = payload.get("activity")
        if not isinstance(activity, dict):
            activity = {}
        run_id = str(activity.get("run_id") or payload.get("run_id") or payload.get("id") or "").strip()
        trace_ref = str(activity.get("trace_ref") or "").strip()
        if requested_view == "full":
            artifact = self._load_turn_artifact(session_id=session_id, run_id=run_id, trace_ref=trace_ref)
            if artifact:
                full_activity = dict(artifact.get("activity") or {})
                full_activity.setdefault("run_id", str(artifact.get("run_id") or run_id or ""))
                full_activity.setdefault("trace_ref", str(artifact.get("trace_ref") or trace_ref or ""))
                full_activity.setdefault("session_id", str(session_id or ""))
                full_activity.setdefault("thread_id", str(session_id or ""))
                full_activity["tool_count"] = self._activity_tool_count(full_activity, artifact)
                full_activity["full_loaded"] = True
                if artifact.get("tool_events") and not full_activity.get("tool_items"):
                    full_activity["tool_items"] = list(artifact.get("tool_events") or [])
                payload["activity"] = full_activity
                payload["answer_bundle"] = dict(artifact.get("answer_bundle") or {})
                payload["run_artifact"] = dict(artifact)
            else:
                payload["activity"] = dict(activity)
                payload["activity"]["full_loaded"] = True
                payload["answer_bundle"] = dict(payload.get("answer_bundle") or {})
                payload["run_artifact"] = {}
            return payload
        payload["activity"] = self._activity_summary(
            activity,
            run_id=run_id,
            trace_ref=trace_ref,
        )
        payload["answer_bundle"] = {}
        payload["run_artifact"] = {}
        return payload

    def _normalize_session(
        self,
        session: dict[str, Any],
        *,
        default_project: dict[str, Any] | None = None,
        repair_stats: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        changed = False
        payload = dict(session or {})

        if not str(payload.get("id") or "").strip():
            payload["id"] = str(uuid.uuid4())
            changed = True
        if not str(payload.get("created_at") or "").strip():
            payload["created_at"] = now_iso()
            changed = True
        if not str(payload.get("updated_at") or "").strip():
            payload["updated_at"] = str(payload.get("created_at") or now_iso())
            changed = True
        if not isinstance(payload.get("turns"), list):
            payload["turns"] = []
            changed = True
        if not isinstance(payload.get("active_attachment_ids"), list):
            payload["active_attachment_ids"] = []
            changed = True
        if not isinstance(payload.get("route_state"), dict):
            payload["route_state"] = {}
            changed = True
        if not isinstance(payload.get("attachment_route_states"), dict):
            payload["attachment_route_states"] = {}
            changed = True
        if not isinstance(payload.get("work_cursor"), dict):
            payload["work_cursor"] = self._default_work_cursor()
            changed = True
        else:
            work_cursor = {**self._default_work_cursor(), **dict(payload.get("work_cursor") or {})}
            if work_cursor != payload.get("work_cursor"):
                payload["work_cursor"] = work_cursor
                changed = True
        if not isinstance(payload.get("task_state"), dict):
            payload["task_state"] = self._default_task_state()
            changed = True
        else:
            task_state = {**self._default_task_state(), **dict(payload.get("task_state") or {})}
            if task_state != payload.get("task_state"):
                payload["task_state"] = task_state
                changed = True
        if not isinstance(payload.get("thread_memory"), dict):
            payload["thread_memory"] = {}
            changed = True
        if not isinstance(payload.get("artifact_memory"), list):
            payload["artifact_memory"] = []
            changed = True
        if not isinstance(payload.get("compaction_state"), dict):
            payload["compaction_state"] = {}
            changed = True
        try:
            context_schema_version = int(payload.get("context_schema_version") or 0)
        except Exception:
            context_schema_version = 0
        if context_schema_version < 0:
            payload["context_schema_version"] = 0
            changed = True
        if not isinstance(payload.get("context_manager"), dict):
            payload["context_manager"] = self._default_context_manager()
            changed = True
        else:
            context_manager = {**self._default_context_manager(), **dict(payload.get("context_manager") or {})}
            if context_manager != payload.get("context_manager"):
                payload["context_manager"] = context_manager
                changed = True
        agent_state = payload.get("agent_state")
        if not isinstance(agent_state, dict):
            payload["agent_state"] = self._default_agent_state()
            changed = True
        else:
            merged_state = {**self._default_agent_state(), **agent_state}
            if merged_state != agent_state:
                payload["agent_state"] = merged_state
                changed = True

        if default_project:
            default_project_id = str(default_project.get("project_id") or "").strip()
            default_project_title = str(default_project.get("title") or "").strip()
            default_project_root = str(default_project.get("root_path") or "").strip()
            default_git_branch = str(default_project.get("git_branch") or "").strip()
            if not str(payload.get("project_id") or "").strip():
                payload["project_id"] = default_project_id
                changed = True
            if not str(payload.get("project_title") or "").strip():
                payload["project_title"] = default_project_title
                changed = True
            if not str(payload.get("project_root") or "").strip():
                payload["project_root"] = default_project_root
                changed = True
            if not str(payload.get("git_branch") or "").strip():
                payload["git_branch"] = default_git_branch
                changed = True
        if not str(payload.get("cwd") or "").strip():
            payload["cwd"] = str(payload.get("project_root") or "")
            changed = True

        payload_before_migration = dict(payload)
        payload, migrated = migrate_legacy_session_to_context_manager(payload)
        if migrated or payload != payload_before_migration:
            changed = True

        from app import session_context as session_context_impl

        if session_context_impl.sync_session_memory_state(payload):
            changed = True
        if self._migrate_turn_artifacts(payload, repair_stats=repair_stats):
            changed = True
        if self._backfill_turn_activity_summaries(payload, repair_stats=repair_stats):
            changed = True

        return payload, changed

    def create(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project.get("project_id") or "").strip()
        project_title = str(project.get("title") or "").strip()
        project_root = str(project.get("root_path") or "").strip()
        git_branch = str(project.get("git_branch") or "").strip()
        session = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "title": "",
            "summary": "",
            "project_id": project_id,
            "project_title": project_title,
            "project_root": project_root,
            "git_branch": git_branch,
            "cwd": project_root,
            "turns": [],
            "active_attachment_ids": [],
            "attachment_context_cleared": False,
            "agent_state": self._default_agent_state(),
            "route_state": {},
            "attachment_route_states": {},
            "work_cursor": {
                **self._default_work_cursor(),
                "project_root": project_root,
                "cwd": project_root,
                "updated_at": now_iso(),
            },
            "task_state": self._default_task_state(),
            "thread_memory": {},
            "artifact_memory": [],
            "compaction_state": {},
            "context_manager": self._default_context_manager(),
            "context_schema_version": CONTEXT_SCHEMA_VERSION,
        }
        self.save(session)
        return session

    def load(self, session_id: str, *, default_project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        with self._lock:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        normalized, changed = self._normalize_session(loaded, default_project=default_project)
        if changed:
            self.save(normalized, touch=False)
        return normalized

    def load_for_view(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            with self._lock:
                loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(loaded, dict):
            return None

        payload = dict(loaded)
        payload["id"] = str(payload.get("id") or session_id or "")
        payload["created_at"] = str(payload.get("created_at") or "")
        payload["updated_at"] = str(payload.get("updated_at") or "")
        payload["title"] = str(payload.get("title") or "")
        payload["summary"] = str(payload.get("summary") or "")
        payload["project_id"] = str(payload.get("project_id") or "")
        payload["project_title"] = str(payload.get("project_title") or "")
        payload["project_root"] = str(payload.get("project_root") or "")
        payload["git_branch"] = str(payload.get("git_branch") or "")
        payload["cwd"] = str(payload.get("cwd") or payload.get("project_root") or "")
        payload["turns"] = _coerce_turns(payload.get("turns"))

        agent_state = payload.get("agent_state")
        if not isinstance(agent_state, dict):
            agent_state = {}
        payload["agent_state"] = {**self._default_agent_state(), **dict(agent_state)}

        work_cursor = payload.get("work_cursor")
        if not isinstance(work_cursor, dict):
            work_cursor = {}
        payload["work_cursor"] = {**self._default_work_cursor(), **dict(work_cursor)}

        task_state = payload.get("task_state")
        if not isinstance(task_state, dict):
            task_state = {}
        payload["task_state"] = {**self._default_task_state(), **dict(task_state)}

        if not isinstance(payload.get("thread_memory"), dict):
            payload["thread_memory"] = {}
        if not isinstance(payload.get("artifact_memory"), list):
            payload["artifact_memory"] = []
        if not isinstance(payload.get("compaction_state"), dict):
            payload["compaction_state"] = {}
        if not isinstance(payload.get("context_manager"), dict):
            payload["context_manager"] = self._default_context_manager()
        return payload

    def load_or_create(
        self,
        session_id: str | None,
        *,
        project: dict[str, Any] | None = None,
        default_project: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not session_id:
            if not project and not default_project:
                raise ValueError("project is required to create a session")
            return self.create(project or default_project or {})
        loaded = self.load(session_id, default_project=default_project)
        if not loaded:
            if not project and not default_project:
                raise ValueError("project is required to create a session")
            return self.create(project or default_project or {})
        return loaded

    def save(self, session: dict[str, Any], *, touch: bool = True) -> None:
        if touch:
            session["updated_at"] = now_iso()
        self._migrate_turn_artifacts(session)
        path = self._path(session["id"])
        with self._lock:
            path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        self.session_meta_store.save_session(session)

    def append_turn(
        self,
        session: dict[str, Any],
        role: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        answer_bundle: dict[str, Any] | None = None,
        activity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        turn = {
            "id": str(uuid.uuid4()),
            "role": role,
            "text": text,
            "attachments": attachments or [],
            "answer_bundle": answer_bundle or {},
            "activity": activity or {},
            "created_at": now_iso(),
        }
        session.setdefault("turns", []).append(turn)
        return turn

    def list_recent_sessions(
        self,
        limit: int = 50,
        *,
        project_id: str | None = None,
        default_project: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        max_items = max(1, min(500, int(limit)))
        wanted_project_id = str(project_id or "").strip()
        files = sorted(
            self.session_meta_store.meta_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files and any(self.sessions_dir.glob("*.json")):
            self.rebuild_metadata_index(default_project=default_project)
        return self.session_meta_store.list_recent(limit=max_items, project_id=wanted_project_id)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        try:
            with self._lock:
                path.unlink(missing_ok=False)
            self.session_meta_store.delete(session_id)
            self.run_artifact_store.delete_session(session_id)
            return True
        except Exception:
            return False

    def delete_by_project(self, project_id: str | None) -> int:
        wanted = str(project_id or "").strip()
        if not wanted:
            return 0
        deleted = 0
        for path in sorted(self.sessions_dir.glob("*.json")):
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("project_id") or "").strip() != wanted:
                continue
            try:
                with self._lock:
                    path.unlink(missing_ok=False)
                sid = str(payload.get("id") or path.stem)
                self.session_meta_store.delete(sid)
                self.run_artifact_store.delete_session(sid)
                deleted += 1
            except Exception:
                continue
        return deleted

    def rebuild_metadata_index(self, *, default_project: dict[str, Any] | None = None) -> int:
        rebuilt = 0
        for path in sorted(self.sessions_dir.glob("*.json")):
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            normalized, changed = self._normalize_session(payload, default_project=default_project)
            if changed:
                self.save(normalized, touch=False)
            else:
                self.session_meta_store.save_session(normalized)
            rebuilt += 1
        return rebuilt

    def repair_sessions(self, *, default_project: dict[str, Any] | None = None) -> dict[str, Any]:
        stats = _new_repair_stats()
        for path in sorted(self.sessions_dir.glob("*.json")):
            stats["scanned_sessions"] = int(stats.get("scanned_sessions") or 0) + 1
            session_repair = {"migrated_turns": 0, "backfilled_turns": 0}
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                normalized, changed = self._normalize_session(
                    payload,
                    default_project=default_project,
                    repair_stats=session_repair,
                )
                if changed:
                    self.save(normalized, touch=False)
                    stats["migrated_sessions"] = int(stats.get("migrated_sessions") or 0) + 1
                else:
                    self.session_meta_store.save_session(normalized)
                    stats["skipped"] = int(stats.get("skipped") or 0) + 1
                stats["migrated_turns"] = int(stats.get("migrated_turns") or 0) + int(session_repair.get("migrated_turns") or 0)
                stats["backfilled_turns"] = int(stats.get("backfilled_turns") or 0) + int(session_repair.get("backfilled_turns") or 0)
                stats["rebuilt_meta"] = int(stats.get("rebuilt_meta") or 0) + 1
            except Exception as exc:
                stats["errors"].append(
                    {
                        "path": str(path),
                        "session_id": str(path.stem or ""),
                        "error": str(exc),
                    }
                )
        return stats

    def migrate_missing_project(self, default_project: dict[str, Any]) -> int:
        migrated = 0
        for path in sorted(self.sessions_dir.glob("*.json")):
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            normalized, changed = self._normalize_session(payload, default_project=default_project)
            if not changed:
                self.session_meta_store.save_session(normalized)
                continue
            self.save(normalized, touch=False)
            migrated += 1
        return migrated


def _project_id_for_root(root_path: Path) -> str:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, str(root_path.resolve()))
    return f"project_{str(digest).replace('-', '')[:16]}"


def _git_output(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _git_metadata(root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--show-toplevel",
                "--abbrev-ref",
                "HEAD",
                "--path-format=absolute",
                "--git-dir",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        proc = None
    lines = (proc.stdout or "").splitlines() if proc is not None and proc.returncode == 0 else []
    if len(lines) >= 4:
        git_root, branch, git_dir, common_dir = [str(item or "").strip() for item in lines[:4]]
    else:
        git_root = _git_output(root, "rev-parse", "--show-toplevel")
        branch = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
        git_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-dir")
        common_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return {
        "git_root": git_root,
        "git_branch": branch,
        "is_worktree": bool(git_root and git_dir and common_dir and Path(git_dir).resolve() != Path(common_dir).resolve()),
    }


class ProjectStore:
    _GIT_METADATA_TTL_SEC = 5.0

    def __init__(self, registry_path: Path, *, default_root: Path) -> None:
        self.registry_path = registry_path
        self.default_root = default_root.resolve()
        self._lock = threading.Lock()
        self._git_metadata_lock = threading.Lock()
        self._git_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write({"projects": {}, "default_project_id": "", "updated_at": now_iso()})

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                return {"projects": {}, "default_project_id": "", "updated_at": now_iso()}

    def _write(self, payload: dict[str, Any]) -> None:
        body = dict(payload or {})
        body["updated_at"] = now_iso()
        with self._lock:
            self.registry_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cached_git_metadata(self, root_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        cache_key = str(root_path)
        now = time.monotonic()
        with self._git_metadata_lock:
            cached = self._git_metadata_cache.get(cache_key)
            if cached and now - float(cached[0] or 0.0) < self._GIT_METADATA_TTL_SEC:
                cached_meta = dict(cached[1])
                payload_git_root = str(payload.get("git_root") or "")
                payload_git_branch = str(payload.get("git_branch") or "")
                payload_has_worktree = "is_worktree" in payload
                payload_matches_cache = (
                    (not payload_git_root or payload_git_root == str(cached_meta.get("git_root") or ""))
                    and (not payload_git_branch or payload_git_branch == str(cached_meta.get("git_branch") or ""))
                    and (
                        not payload_has_worktree
                        or bool(payload.get("is_worktree")) == bool(cached_meta.get("is_worktree"))
                    )
                )
                if payload_matches_cache:
                    return cached_meta
            meta = _git_metadata(root_path)
            self._git_metadata_cache[cache_key] = (now, dict(meta))
            return dict(meta)

    def _normalize_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        root_path = Path(str(payload.get("root_path") or self.default_root)).expanduser().resolve()
        git_meta = self._cached_git_metadata(root_path, payload)
        return {
            "project_id": str(payload.get("project_id") or _project_id_for_root(root_path)),
            "title": str(payload.get("title") or root_path.name or str(root_path)).strip() or (root_path.name or str(root_path)),
            "root_path": str(root_path),
            "created_at": str(payload.get("created_at") or now_iso()),
            "updated_at": str(payload.get("updated_at") or now_iso()),
            "last_opened_at": str(payload.get("last_opened_at") or payload.get("updated_at") or now_iso()),
            "pinned": bool(payload.get("pinned")),
            "is_default": bool(payload.get("is_default")),
            "git_root": str(git_meta.get("git_root") or payload.get("git_root") or ""),
            "git_branch": str(git_meta.get("git_branch") or payload.get("git_branch") or ""),
            "is_worktree": bool(git_meta.get("is_worktree")) if git_meta.get("git_root") else bool(payload.get("is_worktree")),
        }

    def _normalize_projects_map(self, projects: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], bool]:
        normalized_projects: dict[str, dict[str, Any]] = {}
        changed = False
        for key, raw in (projects or {}).items():
            if not isinstance(raw, dict):
                changed = True
                continue
            normalized = self._normalize_record(raw)
            normalized_projects[normalized["project_id"]] = normalized
            if normalized["project_id"] != str(key) or normalized != raw:
                changed = True
        return normalized_projects, changed

    def ensure_default_project(self) -> dict[str, Any]:
        data = self._read()
        projects, changed = self._normalize_projects_map(data.setdefault("projects", {}))
        data["projects"] = projects
        default_id = str(data.get("default_project_id") or "").strip()
        expected = self._normalize_record(
            {
                "project_id": default_id or _project_id_for_root(self.default_root),
                "title": self.default_root.name or str(self.default_root),
                "root_path": str(self.default_root),
                "pinned": True,
                "is_default": True,
            }
        )
        record = projects.get(expected["project_id"]) if expected["project_id"] else None
        normalized = self._normalize_record({**expected, **(record or {})})
        normalized["pinned"] = True
        normalized["is_default"] = True
        if projects.get(normalized["project_id"]) != normalized:
            projects[normalized["project_id"]] = normalized
            changed = True
        if str(data.get("default_project_id") or "").strip() != normalized["project_id"]:
            data["default_project_id"] = normalized["project_id"]
            changed = True
        if changed:
            self._write(data)
        return normalized

    def _sorted(self, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            projects,
            key=lambda item: (
                1 if bool(item.get("is_default")) else 0,
                1 if bool(item.get("pinned")) else 0,
                str(item.get("last_opened_at") or ""),
                str(item.get("title") or ""),
            ),
            reverse=True,
        )

    def list_projects(self) -> list[dict[str, Any]]:
        default_project = self.ensure_default_project()
        data = self._read()
        normalized_projects, changed = self._normalize_projects_map(data.get("projects") or {})
        if normalized_projects.get(default_project["project_id"]) != default_project:
            normalized_projects[default_project["project_id"]] = default_project
            changed = True
        if changed:
            data["projects"] = normalized_projects
            self._write(data)
        projects = list(normalized_projects.values())
        by_id = {item["project_id"]: item for item in projects}
        by_id.setdefault(default_project["project_id"], default_project)
        return self._sorted(list(by_id.values()))

    def all_project_roots(self) -> list[Path]:
        return [Path(item["root_path"]).resolve() for item in self.list_projects()]

    def get(self, project_id: str | None) -> dict[str, Any] | None:
        wanted = str(project_id or "").strip()
        if not wanted:
            return self.ensure_default_project()
        for item in self.list_projects():
            if item["project_id"] == wanted:
                return item
        return None

    def get_cached(self, project_id: str | None) -> dict[str, Any] | None:
        wanted = str(project_id or "").strip()
        data = self._read()
        projects = data.get("projects") or {}
        if not isinstance(projects, dict):
            projects = {}
        if wanted:
            raw = projects.get(wanted)
            if not isinstance(raw, dict):
                return None
            payload = dict(raw)
            payload.setdefault("project_id", wanted)
            return payload
        default_id = str(data.get("default_project_id") or "").strip()
        raw_default = projects.get(default_id) if default_id else None
        if isinstance(raw_default, dict):
            payload = dict(raw_default)
            if default_id:
                payload.setdefault("project_id", default_id)
            return payload
        for raw in projects.values():
            if isinstance(raw, dict) and bool(raw.get("is_default")):
                return dict(raw)
        return None

    def create(self, *, root_path: str, title: str = "") -> dict[str, Any]:
        root = Path(str(root_path or "").strip()).expanduser()
        if not root.is_absolute():
            raise ValueError("root_path must be an absolute local path")
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Path is not a directory: {root}")
        data = self._read()
        projects = data.setdefault("projects", {})
        for item in projects.values():
            existing_root = Path(str((item or {}).get("root_path") or "")).expanduser()
            if existing_root and existing_root.resolve() == root:
                raise FileExistsError(f"Project already exists for path: {root}")
        payload = self._normalize_record(
            {
                "project_id": _project_id_for_root(root),
                "title": title.strip() or root.name or str(root),
                "root_path": str(root),
                "pinned": False,
                "is_default": False,
            }
        )
        projects[payload["project_id"]] = payload
        self._write(data)
        return payload

    def update(self, project_id: str, *, title: str | None = None, pinned: bool | None = None) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        current = projects.get(project_id)
        if not isinstance(current, dict):
            raise FileNotFoundError(f"Project not found: {project_id}")
        payload = self._normalize_record(current)
        if title is not None:
            cleaned_title = str(title or "").strip()
            if cleaned_title:
                payload["title"] = cleaned_title[:120]
        if pinned is not None:
            payload["pinned"] = bool(pinned)
        payload["updated_at"] = now_iso()
        projects[project_id] = payload
        self._write(data)
        return payload

    def touch(self, project_id: str) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        current = projects.get(project_id)
        if not isinstance(current, dict):
            default_project = self.ensure_default_project()
            if default_project["project_id"] == project_id:
                return default_project
            raise FileNotFoundError(f"Project not found: {project_id}")
        payload = self._normalize_record(current)
        stamp = now_iso()
        payload["updated_at"] = stamp
        payload["last_opened_at"] = stamp
        projects[project_id] = payload
        self._write(data)
        return payload

    def touch_cached(self, project_id: str) -> dict[str, Any]:
        data = self._read()
        projects = data.setdefault("projects", {})
        current = projects.get(project_id)
        if not isinstance(current, dict):
            default_project = self.get_cached(None) or self.ensure_default_project()
            if default_project["project_id"] == project_id:
                return default_project
            raise FileNotFoundError(f"Project not found: {project_id}")
        payload = dict(current)
        payload.setdefault("project_id", project_id)
        stamp = now_iso()
        payload["updated_at"] = stamp
        payload["last_opened_at"] = stamp
        projects[project_id] = payload
        self._write(data)
        return payload

    def delete(self, project_id: str) -> None:
        data = self._read()
        default_project_id = str(data.get("default_project_id") or "").strip()
        if project_id == default_project_id:
            raise ValueError("Default project cannot be deleted")
        projects = data.setdefault("projects", {})
        if project_id not in projects:
            raise FileNotFoundError(f"Project not found: {project_id}")
        del projects[project_id]
        self._write(data)


class UploadStore:
    _CHUNK_SIZE = 1024 * 1024
    _INDEX_REWRITE_LIMIT_BYTES = 1024 * 1024

    def __init__(self, uploads_dir: Path) -> None:
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.uploads_dir / "index.json"
        self.meta_dir = self.uploads_dir / ".meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        if not self.index_path.exists():
            self.index_path.write_text("{}", encoding="utf-8")

    def _load_index(self) -> dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _save_index(self, index: dict[str, Any]) -> None:
        with self._lock:
            tmp_path = self.index_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp_path.replace(self.index_path)

    def _meta_path(self, file_id: str) -> Path:
        safe_id = _safe_name(str(file_id or ""))
        return self.meta_dir / f"{safe_id}.json"

    def _save_meta(self, meta: dict[str, Any]) -> None:
        file_id = str(meta.get("id") or "").strip()
        if not file_id:
            return
        target = self._meta_path(file_id)
        tmp_path = target.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp_path.replace(target)

    def _load_meta(self, file_id: str) -> dict[str, Any] | None:
        normalized = str(file_id or "").strip()
        if not normalized:
            return None
        path = self._meta_path(normalized)
        if path.exists():
            try:
                with self._lock:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        index = self._load_index()
        meta = index.get(normalized)
        return dict(meta) if isinstance(meta, dict) else None

    def _index_is_small_enough(self) -> bool:
        try:
            return not self.index_path.exists() or self.index_path.stat().st_size <= self._INDEX_REWRITE_LIMIT_BYTES
        except Exception:
            return False

    def _maybe_update_index_entry(self, file_id: str, meta: dict[str, Any] | None) -> str:
        if not self._index_is_small_enough():
            return "per_upload_metadata"
        index = self._load_index()
        if meta is None:
            index.pop(file_id, None)
        else:
            index[file_id] = meta
        self._save_index(index)
        return "index_json"

    async def save_upload(self, upload: UploadFile, *, max_bytes: int | None = None) -> dict[str, Any]:
        started = time.monotonic()
        file_id = str(uuid.uuid4())
        original_name = upload.filename or "upload.bin"
        safe_name = _safe_name(original_name)
        stored_name = f"{file_id}__{safe_name}"
        target_path = (self.uploads_dir / stored_name).resolve()

        size = 0
        try:
            with target_path.open("wb") as fh:
                while True:
                    chunk = await upload.read(self._CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if max_bytes is not None and size > max(0, int(max_bytes)):
                        raise ValueError("File too large")
                    fh.write(chunk)
        except Exception:
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        mime = upload.content_type or "application/octet-stream"
        suffix = Path(original_name).suffix.lower()
        kind = "other"
        if mime.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}:
            kind = "image"
        elif mime.lower() in {"application/vnd.ms-outlook", "application/x-msg"}:
            kind = "document"
        elif mime.lower() in {"application/atom+xml", "application/rss+xml", "application/xml", "text/xml"}:
            kind = "document"
        elif suffix in {
            ".atom",
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".pdf",
            ".docx",
            ".msg",
            ".zip",
            ".doc",
            ".xlsx",
            ".xlsm",
            ".xltx",
            ".xltm",
            ".xls",
            ".pptx",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".yaml",
            ".yml",
            ".log",
            ".xml",
            ".rss",
        }:
            kind = "document"

        meta = {
            "id": file_id,
            "original_name": original_name,
            "safe_name": safe_name,
            "mime": mime,
            "suffix": suffix,
            "kind": kind,
            "size": size,
            "path": str(target_path),
            "created_at": now_iso(),
            "upload_status": "stored",
            "bytes_written": size,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

        metadata_index_mode = self._maybe_update_index_entry(file_id, meta)
        meta["metadata_index_mode"] = metadata_index_mode
        self._save_meta(meta)
        return meta

    def get_many(self, file_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for file_id in file_ids:
            meta = self._load_meta(str(file_id or ""))
            if meta:
                out.append(meta)
        return out

    def delete(self, file_id: str) -> None:
        normalized = str(file_id or "").strip()
        meta = self._load_meta(normalized)
        if meta and meta.get("path"):
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            self._meta_path(normalized).unlink(missing_ok=True)
        except Exception:
            pass
        if normalized:
            self._maybe_update_index_entry(normalized, None)


def _empty_totals() -> dict[str, int | float]:
    return {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


class TokenStatsStore:
    def __init__(self, stats_path: Path) -> None:
        self.stats_path = stats_path
        self._lock = threading.Lock()
        if not self.stats_path.exists():
            self._write(self._new_state())

    def _new_state(self) -> dict[str, Any]:
        return {
            "totals": _empty_totals(),
            "sessions": {},
            "records": [],
            "updated_at": now_iso(),
        }

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(self.stats_path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            data["updated_at"] = now_iso()
            self.stats_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self._write(self._new_state())

    def _normalize_usage(self, usage: dict[str, Any]) -> dict[str, float]:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0) or 0.0),
        }

    def add_usage(self, session_id: str, usage: dict[str, Any], model: str | None = None) -> dict[str, Any]:
        data = self._read()
        norm = self._normalize_usage(usage)

        totals = data.setdefault("totals", _empty_totals())
        totals["requests"] = int(totals.get("requests", 0) or 0) + 1
        totals["input_tokens"] = int(totals.get("input_tokens", 0) or 0) + norm["input_tokens"]
        totals["output_tokens"] = int(totals.get("output_tokens", 0) or 0) + norm["output_tokens"]
        totals["total_tokens"] = int(totals.get("total_tokens", 0) or 0) + norm["total_tokens"]
        totals["estimated_cost_usd"] = float(totals.get("estimated_cost_usd", 0.0) or 0.0) + norm["estimated_cost_usd"]

        sessions = data.setdefault("sessions", {})
        sess = sessions.setdefault(session_id, _empty_totals())
        sess["requests"] = int(sess.get("requests", 0) or 0) + 1
        sess["input_tokens"] = int(sess.get("input_tokens", 0) or 0) + norm["input_tokens"]
        sess["output_tokens"] = int(sess.get("output_tokens", 0) or 0) + norm["output_tokens"]
        sess["total_tokens"] = int(sess.get("total_tokens", 0) or 0) + norm["total_tokens"]
        sess["estimated_cost_usd"] = float(sess.get("estimated_cost_usd", 0.0) or 0.0) + norm["estimated_cost_usd"]

        records = data.setdefault("records", [])
        records.append(
            {
                "ts": now_iso(),
                "session_id": session_id,
                "model": model,
                "input_tokens": norm["input_tokens"],
                "output_tokens": norm["output_tokens"],
                "total_tokens": norm["total_tokens"],
                "llm_calls": int(usage.get("llm_calls", 0) or 0),
                "estimated_cost_usd": norm["estimated_cost_usd"],
                "pricing_known": bool(usage.get("pricing_known", False)),
                "pricing_model": usage.get("pricing_model"),
                "input_price_per_1m": usage.get("input_price_per_1m"),
                "output_price_per_1m": usage.get("output_price_per_1m"),
            }
        )

        self._write(data)
        return data

    def get_stats(self, max_records: int = 300) -> dict[str, Any]:
        data = self._read()
        records = data.get("records", [])
        if max_records > 0 and len(records) > max_records:
            data["records"] = records[-max_records:]
        return data
