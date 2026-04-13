from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatSettings(BaseModel):
    provider: str | None = None
    model: str | None = None
    max_output_tokens: int = Field(default=128000, ge=120, le=128000)
    max_context_turns: int = Field(default=2000, ge=2, le=2000)
    enable_tools: bool = True
    execution_mode: Literal["host", "docker"] | None = None
    debug_raw: bool = False
    response_style: Literal["short", "normal", "long"] = "normal"


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str | None = None
    message: str = Field(min_length=1)
    attachment_ids: list[str] = Field(default_factory=list)
    settings: ChatSettings = Field(default_factory=ChatSettings)


class ToolEvent(BaseModel):
    name: str
    input: dict | None = None
    output_preview: str
    status: str = "ok"
    group: str = ""
    source: str = ""
    summary: str = ""
    source_refs: list[str] = Field(default_factory=list)
    project_root: str = ""
    cwd: str = ""
    module_id: str = ""
    module_title: str = ""
    module_group: str = ""


class DebugFlowItem(BaseModel):
    step: int
    stage: str
    title: str
    detail: str


class HookTelemetryItem(BaseModel):
    phase: str
    handler: str
    changed_fields: list[str] = Field(default_factory=list)
    route_changed: bool = False
    task_type_before: str = ""
    task_type_after: str = ""
    primary_intent_before: str = ""
    primary_intent_after: str = ""
    execution_policy_before: str = ""
    execution_policy_after: str = ""
    prompt_injection_count: int = 0
    trace_note_count: int = 0
    debug_entry_count: int = 0


class AgentPanel(BaseModel):
    role: str
    title: str
    kind: Literal["agent", "processor", "hybrid"] = "agent"
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)


class RoleRuntimeState(BaseModel):
    role: str
    status: Literal["idle", "seen", "active", "current", "done", "skipped", "failed"] = "idle"
    phase: str = ""
    detail: str = ""


class AnswerCitation(BaseModel):
    id: str
    source_type: Literal["web", "document", "codebase", "table", "tool", "other"] = "other"
    kind: Literal["evidence", "candidate"] = "evidence"
    tool: str = ""
    label: str = ""
    path: str | None = None
    url: str | None = None
    title: str | None = None
    domain: str | None = None
    locator: str | None = None
    excerpt: str = ""
    published_at: str | None = None
    warning: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"


class AnswerClaim(BaseModel):
    statement: str
    citation_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    status: Literal["supported", "partially_supported", "needs_review"] = "supported"


class AnswerBundle(BaseModel):
    summary: str = ""
    claims: list[AnswerClaim] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    estimated_cost_usd: float = 0.0
    pricing_known: bool = False
    pricing_model: str | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None


class TokenTotals(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class ChatResponse(BaseModel):
    session_id: str
    run_id: str | None = None
    agent_id: str = "vintage_programmer"
    agent_title: str = "Vintage Programmer"
    selected_business_module: str = ""
    effective_model: str | None = None
    queue_wait_ms: int = 0
    text: str
    tool_events: list[ToolEvent] = Field(default_factory=list)
    attachment_context_mode: Literal["none", "explicit", "auto_linked", "cleared"] = "none"
    effective_attachment_ids: list[str] = Field(default_factory=list)
    auto_linked_attachment_ids: list[str] = Field(default_factory=list)
    auto_linked_attachment_names: list[str] = Field(default_factory=list)
    missing_attachment_ids: list[str] = Field(default_factory=list)
    attachment_context_key: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    session_token_totals: TokenTotals = Field(default_factory=TokenTotals)
    global_token_totals: TokenTotals = Field(default_factory=TokenTotals)
    inspector: dict[str, object] = Field(default_factory=dict)
    turn_count: int
    summarized: bool = False


class UploadResponse(BaseModel):
    id: str
    name: str
    mime: str
    size: int
    kind: Literal["image", "document", "other"]


class NewSessionResponse(BaseModel):
    session_id: str
    project_id: str = ""


class NewSessionRequest(BaseModel):
    project_id: str | None = None


class UpdateSessionTitleRequest(BaseModel):
    title: str = Field(default="", max_length=120)


class UpdateSessionTitleResponse(BaseModel):
    ok: bool
    session_id: str
    title: str = ""


class DeleteSessionResponse(BaseModel):
    ok: bool
    session_id: str


class SessionTurn(BaseModel):
    role: str
    text: str
    answer_bundle: AnswerBundle = Field(default_factory=AnswerBundle)
    created_at: str | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    title: str = ""
    summary: str = ""
    turn_count: int = 0
    project_id: str = ""
    project_title: str = ""
    project_root: str = ""
    git_branch: str = ""
    cwd: str = ""
    agent_state: dict[str, object] = Field(default_factory=dict)
    turns: list[SessionTurn] = Field(default_factory=list)


class SessionListItem(BaseModel):
    session_id: str
    title: str = ""
    has_custom_title: bool = False
    preview: str = ""
    turn_count: int = 0
    project_id: str = ""
    project_title: str = ""
    project_root: str = ""
    git_branch: str = ""
    cwd: str = ""
    updated_at: str = ""
    created_at: str = ""


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem] = Field(default_factory=list)


