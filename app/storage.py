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
from app.run_record import encode_run_record, hydrate_run_record
from app.thread_transcript import (
    THREAD_TRANSCRIPT_SCHEMA_VERSION,
    append_transcript_item,
    append_transcript_items,
    default_thread_transcript,
    migrate_session_to_thread_transcript,
    normalize_thread_transcript,
)
from app.thread_record import (
    THREAD_RECORD_SCHEMA_VERSION,
    agent_state_compat,
    attach_legacy_turn_metadata,
    encode_thread_record,
    hydrate_thread_record,
    project_turns_from_thread,
)
from app.turn_trace import build_turn_trace, normalize_turn_trace


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
    """Read compatibility for pre-Trace execution artifacts.

    New turns are persisted by TurnTraceStore. This store remains so existing
    Session references continue to open after an upgrade.
    """
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
        payload["thread_id"] = sid
        payload["run_id"] = rid
        payload["updated_at"] = now_iso()
        payload.setdefault("created_at", payload["updated_at"])
        payload = encode_run_record(payload)
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
            if not isinstance(payload, dict):
                return None
            hydrated = hydrate_run_record(payload)
            hydrated["trace_ref"] = self.trace_ref(sid, rid)
            return hydrated
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


class TurnTraceStore:
    def __init__(self, traces_dir: Path) -> None:
        self.traces_dir = traces_dir
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _thread_dir(self, thread_id: str) -> Path:
        return self.traces_dir / _safe_name(str(thread_id or ""))

    def _path(self, thread_id: str, turn_id: str) -> Path:
        return self._thread_dir(thread_id) / f"{_safe_name(str(turn_id or 'turn'))}.json"

    def trace_ref(self, thread_id: str, turn_id: str) -> str:
        return f"turn_traces/{_safe_name(str(thread_id or ''))}/{_safe_name(str(turn_id or 'turn'))}"

    def save(
        self,
        *,
        thread_id: str,
        turn_id: str,
        source: dict[str, Any],
        thread_items: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        tid = str(thread_id or "").strip()
        logical_turn_id = str(turn_id or "").strip()
        if not tid or not logical_turn_id:
            raise ValueError("thread_id and turn_id are required for Turn Trace persistence")
        payload = dump_model(dict(source or {}))
        payload["thread_id"] = tid
        payload["turn_id"] = logical_turn_id
        payload["updated_at"] = now_iso()
        payload.setdefault("created_at", payload["updated_at"])
        trace = build_turn_trace(payload, thread_items=thread_items, turn_id=logical_turn_id)
        target = self._path(tid, logical_turn_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(target)
        return self.trace_ref(tid, logical_turn_id), trace

    def load(self, *, thread_id: str, turn_id: str) -> dict[str, Any] | None:
        tid = str(thread_id or "").strip()
        logical_turn_id = str(turn_id or "").strip()
        if not tid or not logical_turn_id:
            return None
        path = self._path(tid, logical_turn_id)
        if not path.exists():
            return None
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            trace = normalize_turn_trace(payload)
            trace["trace_ref"] = self.trace_ref(tid, logical_turn_id)
            return trace
        except Exception:
            return None

    def load_by_ref(self, trace_ref: str) -> dict[str, Any] | None:
        parts = [part for part in str(trace_ref or "").strip().split("/") if part]
        if len(parts) < 3 or parts[-3] != "turn_traces":
            return None
        return self.load(thread_id=parts[-2], turn_id=parts[-1])

    def delete_thread(self, thread_id: str) -> None:
        target = self._thread_dir(thread_id)
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
        if not turns and isinstance(payload.get("thread_transcript"), dict):
            turns = project_turns_from_thread(payload)
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
        agent_state = agent_state_compat(payload)
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
            "activity_at": str(payload.get("activity_at") or payload.get("updated_at") or ""),
            "activity_revision": max(0, int(payload.get("activity_revision") or 0)),
            "activity_kind": str(payload.get("activity_kind") or ""),
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
        for path in self.meta_dir.glob("*.json"):
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
        return sorted(
            rows,
            key=lambda item: (
                str(item.get("activity_at") or item.get("updated_at") or ""),
                str(item.get("session_id") or ""),
            ),
            reverse=True,
        )[:max_items]

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
        turn_traces_dir: Path | None = None,
        session_meta_dir: Path | None = None,
        run_artifact_store: RunArtifactStore | None = None,
        turn_trace_store: TurnTraceStore | None = None,
        session_meta_store: SessionMetaStore | None = None,
    ) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        data_root = self.sessions_dir.parent
        self.run_artifact_store = run_artifact_store or RunArtifactStore(runs_dir or data_root / "runs")
        self.turn_trace_store = turn_trace_store or TurnTraceStore(turn_traces_dir or data_root / "turn_traces")
        self.session_meta_store = session_meta_store or SessionMetaStore(session_meta_dir or data_root / "session_meta")
        self.migration_backup_dir = data_root / "session_backups"
        self._lock = threading.Lock()

    def _default_thread_transcript(self) -> dict[str, Any]:
        return default_thread_transcript()

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
        logical_turn_id: str | None = None,
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
        transcript = normalize_thread_transcript(session.get("thread_transcript"))
        trace_turn_id = str(logical_turn_id or "").strip()
        if not trace_turn_id:
            response_item = next(
                (
                    item
                    for item in list(transcript.get("items") or [])
                    if isinstance(item, dict) and str(item.get("id") or "") == wanted_turn_id
                ),
                None,
            )
            trace_turn_id = str((response_item or {}).get("turn_id") or wanted_turn_id).strip()
        artifact["logical_turn_id"] = trace_turn_id
        trace_ref, turn_trace = self.turn_trace_store.save(
            thread_id=session_id,
            turn_id=trace_turn_id,
            source=artifact,
            thread_items=[dict(item) for item in list(transcript.get("items") or []) if isinstance(item, dict)],
        )
        artifact_activity = artifact.get("activity") if isinstance(artifact.get("activity"), dict) else {}
        turn["activity"] = self._activity_summary(
            artifact_activity,
            run_id=rid,
            trace_ref=trace_ref,
            tool_count=self._activity_tool_count(artifact_activity, artifact),
        )
        turn["answer_bundle"] = {}
        turn["run_artifact"] = {}
        for item in list(transcript.get("items") or []):
            if not isinstance(item, dict) or str(item.get("id") or "") != wanted_turn_id:
                continue
            item["trace"] = {
                "trace_ref": trace_ref,
                "status": str(turn["activity"].get("status") or "completed"),
                "summary": str(turn["activity"].get("summary") or ""),
                "activity_summary": str(turn["activity"].get("activity_summary") or ""),
                "duration_ms": max(0, int(turn["activity"].get("run_duration_ms") or 0)),
                "tool_count": max(0, int(turn["activity"].get("tool_count") or 0)),
            }
            break
        session["thread_transcript"] = normalize_thread_transcript(transcript)
        return turn_trace

    def _load_turn_artifact(
        self,
        *,
        session_id: str,
        run_id: str,
        trace_ref: str,
    ) -> dict[str, Any] | None:
        artifact = self.turn_trace_store.load_by_ref(trace_ref) if trace_ref else None
        if artifact is not None:
            return artifact
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
        if trace_ref.startswith("turn_traces/"):
            run_id = ""
        if requested_view in {"activity", "debug", "full"}:
            artifact = self._load_turn_artifact(session_id=session_id, run_id=run_id, trace_ref=trace_ref)
            if artifact:
                if int(artifact.get("turn_trace_schema_version") or 0) > 0:
                    trace_steps = [
                        dict(item)
                        for item in list(artifact.get("steps") or [])
                        if isinstance(item, dict)
                    ]
                    tool_steps = [
                        item
                        for item in trace_steps
                        if str(item.get("type") or "").startswith("tool_")
                    ]
                    projected_tool_items = [
                        {
                            **step,
                            **(
                                dict(step.get("audit") or {})
                                if isinstance(step.get("audit"), dict)
                                else {}
                            ),
                            "type": "toolCall",
                            "name": str(step.get("tool_name") or ""),
                            "raw_tool_call": {
                                "id": str(step.get("tool_call_id") or ""),
                                "name": str(step.get("tool_name") or ""),
                            },
                            "validation_result": (
                                dict(
                                    (step.get("audit") or {}).get("validation_result")
                                    or step.get("validation")
                                    or {}
                                )
                                if isinstance(step.get("audit"), dict)
                                else dict(step.get("validation") or {})
                            ),
                        }
                        for step in tool_steps
                    ]
                    activity_view = {
                        "trace_ref": str(artifact.get("trace_ref") or trace_ref or ""),
                        "status": str(artifact.get("status") or "completed"),
                        "started_at": artifact.get("started_at") or 0.0,
                        "finished_at": artifact.get("finished_at") or 0.0,
                        "run_duration_ms": max(0, int(artifact.get("duration_ms") or 0)),
                        "session_id": str(session_id or ""),
                        "thread_id": str(session_id or ""),
                        "tool_count": len(tool_steps),
                        "activity_loaded": True,
                        "debug_loaded": requested_view in {"debug", "full"},
                        "full_loaded": requested_view == "full",
                        "trace_events": [],
                        "tool_items": projected_tool_items,
                        "live_items": [],
                    }
                    if requested_view in {"debug", "full"}:
                        activity_view["turn_trace"] = dict(artifact)
                    payload["activity"] = activity_view
                    payload["answer_bundle"] = {}
                    payload["run_artifact"] = {}
                    return payload
                record = encode_run_record(artifact)
                details = dict(record.get("details") or {})
                operational_details = {
                    key: details[key]
                    for key in ("plan", "plan_explanation", "tool_boundary_clean", "phase_timings")
                    if key in details
                }
                items = [dict(item) for item in list(record.get("items") or []) if isinstance(item, dict)]
                activity_view = {
                    "run_id": str(record.get("run_id") or run_id or ""),
                    "trace_ref": str(artifact.get("trace_ref") or trace_ref or ""),
                    "status": str(record.get("status") or "completed"),
                    "summary": str(record.get("summary") or ""),
                    "activity_summary": str(record.get("summary") or ""),
                    "started_at": record.get("started_at") or 0.0,
                    "finished_at": record.get("finished_at") or 0.0,
                    "run_duration_ms": max(0, int(record.get("duration_ms") or 0)),
                    "session_id": str(session_id or ""),
                    "thread_id": str(session_id or ""),
                    "tool_count": len(list(record.get("tool_events") or [])) or len(items),
                    "activity_loaded": True,
                    "debug_loaded": requested_view in {"debug", "full"},
                    "full_loaded": requested_view == "full",
                    "trace_events": [
                        dict(item)
                        for item in list(record.get("events") or [])
                        if isinstance(item, dict)
                    ],
                    "live_items": items,
                    "tool_items": [
                        dict(item)
                        for item in items
                        if str(item.get("type") or "") in {
                            "toolCall",
                            "commandExecution",
                            "fileChange",
                            "userInputRequest",
                            "imageView",
                        }
                    ],
                    **operational_details,
                }
                if requested_view in {"debug", "full"}:
                    debug = dict(record.get("debug") or {})
                    if requested_view == "full":
                        activity_view.update(details)
                    activity_view.update(
                        {
                            "llm_exchanges": list(debug.get("llm_exchanges") or []),
                            "runtime_error": dict(debug.get("runtime_error") or {}),
                            "runtime_inspector": dict(debug.get("inspector") or {}),
                        }
                    )
                    if requested_view == "full":
                        activity_view["model_draft"] = str(debug.get("model_draft") or "")
                        activity_view["final_answer"] = str(debug.get("final_answer") or "")
                        payload["answer_bundle"] = dict(record.get("answer_bundle") or {})
                        payload["run_artifact"] = dict(artifact)
                    else:
                        payload["answer_bundle"] = {}
                        payload["run_artifact"] = {}
                else:
                    payload["answer_bundle"] = {}
                    payload["run_artifact"] = {}
                payload["activity"] = activity_view
            else:
                payload["activity"] = dict(activity)
                payload["activity"]["activity_loaded"] = True
                payload["activity"]["debug_loaded"] = requested_view in {"debug", "full"}
                payload["activity"]["full_loaded"] = requested_view == "full"
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
        raw_payload = dict(session or {})
        legacy_turns = _coerce_turns(raw_payload.get("turns"))
        payload = hydrate_thread_record(raw_payload)

        if not str(payload.get("id") or "").strip():
            payload["id"] = str(uuid.uuid4())
        if not str(payload.get("created_at") or "").strip():
            payload["created_at"] = now_iso()
        if not str(payload.get("updated_at") or "").strip():
            payload["updated_at"] = str(payload.get("created_at") or now_iso())
        if not str(payload.get("activity_at") or "").strip():
            payload["activity_at"] = str(payload.get("updated_at") or payload.get("created_at") or now_iso())
        try:
            activity_revision = max(0, int(payload.get("activity_revision") or 0))
        except Exception:
            activity_revision = 0
        payload["activity_revision"] = activity_revision
        if not isinstance(payload.get("activity_kind"), str):
            payload["activity_kind"] = ""
        payload["turns"] = legacy_turns
        payload, thread_migrated = migrate_session_to_thread_transcript(payload)
        if not isinstance(payload.get("active_attachment_ids"), list):
            payload["active_attachment_ids"] = []

        if default_project:
            default_project_id = str(default_project.get("project_id") or "").strip()
            default_project_title = str(default_project.get("title") or "").strip()
            default_project_root = str(default_project.get("root_path") or "").strip()
            default_git_branch = str(default_project.get("git_branch") or "").strip()
            if not str(payload.get("project_id") or "").strip():
                payload["project_id"] = default_project_id
            if not str(payload.get("project_title") or "").strip():
                payload["project_title"] = default_project_title
            if not str(payload.get("project_root") or "").strip():
                payload["project_root"] = default_project_root
            if not str(payload.get("git_branch") or "").strip():
                payload["git_branch"] = default_git_branch
        if not str(payload.get("cwd") or "").strip():
            payload["cwd"] = str(payload.get("project_root") or "")

        migrated_turns = self._migrate_turn_artifacts(payload, repair_stats=repair_stats)
        backfilled_turns = self._backfill_turn_activity_summaries(payload, repair_stats=repair_stats)
        payload["thread_transcript"] = attach_legacy_turn_metadata(
            normalize_thread_transcript(payload.get("thread_transcript"), legacy_turns=legacy_turns),
            payload.get("turns") or legacy_turns,
        )
        payload["thread_schema_version"] = THREAD_TRANSCRIPT_SCHEMA_VERSION
        payload["thread_record_schema_version"] = THREAD_RECORD_SCHEMA_VERSION
        pending_interaction = dict(payload.get("pending_interaction") or {})
        pending_turn = dict(pending_interaction.get("turn") or {})
        legacy_plan = [
            dict(item)
            for item in list((raw_payload.get("task_state") or {}).get("plan_items") or [])
            if isinstance(item, dict)
        ]
        if pending_turn and legacy_plan and not list(pending_turn.get("plan") or []):
            pending_turn["plan"] = legacy_plan[:12]
            pending_interaction["turn"] = pending_turn
            payload["pending_interaction"] = pending_interaction
        payload["turns"] = project_turns_from_thread(payload)

        # The loaded Thread is minimal too. Compatibility views are derived at
        # the API boundary, not kept as a second Harness state model.
        for legacy_key in (
            "context_manager",
            "context_schema_version",
            "history_turns",
            "messages",
            "recent_tasks",
            "artifact_memory_preview",
            "context_meter",
            "compaction_status",
            "current_task_focus",
            "task_checkpoint",
            "agent_state",
            "route_state",
            "attachment_route_states",
            "work_cursor",
            "task_state",
            "thread_memory",
            "artifact_memory",
        ):
            payload.pop(legacy_key, None)

        encoded = encode_thread_record(payload)
        source_encoded = encode_thread_record(raw_payload)
        changed = bool(
            int(raw_payload.get("thread_record_schema_version") or 0) < THREAD_RECORD_SCHEMA_VERSION
            or raw_payload != encoded
            or source_encoded != encoded
            or thread_migrated
            or migrated_turns
            or backfilled_turns
        )
        return payload, changed

    def create(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project.get("project_id") or "").strip()
        project_title = str(project.get("title") or "").strip()
        project_root = str(project.get("root_path") or "").strip()
        git_branch = str(project.get("git_branch") or "").strip()
        created_at = now_iso()
        session = hydrate_thread_record({
            "thread_record_schema_version": THREAD_RECORD_SCHEMA_VERSION,
            "id": str(uuid.uuid4()),
            "created_at": created_at,
            "updated_at": created_at,
            "activity_at": created_at,
            "activity_revision": 0,
            "activity_kind": "created",
            "title": "",
            "project_id": project_id,
            "project_title": project_title,
            "project_root": project_root,
            "git_branch": git_branch,
            "cwd": project_root,
            "thread_transcript": self._default_thread_transcript(),
            "thread_schema_version": THREAD_TRANSCRIPT_SCHEMA_VERSION,
            "active_attachment_ids": [],
            "attachment_context_cleared": False,
            "compaction": {},
            "pending_interaction": {},
        })
        session["turns"] = []
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
        return self.load(session_id)

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
        normalized_thread = normalize_thread_transcript(
            session.get("thread_transcript"),
            legacy_turns=session.get("turns") or [],
        )
        session["thread_transcript"] = normalized_thread
        session["thread_schema_version"] = THREAD_TRANSCRIPT_SCHEMA_VERSION
        path = self._path(session["id"])
        encoded = encode_thread_record(session)
        session["pending_interaction"] = dict(encoded.get("pending_interaction") or {})
        if path.exists():
            try:
                with self._lock:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                if int((previous or {}).get("thread_record_schema_version") or 0) < THREAD_RECORD_SCHEMA_VERSION:
                    self.migration_backup_dir.mkdir(parents=True, exist_ok=True)
                    backup = self.migration_backup_dir / f"{_safe_name(str(session['id']))}.v2.json"
                    if not backup.exists():
                        shutil.copy2(path, backup)
            except Exception:
                pass
        tmp_path = path.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(json.dumps(encoded, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        self.session_meta_store.save_session(session)

    def mark_activity(self, session: dict[str, Any], *, kind: str, at: str = "") -> dict[str, Any]:
        """Advance the stable Thread ordering clock for one meaningful event."""
        try:
            previous_revision = max(0, int(session.get("activity_revision") or 0))
        except Exception:
            previous_revision = 0
        stamp = str(at or now_iso()).strip() or now_iso()
        session["activity_revision"] = previous_revision + 1
        session["activity_at"] = stamp
        session["activity_kind"] = str(kind or "activity").strip()[:80] or "activity"
        return {
            "activity_revision": int(session["activity_revision"]),
            "activity_at": str(session["activity_at"]),
            "activity_kind": str(session["activity_kind"]),
        }

    def append_turn(
        self,
        session: dict[str, Any],
        role: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        task_context: dict[str, Any] | None = None,
        answer_bundle: dict[str, Any] | None = None,
        activity: dict[str, Any] | None = None,
        record_transcript: bool = True,
        turn_id: str | None = None,
        logical_turn_id: str | None = None,
    ) -> dict[str, Any]:
        requested_turn_id = str(turn_id or "").strip()
        existing_turn_ids = {
            str(item.get("id") or "").strip()
            for item in list(session.get("turns") or [])
            if isinstance(item, dict)
        }
        resolved_turn_id = (
            requested_turn_id
            if requested_turn_id and requested_turn_id not in existing_turn_ids
            else str(uuid.uuid4())
        )
        turn = {
            "id": resolved_turn_id,
            "role": role,
            "text": text,
            "attachments": attachments or [],
            "answer_bundle": answer_bundle or {},
            "activity": activity or {},
            "created_at": now_iso(),
        }
        session.setdefault("turns", []).append(turn)
        if record_transcript and role in {"user", "assistant"}:
            transcript = session.setdefault("thread_transcript", self._default_thread_transcript())
            append_transcript_item(
                transcript,
                role=role,
                content=text,
                item_id=str(turn["id"]),
                turn_id=str(logical_turn_id or turn["id"]),
                attachments=attachments or [],
                task_context=task_context or {},
                created_at=str(turn["created_at"]),
            )
        return turn

    def append_thread_items(self, session: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transcript = session.setdefault("thread_transcript", self._default_thread_transcript())
        return append_transcript_items(transcript, items)

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
            self.turn_trace_store.delete_thread(session_id)
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
                self.turn_trace_store.delete_thread(sid)
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
