from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PrimaryIntent = Literal[
    "understanding",
    "evidence",
    "web",
    "code_lookup",
    "generation",
    "meeting_minutes",
    "qa",
    "continue_existing_task",
    "standard",
]

ActionType = Literal["answer", "search", "read", "modify", "create"]


class TaskControl(BaseModel):
    start: bool = False
    resume: bool = False
    mode_switch: str | None = None
    position_reset: str | None = None

    def is_active(self) -> bool:
        return bool(
            self.start
            or self.resume
            or str(self.mode_switch or "").strip()
            or str(self.position_reset or "").strip()
        )


class ActiveTask(BaseModel):
    task_id: str
    task_kind: str
    target_id: str
    target_type: str
    mode: str = ""
    progress: dict[str, Any] = Field(default_factory=dict)
    started: bool = False
    finished: bool = False
    last_user_control: str = ""


class RequestSignals(BaseModel):
    text: str = ""
    attachment_metas: list[dict[str, Any]] = Field(default_factory=list)
    route_state: dict[str, Any] = Field(default_factory=dict)
    inline_followup_context: bool = False
    context_dependent_followup: bool = False
    has_attachments: bool = False
    spec_lookup_request: bool = False
    evidence_required: bool = False
    attachment_needs_tooling: bool = False
    inline_parseable_attachments: bool = False
    inline_document_payload: bool = False
    understanding_request: bool = False
    holistic_document_explanation: bool = False
    source_trace_request: bool = False
    explicit_tool_confirmation: bool = False
    meeting_minutes_request: bool = False
    web_news_brief_request: bool = False
    web_request: bool = False
    request_requires_tools: bool = False
    local_code_lookup_request: bool = False
    grounded_code_generation_context: bool = False
    default_root_search: bool = False
    translation_request: bool = False
    task_control_request: bool = False
    translation_followup_like: bool = False
    translation_mode_switch_like: bool = False
    translation_start_like: bool = False
    translation_resume_like: bool = False
    translation_position_reset_like: bool = False
    inherited_primary_intent: str = ""
    short_followup_like: bool = False
    transform_followup_like: bool = False
    reference_followup_like: bool = False
    ambiguity_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["ambiguity_score"] = max(0.0, min(1.0, float(payload.get("ambiguity_score") or 0.0)))
        return payload


class IntentScore(BaseModel):
    intent: str
    score: float
    evidence: list[str] = Field(default_factory=list)


class IntentDecision(BaseModel):
    candidates: list[IntentScore] = Field(default_factory=list)
    top_intent: str = "standard"
    second_intent: str = ""
    task_kind: str = "standard"
    sub_intent: str = ""
    target: str = ""
    confidence: float = 0.0
    margin: float = 0.0
    mixed_intent: bool = False
    requires_clarifying_route: bool = False
    inherited_from_state: str = ""
    requires_tools: bool = False
    requires_grounding: bool = False
    requires_web: bool = False
    requires_local_lookup: bool = False
    needs_file_context: bool = False
    action_type: str = "answer"
    reason_short: str = ""
    source: str = "rules"
    classifier_model: str = ""
    escalation_reason: str = ""
    task_control: TaskControl = Field(default_factory=TaskControl)


class ConversationFrame(BaseModel):
    dominant_intent: str = "standard"
    working_set: list[str] = Field(default_factory=list)
    active_artifacts: list[str] = Field(default_factory=list)
    active_entities: list[str] = Field(default_factory=list)
    current_task_type: str = ""
    current_document_id: str = ""
    current_document_kind: str = ""
    current_operation_mode: str = ""
    current_position: str = ""
    pending_transform: str = ""
    last_answer_shape: str = ""
    last_route_policy: str = ""


class IntentClassification(BaseModel):
    primary_intent: PrimaryIntent = "standard"
    secondary_intents: list[str] = Field(default_factory=list)
    task_kind: str = "standard"
    sub_intent: str = ""
    target: str = ""
    requires_tools: bool = False
    requires_grounding: bool = False
    requires_web: bool = False
    requires_local_lookup: bool = False
    needs_file_context: bool = False
    action_type: ActionType = "answer"
    confidence: float = 0.7
    reason_short: str = ""
    source: str = "rules_intent_classifier"
    classifier_model: str = ""
    mixed_intent: bool = False
    inherited_from_state: str = ""
    escalation_reason: str = ""
    task_control: TaskControl = Field(default_factory=TaskControl)

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["confidence"] = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
        return payload


