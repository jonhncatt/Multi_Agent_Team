from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    profile_id: str
    title: str
    summary: str
    worker_hint: str
    preferred_specialists: tuple[str, ...] = ()
    allows_reviewer: bool = False
    expects_evidence: bool = False


EXPLAINER_PROFILE = RuntimeProfile(
    profile_id="explainer",
    title="Explainer",
    summary="解释型 profile，优先做整体理解、说明和教学式回答。",
    worker_hint="优先解释整体结构、概念关系和主线，不要把回答写成取证审计报告。",
    preferred_specialists=("summarizer", "file_reader"),
    allows_reviewer=False,
    expects_evidence=False,
)


EVIDENCE_PROFILE = RuntimeProfile(
    profile_id="evidence",
    title="Evidence",
    summary="取证型 profile，优先定位出处、命中片段、页码、章节和可复核表达。",
    worker_hint="优先做定位和复核，最终输出必须带证据来源；不足时明确说明不足。",
    preferred_specialists=("file_reader", "researcher"),
    allows_reviewer=True,
    expects_evidence=True,
)


PATCH_WORKER_PROFILE = RuntimeProfile(
    profile_id="patch_worker",
    title="PatchWorker",
    summary="修复型 profile，只允许在 shadow 模块副本里做最小修改和验证。",
    worker_hint="只改 shadow 工作区的模块副本；优先修复阻断错误，再跑 contract/smoke。",
    preferred_specialists=("fixer",),
    allows_reviewer=False,
    expects_evidence=False,
)


RUNTIME_PROFILES = {
    EXPLAINER_PROFILE.profile_id: EXPLAINER_PROFILE,
    EVIDENCE_PROFILE.profile_id: EVIDENCE_PROFILE,
    PATCH_WORKER_PROFILE.profile_id: PATCH_WORKER_PROFILE,
}


def runtime_profile_spec(profile_id: str) -> RuntimeProfile:
    return RUNTIME_PROFILES.get(str(profile_id or "").strip().lower(), EXPLAINER_PROFILE)


def default_runtime_profile_for_route(route: dict[str, Any]) -> str:
    task_type = str(route.get("task_type") or "").strip().lower()
    execution_policy = str(route.get("execution_policy") or "").strip().lower()
    primary_intent = str(route.get("primary_intent") or "").strip().lower()

    if task_type == "patch_worker" or execution_policy == "patch_worker_shadow_loop":
        return PATCH_WORKER_PROFILE.profile_id
    evidence_task_types = {"evidence_lookup", "web_research"}
    evidence_policies = {"evidence_full_pipeline", "web_research_full_pipeline"}
    if task_type in evidence_task_types or execution_policy in evidence_policies or primary_intent == "evidence":
        return EVIDENCE_PROFILE.profile_id
    return EXPLAINER_PROFILE.profile_id


def build_runtime_profile_hint(route: dict[str, Any]) -> str:
    profile = runtime_profile_spec(default_runtime_profile_for_route(route))
    lines = [f"Runtime profile: {profile.title}"]
    if profile.summary:
        lines.append(f"概述: {profile.summary}")
    if profile.worker_hint:
        lines.append(f"执行提示: {profile.worker_hint}")
    if profile.preferred_specialists:
        lines.append(f"优先专门角色: {', '.join(profile.preferred_specialists)}")
    lines.append(f"expects_evidence={str(profile.expects_evidence).lower()}")
    lines.append(f"allows_reviewer={str(profile.allows_reviewer).lower()}")
    return "\n".join(lines)
