from __future__ import annotations

from typing import Any


def summarize_attachment_metas_for_agents(agent: Any, attachment_metas: list[dict[str, Any]]) -> str:
    if not attachment_metas:
        return "(none)"
    lines: list[str] = []
    for idx, meta in enumerate(attachment_metas[:8], start=1):
        name = str(meta.get("original_name") or meta.get("name") or f"file_{idx}")
        kind = str(meta.get("kind") or "other")
        size = agent._format_bytes(meta.get("size"))
        suffix = str(meta.get("suffix") or "")
        lines.append(f"{idx}. {name} kind={kind} size={size} suffix={suffix or '-'}")
    if len(attachment_metas) > 8:
        lines.append(f"... and {len(attachment_metas) - 8} more")
    return "\n".join(lines)


def build_execution_plan(
    agent: Any,
    *,
    attachment_metas: list[dict[str, Any]],
    settings: Any,
    route: dict[str, Any] | None = None,
) -> list[str]:
    route = route or {}
    specialists = agent._normalize_specialists(route.get("specialists") or [])
    task_type = str(route.get("task_type") or "standard")
    primary_intent = str(route.get("primary_intent") or agent._task_type_to_primary_intent(task_type))
    execution_policy = str(route.get("execution_policy") or agent._task_type_to_execution_policy(task_type))
    plan = [
        (
            "Router 分诊主意图与执行链路"
            f"（task_type={task_type}, primary_intent={primary_intent}, "
            f"execution_policy={execution_policy}, complexity={str(route.get('complexity') or 'medium')}）。"
        )
    ]
    plan.append("Coordinator 持有运行时状态，决定 Worker 是否重绑工具并继续执行。")
    for specialist in specialists:
        plan.append(agent._specialist_plan_line(specialist))
    if route.get("use_planner"):
        plan.append("Planner 提炼目标、约束与执行计划。")
    plan.append("Worker 根据当前链路执行与作答。")
    if attachment_metas:
        plan.append(f"解析附件内容（{len(attachment_metas)} 个）。")
    plan.append(f"结合最近 {settings.max_context_turns} 条历史消息组织上下文。")
    if settings.enable_tools and route.get("use_worker_tools"):
        plan.append("如有必要自动连续调用工具（读文件/列目录/执行命令/联网搜索与抓取）获取事实，不逐步征询。")
        if agent.config.enable_session_tools:
            plan.append("涉及历史对话时，自动调用会话工具检索旧 session。")
    if route.get("use_reviewer"):
        plan.append("Reviewer 做最终自检。")
    if route.get("use_revision"):
        plan.append("Revision 按审阅结果做最后修订。")
    if route.get("use_structurer"):
        plan.append("Structurer 在有来源时生成结构化证据包。")
    return plan
