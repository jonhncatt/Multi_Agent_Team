from __future__ import annotations

import json
from typing import Any

from app.agents.planning_support import summarize_attachment_metas_for_agents
from app.agents.role_catalog import SPECIALIST_LABELS
from app.agents.role_helpers import make_role_result, make_role_spec
from app.role_runtime import RoleContext, RoleResult


def specialist_contract(specialist: str, *, initial_triage_request: bool = False) -> dict[str, Any]:
    key = str(specialist or "").strip().lower()
    if key == "researcher":
        return {
            "bullet_limit": 4,
            "query_limit": 4,
            "allow_queries": True,
            "scope": "生成联网取证策略与检索关键词，不直接下最终结论。",
            "stop_rules": [
                "不要直接替 Worker 给最终答案。",
                "不要编造来源或未抓取证据。",
            ],
        }
    if key == "file_reader":
        return {
            "bullet_limit": 4,
            "query_limit": 4,
            "allow_queries": True,
            "scope": "生成文件定位与精读策略，不直接输出最终结论。",
            "stop_rules": [
                "先定位命中再建议精读，不要泛读整库。",
                "不要把缺失路径当作最终结论。",
            ],
        }
    if key == "summarizer":
        return {
            "bullet_limit": 5 if initial_triage_request else 4,
            "query_limit": 0,
            "allow_queries": False,
            "scope": "生成回答组织建议与重点提炼，不直接输出最终答复。",
            "stop_rules": [
                "不要停留在能力确认话术。",
                "不要改写成证据审计风格。",
            ],
        }
    if key == "fixer":
        return {
            "bullet_limit": 4,
            "query_limit": 2,
            "allow_queries": False,
            "scope": "生成修复优先级与变更建议，不直接改写最终输出。",
            "stop_rules": [
                "不要执行写入动作。",
                "不要跳过风险说明。",
            ],
        }
    return {
        "bullet_limit": 4,
        "query_limit": 2,
        "allow_queries": False,
        "scope": "生成专门简报，支持 Worker 执行。",
        "stop_rules": ["不要直接输出最终答案。"],
    }