class ProjectDescriptor(BaseModel):
    project_id: str
    title: str
    root_path: str
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""
    pinned: bool = False
    is_default: bool = False
    git_root: str = ""
    git_branch: str = ""
    is_worktree: bool = False


class ProjectListResponse(BaseModel):
    projects: list[ProjectDescriptor] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="", max_length=120)


class ProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class ProjectDeleteResponse(BaseModel):
    ok: bool
    project_id: str


class ToolDescriptor(BaseModel):
    name: str
    group: str
    source: str
    enabled: bool = True
    read_only: bool = False
    requires_evidence: bool = False
    summary: str = ""


class SkillDescriptor(BaseModel):
    id: str
    title: str
    path: str
    enabled: bool = False
    bind_to: list[str] = Field(default_factory=list)
    summary: str = ""
    validation_status: str = "valid"
    content: str = ""


class SpecDescriptor(BaseModel):
    name: str
    path: str
    editable: bool = True
    validation_status: str = "valid"
    content: str = ""


class WorkbenchToolsResponse(BaseModel):
    tools: list[ToolDescriptor] = Field(default_factory=list)


class WorkbenchSkillsResponse(BaseModel):
    skills: list[SkillDescriptor] = Field(default_factory=list)


class WorkbenchSpecsResponse(BaseModel):
    specs: list[SpecDescriptor] = Field(default_factory=list)


class SkillUpsertRequest(BaseModel):
    content: str = Field(min_length=1)


class ToggleSkillRequest(BaseModel):
    enabled: bool | None = None


class SpecUpsertRequest(BaseModel):
    content: str = Field(min_length=1)


class HealthResponse(BaseModel):
    ok: bool
    app_title: str = ""
    app_version: str = ""
    build_version: str = ""
    default_model: str = ""
    model_options: list[str] = Field(default_factory=list)
    allow_custom_model: bool = True
    llm_provider: str = ""
    provider_options: list[dict[str, object]] = Field(default_factory=list)
    auth_mode: str = ""
    execution_mode_default: Literal["host", "docker"] = "host"
    docker_available: bool = False
    docker_message: str | None = None
    platform_name: str = ""
    workspace_root: str = ""
    allowed_roots: list[str] = Field(default_factory=list)
    max_upload_mb: int = 0
    web_allow_all_domains: bool = True
    web_allowed_domains: list[str] = Field(default_factory=list)
    default_project_id: str = ""
    projects: list[ProjectDescriptor] = Field(default_factory=list)
    runtime_status: dict[str, object] = Field(default_factory=dict)
    agent: dict[str, object] = Field(default_factory=dict)


class KernelManifestUpdateRequest(BaseModel):
    router: str | None = None
    policy: str | None = None
    attachment_context: str | None = None
    finalizer: str | None = None
    tool_registry: str | None = None
    providers: dict[str, str] = Field(default_factory=dict)


class KernelShadowSmokeRequest(BaseModel):
    message: str = "给我今天的新闻"
    validate_provider: bool = True


class KernelShadowReplayRequest(BaseModel):
    run_id: str | None = None


class KernelShadowPipelineRequest(BaseModel):
    router: str | None = None
    policy: str | None = None
    attachment_context: str | None = None
    finalizer: str | None = None
    tool_registry: str | None = None
    providers: dict[str, str] = Field(default_factory=dict)
    smoke_message: str = "给我今天的新闻"
    validate_provider: bool = True
    replay_run_id: str | None = None
    promote_if_healthy: bool = False


class KernelShadowAutoRepairRequest(BaseModel):
    upgrade_run_id: str | None = None
    replay_run_id: str | None = None
    smoke_message: str | None = None
    validate_provider: bool | None = None
    promote_if_healthy: bool | None = None
    max_attempts: int = 1


class KernelShadowPatchWorkerRequest(BaseModel):
    repair_run_id: str | None = None
    replay_run_id: str | None = None
    max_tasks: int = 1
    max_rounds: int = 2
    auto_package_on_success: bool = True
    promote_if_healthy: bool | None = None


class KernelShadowPackageRequest(BaseModel):
    labels: list[str] = Field(default_factory=list)
    package_note: str = ""
    source_run_id: str | None = None
    repair_run_id: str | None = None
    patch_worker_run_id: str | None = None
    runtime_profile: str = ""


class KernelShadowSelfUpgradeRequest(BaseModel):
    upgrade_run_id: str | None = None
    replay_run_id: str | None = None
    smoke_message: str | None = None
    validate_provider: bool | None = None
    max_attempts: int = 1
    max_tasks: int = 1
    max_rounds: int = 2
    promote_if_healthy: bool = True


