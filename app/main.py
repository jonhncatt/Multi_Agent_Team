from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
import queue
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.attachment_evidence import build_attachment_evidence_pack
from app.config import AppConfig, build_provider_config, list_provider_profiles, load_config, normalize_llm_provider_name, normalize_permission_profile
from app.context_meter import (
    build_compaction_status,
    build_context_meter,
    build_context_meter_from_status,
    build_runtime_context_payload,
    ensure_compaction_state,
    maybe_auto_compact_session,
    record_context_usage_observation,
    resolve_context_window,
)
from app.eval_jobs import EvalJobError, EvalJobManager
from app.i18n import normalize_locale, supported_locales, translate
from app.models import (
    AppStatusResponse,
    AppUpdateResponse,
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    ChatSettings,
    ChatSteerRequest,
    ClearStatsResponse,
    CompactRequest,
    CompactResponse,
    EvalRunRequest,
    DeleteThreadResponse,
    DeleteSessionResponse,
    HealthResponse,
    MessageActivity,
    NewSessionResponse,
    NewSessionRequest,
    NewThreadResponse,
    ProjectCreateRequest,
    ProjectDescriptor,
    ProjectDeleteResponse,
    ProjectListResponse,
    ProjectUpdateRequest,
    RuntimeStatusResponse,
    SessionDetailResponse,
    SessionListItem,
    SessionListResponse,
    SessionTurn,
    SkillDeleteResponse,
    SkillDescriptor,
    SkillUpsertRequest,
    SpecDescriptor,
    SpecUpsertRequest,
    UpdateSessionTitleRequest,
    UpdateSessionTitleResponse,
    SandboxDrillRequest,
    SandboxDrillResponse,
    SandboxDrillStep,
    TokenStatsResponse,
    TokenTotals,
    ToggleSkillRequest,
    ToolDescriptor,
    ToolEvent,
    TokenUsage,
    ThreadDetailResponse,
    ThreadListItem,
    ThreadListResponse,
    UploadResponse,
    WorkbenchSkillsResponse,
    WorkbenchSpecsResponse,
    WorkbenchToolsResponse,
)
from app.openai_auth import OpenAIAuthManager
from app.phase_timing import PhaseTimer
from app.pricing import estimate_usage_cost
from app.serialization import dump_model
from app.runtime_boundary import build_turn_runtime_boundary
from app.runtime_contract import build_full_auto_runtime_contract
from app import session_context as session_context_impl
from app.session_context import normalize_attachment_ids
from app.storage import ProjectStore, SessionStore, TokenStatsStore, UploadStore
from app.update_manager import AppUpdateManager
from app.vintage_programmer_runtime import VintageProgrammerRuntime, default_loop_safeguards
from app.workbench import WorkbenchStore

APP_TITLE = "Vintage Programmer"
config = load_config()
DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS = int(config.max_output_tokens)
AGENT_DIR = Path(__file__).resolve().parent.parent / "agents" / "vintage_programmer"
project_store = ProjectStore(config.projects_registry_path, default_root=config.workspace_root)
session_store = SessionStore(
    config.sessions_dir,
    runs_dir=config.runs_dir,
    session_meta_dir=config.session_meta_dir,
)
upload_store = UploadStore(config.uploads_dir)
token_stats_store = TokenStatsStore(config.token_stats_path)
vintage_programmer_runtime = VintageProgrammerRuntime(
    config=config,
    agent_dir=AGENT_DIR,
)
workbench_store = WorkbenchStore(
    config=config,
    agent_dir=AGENT_DIR,
)
APP_VERSION = "3.1.5W"
app_update_manager = AppUpdateManager(app_dir=Path(__file__).resolve().parent.parent)
APP_STARTED_AT = time.monotonic()
default_project = project_store.ensure_default_project()
session_store.migrate_missing_project(default_project)
session_store.rebuild_metadata_index(default_project=default_project)


def _attachment_preview_chars_for_model(model: str | None, max_output_tokens: int | None) -> int:
    context_window, _source = resolve_context_window(model, max_output_tokens=max_output_tokens)
    per_attachment_token_budget = max(3000, int(context_window * 0.10))
    return max(
        12_000,
        min(
            int(config.max_attachment_chars),
            per_attachment_token_budget * 4,
        ),
    )
_provider_runtime_lock = threading.Lock()
_provider_runtime_cache: dict[str, VintageProgrammerRuntime] = {}
_provider_payload_lock = threading.Lock()
_provider_payload_cache: dict[str, Any] = {}
_active_chat_runs_lock = threading.Lock()
_active_chat_runs: dict[str, dict[str, Any]] = {}
_eval_job_manager_lock = threading.Lock()
_eval_job_manager: EvalJobManager | None = None


def _get_eval_job_manager() -> EvalJobManager:
    global _eval_job_manager
    with _eval_job_manager_lock:
        if _eval_job_manager is None:
            _eval_job_manager = EvalJobManager(repo_root=Path(__file__).resolve().parent.parent)
        return _eval_job_manager


def _merge_phase_timings(*payloads: Any) -> dict[str, int]:
    merged: dict[str, int] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for raw_key, raw_value in payload.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            try:
                value = int(raw_value)
            except Exception:
                continue
            merged[key] = max(0, value)
    return merged


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _activity_with_end_to_end_duration(
    activity: dict[str, Any] | None,
    phase_timings: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(activity or {})
    timings = phase_timings if isinstance(phase_timings, dict) else {}
    runtime_duration_ms = max(
        _nonnegative_int(payload.get("run_duration_ms")),
        _nonnegative_int(timings.get("runtime_total_ms")),
        _nonnegative_int(timings.get("runtime_run_ms")),
    )
    total_duration_ms = _nonnegative_int(timings.get("total_ms"))
    final_duration_ms = max(runtime_duration_ms, total_duration_ms)
    if final_duration_ms:
        payload["run_duration_ms"] = final_duration_ms
        payload["final_elapsed_ms"] = max(
            _nonnegative_int(payload.get("final_elapsed_ms")),
            final_duration_ms,
        )
    return payload


def _git_value(*args: str) -> str:
    repo_root = Path(__file__).resolve().parent.parent
    try:
        return (
            subprocess.run(
                ["git", *args],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            ).stdout.strip()
        )
    except Exception:
        return ""


def _resolve_build_version() -> str:
    override = str(
        os.environ.get("VP_BUILD_VERSION") or ""
    ).strip()
    if override:
        return override

    commit = _git_value("rev-parse", "--short", "HEAD")
    branch = _git_value("rev-parse", "--abbrev-ref", "HEAD")

    parts = [f"v{APP_VERSION}"]
    if branch and commit:
        parts.append(f"{branch}@{commit}")
    elif commit:
        parts.append(commit)
    return " · ".join(parts)


BUILD_VERSION = _resolve_build_version()


class AgentRunQueue:
    """
    Session-aware lane queue:
    - one active run per session
    - bounded global concurrency across sessions
    """

    def __init__(self, max_concurrent_runs: int) -> None:
        self._global_sem = threading.BoundedSemaphore(max(1, int(max_concurrent_runs)))
        self._locks_guard = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        sid = str(session_id or "").strip() or "__anon__"
        with self._locks_guard:
            lock = self._session_locks.get(sid)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[sid] = lock
            return lock

    def run_slot(self, session_id: str):
        sid = str(session_id or "").strip() or "__anon__"
        started = time.monotonic()
        session_lock = self._get_session_lock(sid)
        waited = False
        if not session_lock.acquire(blocking=False):
            waited = True
            session_lock.acquire()
        if not self._global_sem.acquire(blocking=False):
            waited = True
            self._global_sem.acquire()
        wait_ms = int((time.monotonic() - started) * 1000)
        return _AgentRunQueueTicket(self._global_sem, session_lock, wait_ms, waited=waited)


class _AgentRunQueueTicket:
    def __init__(
        self,
        global_sem: threading.BoundedSemaphore,
        session_lock: threading.Lock,
        wait_ms: int,
        waited: bool = False,
    ) -> None:
        self._global_sem = global_sem
        self._session_lock = session_lock
        self.wait_ms = max(0, int(wait_ms))
        self.waited = bool(waited)
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._global_sem.release()
        finally:
            self._session_lock.release()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


run_queue = AgentRunQueue(config.max_concurrent_runs)


def get_project_store() -> ProjectStore:
    return project_store


def get_vintage_programmer_runtime() -> VintageProgrammerRuntime:
    return vintage_programmer_runtime


def get_tool_executor() -> Any:
    return get_vintage_programmer_runtime()._backend.tools


def _runtime_meta_payload() -> dict[str, Any]:
    tools = get_tool_executor()
    ocr_payload = tools.ocr_status() if hasattr(tools, "ocr_status") else {}
    return {
        "docker_available": False,
        "docker_message": "Docker status check disabled.",
        "ocr_status": dict(ocr_payload or {}),
    }


def _register_active_chat_run(run_id: str) -> threading.Event:
    cancel_event = threading.Event()
    with _active_chat_runs_lock:
        _active_chat_runs[run_id] = {
            "run_id": run_id,
            "cancel_event": cancel_event,
            "status": "running",
            "session_id": "",
            "project_id": "",
            "created_at": time.time(),
            "accepting_steers": True,
            "pending_steers": [],
        }
    return cancel_event


def _update_active_chat_run(run_id: str, **fields: Any) -> None:
    with _active_chat_runs_lock:
        record = _active_chat_runs.get(run_id)
        if not isinstance(record, dict):
            return
        for key, value in fields.items():
            record[key] = value


def _cancel_active_chat_run(run_id: str) -> dict[str, Any] | None:
    with _active_chat_runs_lock:
        record = _active_chat_runs.get(str(run_id or "").strip())
        if not isinstance(record, dict):
            return None
        cancel_event = record.get("cancel_event")
        if cancel_event and hasattr(cancel_event, "set"):
            cancel_event.set()
        record["status"] = "cancelling"
        record["accepting_steers"] = False
        record["cancel_requested_at"] = time.time()
        return dict(record)


def _enqueue_active_chat_run_steer(
    run_id: str,
    message: str,
    *,
    client_steer_id: str = "",
) -> dict[str, Any] | None:
    steer_text = str(message or "").strip()
    if not steer_text:
        return None
    with _active_chat_runs_lock:
        record = _active_chat_runs.get(str(run_id or "").strip())
        if (
            not isinstance(record, dict)
            or str(record.get("status") or "") != "running"
            or not bool(record.get("accepting_steers"))
        ):
            return None
        steer = {
            "id": str(client_steer_id or "").strip()[:160] or str(uuid.uuid4()),
            "message": steer_text,
            "queued_at": time.time(),
        }
        pending = record.setdefault("pending_steers", [])
        if not isinstance(pending, list):
            pending = []
            record["pending_steers"] = pending
        pending.append(steer)
        return {
            **steer,
            "run_id": str(record.get("run_id") or run_id or ""),
            "session_id": str(record.get("session_id") or ""),
            "project_id": str(record.get("project_id") or ""),
            "status": "queued",
        }


def _drain_active_chat_run_steers(run_id: str, *, final: bool = False) -> list[dict[str, Any]]:
    """Accept at most one queued user message at a clean model boundary.

    A final empty drain atomically closes the turn to new guidance, avoiding a
    message being accepted after the runtime has committed to returning. Later
    queued messages remain ordered for subsequent model boundaries.
    """
    with _active_chat_runs_lock:
        record = _active_chat_runs.get(str(run_id or "").strip())
        if not isinstance(record, dict):
            return []
        raw_pending = record.get("pending_steers")
        queued = [dict(item) for item in raw_pending if isinstance(item, dict)] if isinstance(raw_pending, list) else []
        pending = queued[:1]
        record["pending_steers"] = queued[1:]
        if final and not pending:
            record["accepting_steers"] = False
        if pending:
            accepted_at = time.time()
            for item in pending:
                item["accepted_at"] = accepted_at
            record["accepted_steer_count"] = int(record.get("accepted_steer_count") or 0) + len(pending)
        return pending


def _unregister_active_chat_run(run_id: str) -> None:
    with _active_chat_runs_lock:
        _active_chat_runs.pop(str(run_id or "").strip(), None)


def _build_provider_payload_uncached() -> dict[str, Any]:
    provider_options: list[dict[str, object]] = []
    provider_options_started = time.perf_counter()
    for item in list_provider_profiles(config):
        provider = str(item.get("provider") or "").strip()
        if not provider:
            continue
        provider_config = build_provider_config(config, provider)
        provider_options.append(
            {
                "provider": provider,
                "label": str(item.get("label") or provider),
                "default_model": str(item.get("default_model") or provider_config.default_model or ""),
                "model_options": list(item.get("model_options") or provider_config.model_options or []),
            }
        )
    provider_options_ms = int((time.perf_counter() - provider_options_started) * 1000)
    active_provider = next(
        (
            item
            for item in provider_options
            if str(item.get("provider") or "").strip() == str(config.llm_provider or "").strip()
        ),
        provider_options[0] if provider_options else None,
    )
    active_provider_name = str((active_provider or {}).get("provider") or config.llm_provider or "")
    active_provider_config = build_provider_config(config, active_provider_name)
    return {
        "provider_options": provider_options,
        "active_provider": dict(active_provider or {}),
        "active_provider_name": active_provider_name,
        "active_provider_config": active_provider_config,
        "auth_summary": {
            "available": True,
            "reason": "not_prechecked",
            "mode": "unchecked",
            "provider": active_provider_name,
        },
        "created_at": time.monotonic(),
        "diagnostics": {
            "runtime_status_provider_options_ms": max(0, provider_options_ms),
            "runtime_status_auth_summary_ms": 0,
        },
    }


def _get_provider_payload(*, refresh: bool = False) -> dict[str, Any]:
    with _provider_payload_lock:
        cached = _provider_payload_cache if _provider_payload_cache else None
        if refresh or not isinstance(cached, dict) or not cached:
            next_generation = int((_provider_payload_cache or {}).get("generation") or 0) + 1
            rebuilt = _build_provider_payload_uncached()
            rebuilt["generation"] = next_generation
            _provider_payload_cache.clear()
            _provider_payload_cache.update(rebuilt)
            cached = _provider_payload_cache
        return {
            "provider_options": [dict(item) for item in list(cached.get("provider_options") or []) if isinstance(item, dict)],
            "active_provider": dict(cached.get("active_provider") or {}),
            "active_provider_name": str(cached.get("active_provider_name") or ""),
            "active_provider_config": cached.get("active_provider_config"),
            "auth_summary": dict(cached.get("auth_summary") or {}),
            "created_at": float(cached.get("created_at") or 0.0),
            "generation": int(cached.get("generation") or 0),
            "diagnostics": dict(cached.get("diagnostics") or {}),
        }


def _invalidate_provider_payload_cache() -> None:
    with _provider_payload_lock:
        _provider_payload_cache.clear()


def _provider_options_payload(*, refresh: bool = False) -> list[dict[str, object]]:
    return list(_get_provider_payload(refresh=refresh).get("provider_options") or [])


def _runtime_descriptor(*, locale: str | None = None, refresh: bool = False) -> dict[str, object]:
    runtime = get_vintage_programmer_runtime()
    if refresh and hasattr(runtime, "invalidate_descriptor_cache"):
        try:
            runtime.invalidate_descriptor_cache()
        except Exception:
            pass
    try:
        return runtime.descriptor(locale=locale, refresh=refresh)
    except TypeError:
        if locale is None:
            return runtime.descriptor()
        return runtime.descriptor(locale)


def _invalidate_runtime_descriptor_caches() -> None:
    runtimes: list[Any] = [get_vintage_programmer_runtime()]
    with _provider_runtime_lock:
        runtimes.extend(_provider_runtime_cache.values())
    for runtime in runtimes:
        if hasattr(runtime, "invalidate_descriptor_cache"):
            try:
                runtime.invalidate_descriptor_cache()
            except Exception:
                continue


def _provider_runtime(provider: str) -> tuple[AppConfig, VintageProgrammerRuntime]:
    normalized = normalize_llm_provider_name(provider or config.llm_provider)
    if normalized == config.llm_provider:
        return config, vintage_programmer_runtime
    with _provider_runtime_lock:
        cached = _provider_runtime_cache.get(normalized)
        if cached is None:
            provider_config = build_provider_config(config, normalized)
            cached = VintageProgrammerRuntime(
                config=provider_config,
                agent_dir=AGENT_DIR,
            )
            _provider_runtime_cache[normalized] = cached
        return build_provider_config(config, normalized), cached


def _resolve_requested_provider(req: ChatRequest) -> str:
    requested = normalize_llm_provider_name((req.settings.provider or "").strip() or config.llm_provider)
    provider_payload = _get_provider_payload()
    available = {
        str(item.get("provider") or "").strip()
        for item in list(provider_payload.get("provider_options") or [])
        if str(item.get("provider") or "").strip()
    }
    if not available:
        return config.llm_provider
    if requested not in available:
        raise HTTPException(status_code=400, detail=f"Provider not configured in env: {requested}")
    return requested


def _session_last_compacted_at(session: dict[str, Any] | None) -> str:
    compaction_state = ensure_compaction_state(session or {})
    compacted_at = str(compaction_state.get("last_compacted_at") or "").strip()
    if compacted_at:
        return compacted_at
    agent_state = (session or {}).get("agent_state")
    if not isinstance(agent_state, dict):
        return ""
    return str(agent_state.get("last_compacted_at") or "").strip()


def _build_compaction_status_for_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
    estimate_mode: str = "exact",
) -> dict[str, Any]:
    return build_compaction_status(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at or _session_last_compacted_at(session),
        estimate_mode=estimate_mode,
        auto_compact_ratio=config.context_auto_compact_ratio,
        danger_compact_ratio=config.context_danger_compact_ratio,
        history_soft_limit_tokens=config.context_history_soft_limit_tokens,
        context_window_tokens=config.context_window_tokens,
        auto_compact_token_limit=config.context_auto_compact_token_limit,
    )


