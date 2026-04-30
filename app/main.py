from __future__ import annotations

import ast
import copy
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
from app.chat_product_runtime import ChatProductRuntime
from app.config import AppConfig, build_provider_config, list_provider_profiles, load_config, normalize_llm_provider_name
from app.context_meter import (
    build_compaction_status,
    build_context_meter,
    build_runtime_context_payload,
    ensure_compaction_state,
    maybe_auto_compact_session,
)
from app.evolution import EvolutionStore
from app.i18n import normalize_locale, supported_locales, translate
from app.models import (
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    ClearStatsResponse,
    DeleteThreadResponse,
    DeleteSessionResponse,
    HealthResponse,
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
from app.pricing import estimate_usage_cost
from app import session_context as session_context_impl
from app.session_context import normalize_attachment_ids
from app.storage import ProjectStore, SessionStore, ShadowLogStore, TokenStatsStore, UploadStore
from app.vintage_programmer_runtime import VintageProgrammerRuntime
from app.workbench import WorkbenchStore

APP_TITLE = "Vintage Programmer"
DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS = 128_000
config = load_config()
AGENT_DIR = Path(__file__).resolve().parent.parent / "agents" / "vintage_programmer"
project_store = ProjectStore(config.projects_registry_path, default_root=config.workspace_root)
session_store = SessionStore(config.sessions_dir)
upload_store = UploadStore(config.uploads_dir)
token_stats_store = TokenStatsStore(config.token_stats_path)
shadow_log_store = ShadowLogStore(config.shadow_logs_dir)
evolution_store = EvolutionStore(config.overlay_profile_path, config.evolution_logs_dir)
chat_product_runtime = ChatProductRuntime(config)
vintage_programmer_runtime = VintageProgrammerRuntime(
    config=config,
    agent_dir=AGENT_DIR,
)
workbench_store = WorkbenchStore(
    config=config,
    agent_dir=AGENT_DIR,
)
APP_VERSION = "2.6.0"
default_project = project_store.ensure_default_project()
session_store.migrate_missing_project(default_project)
_provider_runtime_lock = threading.Lock()
_provider_runtime_cache: dict[str, VintageProgrammerRuntime] = {}
_active_chat_runs_lock = threading.Lock()
_active_chat_runs: dict[str, dict[str, Any]] = {}


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
    OpenClaw-style lane queue:
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
        session_lock.acquire()
        self._global_sem.acquire()
        wait_ms = int((time.monotonic() - started) * 1000)
        return _AgentRunQueueTicket(self._global_sem, session_lock, wait_ms)


class _AgentRunQueueTicket:
    def __init__(
        self,
        global_sem: threading.BoundedSemaphore,
        session_lock: threading.Lock,
        wait_ms: int,
    ) -> None:
        self._global_sem = global_sem
        self._session_lock = session_lock
        self.wait_ms = max(0, int(wait_ms))
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


def get_evolution_store() -> EvolutionStore:
    return evolution_store


def get_chat_product_runtime() -> ChatProductRuntime:
    return chat_product_runtime

def get_vintage_programmer_runtime() -> VintageProgrammerRuntime:
    return vintage_programmer_runtime


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
        record["cancel_requested_at"] = time.time()
        return dict(record)


def _unregister_active_chat_run(run_id: str) -> None:
    with _active_chat_runs_lock:
        _active_chat_runs.pop(str(run_id or "").strip(), None)


def _provider_options_payload() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for item in list_provider_profiles(config):
        provider = str(item.get("provider") or "").strip()
        if not provider:
            continue
        provider_config = build_provider_config(config, provider)
        auth_summary = OpenAIAuthManager(provider_config).auth_summary()
        options.append(
            {
                "provider": provider,
                "label": str(item.get("label") or provider),
                "default_model": str(item.get("default_model") or provider_config.default_model or ""),
                "model_options": list(item.get("model_options") or provider_config.model_options or []),
                "auth_ready": bool(auth_summary.get("available")),
                "auth_mode": str(auth_summary.get("mode") or ""),
            }
        )
    return options


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
    available = {
        str(item.get("provider") or "").strip()
        for item in _provider_options_payload()
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
) -> dict[str, Any]:
    return build_compaction_status(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at or _session_last_compacted_at(session),
    )


def _build_context_meter_for_session(
    *,
    session: dict[str, Any] | None = None,
    model: str | None,
    max_output_tokens: int | None = None,
    pending_message: str = "",
    last_compacted_at: str | None = None,
) -> dict[str, Any]:
    return build_context_meter(
        session=session,
        model=model,
        max_output_tokens=max_output_tokens,
        pending_message=pending_message,
        last_compacted_at=last_compacted_at or _session_last_compacted_at(session),
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
    bootstrap = _bootstrap_response_payload()
    runtime_status = _runtime_status_response_payload()
    projects = get_project_store().list_projects()
    return HealthResponse(
        ok=True,
        app_title=bootstrap.app_title,
        app_version=bootstrap.app_version,
        build_version=bootstrap.build_version,
        default_locale=bootstrap.default_locale,
        supported_locales=bootstrap.supported_locales,
        default_model=bootstrap.default_model,
        model_options=bootstrap.model_options,
        allow_custom_model=bootstrap.allow_custom_model,
        llm_provider=bootstrap.llm_provider,
        provider_options=bootstrap.provider_options,
        auth_mode=bootstrap.auth_mode,
        execution_mode_default=bootstrap.execution_mode_default,
        docker_available=bootstrap.docker_available,
        docker_message=bootstrap.docker_message,
        platform_name=bootstrap.platform_name,
        workspace_root=bootstrap.workspace_root,
        allowed_roots=bootstrap.allowed_roots,
        max_upload_mb=bootstrap.max_upload_mb,
        web_allow_all_domains=bootstrap.web_allow_all_domains,
        web_allowed_domains=bootstrap.web_allowed_domains,
        default_project_id=bootstrap.default_project_id,
        projects=[ProjectDescriptor(**item) for item in projects if isinstance(item, dict)],
        runtime_status=runtime_status.runtime_status,
        ocr_status=runtime_status.ocr_status,
        context_meter=runtime_status.context_meter,
        compaction_status=runtime_status.compaction_status,
        agent=bootstrap.agent,
    )


@app.get("/api/bootstrap", response_model=BootstrapResponse)
def bootstrap() -> BootstrapResponse:
    return _bootstrap_response_payload()


@app.get("/api/runtime-status", response_model=RuntimeStatusResponse)
def runtime_status(project_id: str | None = None, model: str | None = None, max_output_tokens: int = DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS) -> RuntimeStatusResponse:
    return _runtime_status_response_payload(
        project_id=project_id,
        model=model,
        max_output_tokens=max_output_tokens,
    )


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
def workbench_skills() -> WorkbenchSkillsResponse:
    skills = get_workbench_store().list_skills()
    return WorkbenchSkillsResponse(skills=[SkillDescriptor(**item) for item in skills if isinstance(item, dict)])


@app.get("/api/workbench/skills/{skill_id}", response_model=SkillDescriptor)
def workbench_skill_detail(skill_id: str) -> SkillDescriptor:
    try:
        return SkillDescriptor(**get_workbench_store().get_skill(skill_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workbench/skills", response_model=SkillDescriptor)
def workbench_create_skill(req: SkillUpsertRequest) -> SkillDescriptor:
    try:
        return SkillDescriptor(**get_workbench_store().create_skill(req.content))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/workbench/skills/{skill_id}", response_model=SkillDescriptor)
def workbench_write_skill(skill_id: str, req: SkillUpsertRequest) -> SkillDescriptor:
    try:
        return SkillDescriptor(**get_workbench_store().write_skill(skill_id, req.content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workbench/skills/{skill_id}/toggle", response_model=SkillDescriptor)
def workbench_toggle_skill(skill_id: str, req: ToggleSkillRequest) -> SkillDescriptor:
    try:
        return SkillDescriptor(**get_workbench_store().toggle_skill(skill_id, enabled=req.enabled))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/workbench/skills/{skill_id}", response_model=SkillDeleteResponse)
def workbench_delete_skill(skill_id: str) -> SkillDeleteResponse:
    try:
        get_workbench_store().delete_skill(skill_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillDeleteResponse(ok=True, skill_id=skill_id)


@app.get("/api/workbench/specs", response_model=WorkbenchSpecsResponse)
def workbench_specs(locale: str | None = None) -> WorkbenchSpecsResponse:
    specs = get_workbench_store().list_agent_specs(locale=locale)
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
def workbench_write_spec(name: str, req: SpecUpsertRequest, locale: str | None = None) -> SpecDescriptor:
    try:
        return SpecDescriptor(**get_workbench_store().write_agent_spec(name, req.content, locale=locale))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


def _resolve_project_for_thread_create(project_id: str | None) -> dict[str, Any]:
    wanted = str(project_id or "").strip()
    project = get_project_store().get_cached(wanted) if hasattr(get_project_store(), "get_cached") else None
    if not project:
        if wanted:
            raise HTTPException(status_code=404, detail=f"Project not found: {wanted}")
        return _default_project()
    return project


def _runtime_provider_payload(*, include_runtime: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any], str, Any, dict[str, Any], dict[str, Any]]:
    runtime_meta = (
        get_chat_product_runtime().runtime_meta()
        if include_runtime
        else {
            "docker_available": False,
            "docker_message": "runtime status is loaded asynchronously",
            "ocr_status": {},
        }
    )
    provider_options = _provider_options_payload()
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
    auth_summary = OpenAIAuthManager(active_provider_config).auth_summary()
    return (
        provider_options,
        active_provider or {},
        active_provider_name,
        active_provider_config,
        auth_summary,
        runtime_meta,
    )


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
    rows = session_store.list_sessions(limit=500, project_id=str(loaded.get("project_id") or ""), default_project=_default_project())
    hit = next((row for row in rows if str(row.get("session_id") or "") == str(session_id or "")), None)
    if hit is None:
        return None
    return _thread_list_item_from_session_row(hit)


def _bootstrap_response_payload() -> BootstrapResponse:
    (
        provider_options,
        active_provider,
        active_provider_name,
        active_provider_config,
        auth_summary,
        runtime_meta,
    ) = _runtime_provider_payload(include_runtime=False)
    default_project = get_project_store().ensure_default_project()
    agent_descriptor = get_vintage_programmer_runtime().descriptor()
    active_model = str((active_provider or {}).get("default_model") or active_provider_config.default_model or agent_descriptor.get("default_model") or "")
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
    (
        provider_options,
        active_provider,
        active_provider_name,
        active_provider_config,
        auth_summary,
        runtime_meta,
    ) = _runtime_provider_payload()
    _ = provider_options
    agent_descriptor = get_vintage_programmer_runtime().descriptor()
    selected_project = _resolve_project_or_default(project_id)
    active_model = str(
        model
        or (active_provider or {}).get("default_model")
        or active_provider_config.default_model
        or agent_descriptor.get("default_model")
        or ""
    ).strip()
    projects = get_project_store().list_projects()
    effective_roots = _effective_allowed_roots(projects)
    runtime_status = {
        "execution_mode": config.execution_mode,
        "auth_ready": bool(auth_summary.get("available")),
        "auth_mode": str(auth_summary.get("mode") or ""),
        "provider": active_provider_name,
        "permission_summary": _permission_summary_for_roots(effective_roots),
        "workspace_label": str(selected_project.get("title") or config.workspace_root.name or str(config.workspace_root)),
        "project_root": str(selected_project.get("root_path") or config.workspace_root),
        "default_project_id": str(_default_project().get("project_id") or ""),
        "git_branch": str(selected_project.get("git_branch") or ""),
        "build_version": BUILD_VERSION,
    }
    context_meter = _build_context_meter_for_session(
        model=active_model,
        max_output_tokens=max_output_tokens,
    )
    compaction_status = _build_compaction_status_for_session(
        model=active_model,
        max_output_tokens=max_output_tokens,
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


def _thread_detail_response_payload(
    session_id: str,
    max_turns: int = 40,
    before_turn_id: str | None = None,
) -> ThreadDetailResponse:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_state = dict(loaded.get("agent_state") or {})
    selected_model = str(agent_state.get("last_model") or config.default_model or "").strip()
    context_meter = _build_context_meter_for_session(
        session=loaded,
        model=selected_model,
        max_output_tokens=DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS,
        last_compacted_at=str(agent_state.get("last_compacted_at") or ""),
    )
    compaction_status = _build_compaction_status_for_session(
        session=loaded,
        model=selected_model,
        max_output_tokens=DEFAULT_CONTEXT_METER_MAX_OUTPUT_TOKENS,
        last_compacted_at=str(agent_state.get("last_compacted_at") or ""),
    )
    agent_state["context_meter"] = dict(context_meter)
    agent_state["compaction_status"] = dict(compaction_status)
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
        turns.append(
            SessionTurn(
                id=_turn_public_id(item, index),
                role=str(item.get("role") or "user"),
                text=str(item.get("text") or ""),
                answer_bundle=item.get("answer_bundle") or {},
                activity=item.get("activity") or {},
                created_at=str(item.get("created_at")) if item.get("created_at") else None,
            )
        )
    return ThreadDetailResponse(
        thread_id=session_id,
        session_id=session_id,
        title=str(loaded.get("title") or ""),
        summary=str(loaded.get("summary") or ""),
        turn_count=len(turns_raw),
        project_id=str(loaded.get("project_id") or ""),
        project_title=str(loaded.get("project_title") or ""),
        project_root=str(loaded.get("project_root") or ""),
        git_branch=str(loaded.get("git_branch") or ""),
        cwd=str(loaded.get("cwd") or ""),
        status=_thread_status_value(session_id),
        agent_state=agent_state,
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
    return UpdateSessionTitleResponse(ok=True, session_id=session_id, title=title)


@app.get("/api/session/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, max_turns: int = 40, before_turn_id: str | None = None) -> SessionDetailResponse:
    thread_payload = _thread_detail_response_payload(session_id, max_turns=max_turns, before_turn_id=before_turn_id)
    return SessionDetailResponse(
        session_id=str(thread_payload.thread_id or ""),
        title=thread_payload.title,
        summary=thread_payload.summary,
        turn_count=thread_payload.turn_count,
        project_id=thread_payload.project_id,
        project_title=thread_payload.project_title,
        project_root=thread_payload.project_root,
        git_branch=thread_payload.git_branch,
        cwd=thread_payload.cwd,
        agent_state=thread_payload.agent_state,
        context_meter=thread_payload.context_meter,
        compaction_status=thread_payload.compaction_status,
        turns=thread_payload.turns,
    )


@app.get("/api/thread/{thread_id}", response_model=ThreadDetailResponse)
def get_thread(thread_id: str, max_turns: int = 40, before_turn_id: str | None = None) -> ThreadDetailResponse:
    return _thread_detail_response_payload(thread_id, max_turns=max_turns, before_turn_id=before_turn_id)


@app.get("/api/sessions", response_model=SessionListResponse)
def list_sessions(limit: int = 50, project_id: str | None = None) -> SessionListResponse:
    rows = session_store.list_sessions(limit=limit, project_id=project_id, default_project=_default_project())
    return SessionListResponse(sessions=[SessionListItem(**row) for row in rows])


@app.get("/api/threads", response_model=ThreadListResponse)
def list_threads(limit: int = 50, project_id: str | None = None) -> ThreadListResponse:
    rows = session_store.list_sessions(limit=limit, project_id=project_id, default_project=_default_project())
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


@app.post("/api/chat", response_model=ChatResponse)
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
    tools = get_chat_product_runtime().tool_executor
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
        list_result = tools.list_directory(path=".", max_entries=20)
        list_ok = bool(list_result.get("ok"))
        list_detail = (
            f"path={list_result.get('path', '')}, entries={len(list_result.get('entries') or [])}"
            if list_ok
            else str(list_result.get("error") or "list_directory failed")
        )
        _append_drill_step(
            steps,
            name="list_directory",
            ok=list_ok,
            detail=list_detail,
            started_at=started,
        )
        if not list_ok:
            failed += 1

        started = time.perf_counter()
        pwd_result = tools.run_shell(command="pwd", cwd=".", timeout_sec=12)
        pwd_ok = bool(pwd_result.get("ok"))
        pwd_detail = (
            f"mode={pwd_result.get('execution_mode')}, host_cwd={pwd_result.get('host_cwd')}, "
            f"sandbox_cwd={pwd_result.get('sandbox_cwd') or '-'}"
            if pwd_ok
            else str(pwd_result.get("error") or "run_shell pwd failed")
        )
        _append_drill_step(
            steps,
            name="run_shell_pwd",
            ok=pwd_ok,
            detail=pwd_detail,
            started_at=started,
        )
        if not pwd_ok:
            failed += 1

        started = time.perf_counter()
        if "python3" in config.allowed_commands:
            py_result = tools.run_shell(command="python3 --version", cwd=".", timeout_sec=12)
            py_ok = bool(py_result.get("ok"))
            py_out = str(py_result.get("stdout") or py_result.get("stderr") or "").strip().splitlines()
            py_detail = py_out[0] if py_out else (
                str(py_result.get("error") or "python3 --version failed") if not py_ok else "python3 ok"
            )
            _append_drill_step(
                steps,
                name="run_shell_python3_version",
                ok=py_ok,
                detail=py_detail,
                started_at=started,
            )
            if not py_ok:
                failed += 1
        else:
            _append_drill_step(
                steps,
                name="run_shell_python3_version",
                ok=True,
                detail="skipped: python3 is not in VP_ALLOWED_COMMANDS",
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
        progress_cb({"event": event, **payload})
    except Exception:
        pass


def _emit_thread_started(progress_cb: Callable[[dict[str, Any]], None] | None, thread_id: str) -> None:
    item = _thread_list_item_for_session_id(thread_id)
    if item is None:
        return
    _emit_progress(progress_cb, "thread/started", thread=item.model_dump())


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
    current_task_focus: dict[str, Any] | None,
    collaboration_mode: str,
    turn_status: str,
    cwd: str,
    plan: list[dict[str, Any]] | None = None,
    pending_user_input: dict[str, Any] | None = None,
    tool_count: int = 0,
    evidence_status: str = "not_needed",
    context_meter: dict[str, Any] | None = None,
    compaction_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_focus = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus or {})
    return {
        "goal": str(goal or "").strip(),
        "collaboration_mode": str(collaboration_mode or "default"),
        "turn_status": str(turn_status or "running"),
        "cwd": str(cwd or normalized_focus.get("cwd") or "").strip(),
        "current_task_focus": normalized_focus,
        "plan": [dict(item) for item in list(plan or []) if isinstance(item, dict)][:12],
        "pending_user_input": dict(pending_user_input or {}),
        "tool_count": int(tool_count or 0),
        "evidence_status": str(evidence_status or "not_needed"),
        "context_meter": dict(context_meter or {}),
        "compaction_status": dict(compaction_status or {}),
    }


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
    requested_provider = _resolve_requested_provider(req)
    provider_config, provider_runtime = _provider_runtime(requested_provider)
    req.settings.provider = requested_provider
    if req.mode_override:
        req.settings.collaboration_mode = req.mode_override
    requested_model = str(req.settings.model or provider_config.default_model or "").strip() or provider_config.default_model
    auth_summary = OpenAIAuthManager(provider_config).auth_summary()
    if not bool(auth_summary.get("available")):
        fallback_goal = str(req.message or "").strip()[:160]
        requested_project = _resolve_project_or_default(req.project_id)
        seed_session = session_store.load_or_create(
            req.session_id,
            project=requested_project,
            default_project=_default_project(),
        )
        fallback_text = translate(locale, "chat.auth_missing")
        user_turn = {"role": "user", "text": req.message}
        assistant_turn = {
            "role": "assistant",
            "text": fallback_text,
            "answer_bundle": {
                "summary": fallback_text,
                "claims": [],
                "citations": [],
                "warnings": ["missing_model_auth"],
            },
        }
        seed_session.setdefault("turns", [])
        seed_session["turns"].append(user_turn)
        seed_session["turns"].append(assistant_turn)
        seed_session["summary"] = fallback_text
        seed_session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fallback_context_meter = _build_context_meter_for_session(
            session=seed_session,
            model=requested_model,
            max_output_tokens=req.settings.max_output_tokens,
            pending_message=req.message,
        )
        seed_session["agent_state"] = {
            "goal": fallback_goal,
            "collaboration_mode": str(req.settings.collaboration_mode or "default"),
            "turn_status": "blocked",
            "plan": [],
            "pending_user_input": {},
            "phase": "report",
            "last_run_id": "",
            "last_provider": requested_provider,
            "last_model": requested_model,
            "last_compacted_at": "",
            "cwd": str(seed_session.get("project_root") or ""),
            "task_checkpoint": {},
            "context_meter": dict(fallback_context_meter),
            "tool_hits": [],
            "tool_count": 0,
            "tool_names": [],
            "evidence_status": "not_needed",
            "enabled_skill_ids": [],
            "updated_at": seed_session["updated_at"],
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
            collaboration_mode=str(req.settings.collaboration_mode or "default"),
            turn_status="blocked",
            plan=[],
            pending_user_input={},
            token_usage=TokenUsage(),
            session_token_totals=TokenTotals(),
            global_token_totals=TokenTotals(),
            inspector={
                "agent": get_vintage_programmer_runtime().descriptor(),
                "notes": ["missing_model_auth"],
                "run_state": {
                    "phase": "report",
                    "goal": fallback_goal,
                    "collaboration_mode": str(req.settings.collaboration_mode or "default"),
                    "turn_status": "blocked",
                    "plan": [],
                    "pending_user_input": {},
                    "context_meter": dict(fallback_context_meter),
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
                },
                "token_usage": {"total_tokens": 0},
                "loaded_skills": [],
            },
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
        requested_project = _resolve_project_or_default(req.project_id)
        seed_session = session_store.load_or_create(
            req.session_id,
            project=requested_project,
            default_project=_default_project(),
        )
        session_id = str(seed_session.get("id") or "")
        if not session_id:
            raise HTTPException(status_code=500, detail="Session create failed")
        _update_active_chat_run(run_id, session_id=session_id, project_id=str(requested_project.get("project_id") or ""))

        queue_wait_ms = 0
        with run_queue.run_slot(session_id) as ticket:
            queue_wait_ms = int(ticket.wait_ms)
            if queue_wait_ms >= config.run_queue_wait_notice_ms:
                _emit_progress(
                    progress_cb,
                    "trace",
                    message=translate(locale, "chat.queue_wait", queue_wait_ms=queue_wait_ms),
                    run_id=run_id,
                )

            session = session_store.load_or_create(
                session_id,
                project=requested_project,
                default_project=_default_project(),
            )
            session_project = get_project_store().get(str(session.get("project_id") or "")) or requested_project
            get_project_store().touch(str(session_project.get("project_id") or ""))
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
                run_snapshot=_build_run_snapshot(
                    goal=req.message,
                    current_task_focus=session_context_impl.get_current_task_focus(session),
                    collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                    turn_status="running",
                    cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                    context_meter=_build_context_meter_for_session(
                        session=session,
                        model=requested_model,
                        max_output_tokens=req.settings.max_output_tokens,
                        pending_message=req.message,
                    ),
                    compaction_status=_build_compaction_status_for_session(
                        session=session,
                        model=requested_model,
                        max_output_tokens=req.settings.max_output_tokens,
                        pending_message=req.message,
                    ),
                ),
            )
            _emit_thread_started(progress_cb, session_id)
        history_turns_before = copy.deepcopy(session.get("turns", []))
        summary_before = str(session.get("summary", "") or "")
        compaction_result = maybe_auto_compact_session(
            session=session,
            model=requested_model,
            max_output_tokens=req.settings.max_output_tokens,
            pending_message=req.message,
            phase="pre_turn",
        )
        summarized = bool(compaction_result.get("compacted"))
        if summarized:
            compaction_after = dict(compaction_result.get("status_after") or {})
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
                    collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                    turn_status="running",
                    cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                    context_meter=_build_context_meter_for_session(
                        session=session,
                        model=requested_model,
                        max_output_tokens=req.settings.max_output_tokens,
                        pending_message=req.message,
                    ),
                    compaction_status=_build_compaction_status_for_session(
                        session=session,
                        model=requested_model,
                        max_output_tokens=req.settings.max_output_tokens,
                        pending_message=req.message,
                    ),
                ),
            )
        session_context_impl.sync_session_memory_state(session)

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

        attachments = upload_store.get_many(effective_attachment_ids)
        attachment_evidence_pack = build_attachment_evidence_pack(attachments, locale=locale)
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
            run_snapshot=_build_run_snapshot(
                goal=req.message,
                current_task_focus=session_context_impl.get_current_task_focus(session),
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=_build_context_meter_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                ),
                compaction_status=_build_compaction_status_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                ),
            ),
        )
        found_attachment_ids = {str(item.get("id")) for item in attachments if item.get("id")}
        missing_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id not in found_attachment_ids]
        resolved_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id in found_attachment_ids]
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
        history_turns_for_runtime = copy.deepcopy(runtime_history_view.get("history_turns") or [])
        summary_for_runtime = str(runtime_history_view.get("summary") or "")
        thread_memory_for_runtime = copy.deepcopy(session_context_impl.get_thread_memory(session))
        current_task_focus_for_runtime = copy.deepcopy(session_context_impl.get_current_task_focus(session))
        recent_tasks_for_runtime = copy.deepcopy(list(thread_memory_for_runtime.get("recent_tasks") or []))
        artifact_memory_preview = copy.deepcopy(session_context_impl.get_artifact_memory_preview(session))
        compaction_status_for_runtime = _build_compaction_status_for_session(
            session=session,
            model=requested_model,
            max_output_tokens=req.settings.max_output_tokens,
            pending_message=req.message,
        )
        recalled_context = copy.deepcopy({
            "recalled_task": attachment_context.get("recalled_task") or {},
            "recalled_artifacts": attachment_context.get("recalled_artifacts") or [],
            "recalled_artifact_ids": attachment_context.get("recalled_attachment_ids") or [],
        })

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
                goal=req.message,
                current_task_focus=current_task_focus_for_runtime,
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=_build_context_meter_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                ),
                compaction_status=compaction_status_for_runtime,
            ),
        )
        _emit_thread_status_changed(progress_cb, thread_id=session_id, status="active")
        _emit_turn_started(
            progress_cb,
            thread_id=session_id,
            turn_id=run_id,
            run_snapshot=_build_run_snapshot(
                goal=req.message,
                current_task_focus=current_task_focus_for_runtime,
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=_build_context_meter_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                ),
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
                goal=req.message,
                current_task_focus=current_task_focus_for_runtime,
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
                context_meter=_build_context_meter_for_session(
                    session=session,
                    model=requested_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                ),
                compaction_status=compaction_status_for_runtime,
            ),
        )
        runtime_result = provider_runtime.run(
            message=req.message,
            settings=req.settings,
            context={
                "session_id": session_id,
                "run_id": run_id,
                "cancel_event": cancel_event,
                "mode_override": req.mode_override or req.settings.collaboration_mode,
                "user_input_response": dict(req.user_input_response or {}),
                "project": {
                    "project_id": str(session_project.get("project_id") or ""),
                    "project_title": str(session_project.get("title") or ""),
                    "project_root": str(session_project.get("root_path") or ""),
                    "git_branch": str(session_project.get("git_branch") or ""),
                    "cwd": str(session.get("cwd") or session_project.get("root_path") or ""),
                    "is_worktree": bool(session_project.get("is_worktree")),
                },
                "summary": summary_for_runtime,
                "thread_memory": thread_memory_for_runtime,
                "current_task_focus": current_task_focus_for_runtime,
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
        tool_events = list(runtime_result.get("tool_events") or [])
        answer_bundle = runtime_result.get("answer_bundle") or {}
        token_usage = dict(runtime_result.get("token_usage") or {})
        effective_model = str(runtime_result.get("effective_model") or "")
        selected_model = effective_model or req.settings.model or provider_config.default_model
        collaboration_mode = str(runtime_result.get("collaboration_mode") or req.settings.collaboration_mode or "default")
        turn_status = str(runtime_result.get("turn_status") or "completed")
        plan = list(runtime_result.get("plan") or [])
        pending_user_input = (
            dict(runtime_result.get("pending_user_input") or {})
            if isinstance(runtime_result.get("pending_user_input"), dict)
            else {}
        )
        activity = dict(runtime_result.get("activity") or {})
        answer_stream = dict(runtime_result.get("answer_stream") or {})
        route_state = (
            runtime_result.get("route_state")
            if isinstance(runtime_result.get("route_state"), dict)
            else dict(route_state_input or {})
        )
        inspector = dict(runtime_result.get("inspector") or {})
        attachment_note = ""

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
                collaboration_mode=collaboration_mode,
                turn_status=turn_status,
                cwd=str((((inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}).get("cwd")) or session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                tool_count=len(tool_events),
                evidence_status=str(((inspector.get("evidence") or {}) if isinstance(inspector.get("evidence"), dict) else {}).get("status") or "not_needed"),
                context_meter=_build_context_meter_for_session(
                    session=session,
                    model=selected_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                    last_compacted_at=_session_last_compacted_at(session),
                ),
                compaction_status=_build_compaction_status_for_session(
                    session=session,
                    model=selected_model,
                    max_output_tokens=req.settings.max_output_tokens,
                    pending_message=req.message,
                    last_compacted_at=_session_last_compacted_at(session),
                ),
            ),
        )
        inspector_notes = list(inspector.get("notes") or [])
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

        user_text = req.message.strip()
        if attachment_note:
            attachment_label = "Attachments" if locale == "en" else ("添付" if locale == "ja-JP" else "附件")
            user_text = f"{user_text}\n\n[{attachment_label}] {attachment_note}"

        if not bool(answer_stream.get("streamed")):
            _emit_agent_message_events(
                progress_cb,
                thread_id=session_id,
                turn_id=run_id,
                text=text,
            )

        session_store.append_turn(
            session,
            role="user",
            text=user_text,
            attachments=[{"id": item.get("id"), "name": item.get("original_name")} for item in attachments],
        )
        session_store.append_turn(session, role="assistant", text=text, answer_bundle=answer_bundle, activity=activity)
        inspector_run_state = (inspector.get("run_state") or {}) if isinstance(inspector.get("run_state"), dict) else {}
        inspector_evidence = (inspector.get("evidence") or {}) if isinstance(inspector.get("evidence"), dict) else {}
        inspector_loaded_skills = list(inspector.get("loaded_skills") or [])
        current_task_focus = dict(
            inspector_run_state.get("current_task_focus")
            or inspector_run_state.get("task_checkpoint")
            or ((route_state or {}).get("current_task_focus") if isinstance(route_state, dict) else {})
            or ((route_state or {}).get("task_checkpoint") if isinstance(route_state, dict) else {})
            or {}
        )
        previous_agent_state = dict(session.get("agent_state") or {})
        last_compacted_at = _session_last_compacted_at(session) or str(previous_agent_state.get("last_compacted_at") or "")
        tool_hits = [
            {
                "name": str(item.get("name") or ""),
                "group": str(item.get("group") or item.get("module_group") or ""),
                "status": str(item.get("status") or ""),
            }
            for item in tool_events
            if isinstance(item, dict)
        ]
        session["agent_state"] = {
            "agent_id": "vintage_programmer",
            "goal": str(inspector_run_state.get("goal") or req.message[:140]),
            "current_goal": str(inspector_run_state.get("goal") or req.message[:140]),
            "collaboration_mode": str(inspector_run_state.get("collaboration_mode") or collaboration_mode),
            "turn_status": str(inspector_run_state.get("turn_status") or turn_status),
            "plan": list(inspector_run_state.get("plan") or plan),
            "pending_user_input": dict(inspector_run_state.get("pending_user_input") or pending_user_input),
            "phase": str(inspector_run_state.get("phase") or "report"),
            "last_run_id": run_id,
            "last_provider": requested_provider,
            "last_model": selected_model,
            "last_compacted_at": last_compacted_at,
            "project_id": str(session.get("project_id") or ""),
            "project_root": str(session.get("project_root") or ""),
            "cwd": str((((inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}).get("cwd")) or session.get("cwd") or ""),
            "current_task_focus": dict(current_task_focus),
            "task_checkpoint": session_context_impl.compat_task_checkpoint_from_focus(current_task_focus),
            "context_meter": {},
            "compaction_status": {},
            "tool_hits": tool_hits,
            "tool_count": len(tool_hits),
            "tool_names": [str(item.get("name") or "") for item in tool_hits if str(item.get("name") or "").strip()],
            "evidence_status": str(inspector_evidence.get("status") or "not_needed"),
            "enabled_skill_ids": [
                str(item.get("id") or "")
                for item in inspector_loaded_skills
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        session_context_impl.record_turn_memory(
            session,
            user_message=req.message,
            assistant_text=text,
            attachments=attachments,
            route_state=route_state,
            tool_events=tool_events,
            answer_bundle=answer_bundle,
        )
        session["cwd"] = str(session["agent_state"].get("cwd") or session.get("project_root") or "")
        thread_memory = session_context_impl.get_thread_memory(session)
        recent_tasks = list(thread_memory.get("recent_tasks") or [])
        artifact_memory_preview = session_context_impl.get_artifact_memory_preview(session)
        current_task_focus = session_context_impl.get_current_task_focus(session)
        context_meter = _build_context_meter_for_session(
            session=session,
            model=selected_model,
            max_output_tokens=req.settings.max_output_tokens,
            last_compacted_at=last_compacted_at,
        )
        compaction_status = _build_compaction_status_for_session(
            session=session,
            model=selected_model,
            max_output_tokens=req.settings.max_output_tokens,
            last_compacted_at=last_compacted_at,
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
        session["agent_state"]["context_meter"] = dict(context_meter)
        session["agent_state"]["last_compacted_at"] = str(compaction_status.get("last_compacted_at") or last_compacted_at or "")
        session["agent_state"]["compaction_status"] = dict(compaction_status)
        inspector_run_state["thread_memory"] = dict(thread_memory)
        inspector_run_state["recent_tasks"] = recent_tasks
        inspector_run_state["artifact_memory_preview"] = artifact_memory_preview
        inspector_run_state["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_run_state["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_run_state["context_meter"] = dict(context_meter)
        inspector_run_state["compaction_status"] = dict(compaction_status)
        inspector["run_state"] = inspector_run_state
        inspector_session = (inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}
        inspector_session["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["thread_memory"] = dict(thread_memory)
        inspector_session["recent_tasks"] = recent_tasks
        inspector_session["artifact_memory_preview"] = artifact_memory_preview
        inspector_session["context_meter"] = dict(context_meter)
        inspector_session["compaction_status"] = dict(compaction_status)
        inspector["session"] = inspector_session
        session_context_impl.store_scoped_route_state(
            session,
            attachment_ids=resolved_attachment_ids,
            route_state=route_state,
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
                current_task_focus=current_task_focus,
                collaboration_mode=collaboration_mode,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
            ),
        )
        updated_thread = _thread_list_item_for_session_id(session["id"])
        if updated_thread is not None:
            _emit_progress(progress_cb, "thread/updated", thread=updated_thread.model_dump())

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
        try:
            evolution_event = get_evolution_store().record_turn(
                session_id=session["id"],
                user_message=req.message,
                assistant_text=text,
                route_state=route_state,
                answer_bundle=answer_bundle,
                attachment_context_mode=attachment_context_mode,
                attachment_count=len(resolved_attachment_ids),
                settings=req.settings.model_dump(),
                effective_model=selected_model,
                turn_count=len(session.get("turns", [])),
            )
            evolution_terms = list(evolution_event.get("domain_terms") or [])
            evolution_note = translate(
                locale,
                "chat.overlay_updated",
                overlay_path=(
                    f"intent={evolution_event.get('primary_intent') or 'standard'}"
                    + (f", terms={', '.join(evolution_terms[:3])}" if evolution_terms else "")
                ),
            )
            inspector_notes.append(evolution_note)
            _emit_progress(progress_cb, "trace", message=evolution_note, run_id=run_id)
        except Exception as exc:
            evolution_note = translate(locale, "chat.overlay_update_failed", error=exc)
            inspector_notes.append(evolution_note)
            _emit_progress(progress_cb, "trace", message=evolution_note, run_id=run_id)
        inspector["notes"] = inspector_notes
        if config.enable_shadow_logging:
            shadow_path = shadow_log_store.append(
                {
                    "run_id": run_id,
                    "agent_id": "vintage_programmer",
                    "session_id": session["id"],
                    "effective_model": selected_model,
                    "project_id": str(session.get("project_id") or ""),
                    "project_root": str(session.get("project_root") or ""),
                    "cwd": str(session.get("cwd") or ""),
                    "attachment_context_mode": attachment_context_mode,
                    "attachment_context_key": resolved_attachment_context_key,
                    "effective_attachment_ids": resolved_attachment_ids,
                    "auto_linked_attachment_ids": [item for item in auto_linked_attachment_ids if item in found_attachment_ids],
                    "missing_attachment_ids": missing_attachment_ids,
                    "route_state_scope": route_state_scope,
                    "route_state_input": route_state_input or {},
                    "route_state": route_state or {},
                    "tool_events_count": len(tool_events),
                    "tool_events": tool_events,
                    "token_usage": token_usage,
                    "inspector": inspector,
                    "message": req.message,
                    "settings": req.settings.model_dump(),
                    "summary_before": summary_before,
                    "history_turns_before": history_turns_before,
                    "attachment_metas": attachments,
                    "attachment_evidence_pack": attachment_evidence_pack,
                    "message_preview": req.message[:500],
                    "response_preview": text[:500],
                }
            )
            _emit_progress(
                progress_cb,
                "trace",
                message=translate(locale, "chat.shadow_log_written", name=shadow_path.name),
                run_id=run_id,
            )
        tool_event_models = [
            item if isinstance(item, ToolEvent) else ToolEvent(**item)
            for item in tool_events
        ]
        response = ChatResponse(
            session_id=session["id"],
            thread_id=session["id"],
            run_id=run_id,
            agent_id="vintage_programmer",
            agent_title=str((inspector.get("agent") or {}).get("title") or "Vintage Programmer"),
            selected_business_module="llm_router_core",
            effective_model=selected_model,
            queue_wait_ms=queue_wait_ms,
            text=text,
            tool_events=tool_event_models,
            attachment_context_mode=attachment_context_mode,
            effective_attachment_ids=resolved_attachment_ids,
            auto_linked_attachment_ids=[item for item in auto_linked_attachment_ids if item in found_attachment_ids],
            auto_linked_attachment_names=auto_linked_attachment_names,
            missing_attachment_ids=missing_attachment_ids,
            attachment_context_key=resolved_attachment_context_key,
            collaboration_mode=collaboration_mode,
            turn_status=turn_status,
            plan=plan,
            pending_user_input=pending_user_input,
            current_task_focus=session_context_impl.compat_task_checkpoint_from_focus(current_task_focus),
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
                collaboration_mode=collaboration_mode,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
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
                collaboration_mode=collaboration_mode,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
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
                collaboration_mode=collaboration_mode,
                turn_status=turn_status,
                cwd=str(session.get("cwd") or ""),
                plan=plan,
                pending_user_input=pending_user_input,
                tool_count=len(tool_events),
                evidence_status=str(inspector_evidence.get("status") or "not_needed"),
                context_meter=context_meter,
                compaction_status=compaction_status,
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


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    locale = normalize_locale(getattr(req.settings, "locale", ""), config.default_locale)
    def event_stream():
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        done_event = threading.Event()
        stream_state: dict[str, Any] = {
            "thread_id": "",
            "turn_id": "",
            "tool_counter": 0,
            "last_compaction_marker": "",
        }

        def put_event(event_name: str, payload: dict[str, Any]) -> None:
            events.put({"event": event_name, "payload": payload})

        def build_tool_item_payload(data: dict[str, Any]) -> dict[str, Any]:
            item = dict(data.get("item") or {})
            run_snapshot = dict(data.get("run_snapshot") or {})
            stream_state["tool_counter"] = int(stream_state.get("tool_counter") or 0) + 1
            item_id = str(item.get("id") or "") or (
                f"{str(stream_state.get('turn_id') or 'turn')}:{stream_state['tool_counter']}:{str(item.get('name') or 'tool')}"
            )
            item_type = "toolCall"
            name = str(item.get("name") or "").strip()
            if name == "exec_command":
                item_type = "commandExecution"
            elif name == "apply_patch":
                item_type = "fileChange"
            elif name == "request_user_input":
                item_type = "userInputRequest"
            elif name == "image_read":
                item_type = "imageView"
            return {
                **item,
                "id": item_id,
                "type": item_type,
                "tool": name,
                "group": str(item.get("group") or ""),
                "status": "completed" if str(item.get("status") or "") == "ok" else "failed",
                "summary": str(item.get("summary") or data.get("summary") or ""),
                "sourceRefs": list(item.get("source_refs") or data.get("source_refs") or []),
                "cwd": str(item.get("cwd") or ""),
                "projectRoot": str(item.get("project_root") or ""),
                "runSnapshot": run_snapshot,
            }

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
            if event_name == "tool":
                item_payload = build_tool_item_payload(data)
                typed_common = {
                    "thread_id": str(stream_state.get("thread_id") or ""),
                    "turn_id": str(stream_state.get("turn_id") or ""),
                }
                put_event("item/started", {**typed_common, "item": {**item_payload, "status": "inProgress"}})
                put_event("item/completed", {**typed_common, "item": item_payload})
            elif event_name == "plan_update":
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
            elif event_name == "request_user_input":
                pending = dict(data.get("pending_user_input") or {})
                item_id = f"{str(stream_state.get('turn_id') or 'turn')}:request_user_input"
                typed_common = {
                    "thread_id": str(stream_state.get("thread_id") or ""),
                    "turn_id": str(stream_state.get("turn_id") or ""),
                }
                item_payload = {
                    "id": item_id,
                    "type": "userInputRequest",
                    "status": "completed",
                    "summary": str(pending.get("summary") or ""),
                    "questions": list(pending.get("questions") or []),
                }
                put_event("item/started", {**typed_common, "item": {**item_payload, "status": "inProgress"}})
                put_event("item/completed", {**typed_common, "item": item_payload})
            elif event_name == "trace":
                run_snapshot = dict(data.get("run_snapshot") or {})
                compaction_status = dict(run_snapshot.get("compaction_status") or {})
                marker = "|".join(
                    [
                        str(compaction_status.get("generation") or ""),
                        str(compaction_status.get("last_compacted_at") or ""),
                        str(compaction_status.get("last_compaction_phase") or ""),
                    ]
                ).strip("|")
                if marker and marker != str(stream_state.get("last_compaction_marker") or ""):
                    stream_state["last_compaction_marker"] = marker
                    item_id = f"{str(stream_state.get('turn_id') or 'turn')}:context_compaction:{marker}"
                    typed_common = {
                        "thread_id": str(stream_state.get("thread_id") or ""),
                        "turn_id": str(stream_state.get("turn_id") or ""),
                    }
                    item_payload = {
                        "id": item_id,
                        "type": "contextCompaction",
                        "status": "completed",
                        "phase": str(compaction_status.get("last_compaction_phase") or ""),
                        "generation": int(compaction_status.get("generation") or 0),
                    }
                    put_event("item/started", {**typed_common, "item": {**item_payload, "status": "inProgress"}})
                    put_event("item/completed", {**typed_common, "item": item_payload})

        def worker() -> None:
            try:
                response = _process_chat_request(req, progress_cb=emit)
                put_event("final", {"response": response.model_dump()})
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
