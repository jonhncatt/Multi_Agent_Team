from __future__ import annotations

from typing import Any

from app.context_assembly import coerce_active_task
from app.intent_constants import SHORT_FOLLOWUP_MAX_LEN
from app.intent_schema import ConversationFrame, RequestSignals


class FrameResolver:
    def resolve(
        self,
        *,
        user_message: str,
        route_state: dict[str, Any] | None,
        signals: RequestSignals,
    ) -> ConversationFrame:
        state = dict(route_state or {})
        text = str(user_message or "").strip()

        dominant_intent = str(state.get("primary_intent") or "standard").strip().lower() or "standard"
        working_set = self._as_list(state.get("working_set"))
        active_artifacts = self._as_list(state.get("active_artifacts") or state.get("specialists"))
        active_entities = self._as_list(state.get("active_entities"))
        last_route_policy = str(state.get("last_route_policy") or state.get("execution_policy") or "").strip()
        last_answer_shape = str(state.get("last_answer_shape") or "").strip()
        active_task = coerce_active_task(state.get("active_task"))
        current_task_type = str(active_task.task_kind if active_task is not None else "").strip()
        current_document_id = str(active_task.target_id if active_task is not None else "").strip()
        current_document_kind = str(active_task.target_type if active_task is not None else "").strip()
        current_operation_mode = str(active_task.mode if active_task is not None else "").strip()
        current_position = ""
        if active_task is not None:
            current_position = str((active_task.progress or {}).get("position") or "").strip()

        if signals.inline_followup_context or signals.context_dependent_followup:
            inherited = str(state.get("primary_intent") or signals.inherited_primary_intent or "").strip().lower()
            if inherited:
                dominant_intent = inherited

        pending_transform = ""
        if signals.short_followup_like and signals.reference_followup_like and signals.transform_followup_like:
            pending_transform = "rewrite_or_transform"

        if signals.inherited_primary_intent and len(text) <= SHORT_FOLLOWUP_MAX_LEN:
            if not working_set:
                working_set = list(active_entities)
            if not dominant_intent or dominant_intent == "standard":
                dominant_intent = str(signals.inherited_primary_intent).strip().lower() or "standard"
        if active_task is not None and signals.translation_followup_like and active_task.task_kind == "document_translation":
            current_task_type = "document_translation"
            current_document_id = str(active_task.target_id or "").strip()
            current_document_kind = str(active_task.target_type or "").strip()
            current_operation_mode = str(active_task.mode or "").strip()
            current_position = str((active_task.progress or {}).get("position") or "").strip()

        return ConversationFrame(
            dominant_intent=dominant_intent or "standard",
            working_set=working_set,
            active_artifacts=active_artifacts,
            active_entities=active_entities,
            current_task_type=current_task_type,
            current_document_id=current_document_id,
            current_document_kind=current_document_kind,
            current_operation_mode=current_operation_mode,
            current_position=current_position,
            pending_transform=pending_transform,
            last_answer_shape=last_answer_shape,
            last_route_policy=last_route_policy,
        )

    def _as_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                text = str(item or "").strip()
                if text and text not in out:
                    out.append(text)
            return out[:10]
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return []
