from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatSettings(BaseModel):
    provider: str | None = None
    model: str | None = None
    locale: str = "ja-JP"
    max_output_tokens: int = Field(default=128000, ge=120, le=128000)
    max_context_turns: int = Field(default=2000, ge=2, le=2000)
    enable_tools: bool = True
    execution_mode: Literal["host", "docker"] | None = None
    collaboration_mode: Literal["default", "plan", "execute"] = "default"
    debug_raw: bool = False
    response_style: Literal["short", "normal", "long"] = "normal"


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str | None = None
    message: str = Field(min_length=1)
    attachment_ids: list[str] = Field(default_factory=list)
    mode_override: Literal["default", "plan", "execute"] | None = None
    user_input_response: dict[str, Any] = Field(default_factory=dict)
    settings: ChatSettings = Field(default_factory=ChatSettings)


class ToolEvent(BaseModel):
    name: str
    input: dict | None = None
    raw_arguments: Any = None
    arguments_preview: str = ""
    preview_error: str = ""
    schema_validation: dict[str, Any] = Field(default_factory=dict)
    output_preview: str
    result_preview: Any = None
    status: str = "ok"
    group: str = ""
    source: str = ""
    summary: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    project_root: str = ""
    cwd: str = ""
    module_id: str = ""
    module_title: str = ""
    module_group: str = ""


class HighLevelProposal(BaseModel):
    intent: str = ""
    task_type: str = "standard"
    current_goal: str = ""
    expects_tools: bool = False
    response_mode: str = "direct_answer"
    user_stage: str = ""
    summary: str = ""
    next_step_hint: str = ""
    change_summary_requested: bool = False
    source: str = "model"


class ValidatedNextStep(BaseModel):
    step_index: int = 0
    action_type: str = "direct_answer"
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_names: list[str] = Field(default_factory=list)
    approved_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    blocked_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    accepted: bool = True
    normalization: str = ""
    validation: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    response_mode: str = "direct_answer"
    task_type: str = "standard"
    current_goal: str = ""
    change_summary_requested: bool = False
    source: str = "harness"


class ExecutionTraceEntry(BaseModel):
    step_index: int = 0
    action_type: str = "direct_answer"
    status: str = "completed"
    title: str = ""
    tool_name: str = ""
    tool_names: list[str] = Field(default_factory=list)
    result_summary: str = ""
    observation_summary: str = ""
    error: str = ""
    detail: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceEventPayload(BaseModel):
    id: str = ""
    run_id: str = ""
    type: str = ""
    title: str = ""
    detail: str = ""
    status: str = "running"
    timestamp: float = 0.0
    duration_ms: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    visible: bool = True


class MessageActivity(BaseModel):
    run_id: str = ""
    status: str = "idle"
    started_at: float = 0.0
    finished_at: float = 0.0
    run_duration_ms: int = 0
    activity_summary: str = ""
    trace_events: list[TraceEventPayload] = Field(default_factory=list)


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


class ContextMeter(BaseModel):
    estimated_tokens: int = 0
    estimated_payload_tokens: int = 0
    overhead_tokens: int = 0
    context_window: int = 0
    auto_compact_token_limit: int = 0
    used_ratio: float = 0.0
    remaining_ratio: float = 0.0
    used_percent: int = 0
    remaining_percent: int = 100
    threshold_source: str = ""
    context_window_known: bool = False
    compaction_enabled: bool = False
    last_compacted_at: str = ""
    warning: str = ""


class CompactionStatus(BaseModel):
    enabled: bool = False
    mode: str = ""
    replacement_history_mode: bool = False
    generation: int = 0
    compacted_history_present: bool = False
    compacted_history_chars: int = 0
    compacted_until_turn_id: str = ""
    retained_turn_ids: list[str] = Field(default_factory=list)
    retained_turn_count: int = 0
    estimated_context_tokens: int = 0
    estimated_payload_tokens: int = 0
    effective_context_window: int = 0
    auto_compact_token_limit: int = 0
    threshold_source: str = ""
    context_window_known: bool = False
    last_compacted_at: str = ""
    last_compaction_reason: str = ""
    last_compaction_phase: str = ""
    warning: str = ""


