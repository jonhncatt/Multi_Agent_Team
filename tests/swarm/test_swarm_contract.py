from __future__ import annotations

from app.contracts import (
    SwarmAggregationResult,
    SwarmBranchSpec,
    SwarmDegradationDecision,
    SwarmJoinSpec,
)


def test_swarm_branch_contract_defaults_to_serial_replay() -> None:
    branch = SwarmBranchSpec(
        branch_id="branch-1",
        task_kind="attachment_analysis",
        objective="Summarize one attachment.",
        input_ref="attachment:a.pdf",
    )

    assert branch.failure_policy == "serial_replay"
    assert branch.to_dict()["failure_policy"] == "serial_replay"


def test_swarm_join_contract_defaults_to_mark_only_conflicts() -> None:
    join = SwarmJoinSpec(join_id="join-1", branch_ids=["branch-1", "branch-2"])

    assert join.aggregation_mode == "merge_deduplicate_mark_conflicts"
    assert join.conflict_policy == "mark_only"
    assert join.to_dict()["conflict_policy"] == "mark_only"


def test_swarm_aggregation_result_and_degradation_decision_are_serializable() -> None:
    result = SwarmAggregationResult(
        join_id="join-1",
        summary="merged output",
        conflicts=[{"claim": "A vs B"}],
        degraded=True,
        degradation_reason="branch failure replayed serially",
    )
    decision = SwarmDegradationDecision(
        policy="serial_replay",
        trigger="branch_failed",
        action="replay_failed_branch_sequentially",
    )

    assert result.to_dict()["degraded"] is True
    assert result.to_dict()["conflicts"][0]["claim"] == "A vs B"
    assert decision.to_dict()["policy"] == "serial_replay"
