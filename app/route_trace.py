from __future__ import annotations

from typing import Any

from app.context_assembly import AssembledContext, coerce_active_task
from app.intent_schema import ConversationFrame, IntentDecision, RequestSignals, RouteTrace


def build_signal_summary(signals: RequestSignals) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "ambiguity_score": round(float(signals.ambiguity_score or 0.0), 4),
    }
    interesting_flags = (
        "has_attachments",
        "spec_lookup_request",
        "evidence_required",
        "attachment_needs_tooling",
        "inline_parseable_attachments",
        "inline_document_payload",
        "understanding_request",
        "holistic_document_explanation",
        "source_trace_request",
        "explicit_tool_confirmation",
        "meeting_minutes_request",
        "web_news_brief_request",
        "web_request",
        "request_requires_tools",
        "local_code_lookup_request",
        "grounded_code_generation_context",
        "default_root_search",
        "translation_request",
        "task_control_request",
        "translation_followup_like",
        "translation_mode_switch_like",
        "translation_start_like",
        "translation_resume_like",
        "translation_position_reset_like",
        "short_followup_like",
        "transform_followup_like",
        "reference_followup_like",
        "context_dependent_followup",
        "inline_followup_context",
    )
    for field in interesting_flags:
        if bool(getattr(signals, field, False)):
            summary[field] = True
    if signals.inherited_primary_intent:
        summary["inherited_primary_intent"] = str(signals.inherited_primary_intent)
    return summary


def build_frame_summary(frame: ConversationFrame) -> dict[str, Any]:
    return {
        "dominant_intent": str(frame.dominant_intent or ""),
        "pending_transform": str(frame.pending_transform or ""),
        "working_set": list(frame.working_set or []),
        "active_artifacts": list(frame.active_artifacts or []),
        "active_entities": list(frame.active_entities or []),
        "current_task_type": str(frame.current_task_type or ""),
        "current_document_id": str(frame.current_document_id or ""),
        "current_document_kind": str(frame.current_document_kind or ""),
        "current_operation_mode": str(frame.current_operation_mode or ""),
        "current_position": str(frame.current_position or ""),
        "last_answer_shape": str(frame.last_answer_shape or ""),
        "last_route_policy": str(frame.last_route_policy or ""),
    }


