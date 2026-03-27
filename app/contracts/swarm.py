from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SwarmBranchFailurePolicy = Literal["serial_replay"]
SwarmConflictPolicy = Literal["mark_only"]
SwarmAggregationMode = Literal["merge_deduplicate_mark_conflicts"]


@dataclass(slots=True)
class SwarmBranchSpec:
    branch_id: str
    task_kind: str
    objective: str
    input_ref: str
    runtime_profile: str = ""
    required_tools: list[str] = field(default_factory=list)
    failure_policy: SwarmBranchFailurePolicy = "serial_replay"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "task_kind": self.task_kind,
            "objective": self.objective,
            "input_ref": self.input_ref,
            "runtime_profile": self.runtime_profile,
            "required_tools": list(self.required_tools),
            "failure_policy": self.failure_policy,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SwarmJoinSpec:
    join_id: str
    branch_ids: list[str]
    aggregation_mode: SwarmAggregationMode = "merge_deduplicate_mark_conflicts"
    conflict_policy: SwarmConflictPolicy = "mark_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "join_id": self.join_id,
            "branch_ids": list(self.branch_ids),
            "aggregation_mode": self.aggregation_mode,
            "conflict_policy": self.conflict_policy,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SwarmAggregationResult:
    join_id: str
    summary: str = ""
    merged_items: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    degradation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "join_id": self.join_id,
            "summary": self.summary,
            "merged_items": list(self.merged_items),
            "conflicts": list(self.conflicts),
            "degraded": bool(self.degraded),
            "degradation_reason": self.degradation_reason,
        }


@dataclass(slots=True)
class SwarmDegradationDecision:
    policy: str
    trigger: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "trigger": self.trigger,
            "action": self.action,
            "details": dict(self.details),
        }