def _build_context_meter_for_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
    estimate_mode: str = "exact",
) -> dict[str, Any]:
    return build_context_meter(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at or _session_last_compacted_at(session),
        estimate_mode=estimate_mode,
        auto_compact_ratio=config.context_auto_compact_ratio,
        danger_compact_ratio=config.context_danger_compact_ratio,
        history_soft_limit_tokens=config.context_history_soft_limit_tokens,
        context_window_tokens=config.context_window_tokens,
        auto_compact_token_limit=config.context_auto_compact_token_limit,
    )


def _context_bundle_for_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
    estimate_mode: str = "exact",
) -> tuple[dict[str, Any], dict[str, Any]]:
    compaction_status = _build_compaction_status_for_session(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at,
        estimate_mode=estimate_mode,
    )
    return build_context_meter_from_status(compaction_status), compaction_status


def _cached_context_bundle_for_view(session: dict[str, Any], agent_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    context_meter = {}
    compaction_status = {}
    for source in (agent_state, session):
        if not isinstance(source, dict):
            continue
        if not context_meter and isinstance(source.get("context_meter"), dict):
            context_meter = dict(source.get("context_meter") or {})
        if not compaction_status and isinstance(source.get("compaction_status"), dict):
            compaction_status = dict(source.get("compaction_status") or {})
    if compaction_status and not context_meter:
        context_meter = build_context_meter_from_status(compaction_status)
    return context_meter, compaction_status


def _context_exact_is_stale(compaction_status: dict[str, Any]) -> bool:
    raw_updated_at = str(compaction_status.get("context_exact_updated_at") or "").strip()
    if not raw_updated_at:
        return False
    try:
        parsed = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() > float(config.context_exact_stale_sec)


def _context_status_response_for_session(
    *,
    session_id: str,
    session: dict[str, Any],
    model: str | None,
    max_output_tokens: int | None,
) -> CompactResponse:
    agent_state = session.get("agent_state") if isinstance(session.get("agent_state"), dict) else {}
    context_meter, compaction_status = _cached_context_bundle_for_view(session, agent_state)
    if compaction_status:
        compaction_status = dict(compaction_status)
        compaction_status["estimate_mode"] = "cached"
        compaction_status["calculation_ms"] = 0
        compaction_status["stale"] = _context_exact_is_stale(compaction_status)
        context_meter = build_context_meter_from_status(compaction_status)
    else:
        context_meter, compaction_status = _context_bundle_for_session(
            session=session,
            model=model,
            max_output_tokens=max_output_tokens,
            estimate_mode="quick",
        )
        compaction_status = dict(compaction_status)
        compaction_status["stale"] = True
        context_meter = build_context_meter_from_status(compaction_status)
        session["context_meter"] = dict(context_meter)
        session["compaction_status"] = dict(compaction_status)
        agent_state["context_meter"] = dict(context_meter)
        agent_state["compaction_status"] = dict(compaction_status)
        session["agent_state"] = dict(agent_state)
        session_store.save(session)
    return CompactResponse(
        ok=True,
        session_id=session_id,
        thread_id=session_id,
        compacted=False,
        summary="",
        context_meter=context_meter,
        compaction_status=compaction_status,
    )


def get_workbench_store() -> WorkbenchStore:
    return workbench_store


app = FastAPI(title=APP_TITLE, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = (Path(__file__).resolve().parent / "static").resolve()
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(str(static_dir / "index.html"))


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        app_version=APP_VERSION,
        build_version=BUILD_VERSION,
        uptime_sec=max(0, int(time.monotonic() - APP_STARTED_AT)),
    )


@app.get("/api/bootstrap", response_model=BootstrapResponse)
def bootstrap(refresh_provider: bool = False, refresh_descriptor: bool = False) -> BootstrapResponse:
    return _bootstrap_response_payload(
        refresh_provider=refresh_provider,
        refresh_descriptor=refresh_descriptor,
    )


@app.get("/api/runtime-status", response_model=RuntimeStatusResponse)
def runtime_status(project_id: str | None = None, model: str | None = None, max_output_tokens: int = DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS) -> RuntimeStatusResponse:
    return _runtime_status_response_payload(
        project_id=project_id,
        model=model,
        max_output_tokens=max_output_tokens,
    )


@app.get("/api/app/status", response_model=AppStatusResponse)
def app_status() -> AppStatusResponse:
    return AppStatusResponse(**app_update_manager.status())


@app.post("/api/app/update", response_model=AppUpdateResponse)
def app_update() -> AppUpdateResponse:
    return AppUpdateResponse(**app_update_manager.update())


@app.get("/api/workbench/tools", response_model=WorkbenchToolsResponse)
def workbench_tools() -> WorkbenchToolsResponse:
    payload = get_vintage_programmer_runtime().descriptor()
    tools = list((payload.get("tools") or []))
    return WorkbenchToolsResponse(tools=[ToolDescriptor(**item) for item in tools if isinstance(item, dict)])


@app.get("/api/projects", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    rows = get_project_store().list_projects()
    return ProjectListResponse(projects=[ProjectDescriptor(**item) for item in rows if isinstance(item, dict)])


@app.post("/api/projects", response_model=ProjectDescriptor)
def create_project(req: ProjectCreateRequest) -> ProjectDescriptor:
    try:
        project = get_project_store().create(root_path=req.root_path, title=req.title)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectDescriptor(**project)


@app.patch("/api/projects/{project_id}", response_model=ProjectDescriptor)
def update_project(project_id: str, req: ProjectUpdateRequest) -> ProjectDescriptor:
    try:
        project = get_project_store().update(project_id, title=req.title, pinned=req.pinned)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectDescriptor(**project)


@app.delete("/api/projects/{project_id}", response_model=ProjectDeleteResponse)
def delete_project(project_id: str) -> ProjectDeleteResponse:
    try:
        project = get_project_store().get(project_id)
        if not project:
            raise FileNotFoundError(f"Project not found: {project_id}")
        if bool(project.get("is_default")):
            raise ValueError("Default project cannot be deleted")
        deleted_session_count = session_store.delete_by_project(project_id)
        get_project_store().delete(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectDeleteResponse(
        ok=True,
        project_id=project_id,
        deleted_session_count=deleted_session_count,
    )


@app.get("/api/workbench/skills", response_model=WorkbenchSkillsResponse)
def workbench_skill_catalog() -> WorkbenchSkillsResponse:
    skills = get_workbench_store().list_skill_entries(include_content=False)
    return WorkbenchSkillsResponse(
        skills=[SkillDescriptor(**item) for item in skills if isinstance(item, dict)],
        migration=get_workbench_store().skill_migration_report,
    )


@app.get("/api/workbench/skills/{skill_name}", response_model=SkillDescriptor)
def workbench_skill_detail(skill_name: str, scope: str = "team") -> SkillDescriptor:
    try:
        return SkillDescriptor(**get_workbench_store().get_skill(skill_name, scope=scope))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workbench/skills", response_model=SkillDescriptor)
def workbench_create_skill(req: SkillUpsertRequest) -> SkillDescriptor:
    try:
        created = SkillDescriptor(**get_workbench_store().create_skill(req.content))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_runtime_descriptor_caches()
    return created


@app.put("/api/workbench/skills/{skill_name}", response_model=SkillDescriptor)
def workbench_update_skill(skill_name: str, req: SkillUpsertRequest, scope: str = "team") -> SkillDescriptor:
    try:
        updated = SkillDescriptor(**get_workbench_store().save_skill(skill_name, req.content, scope=scope))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_runtime_descriptor_caches()
    return updated


@app.post("/api/workbench/skills/{skill_name}/toggle", response_model=SkillDescriptor)
def workbench_set_skill_enabled(skill_name: str, req: ToggleSkillRequest, scope: str = "team") -> SkillDescriptor:
    try:
        updated = SkillDescriptor(**get_workbench_store().set_skill_enabled(skill_name, enabled=req.enabled, scope=scope))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_runtime_descriptor_caches()
    return updated


@app.delete("/api/workbench/skills/{skill_name}", response_model=SkillDeleteResponse)
def workbench_delete_skill(skill_name: str, scope: str = "team") -> SkillDeleteResponse:
    try:
        get_workbench_store().delete_skill(skill_name, scope=scope)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_runtime_descriptor_caches()
    return SkillDeleteResponse(ok=True, skill_id=skill_name)


@app.get("/api/workbench/specs", response_model=WorkbenchSpecsResponse)
def workbench_spec_catalog(locale: str | None = None) -> WorkbenchSpecsResponse:
    specs = get_workbench_store().list_spec_entries(locale=locale)
    return WorkbenchSpecsResponse(specs=[SpecDescriptor(**item) for item in specs if isinstance(item, dict)])


@app.get("/api/workbench/specs/{name}", response_model=SpecDescriptor)
def workbench_spec_detail(name: str, locale: str | None = None) -> SpecDescriptor:
    try:
        return SpecDescriptor(**get_workbench_store().get_agent_spec(name, locale=locale))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/workbench/specs/{name}", response_model=SpecDescriptor)
def workbench_update_spec(name: str, req: SpecUpsertRequest, locale: str | None = None) -> SpecDescriptor:
    try:
        updated = SpecDescriptor(**get_workbench_store().save_agent_spec(name, req.content, locale=locale))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_runtime_descriptor_caches()
    return updated


def _default_project() -> dict[str, Any]:
    return get_project_store().ensure_default_project()


def _resolve_project_or_default(project_id: str | None) -> dict[str, Any]:
    wanted = str(project_id or "").strip()
    if not wanted:
        return _default_project()
    project = get_project_store().get(wanted)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {wanted}")
    return project


def _cached_project_or_none(project_id: str | None) -> dict[str, Any] | None:
    store = get_project_store()
    if not hasattr(store, "get_cached"):
        return None
    try:
        project = store.get_cached(project_id)
    except Exception:
        return None
    return dict(project) if isinstance(project, dict) and project else None


def _resolve_project_for_chat(project_id: str | None) -> dict[str, Any]:
    wanted = str(project_id or "").strip()
    cached = _cached_project_or_none(wanted)
    if cached:
        return cached
    if wanted:
        project = get_project_store().get(wanted)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project not found: {wanted}")
        return project
    return _default_project()


def _touch_project_for_chat(project_id: str) -> dict[str, Any]:
    store = get_project_store()
    if hasattr(store, "touch_cached"):
        return store.touch_cached(project_id)
    return store.touch(project_id)


def _resolve_project_for_thread_create(project_id: str | None) -> dict[str, Any]:
    wanted = str(project_id or "").strip()
    project = get_project_store().get_cached(wanted) if hasattr(get_project_store(), "get_cached") else None
    if not project:
        if wanted:
            raise HTTPException(status_code=404, detail=f"Project not found: {wanted}")
        return _default_project()
    return project


def _runtime_provider_payload(*, include_runtime: bool = True, refresh_provider: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    timer = PhaseTimer()
    with timer.measure("runtime_status_provider_cache_ms"):
        provider_payload = _get_provider_payload(refresh=refresh_provider)
    with timer.measure("runtime_status_runtime_meta_ms"):
        runtime_meta = (
            _runtime_meta_payload()
            if include_runtime
            else {
                "docker_available": False,
                "docker_message": "runtime status is loaded asynchronously",
                "ocr_status": {},
            }
        )
    diagnostics = timer.snapshot(total_key="runtime_status_total_ms")
    created_at = float(provider_payload.get("created_at") or 0.0)
    diagnostics["provider_cache_generation"] = int(provider_payload.get("generation") or 0)
    diagnostics["provider_cache_age_ms"] = max(0, int((time.monotonic() - created_at) * 1000)) if created_at > 0 else 0
    diagnostics["provider_payload_cached"] = True
    diagnostics.update(dict(provider_payload.get("diagnostics") or {}))
    return provider_payload, runtime_meta, diagnostics


def _effective_allowed_roots(projects: list[dict[str, Any]]) -> list[str]:
    effective_roots: list[str] = []
    for raw_root in [*(str(path) for path in config.allowed_roots), *(str(item.get("root_path") or "") for item in projects)]:
        if raw_root and raw_root not in effective_roots:
            effective_roots.append(raw_root)
    return effective_roots


def _permission_summary_for_roots(effective_roots: list[str], locale: str | None = None) -> str:
    effective_locale = normalize_locale(locale, config.default_locale)
    if config.allow_any_path:
        return translate(effective_locale, "health.permission_summary.full_filesystem")
    root_names = [(Path(path).name or str(path)) for path in effective_roots[:4]]
    return translate(
        effective_locale,
        "health.permission_summary.allowed_roots",
        count=len(effective_roots),
        root_names=", ".join(root_names),
    )


def _active_thread_ids() -> set[str]:
    with _active_chat_runs_lock:
        return {
            str(item.get("session_id") or "").strip()
            for item in _active_chat_runs.values()
            if isinstance(item, dict) and str(item.get("session_id") or "").strip()
        }


def _thread_status_value(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if normalized and normalized in _active_thread_ids():
        return "active"
    return "idle"


def _thread_list_item_from_session_row(row: dict[str, Any]) -> ThreadListItem:
    session_id = str(row.get("session_id") or "").strip()
    return ThreadListItem(
        thread_id=session_id,
        session_id=session_id,
        title=str(row.get("title") or ""),
        has_custom_title=bool(row.get("has_custom_title")),
        preview=str(row.get("preview") or ""),
        turn_count=int(row.get("turn_count") or 0),
        project_id=str(row.get("project_id") or ""),
        project_title=str(row.get("project_title") or ""),
        project_root=str(row.get("project_root") or ""),
        git_branch=str(row.get("git_branch") or ""),
        cwd=str(row.get("cwd") or ""),
        updated_at=str(row.get("updated_at") or ""),
        created_at=str(row.get("created_at") or ""),
        status=_thread_status_value(session_id),
    )


def _thread_list_item_for_session_id(session_id: str) -> ThreadListItem | None:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        return None
    rows = session_store.list_recent_sessions(limit=500, project_id=str(loaded.get("project_id") or ""), default_project=_default_project())
    hit = next((row for row in rows if str(row.get("session_id") or "") == str(session_id or "")), None)
    if hit is None:
        return None
    return _thread_list_item_from_session_row(hit)


def _thread_list_item_from_session_snapshot(session: dict[str, Any]) -> ThreadListItem | None:
    if not isinstance(session, dict):
        return None
    row = session_store.session_meta_store.metadata_from_session(session)
    if not str(row.get("session_id") or "").strip():
        return None
    return _thread_list_item_from_session_row(row)


def _bootstrap_response_payload(
    *,
    refresh_provider: bool = False,
    refresh_descriptor: bool = False,
) -> BootstrapResponse:
    provider_payload, runtime_meta, _provider_diagnostics = _runtime_provider_payload(
        include_runtime=False,
        refresh_provider=refresh_provider,
    )
    provider_options = list(provider_payload.get("provider_options") or [])
    active_provider = dict(provider_payload.get("active_provider") or {})
    active_provider_name = str(provider_payload.get("active_provider_name") or config.llm_provider or "")
    active_provider_config = provider_payload.get("active_provider_config") or build_provider_config(config, active_provider_name)
    auth_summary = dict(provider_payload.get("auth_summary") or {})
    default_project = get_project_store().ensure_default_project()
    agent_descriptor = _runtime_descriptor(refresh=refresh_descriptor)
    active_model = str(
        (active_provider or {}).get("default_model")
        or active_provider_config.default_model
        or agent_descriptor.get("default_model")
        or config.default_model
        or ""
    )
    effective_roots = _effective_allowed_roots([default_project])
    return BootstrapResponse(
        ok=True,
        app_title=APP_TITLE,
        app_version=APP_VERSION,
        build_version=BUILD_VERSION,
        default_locale=config.default_locale,
        supported_locales=supported_locales(),
        default_model=active_model,
        model_options=list((active_provider or {}).get("model_options") or active_provider_config.model_options or []),
        allow_custom_model=True,
        llm_provider=active_provider_name,
        provider_options=provider_options,
        auth_mode=str(auth_summary.get("mode") or ""),
        execution_mode_default=config.execution_mode,
        docker_available=bool(runtime_meta.get("docker_available")),
        docker_message=str(runtime_meta.get("docker_message") or "") or None,
        platform_name=config.platform_name,
        workspace_root=str(config.workspace_root),
        allowed_roots=effective_roots,
        default_permission_profile=normalize_permission_profile(getattr(config, "permission_profile", "auto")),
        default_max_output_tokens=int(config.max_output_tokens),
        max_upload_mb=config.max_upload_mb,
        web_allow_all_domains=config.web_allow_all_domains,
        web_allowed_domains=config.web_allowed_domains,
        default_project_id=str(default_project.get("project_id") or ""),
        agent=agent_descriptor,
    )


def _runtime_status_response_payload(
    *,
    project_id: str | None = None,
    model: str | None = None,
    max_output_tokens: int = DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS,
) -> RuntimeStatusResponse:
    provider_payload, runtime_meta, provider_diagnostics = _runtime_provider_payload()
    active_provider = dict(provider_payload.get("active_provider") or {})
    active_provider_name = str(provider_payload.get("active_provider_name") or config.llm_provider or "")
    active_provider_config = provider_payload.get("active_provider_config") or build_provider_config(config, active_provider_name)
    auth_summary = dict(provider_payload.get("auth_summary") or {})
    selected_project = _resolve_project_or_default(project_id)
    active_model = str(
        model
        or (active_provider or {}).get("default_model")
        or active_provider_config.default_model
        or config.default_model
        or ""
    ).strip()
    projects = get_project_store().list_projects()
    effective_roots = _effective_allowed_roots(projects)
    permission_profile = normalize_permission_profile(getattr(config, "permission_profile", "auto"))
    status_settings = ChatSettings(permission_profile=permission_profile, enable_tools=True)
    status_contract = build_full_auto_runtime_contract(settings=status_settings, config=config)
    status_boundary = build_turn_runtime_boundary(
        config=config,
        runtime_contract=status_contract,
        project_root=str(selected_project.get("root_path") or config.workspace_root),
        cwd=str(selected_project.get("root_path") or config.workspace_root),
        attachments=[],
    )
    workspace_boundary = {
        "permission_profile": permission_profile,
        "project_root": status_boundary.project_root,
        "cwd": status_boundary.cwd,
        "readable_roots": list(status_boundary.allowed_roots),
        "writable_roots": list(status_boundary.writable_roots),
        "command_allowed_roots": list(status_boundary.command_allowed_roots),
        "network_allowed": bool(status_boundary.network_allowed),
        "network_reason": status_boundary.network_reason(),
        "shell_allowed": bool(status_boundary.shell_allowed),
        "workspace_write_allowed": bool(status_boundary.workspace_write_allowed),
        "model_view": status_boundary.to_model_view(),
    }
    runtime_status = {
        "execution_mode": config.execution_mode,
        "auth_ready": bool(auth_summary.get("available")),
        "auth_mode": str(auth_summary.get("mode") or ""),
        "provider": active_provider_name,
        "permission_profile": permission_profile,
        "workspace_boundary": workspace_boundary,
        "permission_summary": _permission_summary_for_roots(effective_roots),
        "workspace_label": str(selected_project.get("title") or config.workspace_root.name or str(config.workspace_root)),
        "project_root": str(selected_project.get("root_path") or config.workspace_root),
        "default_project_id": str(_default_project().get("project_id") or ""),
        "git_branch": str(selected_project.get("git_branch") or ""),
        "build_version": BUILD_VERSION,
        "loop_safeguards": default_loop_safeguards(),
        "provider_diagnostics": dict(provider_diagnostics),
    }
    context_meter, compaction_status = _context_bundle_for_session(
        model=active_model,
        max_output_tokens=max_output_tokens,
        estimate_mode="quick",
    )
    return RuntimeStatusResponse(
        ok=True,
        project_id=str(selected_project.get("project_id") or ""),
        project_title=str(selected_project.get("title") or ""),
        project_root=str(selected_project.get("root_path") or ""),
        git_branch=str(selected_project.get("git_branch") or ""),
        cwd=str(selected_project.get("root_path") or ""),
        runtime_status=runtime_status,
        ocr_status=dict(runtime_meta.get("ocr_status") or {}),
        context_meter=context_meter,
        compaction_status=compaction_status,
    )


def _turn_public_id(item: dict[str, Any], index: int) -> str:
    explicit_id = str(item.get("id") or "").strip()
    if explicit_id:
        return explicit_id
    stable_source = "|".join(
        [
            str(index),
            str(item.get("role") or ""),
            str(item.get("created_at") or ""),
            str(item.get("text") or "")[:160],
        ]
    )
    digest = hashlib.sha1(stable_source.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"legacy-{index}-{digest}"


def _normalize_detail_view(view: str | None) -> str:
    normalized = str(view or "summary").strip().lower()
    if normalized not in {"summary", "full"}:
        raise HTTPException(status_code=400, detail="view must be summary or full")
    return normalized


def _session_turn_from_payload(item: dict[str, Any], *, turn_id: str) -> SessionTurn:
    return SessionTurn(
        id=turn_id,
        role=str(item.get("role") or "user"),
        text=str(item.get("text") or ""),
        answer_bundle=item.get("answer_bundle") or {},
        activity=item.get("activity") or {},
        run_artifact=item.get("run_artifact") or {},
        created_at=str(item.get("created_at")) if item.get("created_at") else None,
    )


def _thread_display_title(session: dict[str, Any]) -> str:
    return session_store.session_meta_store.display_title_for_session(session)


def _thread_detail_response_payload(
    session_id: str,
    max_turns: int = 40,
    before_turn_id: str | None = None,
    view: str | None = "summary",
) -> ThreadDetailResponse:
    detail_view = _normalize_detail_view(view)
    loaded = session_store.load_for_view(session_id)
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_state = dict(loaded.get("agent_state") or {})
    context_meter, compaction_status = _cached_context_bundle_for_view(loaded, agent_state)
    if context_meter:
        agent_state.setdefault("context_meter", dict(context_meter))
    if compaction_status:
        agent_state.setdefault("compaction_status", dict(compaction_status))
    turns_raw = loaded.get("turns", [])
    if not isinstance(turns_raw, list):
        turns_raw = []
    turn_limit = max(1, min(2000, int(max_turns)))
    before_id = str(before_turn_id or "").strip()
    indexed_turns = [
        (index, item)
        for index, item in enumerate(turns_raw)
        if isinstance(item, dict)
    ]
    end_index = len(indexed_turns)
    if before_id:
        for position, (index, item) in enumerate(indexed_turns):
            if _turn_public_id(item, index) == before_id:
                end_index = position
                break
    limited_turns = indexed_turns[max(0, end_index - turn_limit) : end_index]
    turns: list[SessionTurn] = []
    for index, item in limited_turns:
        turn_id = _turn_public_id(item, index)
        expanded = session_store.expand_turn_for_view(session_id, item, view=detail_view)
        turns.append(_session_turn_from_payload(expanded, turn_id=turn_id))
    work_cursor = dict(loaded.get("work_cursor") or {})
    task_state = dict(loaded.get("task_state") or {})
    thread_memory = session_context_impl.get_thread_memory(loaded)
    recent_tasks = list(thread_memory.get("recent_tasks") or [])
    artifact_memory_preview = session_context_impl.get_artifact_memory_preview(loaded)
    agent_state.setdefault("work_cursor", work_cursor)
    agent_state.setdefault("task_state", task_state)
    agent_state.setdefault(
        "task_checkpoint",
        session_context_impl.compat_task_checkpoint_from_focus(session_context_impl.get_current_task_focus(loaded)),
    )
    return ThreadDetailResponse(
        thread_id=session_id,
        session_id=session_id,
        title=str(loaded.get("title") or ""),
        display_title=_thread_display_title(loaded),
        has_custom_title=bool(str(loaded.get("title") or "").strip()),
        summary=str(loaded.get("summary") or ""),
        turn_count=len(turns_raw),
        project_id=str(loaded.get("project_id") or ""),
        project_title=str(loaded.get("project_title") or ""),
        project_root=str(loaded.get("project_root") or ""),
        git_branch=str(loaded.get("git_branch") or ""),
        cwd=str(loaded.get("cwd") or ""),
        status=_thread_status_value(session_id),
        agent_state=agent_state,
        work_cursor=work_cursor,
        task_state=task_state,
        recent_tasks=recent_tasks,
        artifact_memory_preview=artifact_memory_preview,
        context_meter=context_meter,
        compaction_status=compaction_status,
        turns=turns,
    )


@app.post("/api/session/new", response_model=NewSessionResponse)
def create_session(req: NewSessionRequest | None = None) -> NewSessionResponse:
    project = _resolve_project_for_thread_create((req.project_id if req else None))
    session = session_store.create(project)
    return NewSessionResponse(session_id=session["id"], project_id=str(project.get("project_id") or ""))


@app.post("/api/thread/new", response_model=NewThreadResponse)
def create_thread(req: NewSessionRequest | None = None) -> NewThreadResponse:
    payload = create_session(req)
    return NewThreadResponse(
        thread_id=str(payload.session_id or ""),
        session_id=str(payload.session_id or ""),
        project_id=str(payload.project_id or ""),
    )


@app.delete("/api/session/{session_id}", response_model=DeleteSessionResponse)
def delete_session(session_id: str) -> DeleteSessionResponse:
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return DeleteSessionResponse(ok=True, session_id=session_id)


@app.delete("/api/thread/{thread_id}", response_model=DeleteThreadResponse)
def delete_thread(thread_id: str) -> DeleteThreadResponse:
    payload = delete_session(thread_id)
    return DeleteThreadResponse(
        ok=bool(payload.ok),
        thread_id=str(thread_id or ""),
        session_id=str(payload.session_id or ""),
    )


@app.patch("/api/session/{session_id}/title", response_model=UpdateSessionTitleResponse)
def update_session_title(session_id: str, req: UpdateSessionTitleRequest) -> UpdateSessionTitleResponse:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")

    title = str(req.title or "").strip()[:120]
    loaded["title"] = title
    session_store.save(loaded)
    return UpdateSessionTitleResponse(
        ok=True,
        session_id=session_id,
        title=title,
        display_title=_thread_display_title(loaded),
        has_custom_title=bool(title),
    )


@app.get("/api/session/{session_id}", response_model=SessionDetailResponse, response_model_exclude_defaults=True)
def get_session(
    session_id: str,
    max_turns: int = 40,
    before_turn_id: str | None = None,
    view: str = "summary",
) -> SessionDetailResponse:
    thread_payload = _thread_detail_response_payload(
        session_id,
        max_turns=max_turns,
        before_turn_id=before_turn_id,
        view=view,
    )
    return SessionDetailResponse(
        session_id=str(thread_payload.thread_id or ""),
        title=thread_payload.title,
        display_title=thread_payload.display_title,
        has_custom_title=thread_payload.has_custom_title,
        summary=thread_payload.summary,
        turn_count=thread_payload.turn_count,
        project_id=thread_payload.project_id,
        project_title=thread_payload.project_title,
        project_root=thread_payload.project_root,
        git_branch=thread_payload.git_branch,
        cwd=thread_payload.cwd,
        agent_state=thread_payload.agent_state,
        work_cursor=thread_payload.work_cursor,
        task_state=thread_payload.task_state,
        recent_tasks=thread_payload.recent_tasks,
        artifact_memory_preview=thread_payload.artifact_memory_preview,
        context_meter=thread_payload.context_meter,
        compaction_status=thread_payload.compaction_status,
        turns=thread_payload.turns,
    )


@app.get("/api/thread/{thread_id}", response_model=ThreadDetailResponse, response_model_exclude_defaults=True)
def get_thread(
    thread_id: str,
    max_turns: int = 40,
    before_turn_id: str | None = None,
    view: str = "summary",
) -> ThreadDetailResponse:
    return _thread_detail_response_payload(thread_id, max_turns=max_turns, before_turn_id=before_turn_id, view=view)


@app.get("/api/thread/{thread_id}/turn/{turn_id}", response_model=SessionTurn, response_model_exclude_defaults=True)
def get_thread_turn(thread_id: str, turn_id: str, view: str = "full") -> SessionTurn:
    detail_view = _normalize_detail_view(view)
    loaded = session_store.load_for_view(thread_id)
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")
    turns_raw = loaded.get("turns", [])
    if not isinstance(turns_raw, list):
        turns_raw = []
    for index, item in enumerate(turns_raw):
        if not isinstance(item, dict):
            continue
        public_id = _turn_public_id(item, index)
        if public_id != str(turn_id or "").strip():
            continue
        expanded = session_store.expand_turn_for_view(thread_id, item, view=detail_view)
        return _session_turn_from_payload(expanded, turn_id=public_id)
    raise HTTPException(status_code=404, detail="Turn not found")


@app.get("/api/sessions", response_model=SessionListResponse)
def get_sessions_endpoint(limit: int = 50, project_id: str | None = None) -> SessionListResponse:
    rows = session_store.list_recent_sessions(limit=limit, project_id=project_id, default_project=_default_project())
    return SessionListResponse(sessions=[SessionListItem(**row) for row in rows])


@app.get("/api/threads", response_model=ThreadListResponse)
def list_threads(limit: int = 50, project_id: str | None = None) -> ThreadListResponse:
    rows = session_store.list_recent_sessions(limit=limit, project_id=project_id, default_project=_default_project())
    return ThreadListResponse(threads=[_thread_list_item_from_session_row(row) for row in rows if isinstance(row, dict)])


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    max_bytes = config.max_upload_mb * 1024 * 1024
    try:
        meta = await upload_store.save_upload(file, max_bytes=max_bytes)
    except ValueError as exc:
        if "large" in str(exc).lower():
            raise HTTPException(status_code=413, detail=f"File too large (>{config.max_upload_mb}MB)") from exc
        raise

    return UploadResponse(
        id=meta["id"],
        name=meta["original_name"],
        mime=meta["mime"],
        size=meta["size"],
        kind=meta["kind"],
        upload_status=str(meta.get("upload_status") or "stored"),
        bytes_written=int(meta.get("bytes_written") or meta.get("size") or 0),
        duration_ms=int(meta.get("duration_ms") or 0),
        metadata_index_mode=str(meta.get("metadata_index_mode") or ""),
    )


@app.get("/api/stats", response_model=TokenStatsResponse)
def get_stats() -> TokenStatsResponse:
    raw = token_stats_store.get_stats(max_records=500)
    sessions: dict[str, TokenTotals] = {}
    for session_id, totals in raw.get("sessions", {}).items():
        sessions[session_id] = TokenTotals(**totals)
    return TokenStatsResponse(
        totals=TokenTotals(**raw.get("totals", {})),
        sessions=sessions,
        records=raw.get("records", []),
    )


@app.post("/api/stats/clear", response_model=ClearStatsResponse)
def clear_stats() -> ClearStatsResponse:
    token_stats_store.clear()
    return ClearStatsResponse(ok=True)


@app.get("/api/sessions/{session_id}/context-status", response_model=CompactResponse)
def get_session_context_status(
    session_id: str,
    model: str | None = None,
    max_output_tokens: int | None = None,
) -> CompactResponse:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")
    provider_config, _runtime_unused = _provider_runtime(config.llm_provider)
    resolved_model = str(model or provider_config.default_model or config.default_model or "").strip()
    resolved_max_output_tokens = int(max_output_tokens or config.max_output_tokens)
    return _context_status_response_for_session(
        session_id=session_id,
        session=loaded,
        model=resolved_model,
        max_output_tokens=resolved_max_output_tokens,
    )


@app.post("/api/sessions/{session_id}/compact", response_model=CompactResponse)
def compact_session_endpoint(session_id: str, req: CompactRequest | None = None) -> CompactResponse:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")
    trigger = str((req.trigger if req else "manual") or "manual")
    provider_config, provider_runtime = _provider_runtime(config.llm_provider)
    model = str(provider_config.default_model or config.default_model or "").strip()
    llm_compactor = None
    if hasattr(provider_runtime, "compact_context"):
        llm_compactor = lambda payload: provider_runtime.compact_context(
            payload,
            model=model,
            max_output_tokens=int(config.max_output_tokens),
        )
    result = maybe_auto_compact_session(
        session=loaded,
        model=model,
        max_output_tokens=int(config.max_output_tokens),
        pending_message="",
        phase="manual",
        retained_raw_turns=2,
        llm_compactor=llm_compactor,
        force=True,
        trigger=trigger,
        auto_compact_ratio=config.context_auto_compact_ratio,
        danger_compact_ratio=config.context_danger_compact_ratio,
        history_soft_limit_tokens=config.context_history_soft_limit_tokens,
        context_window_tokens=config.context_window_tokens,
        auto_compact_token_limit=config.context_auto_compact_token_limit,
    )
    context_meter, compaction_status = _context_bundle_for_session(
        session=loaded,
        model=model,
        max_output_tokens=int(config.max_output_tokens),
        estimate_mode="quick",
    )
    loaded["context_meter"] = dict(context_meter)
    loaded["compaction_status"] = dict(compaction_status)
    agent_state = loaded.get("agent_state") if isinstance(loaded.get("agent_state"), dict) else {}
    agent_state["context_meter"] = dict(context_meter)
    agent_state["compaction_status"] = dict(compaction_status)
    agent_state["last_compacted_at"] = str(compaction_status.get("last_compacted_at") or "")
    loaded["agent_state"] = agent_state
    session_store.save(loaded)
    compacted = bool(result.get("compacted"))
    if compacted:
        summary = translate(config.default_locale, "chat.replacement_history_compacted", generation=compaction_status.get("generation") or 0, retained_turn_count=compaction_status.get("retained_turn_count") or 0)
    else:
        summary = "No compactable history found."
    return CompactResponse(
        ok=True,
        session_id=session_id,
        thread_id=session_id,
        compacted=compacted,
        summary=summary,
        context_meter=context_meter,
        compaction_status=compaction_status,
    )


@app.post("/api/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(req: ChatRequest) -> ChatResponse:
    locale = normalize_locale(getattr(req.settings, "locale", ""), config.default_locale)
    try:
        return _process_chat_request(req)
    except HTTPException as exc:
        payload = _normalize_chat_error_payload(exc.detail, status_code=exc.status_code, locale=locale)
        raise HTTPException(status_code=int(payload["status_code"]), detail=payload) from exc
    except Exception as exc:
        payload = _normalize_chat_error_payload(exc, locale=locale)
        raise HTTPException(status_code=int(payload["status_code"]), detail=payload) from exc


def _resolve_execution_mode(requested_mode: str | None) -> str:
    mode = str(requested_mode or "").strip().lower()
    if mode in {"host", "docker"}:
        return mode
    return config.execution_mode


def _append_drill_step(
    steps: list[SandboxDrillStep],
    *,
    name: str,
    ok: bool,
    detail: str,
    started_at: float,
) -> None:
    steps.append(
        SandboxDrillStep(
            name=name,
            ok=bool(ok),
            detail=str(detail),
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
    )


@app.post("/api/sandbox/drill", response_model=SandboxDrillResponse)
def sandbox_drill(req: SandboxDrillRequest) -> SandboxDrillResponse:
    run_id = str(uuid.uuid4())
    execution_mode = _resolve_execution_mode(req.execution_mode)
    tools = get_tool_executor()
    docker_ok, docker_msg = tools.docker_status()
    steps: list[SandboxDrillStep] = []
    failed = 0
    drill_session_id = f"__drill__{run_id}"
    pwd_result: dict[str, Any] | None = None

    started = time.perf_counter()
    _append_drill_step(
        steps,
        name="runtime_context",
        ok=True,
        detail=f"run_id={run_id}, execution_mode={execution_mode}, session_id={drill_session_id}",
        started_at=started,
    )

    if execution_mode == "docker":
        started = time.perf_counter()
        docker_step_ok = bool(docker_ok)
        _append_drill_step(
            steps,
            name="docker_ready",
            ok=docker_step_ok,
            detail=docker_msg or ("Docker server ready." if docker_step_ok else "Docker unavailable."),
            started_at=started,
        )
        if not docker_step_ok:
            failed += 1

    tools.set_runtime_context(execution_mode=execution_mode, session_id=drill_session_id)
    try:
        started = time.perf_counter()
        list_result = tools.list_dir(path=".", max_entries=20)
        list_ok = bool(list_result.get("ok"))
        list_detail = (
            f"path={list_result.get('path', '')}, entries={len(list_result.get('entries') or [])}"
            if list_ok
            else str(list_result.get("error") or "list_dir failed")
        )
        _append_drill_step(
            steps,
            name="list_dir",
            ok=list_ok,
            detail=list_detail,
            started_at=started,
        )
        if not list_ok:
            failed += 1

        started = time.perf_counter()
        pwd_result = tools.exec_command(cmd="pwd", cwd=".", yield_time_ms=200)
        pwd_ok = bool(pwd_result.get("ok"))
        pwd_detail = (
            f"mode={pwd_result.get('execution_mode')}, cwd={pwd_result.get('cwd')}, "
            f"status={pwd_result.get('status')}"
            if pwd_ok
            else str(pwd_result.get("error") or "exec_command pwd failed")
        )
        _append_drill_step(
            steps,
            name="exec_command_pwd",
            ok=pwd_ok,
            detail=pwd_detail,
            started_at=started,
        )
        if not pwd_ok:
            failed += 1

        started = time.perf_counter()
        python_command = str(config.python_command or "python").strip() or "python"
        if python_command in config.allowed_commands:
            py_result = tools.exec_command(cmd=f"{python_command} --version", cwd=".", yield_time_ms=200)
            py_ok = bool(py_result.get("ok"))
            py_out = str(py_result.get("output") or "").strip().splitlines()
            py_detail = py_out[0] if py_out else (
                str(py_result.get("error") or f"{python_command} --version failed") if not py_ok else f"{python_command} ok"
            )
            _append_drill_step(
                steps,
                name="exec_command_python_version",
                ok=py_ok,
                detail=py_detail,
                started_at=started,
            )
            if not py_ok:
                failed += 1
        else:
            _append_drill_step(
                steps,
                name="exec_command_python_version",
                ok=True,
                detail=f"skipped: {python_command} is not in VP_ALLOWED_COMMANDS",
                started_at=started,
            )

        if execution_mode == "docker":
            started = time.perf_counter()
            mapping_ok = False
            mapping_detail = "missing docker pwd result"
            if isinstance(pwd_result, dict) and pwd_result.get("ok"):
                mode = str(pwd_result.get("execution_mode") or "").strip().lower()
                host_cwd = str(pwd_result.get("host_cwd") or "").strip()
                sandbox_cwd = str(pwd_result.get("sandbox_cwd") or "").strip()
                mounts = pwd_result.get("mount_mappings") if isinstance(pwd_result.get("mount_mappings"), list) else []
                mapping_ok = mode == "docker" and bool(host_cwd) and bool(sandbox_cwd) and bool(mounts)
                mapping_detail = (
                    f"mode={mode}, host_cwd={host_cwd}, sandbox_cwd={sandbox_cwd}, mount_count={len(mounts)}"
                )
            _append_drill_step(
                steps,
                name="docker_path_mapping",
                ok=mapping_ok,
                detail=mapping_detail,
                started_at=started,
            )
            if not mapping_ok:
                failed += 1
    finally:
        tools.clear_runtime_context()

    if failed == 0:
        summary = f"沙盒演练通过（{len(steps)} 步）。"
    else:
        summary = f"沙盒演练发现 {failed} 个失败步骤（共 {len(steps)} 步）。"

    return SandboxDrillResponse(
        ok=failed == 0,
        run_id=run_id,
        execution_mode=execution_mode,
        docker_available=docker_ok,
        docker_message=docker_msg,
        summary=summary,
        steps=steps,
    )


def _emit_progress(progress_cb: Callable[[dict[str, Any]], None] | None, event: str, **payload: Any) -> None:
    if not progress_cb:
        return
    try:
        progress_cb(dump_model({"event": event, **payload}))
    except Exception:
        pass


def _emit_thread_started(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    thread_id: str,
    *,
    session: dict[str, Any] | None = None,
) -> None:
    item = _thread_list_item_from_session_snapshot(session or {}) if session is not None else None
    if item is None:
        item = _thread_list_item_for_session_id(thread_id)
    if item is None:
        return
    _emit_progress(progress_cb, "thread/started", thread=dump_model(item))


def _emit_thread_status_changed(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    *,
    thread_id: str,
    status: str,
) -> None:
    _emit_progress(
        progress_cb,
        "thread/status/changed",
        thread_id=str(thread_id or ""),
        status={"type": str(status or "idle")},
    )


def _emit_turn_started(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    *,
    thread_id: str,
    turn_id: str,
    run_snapshot: dict[str, Any] | None = None,
) -> None:
    payload = {
        "turn": {
            "id": str(turn_id or ""),
            "threadId": str(thread_id or ""),
            "status": "inProgress",
            "items": [],
        }
    }
    if run_snapshot:
        payload["run_snapshot"] = dict(run_snapshot)
    _emit_progress(progress_cb, "turn/started", **payload)


def _emit_agent_message_events(
    progress_cb: Callable[[dict[str, Any]], None] | None,
    *,
    thread_id: str,
    turn_id: str,
    text: str,
) -> None:
    item_id = f"{str(turn_id or 'turn')}:agent_message"
    _emit_progress(
        progress_cb,
        "item/started",
        thread_id=str(thread_id or ""),
        turn_id=str(turn_id or ""),
        item={
            "id": item_id,
            "type": "agentMessage",
            "text": "",
            "status": "inProgress",
        },
    )
    if str(text or ""):
        _emit_progress(
            progress_cb,
            "item/agentMessage/delta",
            thread_id=str(thread_id or ""),
            turn_id=str(turn_id or ""),
            item_id=item_id,
            delta=str(text or ""),
        )
    _emit_progress(
        progress_cb,
        "item/completed",
        thread_id=str(thread_id or ""),
        turn_id=str(turn_id or ""),
        item={
            "id": item_id,
            "type": "agentMessage",
            "text": str(text or ""),
            "status": "completed",
        },
    )


def _build_run_snapshot(
    *,
    goal: str,
    turn_id: str = "",
    current_task_focus: dict[str, Any] | None,
    turn_status: str,
    cwd: str,
    plan: list[dict[str, Any]] | None = None,
    pending_user_input: dict[str, Any] | None = None,
    pending_approval: dict[str, Any] | None = None,
    tool_count: int = 0,
    evidence_status: str = "not_needed",
    context_meter: dict[str, Any] | None = None,
    compaction_status: dict[str, Any] | None = None,
    work_cursor: dict[str, Any] | None = None,
    task_state: dict[str, Any] | None = None,
    task_state_delta: dict[str, Any] | None = None,
    task_state_validation: dict[str, Any] | None = None,
    model_draft: str = "",
    final_answer: str = "",
    runtime_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_focus = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus or {})
    normalized_work_cursor = session_context_impl.normalize_work_cursor(
        work_cursor
        if isinstance(work_cursor, dict) and work_cursor
        else {
            "project_root": normalized_focus.get("project_root") or "",
            "cwd": str(cwd or normalized_focus.get("cwd") or "").strip(),
            "active_files": normalized_focus.get("active_files") or [],
            "active_attachments": normalized_focus.get("active_attachments") or [],
        }
    )
    normalized_task_state = session_context_impl.normalize_task_state(
        task_state
        if isinstance(task_state, dict) and task_state
        else {
            "task_id": normalized_focus.get("task_id") or "",
            "goal": str(goal or normalized_focus.get("goal") or "").strip(),
            "status": str(turn_status or "running"),
            "plan_items": [dict(item) for item in list(plan or []) if isinstance(item, dict)][:12],
            "next_required_action": normalized_focus.get("next_action") or "",
            "blocked_reason": str((runtime_error or {}).get("message") or "") if isinstance(runtime_error, dict) else "",
        }
    )
    payload = {
        "goal": str(goal or "").strip(),
        "turn_status": str(turn_status or "running"),
        "cwd": str(cwd or normalized_focus.get("cwd") or "").strip(),
        "current_task_focus": normalized_focus,
        "work_cursor": normalized_work_cursor,
        "task_state": normalized_task_state,
        "plan": [dict(item) for item in list(plan or []) if isinstance(item, dict)][:12],
        "pending_user_input": dict(pending_user_input or {}),
        "pending_approval": dict(pending_approval or {}),
        "tool_count": int(tool_count or 0),
        "evidence_status": str(evidence_status or "not_needed"),
        "context_meter": dict(context_meter or {}),
        "compaction_status": dict(compaction_status or {}),
    }
    if str(turn_id or "").strip():
        payload["turn_id"] = str(turn_id or "").strip()
    if isinstance(task_state_delta, dict) and task_state_delta:
        payload["task_state_delta"] = session_context_impl.normalize_task_state_delta(task_state_delta)
    if isinstance(task_state_validation, dict) and task_state_validation:
        payload["task_state_validation"] = dict(task_state_validation)
    if str(model_draft or "").strip():
        payload["model_draft"] = str(model_draft or "")
    if str(final_answer or "").strip():
        payload["final_answer"] = str(final_answer or "")
    if isinstance(runtime_error, dict) and runtime_error:
        payload["runtime_error"] = dict(runtime_error)
    return payload


def _stringify_error_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False)
    except Exception:
        return str(detail)


def _parse_error_detail(detail: Any) -> dict[str, Any] | None:
    if isinstance(detail, dict):
        return detail
    raw_text = str(detail or "").strip()
    if not raw_text or raw_text[:1] not in {"{", "["}:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw_text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        normalized = int(str(value).strip())
    except Exception:
        return None
    return normalized if normalized > 0 else None


def _extract_provider_name(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("provider"),
        payload.get("provider_name"),
        ((payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}).get("provider_name"),
    ]
    nested_error = payload.get("error")
    if isinstance(nested_error, dict):
        candidates.extend(
            [
                nested_error.get("provider"),
                nested_error.get("provider_name"),
                ((nested_error.get("metadata") or {}) if isinstance(nested_error.get("metadata"), dict) else {}).get("provider_name"),
            ]
        )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _normalize_chat_error_payload(
    detail: Any,
    *,
    status_code: int | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    effective_locale = normalize_locale(locale, config.default_locale)
    if isinstance(detail, dict) and {"kind", "summary", "detail"}.issubset(detail.keys()):
        normalized = dict(detail)
        normalized["status_code"] = _coerce_int(normalized.get("status_code")) or _coerce_int(status_code) or 500
        normalized["detail"] = _stringify_error_detail(normalized.get("detail"))
        normalized["summary"] = str(normalized.get("summary") or translate(effective_locale, "error.request_failed"))
        normalized["kind"] = str(normalized.get("kind") or "unknown")
        normalized["retryable"] = bool(normalized.get("retryable"))
        normalized["provider"] = str(normalized.get("provider") or "")
        return normalized

    parsed = _parse_error_detail(detail)
    nested_error = (parsed or {}).get("error") if isinstance((parsed or {}).get("error"), dict) else {}
    raw_detail = _stringify_error_detail(detail)
    message_text = str(
        nested_error.get("message")
        or (parsed or {}).get("message")
        or (parsed or {}).get("detail")
        or raw_detail
    ).strip()
    lowered = f"{raw_detail}\n{message_text}".lower()
    extracted_status = (
        _coerce_int(status_code)
        or _coerce_int((parsed or {}).get("status_code"))
        or _coerce_int(nested_error.get("status_code"))
        or _coerce_int((parsed or {}).get("code"))
        or _coerce_int(nested_error.get("code"))
    )
    provider = _extract_provider_name(parsed) or _extract_provider_name(nested_error)

    if extracted_status == 429 or "rate limit" in lowered or "rate-limit" in lowered or "temporarily rate-limited upstream" in lowered or "too many requests" in lowered:
        kind = "rate_limit"
        summary = translate(effective_locale, "error.rate_limit")
        retryable = True
        resolved_status = 429
    elif extracted_status in {401, 403} or "unauthorized" in lowered or "forbidden" in lowered or "api key" in lowered or "credentials" in lowered or "authentication" in lowered:
        kind = "auth"
        summary = translate(effective_locale, "error.auth")
        retryable = False
        resolved_status = extracted_status or 401
    elif extracted_status in {502, 503, 504} or "temporarily unavailable" in lowered or "timeout" in lowered or "timed out" in lowered or "upstream" in lowered:
        kind = "upstream"
        summary = translate(effective_locale, "error.upstream")
        retryable = True
        resolved_status = extracted_status or 503
    else:
        kind = "unknown"
        summary = translate(effective_locale, "error.request_failed_detail")
        retryable = False
        resolved_status = extracted_status or 500

    return {
        "status_code": resolved_status,
        "kind": kind,
        "summary": summary,
        "detail": raw_detail or message_text or "unknown error",
        "retryable": retryable,
        "provider": provider,
    }


def _process_chat_request(
    req: ChatRequest, progress_cb: Callable[[dict[str, Any]], None] | None = None
) -> ChatResponse:
    req.settings.locale = normalize_locale(getattr(req.settings, "locale", ""), config.default_locale)
    locale = req.settings.locale
    request_phase_timer = PhaseTimer()
    client_submitted_at_ms = int(req.client_submitted_at_ms or 0) if req.client_submitted_at_ms else 0
    if client_submitted_at_ms > 0:
        request_phase_timer.record_duration_ms(
            "frontend_submit_to_backend_ms",
            max(0, request_phase_timer.started_at_ms - client_submitted_at_ms),
        )
    with request_phase_timer.measure("provider_profile_resolve_ms"):
        requested_provider = _resolve_requested_provider(req)
    provider_config, provider_runtime = _provider_runtime(requested_provider)
    req.settings.provider = requested_provider
    req.settings.permission_profile = normalize_permission_profile(
        getattr(req.settings, "permission_profile", "") or getattr(config, "permission_profile", "auto")
    )
    requested_model = str(req.settings.model or provider_config.default_model or "").strip() or provider_config.default_model
    with request_phase_timer.measure("provider_auth_summary_ms"):
        auth_summary = OpenAIAuthManager(provider_config).auth_summary()
    if not bool(auth_summary.get("available")):
        fallback_goal = str(req.message or "").strip()[:160]
        fallback_phase_timings = request_phase_timer.snapshot(total_key="total_ms")
        requested_project = _resolve_project_for_chat(req.project_id)
        seed_session = session_store.load_or_create(
            req.session_id,
            project=requested_project,
            default_project=requested_project,
        )
        fallback_text = translate(locale, "chat.auth_missing")
        user_turn = session_store.append_turn(seed_session, role="user", text=req.message)
        session_store.append_turn(
            seed_session,
            role="assistant",
            text=fallback_text,
            answer_bundle={
                "summary": fallback_text,
                "claims": [],
                "citations": [],
                "warnings": ["missing_model_auth"],
            },
            activity={
                "status": "blocked",
                "triggering_user_message": str(req.message or "").strip(),
                "triggering_user_turn_id": str(user_turn.get("id") or ""),
                "phase_timings": dict(fallback_phase_timings),
                "session_id": str(seed_session.get("id") or ""),
                "thread_id": str(seed_session.get("id") or ""),
            },
        )
        seed_session["summary"] = fallback_text
        seed_session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fallback_context_meter = _build_context_meter_for_session(
            session=seed_session,
            model=requested_model,
            max_output_tokens=req.settings.max_output_tokens,
            pending_message=req.message,
        )
        updated_at = seed_session["updated_at"]
        seed_session["work_cursor"] = session_context_impl.normalize_work_cursor(
            {
                "project_root": str(seed_session.get("project_root") or ""),
                "cwd": str(seed_session.get("project_root") or ""),
                "updated_at": updated_at,
            }
        )
        seed_session["task_state"] = session_context_impl.normalize_task_state(
            {
                "goal": fallback_goal,
                "status": "blocked",
                "blocked_reason": "missing_model_auth",
                "next_required_action": fallback_text,
                "updated_at": updated_at,
            }
        )
        seed_session["agent_state"] = {
            "agent_id": "vintage_programmer",
            "permission_profile": str(req.settings.permission_profile or "auto"),
            "turn_status": "blocked",
            "pending_user_input": {},
            "phase": "report",
            "last_run_id": "",
            "last_provider": requested_provider,
            "last_model": requested_model,
            "last_compacted_at": "",
            "tool_count": 0,
            "evidence_status": "not_needed",
            "enabled_skill_ids": [],
            "final_answer_preview": fallback_text[:240],
            "runtime_error": {},
            "updated_at": updated_at,
        }
        session_store.save(seed_session)
        return ChatResponse(
            session_id=seed_session["id"],
            run_id=None,
            agent_id="vintage_programmer",
            agent_title="Vintage Programmer",
            selected_business_module="llm_router_core",
            effective_model="",
            queue_wait_ms=0,
            text=fallback_text,
            tool_events=[],
            permission_profile=str(req.settings.permission_profile or "auto"),
            turn_status="blocked",
            plan=[],
            pending_user_input={},
            work_cursor=dict(seed_session.get("work_cursor") or {}),
            task_state=dict(seed_session.get("task_state") or {}),
            token_usage=TokenUsage(),
            session_token_totals=TokenTotals(),
            global_token_totals=TokenTotals(),
            inspector={
                "agent": get_vintage_programmer_runtime().descriptor(),
                "notes": ["missing_model_auth"],
                "run_state": {
                    "phase": "report",
                    "goal": fallback_goal,
                    "permission_profile": str(req.settings.permission_profile or "auto"),
                    "turn_status": "blocked",
                    "plan": [],
                    "pending_user_input": {},
                    "context_meter": dict(fallback_context_meter),
                    "phase_timings": dict(fallback_phase_timings),
                },
                "tool_timeline": [],
                "evidence": {"status": "not_needed", "required": False, "warning": "", "source_refs": []},
                "session": {
                    "session_id": seed_session["id"],
                    "project_id": str(seed_session.get("project_id") or ""),
                    "project_title": str(seed_session.get("project_title") or ""),
                    "project_root": str(seed_session.get("project_root") or ""),
                    "cwd": str(seed_session.get("project_root") or ""),
                    "history_turn_count": len(seed_session.get("turns") or []),
                    "attachment_count": 0,
                    "context_meter": dict(fallback_context_meter),
                    "phase_timings": dict(fallback_phase_timings),
                },
                "token_usage": {"total_tokens": 0},
                "loaded_skills": [],
            },
            activity=MessageActivity(
                status="blocked",
                triggering_user_message=str(req.message or "").strip(),
                triggering_user_turn_id=str(user_turn.get("id") or ""),
                phase_timings=dict(fallback_phase_timings),
                session_id=str(seed_session.get("id") or ""),
                thread_id=str(seed_session.get("id") or ""),
            ),
            context_meter=fallback_context_meter,
            turn_count=len(seed_session.get("turns") or []),
            summarized=False,
        )
    run_id = str(uuid.uuid4())
    cancel_event = _register_active_chat_run(run_id)
    _emit_progress(
        progress_cb,
        "stage",
        code="backend_start",
        phase="bootstrap",
        label="Bootstrap",
        status="running",
        detail=translate(
            locale,
            "chat.backend_start",
            run_id=run_id,
            auth_mode=auth_summary.get("mode"),
        ),
        run_id=run_id,
    )
    try:
        with request_phase_timer.measure("project_resolve_ms"):
            requested_project = _resolve_project_for_chat(req.project_id)
        with request_phase_timer.measure("session_seed_ms"):
            seed_session = session_store.load_or_create(
                req.session_id,
                project=requested_project,
                default_project=requested_project,
            )
        session_id = str(seed_session.get("id") or "")
        if not session_id:
            raise HTTPException(status_code=500, detail="Session create failed")
        _update_active_chat_run(run_id, session_id=session_id, project_id=str(requested_project.get("project_id") or ""))

        queue_wait_ms = 0
        with run_queue.run_slot(session_id) as ticket:
            queue_wait_ms = int(ticket.wait_ms)
            request_phase_timer.record_duration_ms("queue_wait_ms", queue_wait_ms)
            if queue_wait_ms >= config.run_queue_wait_notice_ms:
                _emit_progress(
                    progress_cb,
                    "trace",
                    message=translate(locale, "chat.queue_wait", queue_wait_ms=queue_wait_ms),
                    run_id=run_id,
                )

            if not bool(getattr(ticket, "waited", queue_wait_ms > 0)):
                request_phase_timer.record_duration_ms("session_load_ms", 0)
                session = seed_session
            else:
                with request_phase_timer.measure("session_load_ms"):
                    session = session_store.load_or_create(
                        session_id,
                        project=requested_project,
                        default_project=requested_project,
                    )
            with request_phase_timer.measure("session_project_resolve_ms"):
                session_project = _cached_project_or_none(str(session.get("project_id") or "")) or requested_project
            with request_phase_timer.measure("project_touch_ms"):
                touched_project = _touch_project_for_chat(str(session_project.get("project_id") or ""))
                if isinstance(touched_project, dict) and touched_project:
                    session_project = {**session_project, **touched_project}
            session["project_id"] = str(session_project.get("project_id") or "")
            session["project_title"] = str(session_project.get("title") or "")
            session["project_root"] = str(session_project.get("root_path") or "")
            session["git_branch"] = str(session_project.get("git_branch") or "")
            if not str(session.get("cwd") or "").strip():
                session["cwd"] = str(session_project.get("root_path") or "")
            _update_active_chat_run(
                run_id,
                session_id=session_id,
                project_id=str(session_project.get("project_id") or ""),
            )
            focus_shift_requested = session_context_impl.infer_focus_shift(
                session,
                message=req.message,
                requested_attachment_ids=req.attachment_ids,
            )
            if focus_shift_requested:
                _emit_progress(
                    progress_cb,
                    "trace",
                    message=translate(locale, "chat.focus_shift"),
                    run_id=run_id,
                )
            with request_phase_timer.measure("session_ready_context_bundle_ms"):
                session_ready_context_meter, session_ready_compaction_status = _context_bundle_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                    estimate_mode="quick",
                )
            request_phase_timer.record_duration_ms(
                "context_quick_estimate_ms",
                int(session_ready_compaction_status.get("calculation_ms") or 0),
            )
            request_phase_timer.record_duration_ms(
                "context_snapshot_ms",
                int(session_ready_compaction_status.get("calculation_ms") or 0),
            )
            with request_phase_timer.measure("session_ready_snapshot_ms"):
                session_ready_snapshot = _build_run_snapshot(
                    goal=req.message,
                    current_task_focus=session_context_impl.get_current_task_focus(session),
                    turn_status="running",
                    cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                    context_meter=session_ready_context_meter,
                    compaction_status=session_ready_compaction_status,
                )
            _emit_progress(
                progress_cb,
                "stage",
                code="session_ready",
                phase="bootstrap",
                label="Session",
                status="completed",
                detail=translate(locale, "chat.session_ready", session_id=session.get("id")),
                run_id=run_id,
                session_id=session_id,
                thread_id=session_id,
                queue_wait_ms=queue_wait_ms,
                run_snapshot=session_ready_snapshot,
            )
            request_phase_timer.record_offset_ms("session_ready_ms")
            with request_phase_timer.measure("thread_started_emit_ms"):
                _emit_thread_started(progress_cb, session_id, session=session)
        with request_phase_timer.measure("history_snapshot_ms"):
            history_turns_before = copy.deepcopy(session.get("turns", []))
            summary_before = str(session.get("summary", "") or "")
        with request_phase_timer.measure("pre_turn_compaction_ms"):
            pre_compaction_probe = _build_compaction_status_for_session(
                session=session,
                model=requested_model,
                max_output_tokens=req.settings.max_output_tokens,
                pending_message=req.message,
                estimate_mode="quick",
            )
            pre_compaction_estimated = int(pre_compaction_probe.get("estimated_context_tokens") or 0)
            pre_compaction_recommendation = str(pre_compaction_probe.get("compact_recommendation") or "none")
            pre_compaction_reason = str(pre_compaction_probe.get("compact_reason") or "")
            pre_compaction_started_item = None
            if pre_compaction_recommendation in {"suggested", "required"}:
                pre_compaction_started_item = {
                    "id": f"{run_id}:context_compaction:pre_turn:{int(pre_compaction_probe.get('generation') or 0) + 1}",
                    "type": "contextCompaction",
                    "status": "inProgress",
                    "phase": "pre_turn",
                    "generation": int(pre_compaction_probe.get("generation") or 0) + 1,
                    "reason": pre_compaction_reason or "context_limit",
                    "before_tokens": pre_compaction_estimated,
                    "after_tokens": 0,
                    "summary": translate(locale, "chat.replacement_history_compacting"),
                }
                _emit_progress(
                    progress_cb,
                    "item/started",
                    thread_id=session_id,
                    turn_id=run_id,
                    item=pre_compaction_started_item,
                )
            llm_compactor = None
            if hasattr(provider_runtime, "compact_context"):
                llm_compactor = lambda payload: provider_runtime.compact_context(
                    payload,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                )
            context_compact_started = time.perf_counter()
            compaction_result = maybe_auto_compact_session(
                session=session,
                model=requested_model,
                max_output_tokens=req.settings.max_output_tokens,
                pending_message=req.message,
                phase="pre_turn",
                llm_compactor=llm_compactor,
                auto_compact_ratio=config.context_auto_compact_ratio,
                danger_compact_ratio=config.context_danger_compact_ratio,
                history_soft_limit_tokens=config.context_history_soft_limit_tokens,
                context_window_tokens=config.context_window_tokens,
                auto_compact_token_limit=config.context_auto_compact_token_limit,
            )
            request_phase_timer.record_duration_ms(
                "context_compact_ms",
                int((time.perf_counter() - context_compact_started) * 1000)
                if bool(compaction_result.get("compacted"))
                else 0,
            )
            compaction_probe_after = dict(compaction_result.get("status_before") or {})
            if str(compaction_probe_after.get("estimate_mode") or "") == "exact":
                request_phase_timer.record_duration_ms(
                    "context_exact_tokenize_ms",
                    int(compaction_probe_after.get("calculation_ms") or 0),
                )
        summarized = bool(compaction_result.get("compacted"))
        if summarized:
            compaction_after = dict(compaction_result.get("status_after") or {})
            compacted_context_meter, compacted_context_status = _context_bundle_for_session(
                session=session,
                model=requested_model,
                max_output_tokens=req.settings.max_output_tokens,
                pending_message=req.message,
                estimate_mode="exact",
            )
            request_phase_timer.record_duration_ms(
                "context_exact_tokenize_ms",
                int(compacted_context_status.get("calculation_ms") or 0),
            )
            _emit_progress(
                progress_cb,
                "trace",
                message=translate(
                    locale,
                    "chat.replacement_history_compacted",
                    generation=compaction_after.get("generation") or 0,
                    retained_turn_count=compaction_after.get("retained_turn_count") or 0,
                ),
                run_id=run_id,
                run_snapshot=_build_run_snapshot(
                    goal=req.message,
                    current_task_focus=session_context_impl.get_current_task_focus(session),
                    turn_status="running",
                    cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                    context_meter=compacted_context_meter,
                    compaction_status=compacted_context_status,
                ),
            )
            compaction_item = {
                "id": (
                    str(pre_compaction_started_item.get("id") or "")
                    if pre_compaction_started_item
                    else f"{run_id}:context_compaction:{compaction_after.get('generation') or 0}:{compaction_after.get('last_compacted_at') or ''}"
                ),
                "type": "contextCompaction",
                "status": "completed",
                "phase": str(compaction_after.get("last_compaction_phase") or compaction_after.get("phase") or "pre_turn"),
                "generation": int(compaction_after.get("generation") or 0),
                "reason": str(compaction_after.get("reason") or compaction_after.get("last_compaction_reason") or ""),
                "before_tokens": int(compaction_after.get("before_tokens") or 0),
                "after_tokens": int(compaction_after.get("after_tokens") or 0),
                "summary": translate(
                    locale,
                    "chat.replacement_history_compacted",
                    generation=compaction_after.get("generation") or 0,
                    retained_turn_count=compaction_after.get("retained_turn_count") or 0,
                ),
            }
            if not pre_compaction_started_item:
                _emit_progress(
                    progress_cb,
                    "item/started",
                    thread_id=session_id,
                    turn_id=run_id,
                    item={**compaction_item, "status": "inProgress"},
                )
            _emit_progress(
                progress_cb,
                "item/completed",
                thread_id=session_id,
                turn_id=run_id,
                item=compaction_item,
            )
        elif pre_compaction_started_item:
            _emit_progress(
                progress_cb,
                "item/completed",
                thread_id=session_id,
                turn_id=run_id,
                item={
                    **pre_compaction_started_item,
                    "status": "completed",
                    "summary": translate(locale, "chat.replacement_history_compaction_checked"),
                },
            )
        with request_phase_timer.measure("session_memory_sync_ms"):
            session_context_impl.sync_session_memory_state(session)

        with request_phase_timer.measure("attachment_context_ms"):
            attachment_context = session_context_impl.resolve_attachment_context(
                session,
                message=req.message,
                requested_attachment_ids=req.attachment_ids,
            )
        requested_attachment_ids = attachment_context["requested_attachment_ids"]
        clear_attachment_context = bool(attachment_context["clear_attachment_context"])
        attachment_context_mode = str(attachment_context["attachment_context_mode"] or "none")
        auto_linked_attachment_ids = list(attachment_context["auto_linked_attachment_ids"] or [])
        effective_attachment_ids = list(attachment_context["effective_attachment_ids"] or [])
        attachment_context_key = str(attachment_context["attachment_context_key"] or "")
        explicit_focus_reset = session_context_impl.message_explicitly_starts_new_task(req.message) or session_context_impl.message_clears_attachment_context(req.message)
        if explicit_focus_reset and not requested_attachment_ids:
            clear_attachment_context = True
            attachment_context_mode = "cleared"
            auto_linked_attachment_ids = []
            effective_attachment_ids = []
            attachment_context_key = ""

        with request_phase_timer.measure("attachment_load_ms"):
            attachments = upload_store.get_many(effective_attachment_ids)
        with request_phase_timer.measure("attachment_evidence_pack_ms"):
            attachment_evidence_pack = build_attachment_evidence_pack(
                attachments,
                locale=locale,
                preview_chars=_attachment_preview_chars_for_model(requested_model, req.settings.max_output_tokens),
            )
        task_state_notes: list[str] = []
        with request_phase_timer.measure("attachments_context_bundle_ms"):
            attachments_context_meter, attachments_compaction_status = (
                (compacted_context_meter, compacted_context_status)
                if summarized
                else (session_ready_context_meter, session_ready_compaction_status)
            )
        request_phase_timer.record_duration_ms("context_cache_ms", 0)
        with request_phase_timer.measure("attachments_ready_snapshot_ms"):
            attachments_ready_snapshot = _build_run_snapshot(
                goal=req.message,
                current_task_focus=session_context_impl.get_current_task_focus(session),
                turn_status="running",
                cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=attachments_context_meter,
                compaction_status=attachments_compaction_status,
            )
        _emit_progress(
            progress_cb,
            "stage",
            code="attachments_ready",
            phase="explore",
            label="Attachments",
            status="completed",
            detail=translate(
                locale,
                "chat.attachments_ready",
                attachment_context_mode=attachment_context_mode,
                requested_count=len(effective_attachment_ids),
                resolved_count=len(attachments),
            ),
            run_id=run_id,
            run_snapshot=attachments_ready_snapshot,
        )
        found_attachment_ids = {str(item.get("id")) for item in attachments if item.get("id")}
        missing_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id not in found_attachment_ids]
        resolved_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id in found_attachment_ids]
        with request_phase_timer.measure("attachment_context_apply_ms"):
            session_context_impl.apply_attachment_context_result(
                session,
                resolved_attachment_ids=resolved_attachment_ids,
                attachment_context_mode=attachment_context_mode,
                clear_attachment_context=clear_attachment_context,
                requested_attachment_ids=requested_attachment_ids,
            )
        resolved_attachment_context_key = attachment_context_key or ""
        if resolved_attachment_ids:
            resolved_attachment_context_key = "|".join(normalize_attachment_ids(resolved_attachment_ids))
        with request_phase_timer.measure("runtime_context_ms"):
            route_state_input, route_state_scope = session_context_impl.resolve_scoped_route_state(
                session,
                attachment_ids=resolved_attachment_ids,
            )
            route_state_input = session_context_impl.prepare_route_state_for_turn(
                route_state_input,
                reset_focus=focus_shift_requested,
            )
            route_state_scope = "focus_reset" if focus_shift_requested and route_state_scope == "session" else route_state_scope
            runtime_history_view = build_runtime_context_payload(session=session)
            thread_transcript_for_runtime = copy.deepcopy(session.get("thread_transcript") or {})
            history_turns_for_runtime = copy.deepcopy(runtime_history_view.get("history_turns") or [])
            summary_for_runtime = str(runtime_history_view.get("summary") or "")
            thread_memory_for_runtime = copy.deepcopy(session_context_impl.get_thread_memory(session))
            current_task_focus_for_runtime = copy.deepcopy(session_context_impl.get_current_task_focus(session))
            active_task_focus_for_runtime = copy.deepcopy(current_task_focus_for_runtime)
            recent_user_messages_for_runtime = list(
                session_context_impl.get_recent_user_messages(session, limit=8)
            )
            current_turn_context = copy.deepcopy(
                session_context_impl.derive_current_turn_context(
                    session,
                    message=req.message,
                    history_turns=history_turns_for_runtime,
                    recent_user_messages=recent_user_messages_for_runtime,
                )
            )
            recent_tasks_for_runtime = copy.deepcopy(list(thread_memory_for_runtime.get("recent_tasks") or []))
            artifact_memory_preview = copy.deepcopy(session_context_impl.get_artifact_memory_preview(session))
            with request_phase_timer.measure("runtime_context_compaction_status_ms"):
                compaction_status_for_runtime = dict(attachments_compaction_status)
            context_meter_for_runtime = build_context_meter_from_status(compaction_status_for_runtime)
            recalled_context = copy.deepcopy({
                "recalled_task": attachment_context.get("recalled_task") or {},
                "recalled_artifacts": attachment_context.get("recalled_artifacts") or [],
                "recalled_artifact_ids": attachment_context.get("recalled_attachment_ids") or [],
            })
        request_phase_timer.record_offset_ms("runtime_context_ready_ms")

        _emit_progress(
            progress_cb,
            "stage",
            code="agent_run_start",
            phase="execute",
            label="Agent Run",
            status="running",
            detail=translate(locale, "chat.agent_run_start"),
            run_id=run_id,
            session_id=session_id,
            thread_id=session_id,
            run_snapshot=_build_run_snapshot(
                goal=str(current_turn_context.get("goal") or req.message),
                current_task_focus=current_task_focus_for_runtime,
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=context_meter_for_runtime,
                compaction_status=compaction_status_for_runtime,
            ),
        )
        _emit_thread_status_changed(progress_cb, thread_id=session_id, status="active")
        _emit_turn_started(
            progress_cb,
            thread_id=session_id,
            turn_id=run_id,
            run_snapshot=_build_run_snapshot(
                goal=str(current_turn_context.get("goal") or req.message),
                current_task_focus=current_task_focus_for_runtime,
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=context_meter_for_runtime,
                compaction_status=compaction_status_for_runtime,
            ),
        )
        _emit_progress(
            progress_cb,
            "run_started",
            run_id=run_id,
            session_id=session_id,
            thread_id=session_id,
            turn_status="running",
            run_snapshot=_build_run_snapshot(
                goal=str(current_turn_context.get("goal") or req.message),
                current_task_focus=current_task_focus_for_runtime,
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=context_meter_for_runtime,
                compaction_status=compaction_status_for_runtime,
            ),
        )
        attachment_note = ""
        user_text = req.message.strip()
        if attachment_note:
            attachment_label = "Attachments" if locale == "en" else ("添付" if locale == "ja-JP" else "附件")
            user_text = f"{user_text}\n\n[{attachment_label}] {attachment_note}"
        user_turn = session_store.append_turn(
            session,
            role="user",
            text=user_text,
            attachments=[{"id": item.get("id"), "name": item.get("original_name")} for item in attachments],
        )
        user_turn_id = str(user_turn.get("id") or "")
        session_store.save(session)
        with request_phase_timer.measure("runtime_run_ms"):
            runtime_result = provider_runtime.run(
                message=req.message,
                settings=req.settings,
                context={
                    "session_id": session_id,
                    "run_id": run_id,
                    "cancel_event": cancel_event,
                    "drain_pending_steers": lambda final=False: _drain_active_chat_run_steers(
                        run_id,
                        final=bool(final),
                    ),
                    "user_input_response": dict(req.user_input_response or {}),
                    "phase_timing_base_ms": request_phase_timer.elapsed_ms(),
                    "project": {
                        "project_id": str(session_project.get("project_id") or ""),
                        "project_title": str(session_project.get("title") or ""),
                        "project_root": str(session_project.get("root_path") or ""),
                        "git_branch": str(session_project.get("git_branch") or ""),
                        "cwd": str(session.get("cwd") or session_project.get("root_path") or ""),
                        "is_worktree": bool(session_project.get("is_worktree")),
                    },
                    "thread_transcript": thread_transcript_for_runtime,
                    "summary": summary_for_runtime,
                    "thread_memory": thread_memory_for_runtime,
                    "current_turn": current_turn_context,
                    "recent_user_messages": recent_user_messages_for_runtime,
                    "active_task_focus": active_task_focus_for_runtime,
                    "current_task_focus": current_task_focus_for_runtime,
                    "work_cursor": copy.deepcopy(session.get("work_cursor") or {}),
                    "task_state": copy.deepcopy(session.get("task_state") or {}),
                    "recent_tasks": recent_tasks_for_runtime,
                    "artifact_memory_preview": artifact_memory_preview,
                    "compaction_status": compaction_status_for_runtime,
                    "attachment_evidence_pack": attachment_evidence_pack,
                    "recalled_context": recalled_context,
                    "history_turns": history_turns_for_runtime,
                    "route_state": route_state_input,
                    "attachments": [
                        {
                            "id": str(item.get("id") or ""),
                            "name": str(item.get("original_name") or item.get("name") or ""),
                            "mime": str(item.get("mime") or ""),
                            "kind": str(item.get("kind") or ""),
                            "path": str(item.get("path") or ""),
                        }
                        for item in attachments
                        if isinstance(item, dict)
                    ],
                },
                progress_cb=progress_cb,
            )
        text = str(runtime_result.get("text") or "")
        final_answer = str(runtime_result.get("final_answer") or "")
        model_draft = str(runtime_result.get("model_draft") or "")
        runtime_error = (
            dict(runtime_result.get("runtime_error") or {})
            if isinstance(runtime_result.get("runtime_error"), dict)
            else {}
        )
        tool_boundary_clean = runtime_result.get("tool_boundary_clean")
        tool_events = list(runtime_result.get("tool_events") or [])
        answer_bundle = runtime_result.get("answer_bundle") or {}
        token_usage = dict(runtime_result.get("token_usage") or {})
        effective_model = str(runtime_result.get("effective_model") or "")
        selected_model = effective_model or req.settings.model or provider_config.default_model
        permission_profile = normalize_permission_profile(
            runtime_result.get("permission_profile") or getattr(req.settings, "permission_profile", "auto")
        )
        turn_status = str(runtime_result.get("turn_status") or "completed")
        task_completion = (
            dict(runtime_result.get("task_completion") or {})
            if isinstance(runtime_result.get("task_completion"), dict)
            else {}
        )
        plan = list(runtime_result.get("plan") or [])
        pending_user_input = (
            dict(runtime_result.get("pending_user_input") or {})
            if isinstance(runtime_result.get("pending_user_input"), dict)
            else {}
        )
        pending_approval = (
            dict(runtime_result.get("pending_approval") or {})
            if isinstance(runtime_result.get("pending_approval"), dict)
            else {}
        )
        activity = dict(runtime_result.get("activity") or {})
        inspector = dict(runtime_result.get("inspector") or {})
        runtime_phase_timings = dict(((inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}).get("phase_timings") or {})
        combined_phase_timings = _merge_phase_timings(
            request_phase_timer.snapshot(total_key="total_ms"),
            runtime_phase_timings,
        )
        answer_stream = dict(runtime_result.get("answer_stream") or {})
        route_state = (
            runtime_result.get("route_state")
            if isinstance(runtime_result.get("route_state"), dict)
            else dict(route_state_input or {})
        )
        activity = {
            **activity,
            "triggering_user_message": user_text,
            "triggering_user_turn_id": user_turn_id,
            "session_id": session_id,
            "thread_id": session_id,
            "model_draft": model_draft,
            "final_answer": final_answer,
            "runtime_error": runtime_error,
            "task_completion": dict(task_completion),
            "tool_boundary_clean": tool_boundary_clean if isinstance(tool_boundary_clean, bool) else None,
        }
        activity = _activity_with_end_to_end_duration(activity, combined_phase_timings)
        agent_run_done_context_meter, agent_run_done_compaction_status = attachments_context_meter, attachments_compaction_status

        _emit_progress(
            progress_cb,
            "stage",
            code="agent_run_done",
            phase="report",
            label="Agent Run",
            status="completed",
            detail=translate(locale, "chat.agent_run_done"),
            run_id=run_id,
            run_snapshot=_build_run_snapshot(
                goal=str(((inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}).get("goal") or req.message),
                current_task_focus=(
                    ((inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}).get("current_task_focus")
                    or ((inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}).get("task_checkpoint")
                ),
                turn_status=turn_status,
                cwd=str((((inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}).get("cwd")) or session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                pending_approval=pending_approval,
                tool_count=len(tool_events),
                evidence_status=str(((inspector.get("evidence") or {}) if isinstance(inspector.get("evidence"), dict) else {}).get("status") or "not_needed"),
                context_meter=agent_run_done_context_meter,
                compaction_status=agent_run_done_compaction_status,
                model_draft=model_draft,
                final_answer=final_answer,
                runtime_error=runtime_error,
            ),
        )
        inspector_notes = [*list(inspector.get("notes") or []), *task_state_notes]
        if attachment_evidence_pack:
            inspector_notes.append(f"attachment_evidence_pack:{len(attachment_evidence_pack)}")
        if missing_attachment_ids:
            warning_msg = translate(locale, "chat.missing_attachments_warning", missing_count=len(missing_attachment_ids))
            inspector_notes.append(warning_msg)
            _emit_progress(progress_cb, "trace", message=warning_msg, run_id=run_id)

        auto_linked_attachment_names = [
            str(item.get("original_name") or "")
            for item in attachments
            if str(item.get("id") or "") in set(auto_linked_attachment_ids)
        ]
        if auto_linked_attachment_names:
            auto_link_msg = translate(
                locale,
                "chat.auto_linked_attachments",
                attachment_names=", ".join(auto_linked_attachment_names[:6]),
            )
            inspector_notes.append(auto_link_msg)
            _emit_progress(progress_cb, "trace", message=auto_link_msg, run_id=run_id)
        elif attachment_context_mode == "cleared" and not requested_attachment_ids:
            cleared_msg = translate(locale, "chat.cleared_attachment_context")
            inspector_notes.append(cleared_msg)
            _emit_progress(progress_cb, "trace", message=cleared_msg, run_id=run_id)
        inspector["notes"] = inspector_notes

        if not bool(answer_stream.get("streamed")):
            _emit_agent_message_events(
                progress_cb,
                thread_id=session_id,
                turn_id=run_id,
                text=text,
            )

        session_store.append_thread_items(
            session,
            [dict(item) for item in list(runtime_result.get("transcript_delta") or []) if isinstance(item, dict)],
        )
        intermediate_turns = [
            dict(item)
            for item in list(runtime_result.get("intermediate_turns") or [])
            if isinstance(item, dict)
            and str(item.get("role") or "") in {"user", "assistant"}
            and str(item.get("text") or "").strip()
        ]
        if not intermediate_turns:
            intermediate_turns = [
                {
                    "role": "user",
                    "text": str(steer.get("message") or "").strip(),
                    "activity": {
                        "status": "steer_accepted",
                        "run_id": run_id,
                        "steer_id": str(steer.get("id") or ""),
                        "queued_at": float(steer.get("queued_at") or 0.0),
                        "accepted_at": float(steer.get("accepted_at") or 0.0),
                    },
                }
                for steer in list(runtime_result.get("steered_user_messages") or [])
                if isinstance(steer, dict) and str(steer.get("message") or "").strip()
            ]
        for item in intermediate_turns:
            session_store.append_turn(
                session,
                role=str(item.get("role") or "user"),
                text=str(item.get("text") or "").strip(),
                activity=dict(item.get("activity") or {}),
                record_transcript=False,
            )
        assistant_turn = session_store.append_turn(session, role="assistant", text=text, answer_bundle=answer_bundle, activity=activity)
        assistant_turn_id = str(assistant_turn.get("id") or "")
        inspector_run_state = (inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}
        inspector_evidence = (inspector.get("evidence") or {}) if isinstance(inspector.get("evidence"), dict) else {}
        inspector_available_skills = list(
            inspector.get("available_skills")
            or inspector.get("loaded_skills")
            or []
        )
        current_task_focus = dict(
            inspector_run_state.get("current_task_focus")
            or inspector_run_state.get("task_checkpoint")
            or ((route_state or {}).get("current_task_focus") if isinstance(route_state, dict) else {})
            or ((route_state or {}).get("task_checkpoint") if isinstance(route_state, dict) else {})
            or {}
        )
        previous_agent_state = dict(session.get("agent_state") or {})
        previous_task_state = session_context_impl.normalize_task_state(copy.deepcopy(session.get("task_state") or {}))
        last_compacted_at = _session_last_compacted_at(session) or str(previous_agent_state.get("last_compacted_at") or "")
        tool_hits = [
            {
                "name": str(item.get("name") or ""),
                "group": str(item.get("group") or ""),
                "status": str(item.get("status") or ""),
            }
            for item in tool_events
            if isinstance(item, dict)
        ]
        normalized_focus = session_context_impl.normalize_current_task_focus(current_task_focus)
        session["work_cursor"] = session_context_impl.normalize_work_cursor(
            {
                "project_root": normalized_focus.get("project_root") or session.get("project_root") or "",
                "cwd": normalized_focus.get("cwd") or (((inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}).get("cwd")) or session.get("cwd") or "",
                "active_files": normalized_focus.get("active_files") or [],
                "active_attachments": normalized_focus.get("active_attachments") or [],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        inspector_session_state = (
            dict(inspector.get("session") or {})
            if isinstance(inspector.get("session"), dict)
            else {}
        )
        runtime_task_state_delta: dict[str, Any] | None = None
        if isinstance(runtime_result.get("task_state_delta"), dict):
            runtime_task_state_delta = dict(runtime_result.get("task_state_delta") or {})
        elif isinstance(inspector_run_state.get("task_state_delta"), dict):
            runtime_task_state_delta = dict(inspector_run_state.get("task_state_delta") or {})
        elif isinstance(inspector_session_state.get("task_state_delta"), dict):
            runtime_task_state_delta = dict(inspector_session_state.get("task_state_delta") or {})
        fallback_error_for_task = runtime_error
        if not fallback_error_for_task:
            fallback_blocked_reason = str(runtime_result.get("blocked_reason") or inspector_run_state.get("blocked_reason") or "").strip()
            fallback_error_for_task = {"message": fallback_blocked_reason} if fallback_blocked_reason else {}
        plan_from_runtime = list(inspector_run_state.get("plan") or plan or [])
        thread_memory_before_task_merge = session_context_impl.get_thread_memory(session)

        def _tool_event_name(event: dict[str, Any]) -> str:
            return str(event.get("name") or event.get("tool") or "").strip().lower()

        def _tool_event_status(event: dict[str, Any]) -> str:
            return str(event.get("status") or "").strip().lower()

        def _successful_update_plan_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                dict(item)
                for item in list(events or [])
                if isinstance(item, dict)
                and _tool_event_name(item) == "update_plan"
                and _tool_event_status(item) in {"ok", "success", "completed", "complete", "done"}
            ]

        def _latest_recent_task_goal(thread_memory: dict[str, Any]) -> str:
            recent_tasks = list(thread_memory.get("recent_tasks") or [])
            for item in recent_tasks:
                if not isinstance(item, dict):
                    continue
                goal = str(item.get("goal") or "").strip()
                if goal:
                    return goal
            return ""

        def _first_plan_step(plan_items: list[dict[str, Any]]) -> str:
            for item in list(plan_items or []):
                if not isinstance(item, dict):
                    continue
                step = str(item.get("step") or item.get("title") or item.get("content") or "").strip()
                if step:
                    return step
            return ""

        def _update_plan_goal(events: list[dict[str, Any]]) -> str:
            for item in reversed(list(events or [])):
                for payload_key in ("result_preview", "input", "normalized_arguments", "raw_arguments"):
                    payload = dict(item.get(payload_key) or {}) if isinstance(item.get(payload_key), dict) else {}
                    explanation = str(payload.get("explanation") or payload.get("goal") or "").strip()
                    if explanation:
                        return explanation
            return ""

        update_plan_success_events = _successful_update_plan_events(tool_events)
        has_successful_update_plan = bool(update_plan_success_events)
        has_previous_task = session_context_impl.task_state_has_checkpoint(previous_task_state)
        has_delta = isinstance(runtime_task_state_delta, dict) and bool(runtime_task_state_delta)
        is_continue_like = session_context_impl.message_likely_continues_task(req.message, session=session)
        should_create_new_task_state = has_successful_update_plan and not has_previous_task
        should_update_existing_task_state = has_previous_task and has_successful_update_plan
        should_track_task = should_create_new_task_state or should_update_existing_task_state

        previous_goal = str(previous_task_state.get("goal") or "").strip()
        focus_goal = str(normalized_focus.get("goal") or "").strip()
        current_turn_goal = str(current_turn_context.get("goal") or "").strip()
        current_turn_source = str(current_turn_context.get("source") or "").strip()
        inspector_goal = str(inspector_run_state.get("goal") or inspector_run_state.get("current_goal") or "").strip()
        update_plan_goal = _update_plan_goal(update_plan_success_events)
        recent_task_goal = _latest_recent_task_goal(thread_memory_before_task_merge)
        first_plan_step = _first_plan_step(plan_from_runtime)

        derived_task_goal = ""
        if is_continue_like and previous_goal:
            derived_task_goal = previous_goal
        elif update_plan_goal:
            derived_task_goal = update_plan_goal
        elif current_turn_source != "latest_user_message" and current_turn_goal:
            derived_task_goal = current_turn_goal
        elif has_successful_update_plan and inspector_goal and inspector_goal != str(req.message or "").strip():
            derived_task_goal = inspector_goal
        elif previous_goal:
            derived_task_goal = previous_goal
        elif focus_goal:
            derived_task_goal = focus_goal
        elif recent_task_goal:
            derived_task_goal = recent_task_goal
        elif has_successful_update_plan and first_plan_step:
            derived_task_goal = first_plan_step

        if has_delta and not (has_previous_task or has_successful_update_plan):
            runtime_task_state_delta = {}
            has_delta = False
            task_state_notes.append("ignored_task_state_delta_without_task_mode")
        elif has_delta and not has_successful_update_plan:
            task_state_notes.append("ignored_task_state_delta_without_update_plan")

        task_state_validation = {}
        if should_track_task:
            base_task_id = str(previous_task_state.get("task_id") or normalized_focus.get("task_id") or "").strip()
            if not base_task_id:
                base_task_id = str(uuid.uuid4())
            task_state_base = {
                **dict(previous_task_state or {}),
                "task_id": base_task_id,
                "goal": derived_task_goal,
                "plan_items": list(previous_task_state.get("plan_items") or []),
            }
            if has_successful_update_plan:
                next_task_state = session_context_impl.merge_task_state_after_turn(
                    task_state_base,
                    plan_from_runtime,
                    tool_events,
                    list(runtime_result.get("progress_signals") or inspector_run_state.get("progress_signals") or []),
                    turn_status,
                    fallback_error_for_task,
                    pending_user_input,
                )
            else:
                next_task_state = session_context_impl.normalize_task_state(task_state_base)
            if not next_task_state.get("task_id"):
                next_task_state["task_id"] = base_task_id or str(uuid.uuid4())
            if not next_task_state.get("goal") and derived_task_goal:
                next_task_state["goal"] = derived_task_goal
            session["task_state"] = session_context_impl.normalize_task_state(next_task_state)
        else:
            session["task_state"] = session_context_impl.normalize_task_state(previous_task_state if has_previous_task else {})
        session["agent_state"] = {
            "agent_id": "vintage_programmer",
            "permission_profile": permission_profile,
            "turn_status": str(inspector_run_state.get("turn_status") or turn_status),
            "task_completion": dict(
                inspector_run_state.get("task_completion")
                if isinstance(inspector_run_state.get("task_completion"), dict)
                else task_completion
            ),
            "pending_user_input": dict(inspector_run_state.get("pending_user_input") or pending_user_input),
            "pending_approval": dict(inspector_run_state.get("pending_approval") or pending_approval),
            "phase": str(inspector_run_state.get("phase") or "report"),
            "last_run_id": run_id,
            "last_provider": requested_provider,
            "last_model": selected_model,
            "final_answer_preview": (final_answer or text).strip()[:240],
            "runtime_error": dict(runtime_error),
            "last_compacted_at": last_compacted_at,
            "tool_count": len(tool_hits),
            "evidence_status": str(inspector_evidence.get("status") or "not_needed"),
            "enabled_skill_keys": [
                str(item.get("key") or "")
                for item in inspector_available_skills
                if isinstance(item, dict) and str(item.get("key") or "").strip()
            ],
            "enabled_skill_ids": [
                str(item.get("name") or item.get("id") or "")
                for item in inspector_available_skills
                if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
            ],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        session_context_impl.record_turn_memory(
            session,
            user_message=req.message,
            assistant_text=final_answer or text,
            attachments=attachments,
            route_state=route_state,
            tool_events=tool_events,
            answer_bundle=answer_bundle,
            touch_task_checkpoint=should_track_task,
        )
        session["cwd"] = str((session.get("work_cursor") or {}).get("cwd") or session.get("project_root") or "")
        thread_memory = session_context_impl.get_thread_memory(session)
        recent_tasks = list(thread_memory.get("recent_tasks") or [])
        artifact_memory_preview = session_context_impl.get_artifact_memory_preview(session)
        current_task_focus = session_context_impl.get_current_task_focus(session)
        active_context_usage = (
            dict(runtime_result.get("active_context_usage") or {})
            if isinstance(runtime_result.get("active_context_usage"), dict)
            else {}
        )
        if active_context_usage:
            record_context_usage_observation(
                session,
                model=selected_model,
                input_tokens=int(active_context_usage.get("input_tokens") or 0),
                output_tokens=int(active_context_usage.get("output_tokens") or 0),
                estimated_input_tokens=int(active_context_usage.get("estimated_input_tokens") or 0),
                estimated_static_tokens=int(active_context_usage.get("estimated_static_tokens") or 0),
            )
        context_meter, compaction_status = _context_bundle_for_session(
            session=session,
            model=selected_model,
            max_output_tokens=req.settings.max_output_tokens,
            last_compacted_at=last_compacted_at,
            estimate_mode="quick",
        )
        runtime_compaction_status = (
            dict(inspector_run_state.get("compaction_status") or {})
            if isinstance(inspector_run_state.get("compaction_status"), dict)
            else {}
        )
        for key, value in runtime_compaction_status.items():
            if value in (None, "", [], {}):
                continue
            compaction_status[key] = value
        session["agent_state"]["last_compacted_at"] = str(compaction_status.get("last_compacted_at") or last_compacted_at or "")
        session["agent_state"]["context_meter"] = dict(context_meter)
        session["agent_state"]["compaction_status"] = dict(compaction_status)
        response_task_state_delta = (
            session_context_impl.normalize_task_state_delta(runtime_task_state_delta)
            if isinstance(runtime_task_state_delta, dict) and runtime_task_state_delta
            else None
        )
        response_task_state_validation = (
            dict(task_state_validation)
            if isinstance(task_state_validation, dict) and task_state_validation
            else None
        )
        inspector_run_state["thread_memory"] = dict(thread_memory)
        inspector_run_state["recent_tasks"] = recent_tasks
        inspector_run_state["artifact_memory_preview"] = artifact_memory_preview
        inspector_run_state["current_turn"] = dict(current_turn_context)
        inspector_run_state["active_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(active_task_focus_for_runtime)
        inspector_run_state["recent_user_messages"] = list(recent_user_messages_for_runtime)
        inspector_run_state["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_run_state["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_run_state["task_state"] = dict(session.get("task_state") or {})
        inspector_run_state["pending_approval"] = dict(inspector_run_state.get("pending_approval") or pending_approval)
        if response_task_state_delta:
            inspector_run_state["task_state_delta"] = dict(response_task_state_delta)
        else:
            inspector_run_state.pop("task_state_delta", None)
        if response_task_state_validation:
            inspector_run_state["task_state_validation"] = dict(response_task_state_validation)
        else:
            inspector_run_state.pop("task_state_validation", None)
        inspector_run_state["context_meter"] = dict(context_meter)
        inspector_run_state["compaction_status"] = dict(compaction_status)
        inspector_run_state["context_version"] = int(session.get("thread_schema_version") or 1)
        inspector_run_state["phase_timings"] = dict(combined_phase_timings)
        inspector_run_state["model_draft"] = model_draft
        inspector_run_state["final_answer"] = final_answer
        inspector_run_state["runtime_error"] = dict(runtime_error)
        inspector["run_state"] = inspector_run_state
        inspector_session = (inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}
        inspector_session["current_turn"] = dict(current_turn_context)
        inspector_session["active_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(active_task_focus_for_runtime)
        inspector_session["recent_user_messages"] = list(recent_user_messages_for_runtime)
        inspector_session["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["task_state"] = dict(session.get("task_state") or {})
        inspector_session["task_completion"] = dict(task_completion)
        if response_task_state_delta:
            inspector_session["task_state_delta"] = dict(response_task_state_delta)
        else:
            inspector_session.pop("task_state_delta", None)
        if response_task_state_validation:
            inspector_session["task_state_validation"] = dict(response_task_state_validation)
        else:
            inspector_session.pop("task_state_validation", None)
        inspector_session["thread_memory"] = dict(thread_memory)
        inspector_session["recent_tasks"] = recent_tasks
        inspector_session["artifact_memory_preview"] = artifact_memory_preview
        inspector_session["context_meter"] = dict(context_meter)
        inspector_session["compaction_status"] = dict(compaction_status)
        inspector_session["thread_transcript"] = {
            "schema_version": int(session.get("thread_schema_version") or 1),
            "item_count": len(list((session.get("thread_transcript") or {}).get("items") or [])),
        }
        inspector_session["phase_timings"] = dict(combined_phase_timings)
        inspector["session"] = inspector_session
        session_context_impl.store_scoped_route_state(
            session,
            attachment_ids=resolved_attachment_ids,
            route_state=route_state,
        )
        if assistant_turn_id:
            turn_artifact_extra = {
                "route_state": route_state,
                "token_usage": token_usage,
                "effective_model": selected_model,
                "permission_profile": permission_profile,
                "turn_status": turn_status,
                "task_completion": dict(task_completion),
                "work_cursor": dict(session.get("work_cursor") or {}),
                "task_state": dict(session.get("task_state") or {}),
            }
            if response_task_state_delta:
                turn_artifact_extra["task_state_delta"] = dict(response_task_state_delta)
            if response_task_state_validation:
                turn_artifact_extra["task_state_validation"] = dict(response_task_state_validation)
            session_store.persist_turn_artifact(
                session,
                turn_id=assistant_turn_id,
                run_id=run_id,
                activity=activity,
                answer_bundle=answer_bundle,
                tool_events=tool_events,
                inspector=inspector,
                extra=turn_artifact_extra,
            )
        session_store.save(session)
        _emit_progress(
            progress_cb,
            "stage",
            code="session_saved",
            phase="report",
            label="Session",
            status="completed",
            detail=translate(locale, "chat.session_saved"),
            run_id=run_id,
            session_id=session_id,
            thread_id=session_id,
            run_snapshot=_build_run_snapshot(
                goal=str(inspector_run_state.get("goal") or req.message),
                turn_id=assistant_turn_id,
                current_task_focus=current_task_focus,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                pending_approval=pending_approval,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
                work_cursor=dict(session.get("work_cursor") or {}),
                task_state=dict(session.get("task_state") or {}),
                task_state_delta=response_task_state_delta,
                task_state_validation=response_task_state_validation,
                model_draft=model_draft,
                final_answer=final_answer,
                runtime_error=runtime_error,
            ),
        )
        updated_thread = _thread_list_item_for_session_id(session["id"])
        if updated_thread is not None:
            _emit_progress(progress_cb, "thread/updated", thread=dump_model(updated_thread))

        pricing_meta = estimate_usage_cost(
            model=selected_model,
            input_tokens=token_usage.get("input_tokens", 0),
            output_tokens=token_usage.get("output_tokens", 0),
        )
        token_usage = {**token_usage, **pricing_meta}
        inspector_notes = list(inspector.get("notes") or [])
        if pricing_meta.get("pricing_known"):
            pricing_note = translate(
                locale,
                "chat.token_usage_priced",
                cost_usd=float(pricing_meta.get("estimated_cost_usd") or 0.0),
                input_tokens=int(token_usage.get("input_tokens", 0) or 0),
                output_tokens=int(token_usage.get("output_tokens", 0) or 0),
            )
            inspector_notes.append(pricing_note)
            _emit_progress(progress_cb, "trace", message=pricing_note, run_id=run_id)
        else:
            pricing_note = translate(locale, "chat.token_usage_unpriced", selected_model=selected_model)
            inspector_notes.append(pricing_note)
            _emit_progress(progress_cb, "trace", message=pricing_note, run_id=run_id)
        inspector["notes"] = inspector_notes
        inspector["token_usage"] = dict(token_usage)

        stats_snapshot = token_stats_store.add_usage(
            session_id=session["id"],
            usage=token_usage,
            model=selected_model,
        )
        session_totals_raw = stats_snapshot.get("sessions", {}).get(session["id"], {})
        global_totals_raw = stats_snapshot.get("totals", {})
        _emit_progress(
            progress_cb,
            "thread/tokenUsage/updated",
            thread_id=str(session["id"]),
            token_usage=dict(token_usage),
            session_token_totals=dict(session_totals_raw),
            global_token_totals=dict(global_totals_raw),
            context_meter=dict(context_meter),
        )
        _emit_progress(
            progress_cb,
            "stage",
            code="stats_saved",
            phase="report",
            label="Usage",
            status="completed",
            detail=translate(locale, "chat.token_stats_updated"),
            run_id=run_id,
        )
        inspector["notes"] = inspector_notes
        tool_event_models = [
            item if isinstance(item, ToolEvent) else ToolEvent(**item)
            for item in tool_events
        ]
        response = ChatResponse(
            session_id=session["id"],
            thread_id=session["id"],
            turn_id=assistant_turn_id,
            run_id=run_id,
            agent_id="vintage_programmer",
            agent_title=str((inspector.get("agent") or {}).get("title") or "Vintage Programmer"),
            selected_business_module="llm_router_core",
            effective_model=selected_model,
            queue_wait_ms=queue_wait_ms,
            text=text,
            final_answer=final_answer,
            model_draft=model_draft,
            runtime_error=runtime_error,
            tool_boundary_clean=tool_boundary_clean if isinstance(tool_boundary_clean, bool) else None,
            tool_events=tool_event_models,
            attachment_context_mode=attachment_context_mode,
            effective_attachment_ids=resolved_attachment_ids,
            auto_linked_attachment_ids=[item for item in auto_linked_attachment_ids if item in found_attachment_ids],
            auto_linked_attachment_names=auto_linked_attachment_names,
            missing_attachment_ids=missing_attachment_ids,
            attachment_context_key=resolved_attachment_context_key,
            permission_profile=permission_profile,
            turn_status=turn_status,
            task_completion=task_completion,
            plan=plan,
            pending_user_input=pending_user_input,
            pending_approval=pending_approval,
            current_task_focus=session_context_impl.compat_task_checkpoint_from_focus(current_task_focus),
            work_cursor=dict(session.get("work_cursor") or {}),
            task_state=dict(session.get("task_state") or {}),
            task_state_delta=response_task_state_delta,
            task_state_validation=response_task_state_validation,
            recent_tasks=recent_tasks,
            activity=activity,
            context_meter=context_meter,
            compaction_status=compaction_status,
            token_usage=TokenUsage(**token_usage),
            session_token_totals=TokenTotals(**session_totals_raw),
            global_token_totals=TokenTotals(**global_totals_raw),
            inspector=inspector,
            turn_count=len(session.get("turns", [])),
            summarized=summarized,
        )
        _emit_progress(
            progress_cb,
            "stage",
            code="ready",
            phase="report",
            label="Ready",
            status="completed",
            detail=translate(locale, "chat.result_ready"),
            run_id=run_id,
            session_id=session_id,
            thread_id=session_id,
            run_snapshot=_build_run_snapshot(
                goal=str(inspector_run_state.get("goal") or req.message),
                current_task_focus=current_task_focus,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                pending_approval=pending_approval,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
                work_cursor=dict(session.get("work_cursor") or {}),
                task_state=dict(session.get("task_state") or {}),
                task_state_delta=response_task_state_delta,
                task_state_validation=response_task_state_validation,
                model_draft=model_draft,
                final_answer=final_answer,
                runtime_error=runtime_error,
            ),
        )
        _emit_progress(
            progress_cb,
            "turn/completed",
            turn={
                "id": str(run_id or ""),
                "threadId": str(session_id or ""),
                "status": str(turn_status or "completed"),
                "items": [],
                "tokenUsage": dict(token_usage),
            },
            run_snapshot=_build_run_snapshot(
                goal=str(inspector_run_state.get("goal") or req.message),
                current_task_focus=current_task_focus,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                pending_approval=pending_approval,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
                work_cursor=dict(session.get("work_cursor") or {}),
                task_state=dict(session.get("task_state") or {}),
                task_state_delta=response_task_state_delta,
                task_state_validation=response_task_state_validation,
                model_draft=model_draft,
                final_answer=final_answer,
                runtime_error=runtime_error,
            ),
        )
        _emit_progress(
            progress_cb,
            "run_finished",
            run_id=run_id,
            session_id=session_id,
            thread_id=session_id,
            turn_status=turn_status,
            duration_ms=int(activity.get("run_duration_ms") or 0),
            run_snapshot=_build_run_snapshot(
                goal=str(inspector_run_state.get("goal") or req.message),
                current_task_focus=current_task_focus,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                pending_approval=pending_approval,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
                model_draft=model_draft,
                final_answer=final_answer,
                runtime_error=runtime_error,
            ),
        )
        _emit_thread_status_changed(progress_cb, thread_id=session_id, status="idle")
        return response
    finally:
        _unregister_active_chat_run(run_id)


def _sse_pack(event: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {raw}\n\n"


@app.post("/api/chat/runs/{run_id}/cancel")
def cancel_chat_run(run_id: str) -> dict[str, Any]:
    record = _cancel_active_chat_run(run_id)
    if not isinstance(record, dict):
        return {
            "ok": False,
            "run_id": str(run_id or ""),
            "cancelled": False,
            "status": "not_found",
        }
    return {
        "ok": True,
        "run_id": str(record.get("run_id") or run_id or ""),
        "cancelled": True,
        "status": "cancelling",
        "session_id": str(record.get("session_id") or ""),
        "project_id": str(record.get("project_id") or ""),
    }


@app.post("/api/chat/runs/{run_id}/steer")
def steer_chat_run(run_id: str, req: ChatSteerRequest) -> dict[str, Any]:
    queued = _enqueue_active_chat_run_steer(
        run_id,
        req.message,
        client_steer_id=str(req.client_steer_id or ""),
    )
    if not isinstance(queued, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "kind": "turn_not_accepting_guidance",
                "summary": "The active turn is no longer accepting queued guidance.",
                "run_id": str(run_id or ""),
            },
        )
    return {"ok": True, **queued}


@app.get("/api/evals/catalog")
def list_eval_catalog() -> dict[str, Any]:
    manager = _get_eval_job_manager()
    return {"suites": manager.catalog()}


@app.get("/api/evals/runs")
def list_eval_runs(limit: int = 20) -> dict[str, Any]:
    manager = _get_eval_job_manager()
    return {"runs": manager.list(limit=limit)}


@app.get("/api/evals/runs/{job_id}")
def get_eval_run(job_id: str) -> dict[str, Any]:
    job = _get_eval_job_manager().get(job_id)
    if not isinstance(job, dict):
        raise HTTPException(status_code=404, detail={"kind": "eval_run_not_found", "summary": "Eval run was not found."})
    return job


@app.post("/api/evals/runs")
def start_eval_run(req: EvalRunRequest) -> dict[str, Any]:
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    try:
        return _get_eval_job_manager().submit(dict(payload or {}))
    except EvalJobError as exc:
        raise HTTPException(
            status_code=400,
            detail={"kind": "eval_run_invalid", "summary": str(exc)},
        ) from exc


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    locale = normalize_locale(getattr(req.settings, "locale", ""), config.default_locale)
    def event_stream():
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        done_event = threading.Event()
        stream_state: dict[str, Any] = {
            "thread_id": "",
            "turn_id": "",
        }

        def put_event(event_name: str, payload: dict[str, Any]) -> None:
            events.put({"event": event_name, "payload": payload})

        def emit(payload: dict[str, Any]) -> None:
            event_name = str(payload.get("event") or "message")
            data = {k: v for k, v in payload.items() if k != "event"}
            if str(data.get("thread_id") or "").strip():
                stream_state["thread_id"] = str(data.get("thread_id") or "").strip()
            elif str(data.get("session_id") or "").strip():
                stream_state["thread_id"] = str(data.get("session_id") or "").strip()
            if str(data.get("run_id") or "").strip():
                stream_state["turn_id"] = str(data.get("run_id") or "").strip()
            if event_name.startswith(("thread/", "turn/", "item/")) or event_name in {"warning", "error", "trace_event", "run_started", "run_finished", "run_failed"}:
                put_event(event_name, data)
                return

            put_event(event_name, data)
            if event_name == "plan_update":
                put_event(
                    "turn/plan/updated",
                    {
                        "thread_id": str(stream_state.get("thread_id") or ""),
                        "turn_id": str(stream_state.get("turn_id") or ""),
                        "plan": list(data.get("plan") or []),
                        "explanation": str(data.get("explanation") or ""),
                        "run_snapshot": dict(data.get("run_snapshot") or {}),
                    },
                )

        def worker() -> None:
            try:
                response = _process_chat_request(req, progress_cb=emit)
                put_event("final", {"response": dump_model(response)})
            except HTTPException as exc:
                payload = _normalize_chat_error_payload(exc.detail, status_code=exc.status_code, locale=locale)
                put_event(
                    "run_failed",
                    {
                        "run_id": str(stream_state.get("turn_id") or ""),
                        "thread_id": str(stream_state.get("thread_id") or ""),
                        "turn_status": "failed",
                        "error": dict(payload),
                    },
                )
                put_event(
                    "error",
                    {
                        **payload,
                    }
                )
            except Exception as exc:
                payload = _normalize_chat_error_payload(exc, locale=locale)
                put_event(
                    "run_failed",
                    {
                        "run_id": str(stream_state.get("turn_id") or ""),
                        "thread_id": str(stream_state.get("thread_id") or ""),
                        "turn_status": "failed",
                        "error": dict(payload),
                    },
                )
                put_event("error", payload)
            finally:
                done_event.set()
                put_event("done", {"ok": True})

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                item = events.get(timeout=10.0)
            except queue.Empty:
                yield _sse_pack("heartbeat", {"ts": int(time.time())})
                if done_event.is_set():
                    break
                continue
            event_name = str(item.get("event") or "message")
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            yield _sse_pack(event_name, payload)
            if event_name == "done":
                break

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)
