from __future__ import annotations

import json
from typing import Any

from app.context_assembly import AssembledContext, coerce_active_task, detect_pdf_target, infer_task_control
from app.intent_constants import INTENT_HIGH_AMBIGUITY_THRESHOLD, INTENT_LOW_CONFIDENCE_THRESHOLD, INTENT_MARGIN_MIXED_THRESHOLD
from app.intent_schema import ConversationFrame, IntentDecision, IntentScore, RequestSignals, TaskControl
from app.serialization import dump_model


_ALLOWED_INTENTS = {
    "understanding",
    "evidence",
    "web",
    "code_lookup",
    "generation",
    "meeting_minutes",
    "qa",
    "continue_existing_task",
    "standard",
}
_ALLOWED_ACTION_TYPES = {"answer", "search", "read", "modify", "create"}


class IntentScorer:
    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def decide(
        self,
        *,
        candidates: list[IntentScore],
        signals: RequestSignals,
        frame: ConversationFrame,
        requested_model: str,
        user_message: str,
        summary: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        assembled_context: AssembledContext | None = None,
        force_rules_only: bool = False,
    ) -> tuple[IntentDecision, str]:
        ranked = sorted(candidates, key=lambda item: float(item.score), reverse=True)
        top = ranked[0] if ranked else IntentScore(intent="standard", score=0.0, evidence=["empty_candidates"])
        second = ranked[1] if len(ranked) > 1 else IntentScore(intent="", score=0.0, evidence=[])
        margin = max(0.0, float(top.score) - float(second.score))

        rules_decision = self._build_rules_decision(
            ranked=ranked,
            top=top,
            second=second,
            margin=margin,
            signals=signals,
            frame=frame,
            assembled_context=assembled_context,
        )
        if force_rules_only:
            return rules_decision, json.dumps(
                {
                    "source": "rules",
                    "task_kind": rules_decision.task_kind,
                    "intent": rules_decision.top_intent,
                    "task_control": dump_model(rules_decision.task_control),
                    "confidence": rules_decision.confidence,
                },
                ensure_ascii=False,
            )

        llm_decision, raw = self._decide_with_llm(
            rules_decision=rules_decision,
            ranked=ranked,
            signals=signals,
            frame=frame,
            requested_model=requested_model,
            user_message=user_message,
            summary=summary,
            attachment_metas=attachment_metas,
            settings=settings,
            assembled_context=assembled_context,
        )
        if str(llm_decision.source or "") != "llm":
            return llm_decision, raw
        if llm_decision.confidence < INTENT_LOW_CONFIDENCE_THRESHOLD and not llm_decision.task_control.is_active():
            fallback = rules_decision.model_copy(
                update={
                    "classifier_model": llm_decision.classifier_model,
                    "escalation_reason": "llm_low_confidence_fallback",
                }
            )
            return fallback, raw
        return llm_decision, raw

    def decide_rules_only(
        self,
        *,
        candidates: list[IntentScore],
        signals: RequestSignals,
        frame: ConversationFrame,
        assembled_context: AssembledContext | None = None,
    ) -> IntentDecision:
        ranked = sorted(candidates, key=lambda item: float(item.score), reverse=True)
        top = ranked[0] if ranked else IntentScore(intent="standard", score=0.0, evidence=["empty_candidates"])
        second = ranked[1] if len(ranked) > 1 else IntentScore(intent="", score=0.0, evidence=[])
        margin = max(0.0, float(top.score) - float(second.score))
        return self._build_rules_decision(
            ranked=ranked,
            top=top,
            second=second,
            margin=margin,
            signals=signals,
            frame=frame,
            assembled_context=assembled_context,
        )

    def _build_rules_decision(
        self,
        *,
        ranked: list[IntentScore],
        top: IntentScore,
        second: IntentScore,
        margin: float,
        signals: RequestSignals,
        frame: ConversationFrame,
        assembled_context: AssembledContext | None,
    ) -> IntentDecision:
        top_intent = str(top.intent or "standard").strip().lower()
        if top_intent not in _ALLOWED_INTENTS:
            top_intent = "standard"
        second_intent = str(second.intent or "").strip().lower()
        if second_intent not in _ALLOWED_INTENTS or float(second.score) <= 0.0:
            second_intent = ""

        active_task = (assembled_context.active_task if assembled_context is not None else None) or coerce_active_task(
            signals.route_state.get("active_task") if isinstance(signals.route_state, dict) else None
        )
        task_control = infer_task_control(signals.text, active_task)
        pdf_target_id, pdf_target_type = detect_pdf_target(signals.attachment_metas)
        translation_target = pdf_target_id if pdf_target_type == "pdf" else ""
        translation_request = bool(signals.translation_request)

        requires_tools = bool(
            signals.request_requires_tools
            or signals.attachment_needs_tooling
            or top_intent in {"evidence", "web", "code_lookup"}
            or (top_intent == "generation" and signals.grounded_code_generation_context)
        )
        requires_grounding = bool(
            signals.source_trace_request
            or signals.spec_lookup_request
            or signals.evidence_required
            or top_intent in {"evidence", "web"}
            or (top_intent == "generation" and signals.grounded_code_generation_context)
        )
        requires_web = bool(signals.web_request or top_intent == "web")
        requires_local_lookup = bool(
            signals.local_code_lookup_request
            or signals.default_root_search
            or signals.has_attachments
            or signals.attachment_needs_tooling
        )
        needs_file_context = bool(signals.has_attachments or active_task is not None)

        task_kind = "standard"
        sub_intent = ""
        target = ""

        if active_task is not None and task_control.is_active():
            top_intent = "continue_existing_task"
            task_kind = str(active_task.task_kind or "continue_existing_task")
            sub_intent = "task_control"
            target = str(active_task.target_id or "")
            requires_tools = True
            requires_grounding = True
            requires_local_lookup = True
            needs_file_context = True
        elif active_task is not None and active_task.task_kind == "document_translation" and translation_request:
            top_intent = "continue_existing_task"
            task_kind = "document_translation"
            sub_intent = "translation_followup"
            target = str(active_task.target_id or "")
            requires_tools = True
            requires_grounding = True
            requires_local_lookup = True
            needs_file_context = True
            if not task_control.is_active():
                task_control.resume = True
        elif translation_request and translation_target:
            task_kind = "document_translation"
            sub_intent = "translation"
            target = translation_target
            requires_tools = True
            requires_grounding = True
            requires_local_lookup = True
            needs_file_context = True
            if top_intent not in {"understanding", "generation", "continue_existing_task"}:
                top_intent = "understanding"
            if not task_control.is_active():
                task_control.start = True
        elif translation_request and active_task is None and not translation_target:
            top_intent = "standard"
            task_kind = "standard"
            sub_intent = "translation_missing_target"
            target = ""
        elif top_intent == "web":
            task_kind = "web_research"
        elif top_intent == "evidence":
            task_kind = "evidence_lookup"
        elif top_intent == "code_lookup":
            task_kind = "code_lookup"
        elif top_intent == "generation":
            task_kind = "grounded_generation" if signals.grounded_code_generation_context else "generation"
        elif top_intent == "meeting_minutes":
            task_kind = "meeting_minutes"
        elif top_intent == "qa":
            task_kind = "simple_qa"
        elif top_intent == "continue_existing_task":
            task_kind = str(active_task.task_kind if active_task is not None else "task_control")
            sub_intent = "task_control"
            target = str(active_task.target_id if active_task is not None else "")
        else:
            task_kind = "understanding" if signals.understanding_request else "standard"

        action_type = self._infer_action_type(
            top_intent=top_intent,
            requires_tools=requires_tools,
            grounded_generation=signals.grounded_code_generation_context,
            task_kind=task_kind,
        )
        mixed_intent = bool(
            float(second.score) > 0.0
            and (
                {top_intent, second_intent} in (
                    {"understanding", "generation"},
                    {"understanding", "meeting_minutes"},
                    {"evidence", "generation"},
                )
                or ({top_intent, second_intent} == {"code_lookup", "generation"} and bool(signals.transform_followup_like))
            )
        )
        confidence = max(0.0, min(1.0, float(top.score)))
        if task_kind == "document_translation":
            confidence = max(confidence, 0.84 if signals.has_attachments else 0.78)
        if top_intent == "continue_existing_task":
            confidence = max(confidence, 0.9 if task_control.is_active() else 0.78)

        text_value = str(signals.text or "").strip()
        very_short_ambiguous = bool(
            (
                len(text_value) <= 6
                or (signals.reference_followup_like and len(text_value) <= 16)
            )
            and str(signals.inherited_primary_intent or frame.dominant_intent or "").strip().lower() in {"", "standard"}
            and not any(
                (
                    signals.understanding_request,
                    signals.source_trace_request,
                    signals.spec_lookup_request,
                    signals.web_request,
                    signals.local_code_lookup_request,
                    signals.meeting_minutes_request,
                    signals.translation_request,
                )
            )
        )
        has_nonstandard_inheritance = str(signals.inherited_primary_intent or frame.dominant_intent or "").strip().lower() not in {
            "",
            "standard",
        }
        requires_clarifying_route = bool(
            confidence < INTENT_LOW_CONFIDENCE_THRESHOLD
            and not has_nonstandard_inheritance
            and (
                float(signals.ambiguity_score) >= INTENT_HIGH_AMBIGUITY_THRESHOLD
                or very_short_ambiguous
            )
        )
        if translation_request and active_task is None and not target:
            requires_clarifying_route = True
        if task_control.is_active() or task_kind == "document_translation":
            requires_clarifying_route = False

        reason_short = (
            f"rules_task_kind={task_kind}, top={top_intent}, "
            f"margin={margin:.2f}, ambiguity={float(signals.ambiguity_score):.2f}"
        )
        inherited = str(signals.inherited_primary_intent or "").strip().lower()
        if not inherited and (signals.context_dependent_followup or signals.inline_followup_context):
            inherited = str(frame.dominant_intent or "").strip().lower()
        if inherited == "standard":
            inherited = ""

        return IntentDecision(
            candidates=ranked,
            top_intent=top_intent,
            second_intent="" if second_intent == top_intent else second_intent,
            task_kind=task_kind,
            sub_intent=sub_intent,
            target=target,
            confidence=confidence,
            margin=max(0.0, min(1.0, margin)),
            mixed_intent=mixed_intent,
            requires_clarifying_route=requires_clarifying_route,
            inherited_from_state=inherited,
            requires_tools=requires_tools,
            requires_grounding=requires_grounding,
            requires_web=requires_web,
            requires_local_lookup=requires_local_lookup,
            needs_file_context=needs_file_context,
            action_type=action_type,
            reason_short=reason_short,
            source="rules",
            escalation_reason="",
            task_control=task_control,
        )

    def _decide_with_llm(
        self,
        *,
        rules_decision: IntentDecision,
        ranked: list[IntentScore],
        signals: RequestSignals,
        frame: ConversationFrame,
        requested_model: str,
        user_message: str,
        summary: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        assembled_context: AssembledContext | None,
    ) -> tuple[IntentDecision, str]:
        auth_summary = self._agent._auth_manager.auth_summary()
        if not bool(auth_summary.get("available")):
            fallback = rules_decision.model_copy(update={"escalation_reason": "llm_unavailable"})
            return fallback, json.dumps({"skipped": auth_summary.get("reason") or "openai_auth_missing"}, ensure_ascii=False)

        active_task = assembled_context.active_task if assembled_context is not None else None
        scorer_input = {
            "context_assembly": dump_model(assembled_context) if assembled_context is not None else {},
            "user_message": str(user_message or "").strip(),
            "history_summary": str(summary or "").strip(),
            "attachments": self._agent._summarize_attachment_metas_for_agents(attachment_metas),
            "enable_tools": bool(getattr(settings, "enable_tools", False)),
            "signals": signals.to_dict(),
            "frame": dump_model(frame),
            "candidates": [dump_model(item) for item in ranked[:7]],
            "rules_hints": {
                "task_kind": rules_decision.task_kind,
                "top_intent": rules_decision.top_intent,
                "second_intent": rules_decision.second_intent,
                "target": rules_decision.target,
                "task_control": dump_model(rules_decision.task_control),
                "reason_short": rules_decision.reason_short,
            },
        }
        messages = [
            self._agent._SystemMessage(
                content=(
                    "你是 Agent OS 的主意图分类器。"
                    "LLM 是主判断器，rules/candidates 只是辅助 hints。"
                    "必须优先理解 active task 和 follow-up control。"
                    "如果 active_task_summary 表明已有 document_translation 任务，"
                    "并且用户说开始/继续/逐句翻译/从第1句开始翻译，"
                    "要把它理解成 task control，而不是要求重复确认。"
                    "只输出 JSON，不要输出解释。"
                    "JSON 字段固定为 task_kind, intent, sub_intent, target, needs_tools, needs_file_context, needs_web, task_control, confidence, reason_short。"
                    "intent 只能是 understanding, evidence, web, code_lookup, generation, meeting_minutes, qa, continue_existing_task, standard。"
                    "task_control 必须包含 start, resume, mode_switch, position_reset。"
                    "confidence 范围 0~1。"
                )
            ),
            self._agent._HumanMessage(content=json.dumps(scorer_input, ensure_ascii=False)),
        ]
        try:
            ai_msg, _, effective_model, notes = self._agent._invoke_chat_with_runner(
                messages=messages,
                model=self._agent.config.summary_model or requested_model,
                max_output_tokens=600,
                enable_tools=False,
            )
            raw_text = self._agent._content_to_text(getattr(ai_msg, "content", "")).strip()
            parsed = self._agent._parse_json_object(raw_text)
            if not parsed:
                fallback = rules_decision.model_copy(
                    update={
                        "source": "rules",
                        "classifier_model": str(effective_model or "").strip(),
                        "escalation_reason": "intent_classifier_invalid_json",
                    }
                )
                return fallback, raw_text

            task_control = self._parse_task_control(parsed.get("task_control"), fallback=rules_decision.task_control)
            top_intent = self._normalize_intent(parsed.get("intent"), fallback=rules_decision.top_intent)
            task_kind = str(parsed.get("task_kind") or rules_decision.task_kind or "standard").strip().lower() or "standard"
            sub_intent = str(parsed.get("sub_intent") or rules_decision.sub_intent or "").strip()
            target = str(parsed.get("target") or rules_decision.target or "").strip()
            confidence = self._normalize_score(parsed.get("confidence"), fallback=rules_decision.confidence)
            if active_task is not None and task_control.is_active():
                top_intent = "continue_existing_task"
                if not task_kind or task_kind == "standard":
                    task_kind = str(active_task.task_kind or "continue_existing_task")
                if not target:
                    target = str(active_task.target_id or "")
            if task_kind == "document_translation" and not task_control.is_active() and signals.has_attachments:
                task_control.start = True
            if task_kind == "document_translation" and not target:
                detected_target, _ = detect_pdf_target(attachment_metas)
                target = target or detected_target
            if task_kind == "document_translation" and not target and active_task is None:
                top_intent = "standard"
                task_kind = "standard"
                sub_intent = "translation_missing_target"

            decided = IntentDecision(
                candidates=ranked,
                top_intent=top_intent,
                second_intent=rules_decision.second_intent,
                task_kind=task_kind,
                sub_intent=sub_intent,
                target=target,
                confidence=confidence,
                margin=rules_decision.margin,
                mixed_intent=bool(rules_decision.mixed_intent),
                requires_clarifying_route=bool(
                    confidence < INTENT_LOW_CONFIDENCE_THRESHOLD
                    and float(signals.ambiguity_score) >= INTENT_HIGH_AMBIGUITY_THRESHOLD
                    and not task_control.is_active()
                ),
                inherited_from_state=rules_decision.inherited_from_state,
                requires_tools=bool(parsed.get("needs_tools", rules_decision.requires_tools)),
                requires_grounding=bool(rules_decision.requires_grounding or task_kind == "document_translation"),
                requires_web=bool(parsed.get("needs_web", rules_decision.requires_web)),
                requires_local_lookup=bool(parsed.get("needs_file_context", rules_decision.needs_file_context) or rules_decision.requires_local_lookup),
                needs_file_context=bool(parsed.get("needs_file_context", rules_decision.needs_file_context)),
                action_type=self._normalize_action_type(parsed.get("action_type"), fallback=rules_decision.action_type),
                reason_short=str(parsed.get("reason_short") or rules_decision.reason_short).strip(),
                source="llm",
                classifier_model=str(effective_model or "").strip(),
                escalation_reason="llm_primary_classifier",
                task_control=task_control,
            )
            if notes:
                extras = self._agent._normalize_string_list(notes, limit=2, item_limit=120)
                if extras:
                    decided.reason_short = "; ".join([decided.reason_short, *extras]).strip("; ")
            if signals.translation_request and active_task is None and not decided.target and decided.task_kind != "document_translation":
                decided.requires_clarifying_route = True
            if task_control.is_active() or task_kind == "document_translation":
                decided.requires_clarifying_route = False
            return decided, raw_text
        except Exception as exc:
            fallback = rules_decision.model_copy(
                update={
                    "source": "rules",
                    "escalation_reason": f"intent_classifier_failed:{str(exc)}",
                }
            )
            return fallback, json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _parse_task_control(self, value: Any, *, fallback: TaskControl) -> TaskControl:
        if isinstance(value, TaskControl):
            return value
        if isinstance(value, dict):
            try:
                return TaskControl.model_validate(value)
            except Exception:
                return fallback.model_copy()
        return fallback.model_copy()

    def _normalize_intent(self, value: Any, *, fallback: str) -> str:
        normalized = str(value or fallback).strip().lower()
        if normalized not in _ALLOWED_INTENTS:
            return str(fallback or "standard").strip().lower() or "standard"
        return normalized

    def _normalize_action_type(self, value: Any, *, fallback: str) -> str:
        normalized = str(value or fallback).strip().lower()
        if normalized not in _ALLOWED_ACTION_TYPES:
            return str(fallback or "answer").strip().lower() or "answer"
        return normalized

    def _normalize_score(self, value: Any, *, fallback: float) -> float:
        try:
            score = float(value)
        except Exception:
            score = float(fallback)
        return max(0.0, min(1.0, score))

    def _infer_action_type(self, *, top_intent: str, requires_tools: bool, grounded_generation: bool, task_kind: str) -> str:
        if task_kind == "document_translation":
            return "read"
        if top_intent in {"evidence", "web"}:
            return "search"
        if top_intent == "code_lookup":
            return "read"
        if top_intent == "generation":
            return "modify" if grounded_generation or requires_tools else "create"
        if top_intent in {"understanding", "meeting_minutes", "qa", "continue_existing_task"}:
            return "answer"
        return "search" if requires_tools else "answer"
