from __future__ import annotations

import ast
import copy
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

from app.bootstrap import AgentOSRuntime, assemble_runtime
from app.config import AppConfig, build_provider_config, list_provider_profiles, load_config, normalize_llm_provider_name
from app.core.bootstrap import build_kernel_runtime
from app.core.healthcheck import build_kernel_health_payload
from app.evals import run_regression_evals
from app.evolution import EvolutionStore
from app.models import (
    ChatRequest,
    ChatResponse,
    ClearStatsResponse,
    DeleteSessionResponse,
    EvalCaseResult,
    EvalRunRequest,
    EvalRunResponse,
    EvolutionRuntimeResponse,
    HealthResponse,
    KernelManifestUpdateRequest,
    KernelShadowPipelineRequest,
    KernelShadowAutoRepairRequest,
    KernelShadowPackageRequest,
    KernelShadowPatchWorkerRequest,
    KernelShadowReplayRequest,
    KernelShadowSelfUpgradeRequest,
    KernelRuntimeResponse,
    KernelShadowSmokeRequest,
    NewSessionResponse,
    NewSessionRequest,
    ProjectCreateRequest,
    ProjectDescriptor,
    ProjectDeleteResponse,
    ProjectListResponse,
    ProjectUpdateRequest,
    SessionDetailResponse,
    SessionListItem,
    SessionListResponse,
    SessionTurn,
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
    UploadResponse,
    WorkbenchSkillsResponse,
    WorkbenchSpecsResponse,
    WorkbenchToolsResponse,
)
from app.openai_auth import OpenAIAuthManager
from app.operations_overview import build_platform_operations_overview
from app.pricing import estimate_usage_cost
from app import session_context as session_context_impl
from app.session_context import normalize_attachment_ids
from app.storage import ProjectStore, SessionStore, ShadowLogStore, TokenStatsStore, UploadStore
from app.vintage_programmer_runtime import VintageProgrammerRuntime
from app.workbench import WorkbenchStore

APP_TITLE = "Vintage Programmer"
config = load_config()
AGENT_DIR = Path(__file__).resolve().parent.parent / "agents" / "vintage_programmer"
project_store = ProjectStore(config.projects_registry_path, default_root=config.workspace_root)
session_store = SessionStore(config.sessions_dir)
upload_store = UploadStore(config.uploads_dir)
token_stats_store = TokenStatsStore(config.token_stats_path)
shadow_log_store = ShadowLogStore(config.shadow_logs_dir)
evolution_store = EvolutionStore(config.overlay_profile_path, config.evolution_logs_dir)
kernel_runtime = build_kernel_runtime(config)
agent_os_runtime: AgentOSRuntime = assemble_runtime(
    config,
    kernel_runtime=kernel_runtime,
)
vintage_programmer_runtime = VintageProgrammerRuntime(
    config=config,
    kernel_runtime=kernel_runtime,
    agent_dir=AGENT_DIR,
)
workbench_store = WorkbenchStore(
    config=config,
    agent_dir=AGENT_DIR,
)
APP_VERSION = "1.0.0"
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
GIT_BRANCH = _git_value("rev-parse", "--abbrev-ref", "HEAD")
LEGACY_AGENT_DIR = Path(__file__).resolve().parent / "agents"


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


def get_kernel_runtime():
    return kernel_runtime


def _list_legacy_agent_manifests() -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    if not LEGACY_AGENT_DIR.is_dir():
        return manifests
    for manifest_path in sorted(LEGACY_AGENT_DIR.glob("*/manifest.json")):
        agent_id = manifest_path.parent.name
        payload: dict[str, Any] = {
            "id": agent_id,
            "name": agent_id,
            "title": agent_id,
            "path": str(manifest_path.parent),
        }
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload.update(
                    {
                        "id": str(raw.get("id") or agent_id),
                        "name": str(raw.get("name") or raw.get("id") or agent_id),
                        "title": str(raw.get("title") or raw.get("name") or raw.get("id") or agent_id),
                    }
                )
        except Exception:
            pass
        manifests.append(payload)
    return manifests


def get_project_store() -> ProjectStore:
    return project_store


def get_evolution_store() -> EvolutionStore:
    return evolution_store


def get_agent_os_runtime() -> AgentOSRuntime:
    return agent_os_runtime


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
                kernel_runtime=kernel_runtime,
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
    runtime = get_agent_os_runtime()
    legacy_tools = runtime.legacy_tools()
    docker_ok, docker_msg = legacy_tools.docker_status()
    ocr_status = legacy_tools.ocr_status() if hasattr(legacy_tools, "ocr_status") else {}
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
    agent_descriptor = get_vintage_programmer_runtime().descriptor()
    projects = get_project_store().list_projects()
    default_project = get_project_store().ensure_default_project()
    effective_roots: list[str] = []
    for raw_root in [*(str(path) for path in config.allowed_roots), *(str(item.get("root_path") or "") for item in projects)]:
        if raw_root and raw_root not in effective_roots:
            effective_roots.append(raw_root)
    if config.allow_any_path:
        permission_summary = "full filesystem access enabled"
    else:
        root_names = [(Path(path).name or str(path)) for path in effective_roots[:4]]
        permission_summary = f"{len(effective_roots)} allowed roots: {', '.join(root_names)}"
    return HealthResponse(
        ok=True,
        app_title=APP_TITLE,
        app_version=APP_VERSION,
        build_version=BUILD_VERSION,
        default_model=str((active_provider or {}).get("default_model") or active_provider_config.default_model or agent_descriptor.get("default_model") or ""),
        model_options=list((active_provider or {}).get("model_options") or active_provider_config.model_options or []),
        allow_custom_model=True,
        llm_provider=active_provider_name,
        provider_options=provider_options,
        auth_mode=str(auth_summary.get("mode") or ""),
        execution_mode_default=config.execution_mode,
        docker_available=docker_ok,
        docker_message=docker_msg,
        platform_name=config.platform_name,
        workspace_root=str(config.workspace_root),
        allowed_roots=effective_roots,
        max_upload_mb=config.max_upload_mb,
        web_allow_all_domains=config.web_allow_all_domains,
        web_allowed_domains=config.web_allowed_domains,
        default_project_id=str(default_project.get("project_id") or ""),
        projects=[ProjectDescriptor(**item) for item in projects if isinstance(item, dict)],
        runtime_status={
            "execution_mode": config.execution_mode,
            "auth_ready": bool(auth_summary.get("available")),
            "auth_mode": str(auth_summary.get("mode") or ""),
            "provider": active_provider_name,
            "permission_summary": permission_summary,
            "workspace_label": str(default_project.get("title") or config.workspace_root.name or str(config.workspace_root)),
            "project_root": str(default_project.get("root_path") or config.workspace_root),
            "default_project_id": str(default_project.get("project_id") or ""),
            "git_branch": GIT_BRANCH,
            "build_version": BUILD_VERSION,
        },
        ocr_status=ocr_status,
        agent=agent_descriptor,
    )


