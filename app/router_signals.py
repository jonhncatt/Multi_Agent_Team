from __future__ import annotations

from typing import Any

from app.context_assembly import coerce_active_task, infer_task_control, looks_like_translation_request, translation_followup_flags
from app.intent_constants import SHORT_FOLLOWUP_MAX_LEN
from app.intent_schema import RequestSignals


class RouterSignalExtractor:
    def __init__(
        self,
        agent: Any,
        *,
        news_hints: tuple[str, ...],
        followup_reference_hints: tuple[str, ...] = (),
        followup_transform_hints: tuple[str, ...] = (),
    ) -> None:
        self._agent = agent
        self._news_hints = tuple(str(item or "").strip().lower() for item in news_hints if str(item or "").strip())
        self._followup_reference_hints = tuple(
            str(item or "").strip().lower() for item in followup_reference_hints if str(item or "").strip()
        )
        self._followup_transform_hints = tuple(
            str(item or "").strip().lower() for item in followup_transform_hints if str(item or "").strip()
        )

    def extract(
        self,
        *,
        user_message: str,
        attachment_metas: list[dict[str, Any]],
        settings: Any,
        route_state: dict[str, Any] | None = None,
        inline_followup_context: bool = False,
    ) -> RequestSignals:
        text = str(user_message or "").strip().lower()
        has_attachments = bool(attachment_metas)

        context_dependent_followup = self._agent._looks_like_context_dependent_followup(user_message)
        spec_lookup_request = self._agent._looks_like_spec_lookup_request(user_message, attachment_metas)
        evidence_required = self._agent._requires_evidence_mode(user_message, attachment_metas)
        attachment_needs_tooling = any(self._agent._attachment_needs_tooling(meta) for meta in attachment_metas)
        inline_parseable_attachments = has_attachments and all(
            self._agent._attachment_is_inline_parseable(meta) for meta in attachment_metas
        )
        inline_document_payload = self._agent._looks_like_inline_document_payload(user_message)
        understanding_request = self._agent._looks_like_understanding_request(user_message)
        holistic_document_explanation = has_attachments and self._agent._looks_like_holistic_document_explanation_request(user_message)
        source_trace_request = self._agent._looks_like_source_trace_request(user_message)
        explicit_tool_confirmation = self._agent._looks_like_explicit_tool_confirmation(user_message)
        meeting_minutes_request = self._agent._looks_like_meeting_minutes_request(user_message)

        has_url = "http://" in text or "https://" in text
        short_query_like = len(text) <= 280 and "\n" not in text
        explicit_web_intent = any(hint in text for hint in ("上网", "网上", "联网", "web research", "web_research"))
        internal_ticket_reference = self._agent._looks_like_internal_ticket_reference(user_message)
        news_request = (
            any(hint in text for hint in self._news_hints)
            and short_query_like
            and not has_attachments
            and not inline_document_payload
            and not internal_ticket_reference
        )

        heavy_web_research_markers = (
            "出处",
            "来源",
            "source",
            "链接",
            "link",
            "比较",
            "对比",
            "compare",
            "comparison",
            "核对",
            "核验",
            "verify",
            "verification",
            "fact check",
            "真假",
            "是否属实",
            "timeline",
            "时间线",
            "谣言",
        )
        explicit_news_brief_markers = (
            "news",
            "新闻",
            "ニュース",
            "headline",
            "头条",
            "热点",
            "热搜",
            "简报",
            "汇总",
        )
        web_news_brief_request = (
            news_request
            and any(marker in text for marker in explicit_news_brief_markers)
            and not any(marker in text for marker in heavy_web_research_markers)
        )
        web_request = (
            news_request
            or explicit_web_intent
            or (
                has_url
                and not internal_ticket_reference
                and not has_attachments
                and not inline_document_payload
            )
        )

        request_requires_tools = self._agent._request_likely_requires_tools(user_message, attachment_metas)
        local_code_lookup_request = self._agent._looks_like_local_code_lookup_request(user_message, attachment_metas)
        grounded_generation_hints = (
            "参考",
            "参照",
            "对照",
            "基于现有",
            "按现有",
            "沿用",
            "按这个目录",
            "在这个目录",
            "在该目录",
            "按这个文件",
            "参考目录",
            "reference",
            "based on",
            "according to",
            "existing code",
            "existing file",
        )
        grounded_code_generation_context = (
            has_attachments
            or inline_document_payload
            or spec_lookup_request
            or evidence_required
            or local_code_lookup_request
            or self._agent._message_has_explicit_local_path(user_message)
            or self._agent._has_file_like_lookup_token(text)
            or any(hint in text for hint in grounded_generation_hints)
        )
        default_root_search = bool(
            bool(getattr(settings, "enable_tools", False))
            and self._agent._should_auto_search_default_roots(user_message, attachment_metas)
        )
        reference_followup_like = self._looks_like_reference_followup(text)
        transform_followup_like = self._looks_like_transform_followup(text)
        short_followup_like = self._looks_like_short_followup(
            text=text,
            context_dependent_followup=context_dependent_followup,
            reference_followup_like=reference_followup_like,
            transform_followup_like=transform_followup_like,
        )
        translation_flags = translation_followup_flags(user_message)

        signals = RequestSignals(
            text=text,
            attachment_metas=attachment_metas,
            route_state=dict(route_state or {}),
            inline_followup_context=bool(inline_followup_context),
            context_dependent_followup=bool(context_dependent_followup),
            has_attachments=has_attachments,
            spec_lookup_request=bool(spec_lookup_request),
            evidence_required=bool(evidence_required),
            attachment_needs_tooling=bool(attachment_needs_tooling),
            inline_parseable_attachments=bool(inline_parseable_attachments),
            inline_document_payload=bool(inline_document_payload),
            understanding_request=bool(understanding_request),
            holistic_document_explanation=bool(holistic_document_explanation),
            source_trace_request=bool(source_trace_request),
            explicit_tool_confirmation=bool(explicit_tool_confirmation),
            meeting_minutes_request=bool(meeting_minutes_request),
            web_news_brief_request=bool(web_news_brief_request),
            web_request=bool(web_request),
            request_requires_tools=bool(request_requires_tools),
            local_code_lookup_request=bool(local_code_lookup_request),
            grounded_code_generation_context=bool(grounded_code_generation_context),
            default_root_search=default_root_search,
            translation_request=bool(looks_like_translation_request(user_message)),
            task_control_request=bool(infer_task_control(user_message, coerce_active_task(route_state.get("active_task") if isinstance(route_state, dict) else None)).is_active()),
            translation_followup_like=bool(translation_flags["translation_followup_like"]),
            translation_mode_switch_like=bool(translation_flags["translation_mode_switch_like"]),
            translation_start_like=bool(translation_flags["translation_start_like"]),
            translation_resume_like=bool(translation_flags["translation_resume_like"]),
            translation_position_reset_like=bool(translation_flags["translation_position_reset_like"]),
            short_followup_like=short_followup_like,
            transform_followup_like=transform_followup_like,
            reference_followup_like=reference_followup_like,
        )

        inherited_primary_intent = self._agent._infer_followup_primary_intent_from_state(
            user_message=user_message,
            route_state=route_state,
            signals=signals.to_dict(),
        )
        if inherited_primary_intent:
            signals.inherited_primary_intent = str(inherited_primary_intent)
        signals.ambiguity_score = self._ambiguity_score(signals)
        return signals

    def _looks_like_reference_followup(self, text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        return any(hint in lowered for hint in self._followup_reference_hints)

    def _looks_like_transform_followup(self, text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        if any(hint in lowered for hint in self._followup_transform_hints):
            return True
        return bool(self._agent._looks_like_write_or_edit_action(lowered))

    def _looks_like_short_followup(
        self,
        *,
        text: str,
        context_dependent_followup: bool,
        reference_followup_like: bool,
        transform_followup_like: bool,
    ) -> bool:
        compact = str(text or "").strip()
        if not compact:
            return False
        if len(compact) <= 18 and context_dependent_followup:
            return True
        if len(compact) <= 28 and (reference_followup_like or transform_followup_like):
            return True
        if len(compact) <= SHORT_FOLLOWUP_MAX_LEN and context_dependent_followup and reference_followup_like:
            return True
        return False

    def _ambiguity_score(self, signals: RequestSignals) -> float:
        score = 0.0
        text_len = len(str(signals.text or "").strip())
        if signals.inherited_primary_intent and text_len <= SHORT_FOLLOWUP_MAX_LEN:
            score += 0.28
        if signals.context_dependent_followup:
            score += 0.2
        if signals.inline_followup_context:
            score += 0.16
        if signals.short_followup_like:
            score += 0.2
        if signals.reference_followup_like:
            score += 0.12
        if signals.transform_followup_like:
            score += 0.12
        if signals.reference_followup_like and signals.transform_followup_like:
            score += 0.1
        if signals.request_requires_tools and not (
            signals.source_trace_request
            or signals.spec_lookup_request
            or signals.web_request
            or signals.local_code_lookup_request
        ):
            score += 0.08
        if signals.translation_request:
            score -= 0.06
        if signals.task_control_request:
            score -= 0.1
        if signals.source_trace_request or signals.spec_lookup_request or signals.meeting_minutes_request:
            score -= 0.18
        if signals.web_request:
            score -= 0.1
        return max(0.0, min(1.0, score))
