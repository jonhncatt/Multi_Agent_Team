from __future__ import annotations

import json
from typing import Any

from app.vp_support.planning_support import summarize_attachment_metas_for_agents
from app.vp_support.review_support import summarize_tool_events_for_review, summarize_validation_context
from app.vp_support import RoleContext, RoleResult


def run_conflict_detector_role(agent: Any, *, context: RoleContext) -> RoleResult:
    spec = agent._make_role_spec(
        "conflict_detector",
        description="检查答案是否与通识或成熟工程知识明显冲突。",
        output_keys=["has_conflict", "confidence", "summary", "concerns", "suggested_checks"],
    )
    validation_context = summarize_validation_context(agent, context.tool_events)
    attachment_summary = summarize_attachment_metas_for_agents(agent, context.attachment_metas)
    tool_summaries = summarize_tool_events_for_review(agent, context.tool_events, limit=10)
    detector_input = "\n".join(
        [
            f"effective_user_request:\n{context.primary_user_request or '(empty)'}",
            f"raw_user_message:\n{context.user_message.strip() or '(empty)'}",
            f"history_summary:\n{context.history_summary.strip() or '(none)'}",
            f"attachments:\n{attachment_summary}",
            f"planner_objective:\n{str(context.planner_brief.get('objective') or '').strip() or '(none)'}",
            f"spec_lookup_request={str(bool(context.extra.get('spec_lookup_request'))).lower()}",
            f"evidence_required_mode={str(bool(context.extra.get('evidence_required_mode'))).lower()}",
            f"web_tools_used={str(validation_context['web_tools_used']).lower()}",
            f"web_tools_success={str(validation_context['web_tools_success']).lower()}",
            "web_tool_notes:",
            *[f"- {item}" for item in validation_context["web_tool_notes"]],
            "web_tool_warnings:",
            *[f"- {item}" for item in validation_context["web_tool_warnings"]],
            "tool_events:",
            *(tool_summaries or ["(none)"]),
            f"answer:\n{context.response_text.strip() or '(empty)'}",
        ]
    )
    fallback = {
        "has_conflict": False,
        "confidence": "medium",
        "summary": "Conflict Detector 未发现明显常识冲突。",
        "concerns": [],
        "suggested_checks": [],
        "usage": agent._empty_usage(),
        "effective_model": context.requested_model,
        "notes": [],
    }
    messages = [
        agent._SystemMessage(
            content=(
                "你是 Answer Conflict Detector。"
                "基于通识、成熟工程知识和任务上下文，检查当前答案是否存在明显可疑点、过度确定、或与常见知识冲突。"
                "不要输出思维链。"
                "你的知识只能用于报警和建议复核，不能替代文件证据。"
                "如果 attachments 或 tool_events 已显示本轮存在附件/本地文件且 Worker 已经读取过，"
                "不要仅因为 raw_user_message 是短跟进、或你自己没有独立文件证据，就把答案判成“没有依据”。"
                "只有当答案和通识或工程常识存在明确冲突时，才应标记 has_conflict=true。"
                "必须区分底层模型限制与工具增强后的系统能力。"
                "如果本轮已经成功使用 web_search、web_fetch 或 web_download 获得实时来源，"
                "不能仅因为“模型原生不支持实时信息”就判定答案冲突；"
                "这类情况最多只能提醒来源质量、时效性或复核范围。"
                '只返回 JSON 对象，字段固定为 has_conflict, confidence, summary, concerns, suggested_checks。'
                "has_conflict 必须是 true 或 false；confidence 只能是 high, medium, low。"
            )
        ),
        agent._HumanMessage(content=detector_input),
    ]
    try:
        ai_msg, _, effective_model, notes = agent._invoke_chat_with_runner(
            messages=messages,
            model=context.requested_model,
            max_output_tokens=900,
            enable_tools=False,
        )
        raw_text = agent._content_to_text(getattr(ai_msg, "content", "")).strip()
        parsed = agent._parse_json_object(raw_text)
        if not parsed:
            fallback["notes"] = ["Conflict Detector 未返回标准 JSON，已忽略冲突检查结果。", *notes]
            fallback["usage"] = agent._extract_usage_from_message(ai_msg)
            fallback["effective_model"] = effective_model
            return agent._make_role_result(spec, context, fallback, raw_text)

        has_conflict_raw = parsed.get("has_conflict")
        if isinstance(has_conflict_raw, bool):
            has_conflict = has_conflict_raw
        else:
            has_conflict = str(has_conflict_raw or "").strip().lower() in {"1", "true", "yes", "on"}
        confidence = str(parsed.get("confidence") or "medium").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        detector = {
            "has_conflict": has_conflict,
            "confidence": confidence,
            "summary": str(parsed.get("summary") or fallback["summary"]).strip() or fallback["summary"],
            "concerns": agent._normalize_string_list(parsed.get("concerns") or [], limit=4, item_limit=180),
            "suggested_checks": agent._normalize_string_list(
                parsed.get("suggested_checks") or [], limit=4, item_limit=180
            ),
            "usage": agent._extract_usage_from_message(ai_msg),
            "effective_model": effective_model,
            "notes": notes,
        }
        return agent._make_role_result(spec, context, detector, raw_text)
    except Exception as exc:
        fallback["notes"] = [f"Conflict Detector 调用失败，已跳过: {agent._shorten(exc, 180)}"]
        raw_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
        return agent._make_role_result(spec, context, fallback, raw_text)