@app.get("/api/agents")
def list_legacy_agents() -> dict[str, Any]:
    agents = _list_legacy_agent_manifests()
    return {
        "ok": True,
        "count": len(agents),
        "agents": agents,
    }


@app.post("/api/agents/{agent_id}/reload")
def reload_legacy_agent(agent_id: str) -> dict[str, Any]:
    normalized = str(agent_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="agent_id is required")
    known = {str(item.get("id") or "") for item in _list_legacy_agent_manifests()}
    if normalized not in known:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {normalized}")
    return {
        "ok": True,
        "agent_id": normalized,
        "reloaded": True,
    }


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
        get_project_store().delete(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectDeleteResponse(ok=True, project_id=project_id)


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


@app.get("/api/workbench/specs", response_model=WorkbenchSpecsResponse)
def workbench_specs() -> WorkbenchSpecsResponse:
    specs = get_workbench_store().list_agent_specs()
    return WorkbenchSpecsResponse(specs=[SpecDescriptor(**item) for item in specs if isinstance(item, dict)])


@app.get("/api/workbench/specs/{name}", response_model=SpecDescriptor)
def workbench_spec_detail(name: str) -> SpecDescriptor:
    try:
        return SpecDescriptor(**get_workbench_store().get_agent_spec(name))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/workbench/specs/{name}", response_model=SpecDescriptor)
def workbench_write_spec(name: str, req: SpecUpsertRequest) -> SpecDescriptor:
    try:
        return SpecDescriptor(**get_workbench_store().write_agent_spec(name, req.content))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _kernel_runtime_response(
    *,
    ok: bool,
    detail: str = "",
    validation: dict[str, object] | None = None,
    contracts: dict[str, object] | None = None,
    smoke: dict[str, object] | None = None,
    replay: dict[str, object] | None = None,
    pipeline: dict[str, object] | None = None,
    repair: dict[str, object] | None = None,
    patch_worker: dict[str, object] | None = None,
) -> KernelRuntimeResponse:
    kernel_health = build_kernel_health_payload(get_kernel_runtime())
    evolution_payload = get_evolution_store().runtime_payload(limit=10)
    tool_registry = get_agent_os_runtime().debug_tool_registry_snapshot()
    return KernelRuntimeResponse(
        ok=ok,
        detail=detail,
        validation=dict(validation or {}),
        contracts=dict(contracts or {}),
        smoke=dict(smoke or {}),
        replay=dict(replay or {}),
        pipeline=dict(pipeline or {}),
        repair=dict(repair or {}),
        patch_worker=dict(patch_worker or {}),
        kernel_active_manifest=dict(kernel_health.get("active_manifest") or {}),
        kernel_shadow_manifest=dict(kernel_health.get("shadow_manifest") or {}),
        kernel_shadow_validation=dict(kernel_health.get("shadow_validation") or {}),
        kernel_shadow_promote_check=dict(kernel_health.get("shadow_promote_check") or {}),
        kernel_rollback_pointer=dict(kernel_health.get("rollback_pointer") or {}),
        kernel_last_shadow_run=dict(kernel_health.get("last_shadow_run") or {}),
        kernel_last_upgrade_run=dict(kernel_health.get("last_upgrade_run") or {}),
        kernel_last_repair_run=dict(kernel_health.get("last_repair_run") or {}),
        kernel_last_patch_worker_run=dict(kernel_health.get("last_patch_worker_run") or {}),
        kernel_last_package_run=dict(kernel_health.get("last_package_run") or {}),
        kernel_selected_modules=dict(kernel_health.get("selected_modules") or {}),
        kernel_module_health=dict(kernel_health.get("module_health") or {}),
        kernel_runtime_files=dict(kernel_health.get("runtime_files") or {}),
        kernel_tool_registry=dict(tool_registry or {}),
        assistant_overlay_profile=dict(evolution_payload.get("overlay_profile") or {}),
        assistant_evolution_recent=list(evolution_payload.get("recent_events") or []),
    )


@app.get("/api/evolution/runtime", response_model=EvolutionRuntimeResponse)
def evolution_runtime_state(limit: int = 10) -> EvolutionRuntimeResponse:
    payload = get_evolution_store().runtime_payload(limit=limit)
    return EvolutionRuntimeResponse(
        ok=True,
        detail="当前个体覆层与最近进化日志。",
        assistant_overlay_profile=dict(payload.get("overlay_profile") or {}),
        assistant_evolution_recent=list(payload.get("recent_events") or []),
    )


@app.get("/api/operations/overview")
def platform_operations_overview() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    return build_platform_operations_overview(repo_root)


def _find_shadow_replay_record(run_id: str | None = None) -> dict[str, Any] | None:
    run_id_text = str(run_id or "").strip()
    if run_id_text:
        return shadow_log_store.find_run(run_id_text)
    recent = shadow_log_store.list_recent(limit=1)
    return recent[0] if recent else None


def _find_upgrade_run(run_id: str | None = None) -> dict[str, Any] | None:
    runtime = get_kernel_runtime()
    payload = runtime.find_upgrade_run(run_id)
    return payload if isinstance(payload, dict) and payload else None


def _find_repair_run(run_id: str | None = None) -> dict[str, Any] | None:
    runtime = get_kernel_runtime()
    payload = runtime.find_repair_run(run_id)
    return payload if isinstance(payload, dict) and payload else None


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


@app.get("/api/kernel/runtime", response_model=KernelRuntimeResponse)
def kernel_runtime_state() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    return _kernel_runtime_response(
        ok=True,
        detail="内核运行时状态。",
        validation=runtime.validate_shadow_manifest(),
    )


@app.get("/api/kernel/repairs", response_model=KernelRuntimeResponse)
def kernel_repair_history(limit: int = 10) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    runs = runtime.list_repair_runs(limit=limit)
    summary = [
        {
            "run_id": str(item.get("run_id") or ""),
            "ok": bool(item.get("ok")),
            "base_upgrade_run_id": str(item.get("base_upgrade_run_id") or ""),
            "strategy": str(item.get("strategy") or ""),
            "attempt_count": len(item.get("attempts") or []) if isinstance(item.get("attempts"), list) else 0,
            "finished_at": str(item.get("finished_at") or ""),
        }
        for item in runs
    ]
    return _kernel_runtime_response(
        ok=True,
        detail="最近 repair attempts。",
        repair={"repair_runs": summary},
    )


@app.get("/api/kernel/patch-workers", response_model=KernelRuntimeResponse)
def kernel_patch_worker_history(limit: int = 10) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    runs = runtime.list_patch_worker_runs(limit=limit)
    summary = [
        {
            "run_id": str(item.get("run_id") or ""),
            "ok": bool(item.get("ok")),
            "base_repair_run_id": str(item.get("base_repair_run_id") or ""),
            "task_count": len(item.get("executed_tasks") or []) if isinstance(item.get("executed_tasks"), list) else 0,
            "round_count": int(item.get("round_count") or 0),
            "stop_reason": str(item.get("stop_reason") or ""),
            "finished_at": str(item.get("finished_at") or ""),
        }
        for item in runs
    ]
    return _kernel_runtime_response(
        ok=True,
        detail="最近 patch worker runs。",
        patch_worker={"patch_worker_runs": summary},
    )


@app.get("/api/kernel/packages", response_model=KernelRuntimeResponse)
def kernel_package_history(limit: int = 10) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    runs = runtime.list_package_runs(limit=limit)
    summary = [
        {
            "run_id": str(item.get("run_id") or ""),
            "ok": bool(item.get("ok")),
            "packaged_count": len(item.get("packaged_modules") or []) if isinstance(item.get("packaged_modules"), list) else 0,
            "packaged_labels": list(item.get("packaged_labels") or []) if isinstance(item.get("packaged_labels"), list) else [],
            "finished_at": str(item.get("finished_at") or ""),
        }
        for item in runs
    ]
    return _kernel_runtime_response(
        ok=True,
        detail="最近 package runs。",
        pipeline={"package_runs": summary},
    )


@app.get("/api/kernel/upgrades", response_model=KernelRuntimeResponse)
def kernel_upgrade_history(limit: int = 10) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    runs = runtime.list_upgrade_runs(limit=limit)
    summary = [
        {
            "run_id": str(item.get("run_id") or ""),
            "ok": bool(item.get("ok")),
            "started_at": str(item.get("started_at") or ""),
            "finished_at": str(item.get("finished_at") or ""),
            "failed_stage": str(((item.get("failure_classification") or {}) if isinstance(item.get("failure_classification"), dict) else {}).get("failed_stage") or ""),
            "category": str(((item.get("failure_classification") or {}) if isinstance(item.get("failure_classification"), dict) else {}).get("category") or ""),
        }
        for item in runs
    ]
    return _kernel_runtime_response(
        ok=True,
        detail="最近 upgrade attempts。",
        pipeline={"upgrade_runs": summary},
    )


@app.post("/api/kernel/shadow/stage", response_model=KernelRuntimeResponse)
def kernel_shadow_stage(req: KernelManifestUpdateRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    result = runtime.stage_shadow_manifest(overrides=req.model_dump(exclude_none=True))
    return _kernel_runtime_response(
        ok=bool(result.get("ok")),
        detail="shadow manifest 已更新。",
        validation=result.get("validation") if isinstance(result.get("validation"), dict) else {},
    )


@app.post("/api/kernel/shadow/validate", response_model=KernelRuntimeResponse)
def kernel_shadow_validate() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    validation = runtime.validate_shadow_manifest()
    return _kernel_runtime_response(
        ok=bool(validation.get("ok")),
        detail="shadow manifest 校验完成。",
        validation=validation,
    )


@app.get("/api/kernel/shadow/promote-check", response_model=KernelRuntimeResponse)
def kernel_shadow_promote_check() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    promote_check = runtime.shadow_promote_check()
    return _kernel_runtime_response(
        ok=bool(promote_check.get("ok")),
        detail="shadow promote 检查完成。",
        validation=runtime.validate_shadow_manifest(),
        pipeline={"promote_check": promote_check},
    )


@app.post("/api/kernel/shadow/contracts", response_model=KernelRuntimeResponse)
def kernel_shadow_contracts() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    contracts = runtime.run_shadow_contracts()
    validation = runtime.validate_shadow_manifest()
    return _kernel_runtime_response(
        ok=bool(contracts.get("ok")),
        detail="shadow contracts 已执行。",
        validation=validation,
        contracts=contracts,
    )


@app.post("/api/kernel/active/contracts", response_model=KernelRuntimeResponse)
def kernel_active_contracts() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    contracts = runtime.run_active_contracts()
    validation = runtime.validate_active_manifest()
    return _kernel_runtime_response(
        ok=bool(contracts.get("ok")),
        detail="active contracts 已执行。",
        validation=validation,
        contracts=contracts,
    )


@app.post("/api/kernel/shadow/smoke", response_model=KernelRuntimeResponse)
def kernel_shadow_smoke(req: KernelShadowSmokeRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    smoke = runtime.run_shadow_smoke(
        user_message=req.message,
        validate_provider=bool(req.validate_provider),
    )
    return _kernel_runtime_response(
        ok=bool(smoke.get("ok")),
        detail="shadow smoke 已执行。",
        validation=runtime.validate_shadow_manifest(),
        smoke=smoke,
    )


@app.get("/api/kernel/shadow/logs", response_model=KernelRuntimeResponse)
def kernel_shadow_logs(limit: int = 10) -> KernelRuntimeResponse:
    records = shadow_log_store.list_recent(limit=limit)
    summary = [
        {
            "run_id": str(item.get("run_id") or ""),
            "logged_at": str(item.get("logged_at") or ""),
            "session_id": str(item.get("session_id") or ""),
            "message_preview": str(item.get("message_preview") or ""),
            "effective_model": str(item.get("effective_model") or ""),
        }
        for item in records
    ]
    return _kernel_runtime_response(
        ok=True,
        detail="最近 shadow log 列表。",
        pipeline={"recent_runs": summary},
    )


@app.post("/api/kernel/shadow/replay", response_model=KernelRuntimeResponse)
def kernel_shadow_replay(req: KernelShadowReplayRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    record = _find_shadow_replay_record(req.run_id)
    if not isinstance(record, dict):
        return _kernel_runtime_response(
            ok=False,
            detail="未找到可回放的 shadow log 记录。",
        )
    replay = runtime.run_shadow_replay(replay_record=record)
    return _kernel_runtime_response(
        ok=bool(replay.get("ok")),
        detail="shadow replay 已执行。",
        validation=runtime.validate_shadow_manifest(),
        replay=replay,
    )


@app.post("/api/kernel/shadow/promote", response_model=KernelRuntimeResponse)
def kernel_shadow_promote() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    result = runtime.promote_shadow_manifest()
    return _kernel_runtime_response(
        ok=bool(result.get("ok")),
        detail="shadow manifest promote 完成。" if result.get("ok") else "shadow manifest promote 失败。",
        validation=result.get("validation") if isinstance(result.get("validation"), dict) else {},
    )


@app.post("/api/kernel/rollback", response_model=KernelRuntimeResponse)
def kernel_runtime_rollback() -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    result = runtime.rollback_active_manifest()
    return _kernel_runtime_response(
        ok=bool(result.get("ok")),
        detail="active manifest 回滚完成。" if result.get("ok") else "active manifest 回滚失败。",
        validation=result.get("validation") if isinstance(result.get("validation"), dict) else {},
    )


@app.post("/api/kernel/shadow/pipeline", response_model=KernelRuntimeResponse)
def kernel_shadow_pipeline(req: KernelShadowPipelineRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    overrides = req.model_dump(
        exclude_none=True,
        include={"router", "policy", "attachment_context", "finalizer", "tool_registry", "providers"},
    )
    replay_record = _find_shadow_replay_record(req.replay_run_id) if (req.replay_run_id or shadow_log_store.list_recent(limit=1)) else None
    pipeline = runtime.run_shadow_pipeline(
        overrides=overrides,
        smoke_message=req.smoke_message,
        validate_provider=bool(req.validate_provider),
        replay_record=replay_record if isinstance(replay_record, dict) else None,
        promote_if_healthy=bool(req.promote_if_healthy),
    )
    validation = pipeline.get("validation") if isinstance(pipeline.get("validation"), dict) else {}
    contracts = pipeline.get("contracts") if isinstance(pipeline.get("contracts"), dict) else {}
    smoke = pipeline.get("smoke") if isinstance(pipeline.get("smoke"), dict) else {}
    replay = pipeline.get("replay") if isinstance(pipeline.get("replay"), dict) else {}

    return _kernel_runtime_response(
        ok=bool(pipeline.get("ok")),
        detail="shadow pipeline 已执行。",
        validation=validation,
        contracts=contracts,
        smoke=smoke,
        replay=replay,
        pipeline=pipeline,
    )


@app.post("/api/kernel/shadow/auto-repair", response_model=KernelRuntimeResponse)
def kernel_shadow_auto_repair(req: KernelShadowAutoRepairRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    base_upgrade_run = _find_upgrade_run(req.upgrade_run_id)
    if not isinstance(base_upgrade_run, dict):
        return _kernel_runtime_response(
            ok=False,
            detail="未找到可修复的 upgrade attempt。",
        )
    replay_source_run_id = req.replay_run_id or str(base_upgrade_run.get("replay_source_run_id") or "").strip() or None
    replay_record = _find_shadow_replay_record(replay_source_run_id)
    repair = runtime.run_shadow_auto_repair(
        base_upgrade_run=base_upgrade_run,
        replay_record=replay_record if isinstance(replay_record, dict) else None,
        smoke_message=req.smoke_message,
        validate_provider=req.validate_provider,
        promote_if_healthy=req.promote_if_healthy,
        max_attempts=req.max_attempts,
    )
    repaired_pipeline = repair.get("repaired_pipeline") if isinstance(repair.get("repaired_pipeline"), dict) else {}
    validation = repaired_pipeline.get("validation") if isinstance(repaired_pipeline.get("validation"), dict) else runtime.validate_shadow_manifest()
    contracts = repaired_pipeline.get("contracts") if isinstance(repaired_pipeline.get("contracts"), dict) else {}
    smoke = repaired_pipeline.get("smoke") if isinstance(repaired_pipeline.get("smoke"), dict) else {}
    replay = repaired_pipeline.get("replay") if isinstance(repaired_pipeline.get("replay"), dict) else {}
    return _kernel_runtime_response(
        ok=bool(repair.get("ok")),
        detail="shadow auto-repair 已执行。",
        validation=validation,
        contracts=contracts,
        smoke=smoke,
        replay=replay,
        repair=repair,
    )


@app.post("/api/kernel/shadow/patch-worker", response_model=KernelRuntimeResponse)
def kernel_shadow_patch_worker(req: KernelShadowPatchWorkerRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    repair_run = _find_repair_run(req.repair_run_id)
    if not isinstance(repair_run, dict):
        return _kernel_runtime_response(
            ok=False,
            detail="未找到可执行 patch worker 的 repair run。",
        )
    replay_source_run_id = req.replay_run_id or str((repair_run.get("repaired_pipeline") or {}).get("replay_source_run_id") or "").strip() or None
    replay_record = _find_shadow_replay_record(replay_source_run_id)
    patch_worker = runtime.run_shadow_patch_worker(
        repair_run=repair_run,
        replay_record=replay_record if isinstance(replay_record, dict) else None,
        max_tasks=req.max_tasks,
        max_rounds=req.max_rounds,
        auto_package_on_success=bool(req.auto_package_on_success),
        promote_if_healthy=req.promote_if_healthy,
    )
    pipeline = patch_worker.get("pipeline") if isinstance(patch_worker.get("pipeline"), dict) else {}
    validation = pipeline.get("validation") if isinstance(pipeline.get("validation"), dict) else runtime.validate_shadow_manifest()
    contracts = pipeline.get("contracts") if isinstance(pipeline.get("contracts"), dict) else {}
    smoke = pipeline.get("smoke") if isinstance(pipeline.get("smoke"), dict) else {}
    replay = pipeline.get("replay") if isinstance(pipeline.get("replay"), dict) else {}
    return _kernel_runtime_response(
        ok=bool(patch_worker.get("ok")),
        detail="shadow patch worker 已执行。",
        validation=validation,
        contracts=contracts,
        smoke=smoke,
        replay=replay,
        pipeline=pipeline,
        patch_worker=patch_worker,
    )


@app.post("/api/kernel/shadow/package", response_model=KernelRuntimeResponse)
def kernel_shadow_package(req: KernelShadowPackageRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    package_run = runtime.package_shadow_modules(
        labels=req.labels,
        package_note=req.package_note,
        source_run_id=str(req.source_run_id or ""),
        repair_run_id=str(req.repair_run_id or ""),
        patch_worker_run_id=str(req.patch_worker_run_id or ""),
        runtime_profile=req.runtime_profile,
    )
    validation = package_run.get("validation") if isinstance(package_run.get("validation"), dict) else runtime.validate_shadow_manifest()
    return _kernel_runtime_response(
        ok=bool(package_run.get("ok")),
        detail="shadow modules 已打包为正式版本。" if package_run.get("ok") else "shadow modules 打包失败。",
        validation=validation,
        pipeline={"package_run": package_run},
    )


@app.post("/api/kernel/shadow/self-upgrade", response_model=KernelRuntimeResponse)
def kernel_shadow_self_upgrade(req: KernelShadowSelfUpgradeRequest) -> KernelRuntimeResponse:
    runtime = get_kernel_runtime()
    base_upgrade_run = _find_upgrade_run(req.upgrade_run_id)
    if not isinstance(base_upgrade_run, dict):
        return _kernel_runtime_response(
            ok=False,
            detail="未找到可执行 self-upgrade 的 upgrade run。",
        )
    replay_source_run_id = req.replay_run_id or str(base_upgrade_run.get("replay_source_run_id") or "").strip() or None
    replay_record = _find_shadow_replay_record(replay_source_run_id)
    self_upgrade = runtime.run_shadow_self_upgrade(
        base_upgrade_run=base_upgrade_run,
        replay_record=replay_record if isinstance(replay_record, dict) else None,
        smoke_message=req.smoke_message,
        validate_provider=req.validate_provider,
        max_attempts=req.max_attempts,
        max_tasks=req.max_tasks,
        max_rounds=req.max_rounds,
        promote_if_healthy=bool(req.promote_if_healthy),
    )
    final_pipeline = self_upgrade.get("final_pipeline") if isinstance(self_upgrade.get("final_pipeline"), dict) else {}
    validation = final_pipeline.get("validation") if isinstance(final_pipeline.get("validation"), dict) else runtime.validate_shadow_manifest()
    contracts = final_pipeline.get("contracts") if isinstance(final_pipeline.get("contracts"), dict) else {}
    smoke = final_pipeline.get("smoke") if isinstance(final_pipeline.get("smoke"), dict) else {}
    replay = final_pipeline.get("replay") if isinstance(final_pipeline.get("replay"), dict) else {}
    return _kernel_runtime_response(
        ok=bool(self_upgrade.get("ok")),
        detail="shadow self-upgrade 已执行。",
        validation=validation,
        contracts=contracts,
        smoke=smoke,
        replay=replay,
        pipeline={"self_upgrade": self_upgrade},
        repair=self_upgrade.get("repair") if isinstance(self_upgrade.get("repair"), dict) else {},
        patch_worker=self_upgrade.get("patch_worker") if isinstance(self_upgrade.get("patch_worker"), dict) else {},
    )


@app.post("/api/session/new", response_model=NewSessionResponse)
def create_session(req: NewSessionRequest | None = None) -> NewSessionResponse:
    project = _resolve_project_or_default((req.project_id if req else None))
    get_project_store().touch(str(project.get("project_id") or ""))
    session = session_store.create(project)
    return NewSessionResponse(session_id=session["id"], project_id=str(project.get("project_id") or ""))


@app.delete("/api/session/{session_id}", response_model=DeleteSessionResponse)
def delete_session(session_id: str) -> DeleteSessionResponse:
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return DeleteSessionResponse(ok=True, session_id=session_id)


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
def get_session(session_id: str, max_turns: int = 200) -> SessionDetailResponse:
    loaded = session_store.load(session_id, default_project=_default_project())
    if not loaded:
        raise HTTPException(status_code=404, detail="Session not found")

    turns_raw = loaded.get("turns", [])
    if not isinstance(turns_raw, list):
        turns_raw = []
    limited_turns = turns_raw[-max(1, min(2000, max_turns)) :]
    turns: list[SessionTurn] = []
    for item in limited_turns:
        if not isinstance(item, dict):
            continue
        turns.append(
            SessionTurn(
                role=str(item.get("role") or "user"),
                text=str(item.get("text") or ""),
                answer_bundle=item.get("answer_bundle") or {},
                created_at=str(item.get("created_at")) if item.get("created_at") else None,
            )
        )

    return SessionDetailResponse(
        session_id=session_id,
        title=str(loaded.get("title") or ""),
        summary=str(loaded.get("summary") or ""),
        turn_count=len(turns_raw),
        project_id=str(loaded.get("project_id") or ""),
        project_title=str(loaded.get("project_title") or ""),
        project_root=str(loaded.get("project_root") or ""),
        git_branch=str(loaded.get("git_branch") or ""),
        cwd=str(loaded.get("cwd") or ""),
        agent_state=dict(loaded.get("agent_state") or {}),
        turns=turns,
    )


@app.get("/api/sessions", response_model=SessionListResponse)
def list_sessions(limit: int = 50, project_id: str | None = None) -> SessionListResponse:
    rows = session_store.list_sessions(limit=limit, project_id=project_id, default_project=_default_project())
    return SessionListResponse(sessions=[SessionListItem(**row) for row in rows])


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    meta = await upload_store.save_upload(file)
    max_bytes = config.max_upload_mb * 1024 * 1024
    if meta["size"] > max_bytes:
        upload_store.delete(meta["id"])
        raise HTTPException(status_code=413, detail=f"File too large (>{config.max_upload_mb}MB)")

    return UploadResponse(
        id=meta["id"],
        name=meta["original_name"],
        mime=meta["mime"],
        size=meta["size"],
        kind=meta["kind"],
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
    try:
        return _process_chat_request(req)
    except HTTPException as exc:
        payload = _normalize_chat_error_payload(exc.detail, status_code=exc.status_code)
        raise HTTPException(status_code=int(payload["status_code"]), detail=payload) from exc
    except Exception as exc:
        payload = _normalize_chat_error_payload(exc)
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
    tools = get_agent_os_runtime().legacy_tools()
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


@app.post("/api/evals/run", response_model=EvalRunResponse)
def run_evals(req: EvalRunRequest) -> EvalRunResponse:
    run_id = str(uuid.uuid4())
    summary = run_regression_evals(
        include_optional=bool(req.include_optional),
        name_filter=str(req.name_filter or "").strip(),
    )
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    skipped = int(summary.get("skipped") or 0)
    total = int(summary.get("total") or 0)
    duration_ms = int(summary.get("duration_ms") or 0)
    summary_text = (
        f"回归测试通过：passed={passed}, failed={failed}, skipped={skipped}, total={total}"
        if failed == 0
        else f"回归测试失败：passed={passed}, failed={failed}, skipped={skipped}, total={total}"
    )
    return EvalRunResponse(
        ok=bool(summary.get("ok")),
        run_id=run_id,
        include_optional=bool(summary.get("include_optional")),
        name_filter=str(summary.get("name_filter") or ""),
        cases_path=str(summary.get("cases_path") or ""),
        passed=passed,
        failed=failed,
        skipped=skipped,
        total=total,
        duration_ms=duration_ms,
        summary=summary_text,
        results=[EvalCaseResult(**item) for item in summary.get("results") or [] if isinstance(item, dict)],
    )


def _emit_progress(progress_cb: Callable[[dict[str, Any]], None] | None, event: str, **payload: Any) -> None:
    if not progress_cb:
        return
    try:
        progress_cb({"event": event, **payload})
    except Exception:
        pass


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


def _normalize_chat_error_payload(detail: Any, *, status_code: int | None = None) -> dict[str, Any]:
    if isinstance(detail, dict) and {"kind", "summary", "detail"}.issubset(detail.keys()):
        normalized = dict(detail)
        normalized["status_code"] = _coerce_int(normalized.get("status_code")) or _coerce_int(status_code) or 500
        normalized["detail"] = _stringify_error_detail(normalized.get("detail"))
        normalized["summary"] = str(normalized.get("summary") or "请求失败，请稍后重试。")
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
        summary = "模型提供方限流，请稍后重试。"
        retryable = True
        resolved_status = 429
    elif extracted_status in {401, 403} or "unauthorized" in lowered or "forbidden" in lowered or "api key" in lowered or "credentials" in lowered or "authentication" in lowered:
        kind = "auth"
        summary = "认证失败，请检查 OpenRouter / OpenAI-compatible key。"
        retryable = False
        resolved_status = extracted_status or 401
    elif extracted_status in {502, 503, 504} or "temporarily unavailable" in lowered or "timeout" in lowered or "timed out" in lowered or "upstream" in lowered:
        kind = "upstream"
        summary = "模型提供方暂时不可用，请稍后重试。"
        retryable = True
        resolved_status = extracted_status or 503
    else:
        kind = "unknown"
        summary = "请求失败，请稍后重试或查看错误详情。"
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
    requested_provider = _resolve_requested_provider(req)
    provider_config, provider_runtime = _provider_runtime(requested_provider)
    req.settings.provider = requested_provider
    if req.mode_override:
        req.settings.collaboration_mode = req.mode_override
    auth_summary = OpenAIAuthManager(provider_config).auth_summary()
    if not bool(auth_summary.get("available")):
        fallback_goal = str(req.message or "").strip()[:160]
        requested_project = _resolve_project_or_default(req.project_id)
        seed_session = session_store.load_or_create(
            req.session_id,
            project=requested_project,
            default_project=_default_project(),
        )
        fallback_text = (
            "当前还没有可用的模型认证。请在 Settings 里补充当前 provider 的 API key，"
            "或切换到一个已经配置好的 provider 后再继续。"
        )
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
        seed_session["agent_state"] = {
            "goal": fallback_goal,
            "collaboration_mode": str(req.settings.collaboration_mode or "default"),
            "turn_status": "blocked",
            "plan": [],
            "pending_user_input": {},
            "phase": "report",
            "last_run_id": "",
            "last_model": "",
            "cwd": str(seed_session.get("project_root") or ""),
            "task_checkpoint": {},
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
                },
                "token_usage": {"total_tokens": 0},
                "loaded_skills": [],
            },
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
        detail=f"后端已接收请求，开始处理。run_id={run_id}, auth_mode={auth_summary.get('mode')}",
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
                    message=f"当前会话存在并发请求，已排队等待 {queue_wait_ms} ms。",
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
                    message="检测到当前任务焦点切换，本轮会刷新 current_task_focus，但继续保留 thread 记忆。",
                    run_id=run_id,
                )
            _emit_progress(
                progress_cb,
                "stage",
                code="session_ready",
                phase="bootstrap",
                label="Session",
                status="completed",
                detail=f"会话已就绪: {session.get('id')}",
                run_id=run_id,
                queue_wait_ms=queue_wait_ms,
                run_snapshot=_build_run_snapshot(
                    goal=req.message,
                    current_task_focus=session_context_impl.get_current_task_focus(session),
                    collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                    turn_status="running",
                    cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
                ),
            )
        history_turns_before = copy.deepcopy(session.get("turns", []))
        summary_before = str(session.get("summary", "") or "")
        agent_os = get_agent_os_runtime()
        summarized = agent_os.maybe_compact_session(session, req.settings.max_context_turns)
        if summarized:
            _emit_progress(progress_cb, "trace", message="历史上下文已自动压缩摘要。", run_id=run_id)
        session_context_impl.sync_session_memory_state(session)

        runtime = get_kernel_runtime()
        attachment_registry = runtime.registry
        attachment_module = attachment_registry.attachment_context
        attachment_selected_ref = str((attachment_registry.selected_refs or {}).get("attachment_context") or "")
        attachment_fallback_ref = "attachment_context@1.0.0"
        try:
            attachment_context = attachment_module.resolve_attachment_context(
                session=session,
                message=req.message,
                requested_attachment_ids=req.attachment_ids,
            )
            runtime.record_module_success(
                kind="attachment_context",
                selected_ref=attachment_selected_ref or attachment_fallback_ref,
            )
        except Exception as exc:
            runtime.record_module_failure(
                kind="attachment_context",
                requested_ref=attachment_selected_ref or attachment_fallback_ref,
                fallback_ref=attachment_fallback_ref,
                error=str(exc),
            )
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
        _emit_progress(
            progress_cb,
            "stage",
            code="attachments_ready",
            phase="explore",
            label="Attachments",
            status="completed",
            detail=(
                f"附件检查完成: mode={attachment_context_mode}, "
                f"请求 {len(effective_attachment_ids)} 个，命中 {len(attachments)} 个。"
            ),
            run_id=run_id,
            run_snapshot=_build_run_snapshot(
                goal=req.message,
                current_task_focus=session_context_impl.get_current_task_focus(session),
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str(session.get("cwd") or session_project.get("root_path") or ""),
            ),
        )
        found_attachment_ids = {str(item.get("id")) for item in attachments if item.get("id")}
        missing_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id not in found_attachment_ids]
        resolved_attachment_ids = [file_id for file_id in effective_attachment_ids if file_id in found_attachment_ids]
        try:
            attachment_module.apply_attachment_context_result(
                session=session,
                resolved_attachment_ids=resolved_attachment_ids,
                attachment_context_mode=attachment_context_mode,
                clear_attachment_context=clear_attachment_context,
                requested_attachment_ids=requested_attachment_ids,
            )
            runtime.record_module_success(
                kind="attachment_context",
                selected_ref=attachment_selected_ref or attachment_fallback_ref,
            )
        except Exception as exc:
            runtime.record_module_failure(
                kind="attachment_context",
                requested_ref=attachment_selected_ref or attachment_fallback_ref,
                fallback_ref=attachment_fallback_ref,
                error=str(exc),
            )
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
        try:
            route_state_input, route_state_scope = attachment_module.resolve_scoped_route_state(
                session=session,
                attachment_ids=resolved_attachment_ids,
            )
            runtime.record_module_success(
                kind="attachment_context",
                selected_ref=attachment_selected_ref or attachment_fallback_ref,
            )
        except Exception as exc:
            runtime.record_module_failure(
                kind="attachment_context",
                requested_ref=attachment_selected_ref or attachment_fallback_ref,
                fallback_ref=attachment_fallback_ref,
                error=str(exc),
            )
            route_state_input, route_state_scope = session_context_impl.resolve_scoped_route_state(
                session,
                attachment_ids=resolved_attachment_ids,
            )
        route_state_input = session_context_impl.prepare_route_state_for_turn(
            route_state_input,
            reset_focus=focus_shift_requested,
        )
        route_state_scope = "focus_reset" if focus_shift_requested and route_state_scope == "session" else route_state_scope
        history_turns_for_runtime = copy.deepcopy(session.get("turns", []))
        summary_for_runtime = session.get("summary", "")
        thread_memory_for_runtime = copy.deepcopy(session_context_impl.get_thread_memory(session))
        current_task_focus_for_runtime = copy.deepcopy(session_context_impl.get_current_task_focus(session))
        recent_tasks_for_runtime = copy.deepcopy(list(thread_memory_for_runtime.get("recent_tasks") or []))
        artifact_memory_preview = copy.deepcopy(session_context_impl.get_artifact_memory_preview(session))
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
            detail="开始通过 vintage_programmer 执行。",
            run_id=run_id,
            run_snapshot=_build_run_snapshot(
                goal=req.message,
                current_task_focus=current_task_focus_for_runtime,
                collaboration_mode=req.mode_override or req.settings.collaboration_mode or "default",
                turn_status="running",
                cwd=str((current_task_focus_for_runtime or {}).get("cwd") or session.get("cwd") or session_project.get("root_path") or ""),
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
        collaboration_mode = str(runtime_result.get("collaboration_mode") or req.settings.collaboration_mode or "default")
        turn_status = str(runtime_result.get("turn_status") or "completed")
        plan = list(runtime_result.get("plan") or [])
        pending_user_input = (
            dict(runtime_result.get("pending_user_input") or {})
            if isinstance(runtime_result.get("pending_user_input"), dict)
            else {}
        )
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
            detail="模型推理结束，开始写入会话与统计。",
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
            ),
        )
        inspector_notes = list(inspector.get("notes") or [])
        if missing_attachment_ids:
            warning_msg = f"警告: {len(missing_attachment_ids)} 个附件未找到，可能已被清理或会话刷新，请重新上传。"
            inspector_notes.append(warning_msg)
            _emit_progress(progress_cb, "trace", message=warning_msg, run_id=run_id)

        auto_linked_attachment_names = [
            str(item.get("original_name") or "")
            for item in attachments
            if str(item.get("id") or "") in set(auto_linked_attachment_ids)
        ]
        if auto_linked_attachment_names:
            auto_link_msg = f"已自动关联历史附件: {', '.join(auto_linked_attachment_names[:6])}"
            inspector_notes.append(auto_link_msg)
            _emit_progress(progress_cb, "trace", message=auto_link_msg, run_id=run_id)
        elif attachment_context_mode == "cleared" and not requested_attachment_ids:
            cleared_msg = "已按用户指令清空历史附件关联。"
            inspector_notes.append(cleared_msg)
            _emit_progress(progress_cb, "trace", message=cleared_msg, run_id=run_id)
        inspector["notes"] = inspector_notes

        user_text = req.message.strip()
        if attachment_note:
            user_text = f"{user_text}\n\n[附件] {attachment_note}"

        session_store.append_turn(
            session,
            role="user",
            text=user_text,
            attachments=[{"id": item.get("id"), "name": item.get("original_name")} for item in attachments],
        )
        session_store.append_turn(session, role="assistant", text=text, answer_bundle=answer_bundle)
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
            "last_model": effective_model or req.settings.model or provider_config.default_model,
            "project_id": str(session.get("project_id") or ""),
            "project_root": str(session.get("project_root") or ""),
            "cwd": str((((inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}).get("cwd")) or session.get("cwd") or ""),
            "current_task_focus": dict(current_task_focus),
            "task_checkpoint": session_context_impl.compat_task_checkpoint_from_focus(current_task_focus),
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
        inspector_run_state["thread_memory"] = dict(thread_memory)
        inspector_run_state["recent_tasks"] = recent_tasks
        inspector_run_state["artifact_memory_preview"] = artifact_memory_preview
        inspector_run_state["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_run_state["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector["run_state"] = inspector_run_state
        inspector_session = (inspector.get("session") or {}) if isinstance(inspector.get("session"), dict) else {}
        inspector_session["current_task_focus"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["task_checkpoint"] = session_context_impl.compat_task_checkpoint_from_focus(current_task_focus)
        inspector_session["thread_memory"] = dict(thread_memory)
        inspector_session["recent_tasks"] = recent_tasks
        inspector_session["artifact_memory_preview"] = artifact_memory_preview
        inspector["session"] = inspector_session
        try:
            attachment_module.store_scoped_route_state(
                session=session,
                attachment_ids=resolved_attachment_ids,
                route_state=route_state,
            )
            runtime.record_module_success(
                kind="attachment_context",
                selected_ref=attachment_selected_ref or attachment_fallback_ref,
            )
        except Exception as exc:
            runtime.record_module_failure(
                kind="attachment_context",
                requested_ref=attachment_selected_ref or attachment_fallback_ref,
                fallback_ref=attachment_fallback_ref,
                error=str(exc),
            )
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
            detail="会话已写入本地存储。",
            run_id=run_id,
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
            ),
        )

        selected_model = effective_model or req.settings.model or provider_config.default_model
        pricing_meta = estimate_usage_cost(
            model=selected_model,
            input_tokens=token_usage.get("input_tokens", 0),
            output_tokens=token_usage.get("output_tokens", 0),
        )
        token_usage = {**token_usage, **pricing_meta}
        inspector_notes = list(inspector.get("notes") or [])
        if pricing_meta.get("pricing_known"):
            pricing_note = (
                "费用估算: "
                f"input ${pricing_meta.get('input_price_per_1m')}/1M, "
                f"output ${pricing_meta.get('output_price_per_1m')}/1M."
            )
            inspector_notes.append(pricing_note)
            _emit_progress(progress_cb, "trace", message=pricing_note, run_id=run_id)
        else:
            pricing_note = f"费用估算未启用: 当前模型 {selected_model} 未匹配价格表。"
            inspector_notes.append(pricing_note)
            _emit_progress(progress_cb, "trace", message=pricing_note, run_id=run_id)
        inspector["notes"] = inspector_notes
        inspector["token_usage"] = dict(token_usage)

        stats_snapshot = token_stats_store.add_usage(
            session_id=session["id"],
            usage=token_usage,
            model=selected_model,
        )
        _emit_progress(
            progress_cb,
            "stage",
            code="stats_saved",
            phase="report",
            label="Usage",
            status="completed",
            detail="Token 统计已更新。",
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
            evolution_note = (
                "个体覆层已更新: "
                f"intent={evolution_event.get('primary_intent') or 'standard'}"
                + (f"，terms={', '.join(evolution_terms[:3])}" if evolution_terms else "")
            )
            inspector_notes.append(evolution_note)
            _emit_progress(progress_cb, "trace", message=evolution_note, run_id=run_id)
        except Exception as exc:
            evolution_note = f"个体覆层更新失败: {exc}"
            inspector_notes.append(evolution_note)
            _emit_progress(progress_cb, "trace", message=evolution_note, run_id=run_id)
        inspector["notes"] = inspector_notes
        if config.enable_shadow_logging:
            kernel_health = build_kernel_health_payload(get_kernel_runtime())
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
                    "kernel_selected_modules": kernel_health.get("selected_modules") or {},
                    "kernel_module_health": kernel_health.get("module_health") or {},
                    "message_preview": req.message[:500],
                    "response_preview": text[:500],
                }
            )
            _emit_progress(
                progress_cb,
                "trace",
                message=f"shadow log 已写入: {shadow_path.name}",
                run_id=run_id,
            )
        session_totals_raw = stats_snapshot.get("sessions", {}).get(session["id"], {})
        global_totals_raw = stats_snapshot.get("totals", {})
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
            detail="本轮结果已准备完成。",
            run_id=run_id,
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
            ),
        )
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
    def event_stream():
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        done_event = threading.Event()

        def emit(payload: dict[str, Any]) -> None:
            event_name = str(payload.get("event") or "message")
            data = {k: v for k, v in payload.items() if k != "event"}
            events.put({"event": event_name, "payload": data})

        def worker() -> None:
            try:
                response = _process_chat_request(req, progress_cb=emit)
                events.put({"event": "final", "payload": {"response": response.model_dump()}})
            except HTTPException as exc:
                payload = _normalize_chat_error_payload(exc.detail, status_code=exc.status_code)
                events.put(
                    {
                        "event": "error",
                        "payload": payload,
                    }
                )
            except Exception as exc:
                events.put({"event": "error", "payload": _normalize_chat_error_payload(exc)})
            finally:
                done_event.set()
                events.put({"event": "done", "payload": {"ok": True}})

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
