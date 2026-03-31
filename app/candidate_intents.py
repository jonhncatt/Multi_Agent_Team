from __future__ import annotations

from app.context_assembly import coerce_active_task, infer_task_control
from app.intent_schema import ConversationFrame, IntentScore, RequestSignals


_BASE_INTENTS = (
    "understanding",
    "evidence",
    "web",
    "code_lookup",
    "generation",
    "meeting_minutes",
    "continue_existing_task",
    "standard",
)


class CandidateIntentGenerator:
    def generate(
        self,
        *,
        signals: RequestSignals,
        frame: ConversationFrame,
    ) -> list[IntentScore]:
        scores: dict[str, IntentScore] = {
            intent: IntentScore(intent=intent, score=0.0, evidence=[])
            for intent in _BASE_INTENTS
        }

        if signals.source_trace_request or signals.evidence_required or signals.spec_lookup_request:
            self._bump(scores, "evidence", 0.55, "source_trace_request + evidence_lookup_context")
        if signals.web_request:
            self._bump(scores, "web", 0.60, "web_request")
        if signals.local_code_lookup_request:
            self._bump(scores, "code_lookup", 0.65, "local_code_lookup_request")
        text_value = str(signals.text or "").strip().lower()
        kernel_upgrade_request = any(
            marker in text_value
            for marker in (
                "升级",
                "进化",
                "热插拔",
                "自我修复",
                "自我更新",
                "自我升级",
                "self-upgrade",
                "self upgrade",
                "self-update",
                "self update",
                "patch_worker",
                "shadow pipeline",
                "shadow",
            )
        )
        if kernel_upgrade_request:
            self._bump(scores, "code_lookup", 0.66, "kernel_upgrade_request")
            self._bump(scores, "generation", 0.22, "kernel_upgrade_request")
        if signals.local_code_lookup_request and (signals.source_trace_request or signals.evidence_required or signals.spec_lookup_request):
            self._bump(scores, "code_lookup", 0.28, "grounded_code_lookup + evidence_competition")
        if signals.grounded_code_generation_context and (
            signals.transform_followup_like
            or signals.local_code_lookup_request
        ):
            self._bump(scores, "generation", 0.48, "grounded_code_generation_context")
        if signals.transform_followup_like and not signals.reference_followup_like:
            self._bump(scores, "generation", 0.34, "write_or_edit_request")
        if signals.transform_followup_like and signals.local_code_lookup_request:
            self._bump(scores, "generation", 0.28, "transform_followup_like + local_code_lookup_request")
        if signals.has_attachments and signals.understanding_request:
            self._bump(scores, "understanding", 0.50, "has_attachments + understanding_request")
        if signals.meeting_minutes_request:
            self._bump(scores, "meeting_minutes", 0.62, "meeting_minutes_request")

        inherited = str(frame.dominant_intent or signals.inherited_primary_intent or "").strip().lower()
        active_task = coerce_active_task(signals.route_state.get("active_task") if isinstance(signals.route_state, dict) else None)
        task_control = infer_task_control(signals.text, active_task)
        if active_task is not None and task_control.is_active():
            self._bump(scores, "continue_existing_task", 0.92, "active_task + explicit_task_control")
        if active_task is not None and active_task.task_kind == "document_translation" and signals.translation_request:
            self._bump(scores, "continue_existing_task", 0.72, "document_translation_active_task + translation_request")

        if inherited in scores and inherited != "standard" and signals.short_followup_like:
            self._bump(scores, inherited, 0.35, "inherited_dominant_intent + short_followup")

        if signals.transform_followup_like and signals.reference_followup_like:
            self._bump(scores, "generation", 0.28, "transform_followup_like + reference_followup_like")
            self._bump(scores, "understanding", 0.18, "reference_followup_like + inherited_context")

        clear_intent = any(
            (
                signals.source_trace_request,
                signals.evidence_required,
                signals.spec_lookup_request,
                signals.web_request,
                signals.local_code_lookup_request,
                kernel_upgrade_request,
                signals.meeting_minutes_request,
                (signals.has_attachments and signals.understanding_request),
            )
        )
        if signals.request_requires_tools and not clear_intent:
            self._bump(scores, "standard", 0.20, "request_requires_tools + unclear_intent")

        if signals.context_dependent_followup and inherited in scores and inherited != "standard":
            self._bump(scores, inherited, 0.18, "context_dependent_followup + inherited_intent")

        if not any(item.score > 0 for item in scores.values()):
            self._bump(scores, "standard", 0.35, "default_fallback")

        out = sorted(scores.values(), key=lambda item: item.score, reverse=True)
        for item in out:
            item.score = max(0.0, min(1.0, round(float(item.score), 4)))
        return out

    def _bump(self, scores: dict[str, IntentScore], intent: str, delta: float, evidence: str) -> None:
        current = scores[intent]
        current.score = float(current.score) + float(delta)
        note = str(evidence or "").strip()
        if note and note not in current.evidence:
            current.evidence.append(note)
