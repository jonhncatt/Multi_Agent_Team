from __future__ import annotations

from app.tool_failures import classify_tool_event, classify_tool_failure, failure_key


def test_top_level_command_error_kind_is_preserved_without_error_text() -> None:
    failure = classify_tool_failure(
        tool_name="exec_command",
        payload={
            "ok": False,
            "error": "C:/Company/secret/source.cpp was rejected",
            "error_kind": "command_path_outside_allowed_roots",
            "returncode": 126,
        },
        event_status="error",
    )

    assert failure == {
        "schema_version": 2,
        "tool": "exec_command",
        "outcome": "rejected",
        "failure_phase": "policy",
        "category": "tool_call_failure",
        "error_kind": "command_path_outside_allowed_roots",
        "retryability": "change_arguments",
        "required_action": "revise_arguments_or_choose_another_tool",
        "returncode": 126,
        "is_verification": False,
    }
    assert "Company" not in str(failure)
    assert "source.cpp" not in str(failure)


def test_nonzero_verification_command_is_classified_separately() -> None:
    failure = classify_tool_failure(
        tool_name="exec_command",
        payload={"ok": True, "returncode": 1, "output": "private test output"},
        event_status="ok",
        is_verification=True,
    )

    assert failure is not None
    assert failure["category"] == "verification_failure"
    assert failure["error_kind"] == "command_exit_nonzero"
    assert failure["retryability"] == "change_strategy"
    assert "private test output" not in str(failure)


def test_successful_event_has_no_failure_classification() -> None:
    assert classify_tool_event(
        {
            "name": "read_file",
            "status": "ok",
            "result_preview": {"ok": True, "content": "private content"},
        }
    ) is None


def test_apply_patch_existing_file_requires_changed_arguments() -> None:
    failure = classify_tool_failure(
        tool_name="apply_patch",
        payload={
            "ok": False,
            "error": {
                "kind": "file_already_exists",
                "operation": "add",
                "message": "redacted path",
            },
        },
        event_status="error",
    )

    assert failure is not None
    assert failure["category"] == "tool_call_failure"
    assert failure["error_kind"] == "file_already_exists"
    assert failure["retryability"] == "change_arguments"
    assert failure["required_action"] == "revise_arguments_or_choose_another_tool"


def test_stored_runtime_classification_is_reused_by_eval() -> None:
    failure = classify_tool_event(
        {
            "name": "apply_patch",
            "status": "error",
            "diagnostics": {
                "failure": {
                    "schema_version": 1,
                    "tool": "apply_patch",
                    "category": "tool_call_failure",
                    "error_kind": "bad_tool_arguments",
                    "retryability": "change_arguments",
                    "required_action": "revise_arguments_or_choose_another_tool",
                    "occurrence": 2,
                    "consecutive_occurrence": 2,
                }
            },
        }
    )

    assert failure is not None
    assert failure["occurrence"] == 2
    assert failure["consecutive_occurrence"] == 2
    assert failure_key(failure) == "apply_patch:failed:execution:tool_call_failure:bad_tool_arguments"


def test_allowed_validation_code_is_not_used_as_execution_error_kind() -> None:
    failure = classify_tool_failure(
        tool_name="search_codebase",
        payload={
            "ok": False,
            "error": "Not a directory: C:\\work\\Script\\PLP_10.cpp",
            "cwd": "C:\\work\\Script\\PLP_10.cpp",
        },
        event_status="error",
        validation_result={"allowed": True, "code": "allowed"},
        normalized_arguments={"query": "PLP", "root": "."},
    )

    assert failure is not None
    assert failure["outcome"] == "failed"
    assert failure["failure_phase"] == "execution"
    assert failure["category"] == "tool_call_failure"
    assert failure["error_kind"] == "not_a_directory"
    assert failure["error_kind"] != "allowed"
    assert failure["target_fingerprint"]


def test_policy_rejection_has_distinct_command_target_fingerprint() -> None:
    select_string = classify_tool_failure(
        tool_name="exec_command",
        payload={"ok": False, "code": "command_not_allowed", "summary": "Command not allowed: select-string"},
        event_status="rejected",
        validation_result={"allowed": False, "code": "command_not_allowed"},
        normalized_arguments={"cmd": "select-string -Pattern foo PLP_10.cpp"},
    )
    ripgrep = classify_tool_failure(
        tool_name="exec_command",
        payload={"ok": False, "code": "command_not_allowed", "summary": "Command not allowed: rg"},
        event_status="rejected",
        validation_result={"allowed": False, "code": "command_not_allowed"},
        normalized_arguments={"cmd": "rg -n foo PLP_10.cpp"},
    )

    assert select_string is not None and ripgrep is not None
    assert select_string["outcome"] == "rejected"
    assert select_string["failure_phase"] == "policy"
    assert select_string["target_fingerprint"] != ripgrep["target_fingerprint"]
    assert failure_key(select_string) != failure_key(ripgrep)


def test_skipped_and_cancelled_calls_are_not_failures() -> None:
    for status, kind in (("skipped", "tool_skipped"), ("cancelled", "tool_cancelled")):
        assert classify_tool_failure(
            tool_name="search_codebase",
            payload={"ok": False, "error": {"kind": kind, "message": "not executed"}},
            event_status=status,
            validation_result={"allowed": False, "code": kind},
            normalized_arguments={"query": "x", "root": "."},
        ) is None
