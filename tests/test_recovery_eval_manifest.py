from __future__ import annotations

from scripts.run_recovery_evals import DEFAULT_CASES, _load_cases


def test_recovery_eval_manifest_covers_model_led_continuation_and_query_misses() -> None:
    manifest = _load_cases(DEFAULT_CASES)
    cases = {str(item.get("name") or ""): dict(item) for item in manifest["cases"]}

    miss = cases["where_and_rg_query_miss_is_not_failure"]
    assert miss["test_node"].endswith("::test_query_miss_is_not_a_tool_failure")
    assert miss["expected_failure_counted"] is False
    assert miss["expected_continuation_policy"] == "model_led"

    repeated = cases["repeated_tool_failures_remain_model_led"]
    assert repeated["test_node"].endswith("::test_runtime_leaves_repeated_tool_failures_to_the_model")
    assert repeated["expected_turn_status"] == "completed"
    assert repeated["expected_continuation_policy"] == "model_led"

    total = cases["no_total_failure_budget"]
    assert total["test_node"].endswith("::test_runtime_has_no_total_distinct_failure_budget")
    assert total["max_tool_calls"] == 5

    changed_strategy = cases["search_failure_rejection_then_rg_continues_model_led"]
    assert changed_strategy["test_node"].endswith(
        "::test_runtime_executes_all_calls_and_allows_new_strategy_after_failures"
    )
    assert changed_strategy["expected_error_kinds"] == ["not_a_directory", "command_not_allowed"]
    assert changed_strategy["expected_outcomes"] == ["failed", "rejected"]
    assert changed_strategy["expected_recovery_tool"] == "exec_command"
