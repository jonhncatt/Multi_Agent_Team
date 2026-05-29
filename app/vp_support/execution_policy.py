from __future__ import annotations

"""Canonical execution-policy definitions for the VP runtime."""

from dataclasses import dataclass
from typing import Literal


PlannerMode = Literal["always", "never", "when_tools"]


@dataclass(frozen=True, slots=True)
class ExecutionPolicySpec:
    planner: PlannerMode = "never"
    reviewer: bool = False
    revision: bool = False
    structurer: bool = False
    conflict_detector: bool = False


_DEFAULT_SPEC = ExecutionPolicySpec(
    planner="always",
    reviewer=True,
    revision=True,
    structurer=True,
    conflict_detector=True,
)

_POLICY_SPECS: dict[str, ExecutionPolicySpec] = {
    "standard_safe_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=False,
        conflict_detector=True,
    ),
    "understanding_direct": ExecutionPolicySpec(planner="never"),
    "evidence_lookup": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=True,
        conflict_detector=True,
    ),
    "web_research": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=True,
        conflict_detector=True,
    ),
    "code_lookup": ExecutionPolicySpec(planner="never"),
    "grounded_generation_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=False,
        conflict_detector=True,
    ),
    "direct_generation": ExecutionPolicySpec(planner="never"),
    "meeting_minutes_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=False,
        revision=False,
        structurer=True,
        conflict_detector=False,
    ),
    "mixed_intent_planner_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=False,
        conflict_detector=True,
    ),
    "followup_transform_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=False,
        revision=False,
        structurer=False,
        conflict_detector=False,
    ),
    "task_control_pipeline": ExecutionPolicySpec(
        planner="never",
        reviewer=False,
        revision=False,
        structurer=False,
        conflict_detector=False,
    ),
    "translation_session_pipeline": ExecutionPolicySpec(
        planner="never",
        reviewer=False,
        revision=False,
        structurer=False,
        conflict_detector=False,
    ),
    "standard_full_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=True,
        conflict_detector=True,
    ),
    "evidence_full_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=True,
        conflict_detector=True,
    ),
    "web_news_brief": ExecutionPolicySpec(planner="never"),
    "web_research_full_pipeline": ExecutionPolicySpec(
        planner="always",
        reviewer=True,
        revision=True,
        structurer=True,
        conflict_detector=True,
    ),
    "grounded_generation_with_tools": ExecutionPolicySpec(planner="always"),
    "generation_with_tools": ExecutionPolicySpec(planner="always"),
    "meeting_minutes_output": ExecutionPolicySpec(planner="when_tools"),
    "attachment_holistic_understanding_with_tools": ExecutionPolicySpec(planner="never"),
    "attachment_followup_understanding_with_tools": ExecutionPolicySpec(planner="always"),
    "attachment_understanding_with_tools": ExecutionPolicySpec(planner="always"),
    "attachment_tooling_generic": ExecutionPolicySpec(planner="always"),
    "code_lookup_with_tools": ExecutionPolicySpec(planner="never"),
    "continue_tooling": ExecutionPolicySpec(planner="always"),
    "llm_router_attachment_ambiguity": ExecutionPolicySpec(planner="always"),
    "llm_router_tool_ambiguity": ExecutionPolicySpec(planner="always"),
    "inline_followup_understanding": ExecutionPolicySpec(planner="never"),
    "attachment_holistic_understanding_direct": ExecutionPolicySpec(planner="never"),
    "attachment_followup_understanding_direct": ExecutionPolicySpec(planner="never"),
    "attachment_understanding_direct": ExecutionPolicySpec(planner="never"),
    "small_parseable_attachment_understanding": ExecutionPolicySpec(planner="never"),
    "inline_document_understanding_direct": ExecutionPolicySpec(planner="never"),
    "qa_direct": ExecutionPolicySpec(planner="never"),
    "llm_router_general_ambiguity": ExecutionPolicySpec(planner="never"),
}


def execution_policy_spec(policy: str) -> ExecutionPolicySpec:
    normalized = str(policy or "").strip().lower()
    if not normalized:
        return _DEFAULT_SPEC
    return _POLICY_SPECS.get(normalized, _DEFAULT_SPEC)


def planner_enabled_for_policy(policy: str, *, use_worker_tools: bool) -> bool:
    spec = execution_policy_spec(policy)
    if spec.planner == "always":
        return True
    if spec.planner == "when_tools":
        return bool(use_worker_tools)
    return False


__all__ = [
    "ExecutionPolicySpec",
    "PlannerMode",
    "execution_policy_spec",
    "planner_enabled_for_policy",
]
