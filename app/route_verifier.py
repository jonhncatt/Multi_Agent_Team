from __future__ import annotations

from app.context_assembly import AssembledContext, coerce_active_task
from app.intent_schema import ConversationFrame, IntentDecision, RequestSignals


class RouteVerifier:
    def verify(
        self,
        *,
        decision: IntentDecision,
        route: dict[str, object],
        signals: RequestSignals,
        frame: ConversationFrame,
        assembled_context: AssembledContext | None = None,
    ) -> tuple[dict[str, object], list[str]]:
        updated = dict(route or {})
        notes: list[str] = []
        actions: list[str] = []

        if bool(decision.requires_tools) and not bool(updated.get("use_worker_tools")):
            updated["use_worker_tools"] = True
            notes.append("requires_tools=true but use_worker_tools=false; forced enable.")
            actions.append("force_enable_worker_tools")

        if bool(decision.mixed_intent) and not bool(updated.get("use_planner")):
            updated["use_planner"] = True
            notes.append("mixed_intent=true but planner was disabled; forced planner.")
            actions.append("force_enable_planner")

        top_intent = str(decision.top_intent or "").strip().lower()
        specialists = list(updated.get("specialists") or [])
        if top_intent in {"evidence", "code_lookup"} and "file_reader" not in specialists:
            notes.append(f"{top_intent} route missing file_reader specialist.")
        if top_intent == "web" and "researcher" not in specialists:
            notes.append("web route missing researcher specialist.")

        execution_policy = str(updated.get("execution_policy") or "").strip().lower()
        if execution_policy == "grounded_generation_pipeline":
            if not bool(updated.get("use_reviewer")):
                updated["use_reviewer"] = True
                notes.append("grounded generation missing reviewer; forced reviewer.")
                actions.append("force_enable_reviewer")
            if not bool(updated.get("use_revision")):
                updated["use_revision"] = True
                notes.append("grounded generation missing revision; forced revision.")
                actions.append("force_enable_revision")
            if not bool(updated.get("use_conflict_detector")):
                updated["use_conflict_detector"] = True
                notes.append("grounded generation missing conflict detector; forced enable.")
                actions.append("force_enable_conflict_detector")

        inherited_value = str(decision.inherited_from_state or "").strip().lower()
        inherited_transform = bool(
            inherited_value
            and inherited_value != "standard"
            and signals.transform_followup_like
            and signals.reference_followup_like
        )
        if inherited_transform and execution_policy == "standard_safe_pipeline":
            updated["task_type"] = "followup_transform"
            updated["execution_policy"] = "followup_transform_pipeline"
            updated["use_planner"] = True
            updated["reason"] = "verifier_followup_transform_override"
            updated["summary"] = "识别到继承态 follow-up transform，改走 followup transform pipeline。"
            notes.append("inherited followup transform routed as standard; switched to followup transform pipeline.")
            actions.append("reroute_followup_transform")

        active_task = coerce_active_task(updated.get("active_task")) or (
            assembled_context.active_task if assembled_context is not None else None
        ) or coerce_active_task((signals.route_state or {}).get("active_task") if isinstance(signals.route_state, dict) else None)
        updated["active_task_kind"] = str(updated.get("active_task_kind") or (active_task.task_kind if active_task is not None else "") or "")
        updated["task_control_mode"] = str(updated.get("task_control_mode") or decision.task_control.mode_switch or "")
        updated["task_control_position"] = str(updated.get("task_control_position") or decision.task_control.position_reset or "")
        translation_control = bool(
            active_task is not None
            and active_task.task_kind == "document_translation"
            and (
                decision.task_control.is_active()
                or bool(signals.task_control_request)
                or bool(signals.translation_request)
                or str(decision.task_kind or "").strip().lower() == "document_translation"
            )
        )
        if translation_control and execution_policy in {"standard_safe_pipeline", "task_control_pipeline"}:
            updated["task_type"] = "translation_session"
            updated["task_kind"] = "document_translation"
            updated["execution_policy"] = "translation_session_pipeline"
            updated["use_planner"] = False
            updated["use_worker_tools"] = True
            updated["use_reviewer"] = False
            updated["use_revision"] = False
            updated["use_structurer"] = False
            updated["use_web_prefetch"] = False
            updated["use_conflict_detector"] = False
            updated["reason"] = "verifier_translation_session_override"
            updated["summary"] = "识别到文档翻译连续任务控制，强制切到 translation session pipeline。"
            if active_task is not None:
                updated["active_task"] = active_task.model_dump()
                updated["target"] = str(updated.get("target") or active_task.target_id or "")
                updated["active_task_kind"] = "document_translation"
            updated["task_control_mode"] = str(updated.get("task_control_mode") or decision.task_control.mode_switch or "")
            updated["task_control_position"] = str(updated.get("task_control_position") or decision.task_control.position_reset or "")
            notes.append("document translation task control routed to safe/task control path; switched to translation session pipeline.")
            actions.append("reroute_to_translation_session_pipeline")

        updated["route_verified"] = True
        updated["verifier_notes"] = notes
        updated["verifier_actions"] = actions
        updated["frame_dominant_intent"] = str(frame.dominant_intent or updated.get("frame_dominant_intent") or "")
        return updated, notes