class ChatResponse(BaseModel):
    session_id: str
    thread_id: str | None = None
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
    collaboration_mode: Literal["default", "plan", "execute"] = "default"
    turn_status: str = "completed"
    plan: list[dict[str, Any]] = Field(default_factory=list)
    pending_user_input: dict[str, Any] = Field(default_factory=dict)
    current_task_focus: dict[str, Any] = Field(default_factory=dict)
    recent_tasks: list[dict[str, Any]] = Field(default_factory=list)
    activity: MessageActivity = Field(default_factory=MessageActivity)
    context_meter: ContextMeter = Field(default_factory=ContextMeter)
    compaction_status: CompactionStatus = Field(default_factory=CompactionStatus)
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
    upload_status: str = "stored"
    bytes_written: int = 0
    duration_ms: int = 0
    metadata_index_mode: str = ""


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
    id: str = ""
    role: str
    text: str
    answer_bundle: AnswerBundle = Field(default_factory=AnswerBundle)
    activity: MessageActivity = Field(default_factory=MessageActivity)
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
    context_meter: ContextMeter = Field(default_factory=ContextMeter)
    compaction_status: CompactionStatus = Field(default_factory=CompactionStatus)
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


class ThreadDetailResponse(BaseModel):
    thread_id: str
    session_id: str = ""
    title: str = ""
    summary: str = ""
    turn_count: int = 0
    project_id: str = ""
    project_title: str = ""
    project_root: str = ""
    git_branch: str = ""
    cwd: str = ""
    status: Literal["not_loaded", "idle", "active", "system_error"] = "idle"
    agent_state: dict[str, object] = Field(default_factory=dict)
    context_meter: ContextMeter = Field(default_factory=ContextMeter)
    compaction_status: CompactionStatus = Field(default_factory=CompactionStatus)
    turns: list[SessionTurn] = Field(default_factory=list)


class ThreadListItem(BaseModel):
    thread_id: str
    session_id: str = ""
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
    status: Literal["not_loaded", "idle", "active", "system_error"] = "idle"


class ThreadListResponse(BaseModel):
    threads: list[ThreadListItem] = Field(default_factory=list)


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
    deleted_session_count: int = 0


class NewThreadResponse(BaseModel):
    thread_id: str
    session_id: str = ""
    project_id: str = ""


class DeleteThreadResponse(BaseModel):
    ok: bool
    thread_id: str
    session_id: str = ""


class SkillDeleteResponse(BaseModel):
    ok: bool
    skill_id: str


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
    resolved_path: str = ""
    locale: str = "zh-CN"
    fallback_from_base: bool = False
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
    default_locale: str = "ja-JP"
    supported_locales: list[str] = Field(default_factory=list)
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
    ocr_status: dict[str, object] = Field(default_factory=dict)
    context_meter: ContextMeter = Field(default_factory=ContextMeter)
    compaction_status: CompactionStatus = Field(default_factory=CompactionStatus)
    agent: dict[str, object] = Field(default_factory=dict)


class BootstrapResponse(BaseModel):
    ok: bool
    app_title: str = ""
    app_version: str = ""
    build_version: str = ""
    default_locale: str = "ja-JP"
    supported_locales: list[str] = Field(default_factory=list)
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
    agent: dict[str, object] = Field(default_factory=dict)


class RuntimeStatusResponse(BaseModel):
    ok: bool
    project_id: str = ""
    project_title: str = ""
    project_root: str = ""
    git_branch: str = ""
    cwd: str = ""
    runtime_status: dict[str, object] = Field(default_factory=dict)
    ocr_status: dict[str, object] = Field(default_factory=dict)
    context_meter: ContextMeter = Field(default_factory=ContextMeter)
    compaction_status: CompactionStatus = Field(default_factory=CompactionStatus)


class KernelManifestUpdateRequest(BaseModel):
    router: str | None = None
    policy: str | None = None
    attachment_context: str | None = None
    finalizer: str | None = None
    tool_registry: str | None = None
    providers: dict[str, str] = Field(default_factory=dict)


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
