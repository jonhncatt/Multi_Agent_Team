from __future__ import annotations

from scripts.run_recovery_evals import DEFAULT_CASES, _load_cases


def test_recovery_eval_manifest_includes_replan_new_strategy_regression() -> None:
    manifest = _load_cases(DEFAULT_CASES)
    cases = {str(item.get("name") or ""): dict(item) for item in manifest["cases"]}

    case = cases["replan_allows_rejected_then_new_command_strategy"]
    assert case["test_node"].endswith(
        "::test_runtime_allows_new_strategy_after_replan_and_does_not_count_skipped_call"
    )
    assert case["expected_turn_status"] == "completed"
    assert case["expected_replan_trigger"] == "repeated_tool_failure"
    assert case["expected_error_kinds"] == ["not_a_directory", "command_not_allowed"]
    assert case["expected_outcomes"] == ["failed", "rejected"]
    assert case["expected_skipped_calls"] == 1
    assert case["expected_recovery_tool"] == "exec_command"