class RouteDecision(BaseModel):
    task_type: str = "standard"
    task_kind: str = "standard"
    sub_intent: str = ""
    target: str = ""
    complexity: Literal["low", "medium", "high"] = "medium"
    use_planner: bool = False
    use_worker_tools: bool = False
    use_reviewer: bool = False
    use_revision: bool = False
    use_structurer: bool = False
    use_web_prefetch: bool = False
    use_conflict_detector: bool = False
    specialists: list[str] = Field(default_factory=list)
    needs_llm_router: bool = False
    reason: str = ""
    summary: str = ""
    source: str = "rules"
    router_model: str = ""
    execution_policy: str = "standard_safe_pipeline"
    runtime_profile: str = "evidence"
    primary_intent: PrimaryIntent = "standard"
    secondary_intents: list[str] = Field(default_factory=list)
    requires_tools: bool = False
    requires_grounding: bool = False
    requires_web: bool = False
    requires_local_lookup: bool = False
    needs_file_context: bool = False
    action_type: ActionType = "answer"
    task_control: TaskControl = Field(default_factory=TaskControl)
    active_task: ActiveTask | None = None
    active_task_kind: str = ""
    task_control_mode: str = ""
    task_control_position: str = ""
    intent_confidence: float = 0.7
    intent_source: str = "rules_intent_classifier"
    intent_reason: str = ""
    mixed_intent: bool = False
    inherited_from_state: str = ""
    escalation_reason: str = ""
    intent_candidates: list[dict[str, Any]] = Field(default_factory=list)
    intent_margin: float = 0.0
    frame_dominant_intent: str = ""
    route_verified: bool = False
    verifier_notes: list[str] = Field(default_factory=list)
    verifier_actions: list[str] = Field(default_factory=list)
    spec_lookup_request: bool = False
    evidence_required_mode: bool = False
    default_root_search: bool = False

    def to_route_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["intent_confidence"] = max(0.0, min(1.0, float(payload.get("intent_confidence") or 0.0)))
        payload["intent_margin"] = max(0.0, min(1.0, float(payload.get("intent_margin") or 0.0)))
        return payload


class DecisionTrace(BaseModel):
    user_message_excerpt: str = ""
    signal_summary: dict[str, Any] = Field(default_factory=dict)
    frame_summary: dict[str, Any] = Field(default_factory=dict)
    intent_candidates: list[dict[str, Any]] = Field(default_factory=list)
    top_intent: str = "standard"
    second_intent: str = ""
    task_kind: str = "standard"
    sub_intent: str = ""
    target: str = ""
    active_task_summary: str = ""
    task_control: TaskControl = Field(default_factory=TaskControl)
    active_task_kind: str = ""
    task_control_mode: str = ""
    task_control_position: str = ""
    confidence: float = 0.0
    margin: float = 0.0
    ambiguity_score: float = 0.0
    mixed_intent: bool = False
    requires_clarifying_route: bool = False
    requires_tools: bool = False
    requires_grounding: bool = False
    requires_web: bool = False
    requires_local_lookup: bool = False
    llm_escalated: bool = False
    classifier_model: str = ""
    decision_source: str = "rules"
    escalation_reason: str = ""


class RouteTrace(DecisionTrace):
    request_id: str = ""
    timestamp: str = ""
    chosen_execution_policy: str = "standard_safe_pipeline"
    chosen_runtime_profile: str = "evidence"
    planner_enabled: bool = False
    reviewer_enabled: bool = False
    revision_enabled: bool = False
    verifier_notes: list[str] = Field(default_factory=list)
    verifier_actions: list[str] = Field(default_factory=list)
    route_verified: bool = False
    runtime_override_notes: list[str] = Field(default_factory=list)
    runtime_override_actions: list[str] = Field(default_factory=list)