def build_route_trace(
    *,
    request_id: str,
    timestamp: str,
    user_message: str,
    signals: RequestSignals,
    frame: ConversationFrame,
    decision: IntentDecision,
    route: dict[str, Any],
    assembled_context: AssembledContext | None = None,
    runtime_override_notes: list[str] | None = None,
    runtime_override_actions: list[str] | None = None,
) -> RouteTrace:
    excerpt = str(user_message or "").strip().replace("\n", " ")
    if len(excerpt) > 240:
        excerpt = excerpt[:237].rstrip() + "..."
    active_task_summary = ""
    if assembled_context is not None and assembled_context.active_task_summary:
        active_task_summary = str(assembled_context.active_task_summary)
    else:
        active_task = coerce_active_task(route.get("active_task"))
        if active_task is not None:
            progress = ", ".join(f"{key}={value}" for key, value in sorted((active_task.progress or {}).items())) or "none"
            active_task_summary = (
                f"task_kind={active_task.task_kind}; "
                f"target={active_task.target_type}:{active_task.target_id}; "
                f"mode={active_task.mode or 'none'}; "
                f"progress={progress}; "
                f"started={active_task.started}; finished={active_task.finished}"
            )
    active_task_kind = str(route.get("active_task_kind") or "")
    task_control_mode = str(route.get("task_control_mode") or "")
    task_control_position = str(route.get("task_control_position") or "")
    if not active_task_kind:
        active_task = coerce_active_task(route.get("active_task"))
        active_task_kind = str(active_task.task_kind if active_task is not None else decision.task_kind or "")
    if not task_control_mode:
        task_control_mode = str(decision.task_control.mode_switch or "")
    if not task_control_position:
        task_control_position = str(decision.task_control.position_reset or "")
    return RouteTrace(
        request_id=request_id,
        timestamp=timestamp,
        user_message_excerpt=excerpt,
        signal_summary=build_signal_summary(signals),
        frame_summary=build_frame_summary(frame),
        intent_candidates=[item.model_dump() for item in decision.candidates],
        top_intent=str(decision.top_intent or "standard"),
        second_intent=str(decision.second_intent or ""),
        task_kind=str(decision.task_kind or "standard"),
        sub_intent=str(decision.sub_intent or ""),
        target=str(decision.target or ""),
        active_task_summary=active_task_summary,
        task_control=decision.task_control.model_copy(),
        active_task_kind=active_task_kind,
        task_control_mode=task_control_mode,
        task_control_position=task_control_position,
        confidence=max(0.0, min(1.0, float(decision.confidence or 0.0))),
        margin=max(0.0, min(1.0, float(decision.margin or 0.0))),
        ambiguity_score=max(0.0, min(1.0, float(signals.ambiguity_score or 0.0))),
        mixed_intent=bool(decision.mixed_intent),
        requires_clarifying_route=bool(decision.requires_clarifying_route),
        requires_tools=bool(decision.requires_tools),
        requires_grounding=bool(decision.requires_grounding),
        requires_web=bool(decision.requires_web),
        requires_local_lookup=bool(decision.requires_local_lookup),
        llm_escalated=str(decision.source or "").strip().lower() == "llm",
        classifier_model=str(decision.classifier_model or ""),
        decision_source=str(decision.source or "rules"),
        escalation_reason=str(decision.escalation_reason or ""),
        chosen_execution_policy=str(route.get("execution_policy") or "standard_safe_pipeline"),
        chosen_runtime_profile=str(route.get("runtime_profile") or "evidence"),
        planner_enabled=bool(route.get("use_planner")),
        reviewer_enabled=bool(route.get("use_reviewer")),
        revision_enabled=bool(route.get("use_revision")),
        verifier_notes=list(route.get("verifier_notes") or []),
        verifier_actions=list(route.get("verifier_actions") or []),
        route_verified=bool(route.get("route_verified")),
        runtime_override_notes=list(runtime_override_notes or []),
        runtime_override_actions=list(runtime_override_actions or []),
    )


def route_trace_payload(trace: RouteTrace, *, detailed: bool) -> dict[str, Any]:
    if detailed:
        return trace.model_dump()
    return {
        "request_id": trace.request_id,
        "timestamp": trace.timestamp,
        "user_message_excerpt": trace.user_message_excerpt,
        "top_intent": trace.top_intent,
        "second_intent": trace.second_intent,
        "task_kind": trace.task_kind,
        "sub_intent": trace.sub_intent,
        "target": trace.target,
        "active_task_summary": trace.active_task_summary,
        "active_task_kind": trace.active_task_kind,
        "task_control_mode": trace.task_control_mode,
        "task_control_position": trace.task_control_position,
        "confidence": trace.confidence,
        "margin": trace.margin,
        "ambiguity_score": trace.ambiguity_score,
        "mixed_intent": trace.mixed_intent,
        "requires_clarifying_route": trace.requires_clarifying_route,
        "requires_tools": trace.requires_tools,
        "requires_grounding": trace.requires_grounding,
        "requires_web": trace.requires_web,
        "requires_local_lookup": trace.requires_local_lookup,
        "chosen_execution_policy": trace.chosen_execution_policy,
        "chosen_runtime_profile": trace.chosen_runtime_profile,
        "planner_enabled": trace.planner_enabled,
        "reviewer_enabled": trace.reviewer_enabled,
        "revision_enabled": trace.revision_enabled,
        "verifier_notes": list(trace.verifier_notes),
        "verifier_actions": list(trace.verifier_actions),
        "runtime_override_actions": list(trace.runtime_override_actions),
        "llm_escalated": trace.llm_escalated,
        "classifier_model": trace.classifier_model,
        "decision_source": trace.decision_source,
        "escalation_reason": trace.escalation_reason,
    }