class KernelRuntimeResponse(BaseModel):
    ok: bool
    detail: str = ""
    validation: dict[str, object] = Field(default_factory=dict)
    contracts: dict[str, object] = Field(default_factory=dict)
    smoke: dict[str, object] = Field(default_factory=dict)
    replay: dict[str, object] = Field(default_factory=dict)
    pipeline: dict[str, object] = Field(default_factory=dict)
    repair: dict[str, object] = Field(default_factory=dict)
    patch_worker: dict[str, object] = Field(default_factory=dict)
    kernel_active_manifest: dict[str, object] = Field(default_factory=dict)
    kernel_shadow_manifest: dict[str, object] = Field(default_factory=dict)
    kernel_shadow_validation: dict[str, object] = Field(default_factory=dict)
    kernel_shadow_promote_check: dict[str, object] = Field(default_factory=dict)
    kernel_rollback_pointer: dict[str, object] = Field(default_factory=dict)
    kernel_last_shadow_run: dict[str, object] = Field(default_factory=dict)
    kernel_last_upgrade_run: dict[str, object] = Field(default_factory=dict)
    kernel_last_repair_run: dict[str, object] = Field(default_factory=dict)
    kernel_last_patch_worker_run: dict[str, object] = Field(default_factory=dict)
    kernel_last_package_run: dict[str, object] = Field(default_factory=dict)
    kernel_selected_modules: dict[str, str] = Field(default_factory=dict)
    kernel_module_health: dict[str, dict[str, object]] = Field(default_factory=dict)
    kernel_runtime_files: dict[str, str] = Field(default_factory=dict)
    kernel_tool_registry: dict[str, object] = Field(default_factory=dict)
    assistant_overlay_profile: dict[str, object] = Field(default_factory=dict)
    assistant_evolution_recent: list[dict[str, object]] = Field(default_factory=list)


class EvolutionRuntimeResponse(BaseModel):
    ok: bool
    detail: str = ""
    assistant_overlay_profile: dict[str, object] = Field(default_factory=dict)
    assistant_evolution_recent: list[dict[str, object]] = Field(default_factory=list)


class RoleLabRuntimeResponse(BaseModel):
    ok: bool
    detail: str = ""
    role_lab_runtime: dict[str, object] = Field(default_factory=dict)


class AgentPluginInfo(BaseModel):
    plugin_id: str
    title: str
    description: str = ""
    sprite_role: str = "worker"
    supports_swarm: bool = False
    swarm_mode: str = "none"
    swarm_role: str = "leaf"
    swarm_enabled_by_default: bool = False
    swarm_max_depth: int = 1
    swarm_max_children: int = 1
    swarm_join_policy: str = "none"
    swarm_failure_policy: str = "none"
    swarm_children: list[dict[str, Any]] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    tool_profile: str = "none"
    allowed_tools: list[str] = Field(default_factory=list)
    max_tool_rounds: int = 0
    quality_profile: str = ""
    scope: str = ""
    stop_rules: list[str] = Field(default_factory=list)
    response_mode: str = "text"
    response_keys: list[str] = Field(default_factory=list)
    response_max_items: int = 0
    tool_expect_keywords: list[str] = Field(default_factory=list)
    tool_expect_min_calls: int = 0
    source_path: str = ""
    independent_runnable: bool = True


class AgentPluginListResponse(BaseModel):
    ok: bool
    detail: str = ""
    plugins: list[AgentPluginInfo] = Field(default_factory=list)
    tool_model: dict[str, object] = Field(default_factory=dict)


class AgentPluginRunRequest(BaseModel):
    plugin_id: str
    message: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    settings: ChatSettings = Field(default_factory=ChatSettings)
    max_tool_rounds: int | None = None


class AgentPluginRunResponse(BaseModel):
    ok: bool
    plugin_id: str
    text: str
    effective_model: str = ""
    tool_events: list[ToolEvent] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    notes: list[str] = Field(default_factory=list)
    decision: dict[str, object] = Field(default_factory=dict)


class TokenStatsResponse(BaseModel):
    totals: TokenTotals = Field(default_factory=TokenTotals)
    sessions: dict[str, TokenTotals] = Field(default_factory=dict)
    records: list[dict] = Field(default_factory=list)


class ClearStatsResponse(BaseModel):
    ok: bool


class SandboxDrillRequest(BaseModel):
    execution_mode: Literal["host", "docker"] | None = None


class SandboxDrillStep(BaseModel):
    name: str
    ok: bool
    detail: str
    duration_ms: int = 0


class SandboxDrillResponse(BaseModel):
    ok: bool
    run_id: str
    execution_mode: Literal["host", "docker"] = "host"
    docker_available: bool = False
    docker_message: str | None = None
    summary: str = ""
    steps: list[SandboxDrillStep] = Field(default_factory=list)


class EvalRunRequest(BaseModel):
    include_optional: bool = False
    name_filter: str = ""


class EvalCaseResult(BaseModel):
    name: str
    kind: str | None = None
    status: Literal["passed", "failed", "skipped"]
    reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class EvalRunResponse(BaseModel):
    ok: bool
    run_id: str
    include_optional: bool = False
    name_filter: str = ""
    cases_path: str = ""
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    total: int = 0
    duration_ms: int = 0
    summary: str = ""
    results: list[EvalCaseResult] = Field(default_factory=list)