def build_specialist_input_payload(
    agent: Any,
    *,
    specialist: str,
    context: RoleContext,
    route_summary: str,
    payload_preview: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    return {
        "specialist": str(specialist or "").strip().lower(),
        "effective_user_request": context.primary_user_request or "(empty)",
        "raw_user_message": context.user_message.strip() or "(empty)",
        "history_summary": context.history_summary.strip() or "(none)",
        "route": route_summary,
        "attachments": summarize_attachment_metas_for_agents(agent, context.attachment_metas),
        "context_preview": payload_preview or "(empty)",
        "scope": str(contract.get("scope") or "").strip(),
        "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
    }


def normalize_specialist_brief_payload(
    agent: Any,
    *,
    specialist: str,
    parsed: dict[str, Any],
    fallback: dict[str, Any],
    usage: dict[str, int],
    effective_model: str,
    notes: list[str],
    contract: dict[str, Any],
    initial_triage_request: bool = False,
) -> dict[str, Any]:
    bullet_limit = max(1, int(contract.get("bullet_limit") or 4))
    query_limit = max(0, int(contract.get("query_limit") or 0))
    allow_queries = bool(contract.get("allow_queries"))
    brief = {
        "role": specialist,
        "summary": str(parsed.get("summary") or fallback["summary"]).strip() or fallback["summary"],
        "bullets": agent._normalize_string_list(
            parsed.get("bullets") or fallback["bullets"],
            limit=bullet_limit,
            item_limit=180,
        ),
        "worker_hint": str(parsed.get("worker_hint") or fallback["worker_hint"]).strip() or fallback["worker_hint"],
        "queries": (
            agent._normalize_string_list(parsed.get("queries") or [], limit=query_limit, item_limit=80)
            if allow_queries and query_limit > 0
            else []
        ),
        "scope": str(parsed.get("scope") or fallback.get("scope") or contract.get("scope") or "").strip(),
        "stop_rules": agent._normalize_string_list(
            parsed.get("stop_rules") or fallback.get("stop_rules") or contract.get("stop_rules") or [],
            limit=3,
            item_limit=120,
        ),
        "usage": usage,
        "effective_model": effective_model,
        "notes": notes,
    }
    if specialist == "summarizer" and initial_triage_request:
        brief["bullets"] = agent._normalize_string_list(
            [
                "不要只回答“能理解/可以看懂”。",
                "首次回复先给一句结论，再给 3 到 5 条具体发现。",
                "优先提取主题、entry 含义、主要问题、时间线或状态变化。",
                *agent._normalize_string_list(brief.get("bullets") or [], limit=4, item_limit=180),
            ],
            limit=5,
            item_limit=180,
        )
        worker_hint = str(brief.get("worker_hint") or "").strip()
        brief["worker_hint"] = (
            "如果用户只是先确认你能不能理解内容，也要直接给高信息量摘要，不要停留在能力确认。"
            + (f" {worker_hint}" if worker_hint else "")
        ).strip()
    return brief


def specialist_fallback(
    agent: Any,
    *,
    specialist: str,
    requested_model: str,
    attachment_metas: list[dict[str, Any]],
    initial_triage_request: bool = False,
) -> dict[str, Any]:
    contract = specialist_contract(specialist, initial_triage_request=initial_triage_request)
    attachment_summary = summarize_attachment_metas_for_agents(agent, attachment_metas)
    if specialist == "researcher":
        return {
            "role": specialist,
            "summary": "优先聚焦公开来源、近期时间线与权威报道。",
            "bullets": [
                "优先用 search_web 找候选，再用 fetch_web 读正文。",
                "优先查看权威媒体、官方赛事和可核实新闻来源。",
            ],
            "worker_hint": "先围绕时间、地点、事件三件事取证，再给结论，避免只基于搜索摘要。",
            "queries": [],
            "scope": str(contract.get("scope") or ""),
            "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
            "usage": agent._empty_usage(),
            "effective_model": requested_model,
            "notes": [],
        }
    if specialist == "file_reader":
        return {
            "role": specialist,
            "summary": "先缩小目标范围，再进入命中上下文或相关附件。",
            "bullets": [
                f"附件概览: {agent._shorten(attachment_summary, 120)}",
                "优先定位关键词、章节、表格或命中片段，再读取上下文。",
            ],
            "worker_hint": "文件任务先做定位，再精读命中附近内容，不要泛读整份文档。",
            "queries": [],
            "scope": str(contract.get("scope") or ""),
            "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
            "usage": agent._empty_usage(),
            "effective_model": requested_model,
            "notes": [],
        }
    if specialist == "summarizer":
        if initial_triage_request:
            return {
                "role": specialist,
                "summary": "先确认内容可读，但主体必须直接给出高信息量首次摘要。",
                "bullets": [
                    "首次回复先给一句结论，再补 3-5 条具体发现。",
                    "优先提取主题、对象、entry 含义、主要问题、时间线或状态变化。",
                    "避免停留在“可以理解 XML/Atom 结构”这类能力确认。",
                ],
                "worker_hint": (
                    "用户是在确认你能不能理解内容时，也要直接给有帮助的摘要；"
                    "不要把回答停留在能力确认或流程说明上。"
                ),
                "queries": [],
                "scope": str(contract.get("scope") or ""),
                "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
                "usage": agent._empty_usage(),
                "effective_model": requested_model,
                "notes": [],
            }
        return {
            "role": specialist,
            "summary": "直接围绕用户问题提炼当前内联内容的核心信息。",
            "bullets": [
                "先给结论，再补 2-4 条关键点。",
                "避免流程化话术，不要改写成取证报告。",
            ],
            "worker_hint": "直接总结当前消息和附件内容，不要解释内部流程，也不要假装缺少工具。",
            "queries": [],
            "scope": str(contract.get("scope") or ""),
            "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
            "usage": agent._empty_usage(),
            "effective_model": requested_model,
            "notes": [],
        }
    return {
        "role": specialist,
        "summary": f"{SPECIALIST_LABELS.get(specialist, specialist)} 已回退到默认简报。",
        "bullets": [],
        "worker_hint": "",
        "queries": [],
        "scope": str(contract.get("scope") or ""),
        "stop_rules": agent._normalize_string_list(contract.get("stop_rules") or [], limit=3, item_limit=120),
        "usage": agent._empty_usage(),
        "effective_model": requested_model,
        "notes": [],
    }


def run_specialist_with_context(agent: Any, *, context: RoleContext) -> RoleResult:
    specialist = context.role
    initial_triage_request = agent._looks_like_initial_content_triage_request(context.user_message)
    contract = specialist_contract(specialist, initial_triage_request=initial_triage_request)
    spec = make_role_spec(
        agent,
        specialist,
        description=f"{SPECIALIST_LABELS.get(specialist, specialist)} 专门简报生成。",
        output_keys=["summary", "bullets", "worker_hint", "queries", "scope", "stop_rules"],
    )
    fallback = specialist_fallback(
        agent,
        specialist=specialist,
        requested_model=context.requested_model,
        attachment_metas=context.attachment_metas,
        initial_triage_request=initial_triage_request,
    )
    if specialist not in SPECIALIST_LABELS:
        fallback["notes"] = [f"未知专门角色: {specialist}"]
        raw_text = json.dumps({"error": "unknown specialist"}, ensure_ascii=False)
        return make_role_result(agent, spec, context, fallback, raw_text)

    payload_preview = agent._shorten(agent._content_to_text(context.user_content), 16000)
    route_summary = json.dumps(
        {
            "task_type": context.route.get("task_type"),
            "complexity": context.route.get("complexity"),
            "use_worker_tools": bool(context.route.get("use_worker_tools")),
            "use_reviewer": bool(context.route.get("use_reviewer")),
        },
        ensure_ascii=False,
    )
    specialist_input_payload = build_specialist_input_payload(
        agent,
        specialist=specialist,
        context=context,
        route_summary=route_summary,
        payload_preview=payload_preview,
        contract=contract,
    )
    specialist_input = json.dumps(specialist_input_payload, ensure_ascii=False, indent=2)

    if specialist == "researcher":
        system_prompt = (
            "你是 Researcher 专门角色。"
            "你的职责是为后续 Worker 生成联网取证简报，而不是直接回答用户。"
            "如果 raw user_message 只是短跟进或纠偏，而 effective_user_request 延续了完整目标，"
            "必须以 effective_user_request 作为主要分析目标。"
            "聚焦：搜索角度、来源优先级、需要核对的时间/地点/人物关系。"
            f"scope 固定围绕：{str(contract.get('scope') or '').strip()} "
            '只返回 JSON，对象字段固定为 summary, bullets, worker_hint, queries, scope, stop_rules。'
            "bullets 最多 4 条，queries 最多 4 条，stop_rules 最多 3 条。"
        )
    elif specialist == "file_reader":
        system_prompt = (
            "你是 FileReader 专门角色。"
            "你的职责是为文档/附件任务生成阅读与定位简报，而不是直接回答用户。"
            "如果 raw user_message 只是短跟进或纠偏，而 effective_user_request 延续了完整目标，"
            "必须以 effective_user_request 作为主要阅读目标。"
            "聚焦：应优先看的文件、章节、关键词、命中策略。"
            f"scope 固定围绕：{str(contract.get('scope') or '').strip()} "
            '只返回 JSON，对象字段固定为 summary, bullets, worker_hint, queries, scope, stop_rules。'
            "bullets 最多 4 条，queries 最多 4 条，stop_rules 最多 3 条。"
        )
    elif specialist == "summarizer":
        bullet_limit = max(1, int(contract.get("bullet_limit") or 4))
        system_prompt = (
            "你是 Summarizer 专门角色。"
            "你的职责是为简单理解任务生成内容提炼简报，而不是输出最终答复。"
            "如果 raw user_message 只是短跟进或纠偏，而 effective_user_request 延续了完整目标，"
            "必须以 effective_user_request 作为主要整理目标。"
            "聚焦：用户真正要的结论、重点信息、回答组织方式。"
            f"scope 固定围绕：{str(contract.get('scope') or '').strip()} "
            '只返回 JSON，对象字段固定为 summary, bullets, worker_hint, queries, scope, stop_rules。'
            f"bullets 最多 {bullet_limit} 条；queries 必须返回空数组；stop_rules 最多 3 条。"
        )
        if initial_triage_request:
            system_prompt += (
                "如果用户是在问“你能不能理解/帮我看一下”，"
                "不要只回答“可以理解”。"
                "你必须引导 Worker 直接给出高信息量首次摘要："
                "先一句结论，再给 3 到 5 条具体发现，"
                "例如主题、对象、时间、状态变化、异常点、主要问题或记录类型；"
                "最后再用一句话说明还能继续从哪些角度深挖。"
            )
    else:
        system_prompt = (
            "你是专门角色。"
            f"scope 固定围绕：{str(contract.get('scope') or '').strip()} "
            '只返回 JSON，对象字段固定为 summary, bullets, worker_hint, queries, scope, stop_rules。'
        )

    messages = [
        agent._SystemMessage(content=system_prompt),
        agent._HumanMessage(content=specialist_input),
    ]
    try:
        ai_msg, _, effective_model, notes = agent._invoke_chat_with_runner(
            messages=messages,
            model=agent.config.summary_model or context.requested_model,
            max_output_tokens=900,
            enable_tools=False,
        )
        raw_text = agent._content_to_text(getattr(ai_msg, "content", "")).strip()
        parsed = agent._parse_json_object(raw_text)
        usage = agent._extract_usage_from_message(ai_msg)
        if not parsed:
            fallback["notes"] = [f"{SPECIALIST_LABELS[specialist]} 未返回标准 JSON，已回退默认简报。", *notes]
            fallback["usage"] = usage
            fallback["effective_model"] = effective_model
            return make_role_result(agent, spec, context, fallback, raw_text)
        brief = normalize_specialist_brief_payload(
            agent,
            specialist=specialist,
            parsed=parsed,
            fallback=fallback,
            usage=usage,
            effective_model=effective_model,
            notes=notes,
            contract=contract,
            initial_triage_request=initial_triage_request,
        )
        return make_role_result(agent, spec, context, brief, raw_text)
    except Exception as exc:
        fallback["notes"] = [f"{SPECIALIST_LABELS[specialist]} 调用失败，已回退默认简报: {agent._shorten(exc, 180)}"]
        raw_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
        return make_role_result(agent, spec, context, fallback, raw_text)


def format_specialist_system_hint(agent: Any, specialist: str, brief: RoleResult | dict[str, Any]) -> str:
    brief_payload = agent._role_payload_dict(brief)
    label = SPECIALIST_LABELS.get(specialist, specialist)
    lines = [f"专门角色摘要（来自 {label}）："]
    summary = str(brief_payload.get("summary") or "").strip()
    bullets = agent._normalize_string_list(brief_payload.get("bullets") or [], limit=5, item_limit=180)
    worker_hint = str(brief_payload.get("worker_hint") or "").strip()
    queries = agent._normalize_string_list(brief_payload.get("queries") or [], limit=4, item_limit=80)
    scope = str(brief_payload.get("scope") or "").strip()
    stop_rules = agent._normalize_string_list(brief_payload.get("stop_rules") or [], limit=3, item_limit=120)
    if summary:
        lines.append(f"摘要: {summary}")
    if scope:
        lines.append(f"范围: {scope}")
    if bullets:
        lines.append("要点:")
        lines.extend(f"- {item}" for item in bullets)
    if queries:
        lines.append("建议关键词/查询:")
        lines.extend(f"- {item}" for item in queries)
    if stop_rules:
        lines.append("边界:")
        lines.extend(f"- {item}" for item in stop_rules)
    if worker_hint:
        lines.append(f"执行提示: {worker_hint}")
    return "\n".join(lines) if len(lines) > 1 else ""
