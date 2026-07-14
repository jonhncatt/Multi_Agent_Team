from __future__ import annotations

import json
import re
from typing import Any


FAILURE_SCHEMA_VERSION = 1

_FAILED_STATUSES = {"error", "failed", "blocked", "rejected"}
_VALIDATION_TYPES = {"validation_error", "boundary_denied", "loop_safeguard"}
_VALIDATION_KINDS = {
    "bad_tool_arguments",
    "invalid_arguments",
    "invalid_tool_arguments",
    "schema_validation_failed",
    "unknown_tool",
    "tool_not_allowed",
    "path_outside_allowed_roots",
    "write_outside_writable_roots",
    "command_path_outside_allowed_roots",
    "compound_shell_subcommand_rejected",
    "dangerous_command",
    "file_already_exists",
}
_ENVIRONMENT_KINDS = {
    "authentication_unavailable",
    "browser_not_allowed",
    "ca_certificate_unavailable",
    "command_execution_approval_required",
    "compiler_unavailable",
    "connection_unavailable",
    "credential_unavailable",
    "network_not_allowed",
    "provider_unavailable",
    "shell_not_allowed",
    "tool_unavailable",
    "workspace_read_not_allowed",
    "workspace_write_not_allowed",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_code(value: Any, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized[:80] or fallback


def _returncode(payload: dict[str, Any]) -> int | None:
    raw = payload.get("returncode")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    preview = event.get("result_preview")
    if isinstance(preview, dict):
        return dict(preview)
    output = str(event.get("output_preview") or "").strip()
    if output.startswith("{"):
        try:
            decoded = json.loads(output)
        except Exception:
            decoded = None
        if isinstance(decoded, dict):
            return dict(decoded)
    return {}


def classify_tool_failure(
    *,
    tool_name: str,
    payload: dict[str, Any] | None,
    event_status: str = "",
    validation_result: dict[str, Any] | None = None,
    is_verification: bool = False,
) -> dict[str, Any] | None:
    """Return a content-free failure classification suitable for model feedback and reports."""

    result = _mapping(payload)
    validation = _mapping(validation_result)
    nested_error = _mapping(result.get("error"))
    returncode = _returncode(result)
    status = str(event_status or "").strip().lower()
    explicitly_failed = bool(
        result.get("ok") is False
        or status in _FAILED_STATUSES
        or (returncode is not None and returncode != 0)
        or validation.get("allowed") is False
    )
    if not explicitly_failed:
        return None

    raw_kind = (
        nested_error.get("kind")
        or result.get("error_kind")
        or result.get("code")
        or validation.get("code")
        or result.get("type")
    )
    if not raw_kind and returncode is not None and returncode != 0:
        raw_kind = "command_exit_nonzero"
    error_kind = _safe_code(raw_kind, fallback="tool_error")
    observation_type = _safe_code(result.get("type"), fallback="")

    if error_kind in _ENVIRONMENT_KINDS:
        category = "environment_blocked"
        retryability = "blocked"
        required_action = "choose_available_alternative_or_report_blocker"
    elif is_verification and returncode not in (None, 0):
        category = "verification_failure"
        retryability = "change_strategy"
        required_action = "change_target_or_verification_strategy"
    elif (
        validation.get("allowed") is False
        or observation_type in _VALIDATION_TYPES
        or error_kind in _VALIDATION_KINDS
    ):
        category = "tool_call_failure"
        retryability = "change_arguments"
        required_action = "revise_arguments_or_choose_another_tool"
    elif str(tool_name or "").strip() in {"exec_command", "write_stdin"} or returncode not in (None, 0):
        category = "command_failure"
        retryability = "change_strategy"
        required_action = "inspect_exit_status_and_choose_a_different_action"
    else:
        category = "tool_execution_failure"
        retryability = "retry_once"
        required_action = "retry_once_then_change_strategy"

    return {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "tool": str(tool_name or "tool").strip() or "tool",
        "category": category,
        "error_kind": error_kind,
        "retryability": retryability,
        "required_action": required_action,
        "returncode": returncode,
        "is_verification": bool(is_verification),
    }


def classify_tool_event(
    event: dict[str, Any],
    *,
    is_verification: bool = False,
) -> dict[str, Any] | None:
    item = _mapping(event)
    diagnostics = _mapping(item.get("diagnostics"))
    stored = _mapping(diagnostics.get("failure"))
    if stored.get("category") and stored.get("error_kind"):
        return {
            key: stored.get(key)
            for key in (
                "schema_version",
                "tool",
                "category",
                "error_kind",
                "retryability",
                "required_action",
                "returncode",
                "is_verification",
                "occurrence",
                "consecutive_occurrence",
                "precondition",
            )
            if key in stored
        }
    return classify_tool_failure(
        tool_name=str(item.get("name") or "tool"),
        payload=_event_payload(item),
        event_status=str(item.get("status") or ""),
        validation_result=_mapping(item.get("validation_result")),
        is_verification=is_verification,
    )


def failure_key(failure: dict[str, Any] | None) -> str:
    item = _mapping(failure)
    if not item:
        return ""
    return ":".join(
        (
            _safe_code(item.get("tool"), fallback="tool"),
            _safe_code(item.get("category"), fallback="tool_execution_failure"),
            _safe_code(item.get("error_kind"), fallback="tool_error"),
        )
    )
