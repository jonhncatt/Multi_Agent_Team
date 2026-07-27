from __future__ import annotations

import hashlib
import json
import re
import shlex
from typing import Any


FAILURE_SCHEMA_VERSION = 2

_FAILED_STATUSES = {"error", "failed", "blocked", "rejected"}
_NON_FAILURE_STATUSES = {"cancelled", "canceled", "skipped"}
_NON_FAILURE_KINDS = {"tool_cancelled", "tool_canceled", "tool_skipped"}
_VALIDATION_TYPES = {"validation_error", "boundary_denied", "loop_safeguard"}
_VALIDATION_KINDS = {
    "bad_tool_arguments",
    "invalid_arguments",
    "invalid_tool_arguments",
    "schema_validation_failed",
    "unknown_tool",
    "tool_not_allowed",
    "command_not_allowed",
    "path_outside_allowed_roots",
    "write_outside_writable_roots",
    "command_path_outside_allowed_roots",
    "compound_shell_subcommand_rejected",
    "dangerous_command",
    "file_already_exists",
    "not_a_directory",
    "is_a_directory",
    "path_not_found",
}
_POLICY_KINDS = {
    "browser_not_allowed",
    "command_not_allowed",
    "command_path_outside_allowed_roots",
    "dangerous_command",
    "network_not_allowed",
    "path_outside_allowed_roots",
    "shell_not_allowed",
    "tool_not_allowed",
    "workspace_read_not_allowed",
    "workspace_write_not_allowed",
    "write_outside_writable_roots",
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
    "task_update_approval_required",
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


def _infer_error_kind(result: dict[str, Any], nested_error: dict[str, Any]) -> str:
    raw_error = nested_error.get("message") if nested_error else result.get("error")
    message = " ".join(
        str(item or "").strip()
        for item in (raw_error, result.get("stderr"), result.get("summary"), result.get("message"))
        if str(item or "").strip()
    ).lower()
    patterns = (
        ("not a directory", "not_a_directory"),
        ("is a directory", "is_a_directory"),
        ("no such file or directory", "path_not_found"),
        ("path not found", "path_not_found"),
        ("command not allowed", "command_not_allowed"),
        ("permission denied", "permission_denied"),
        ("timed out", "timeout"),
        ("timeout", "timeout"),
        ("query is empty", "invalid_arguments"),
        ("empty command", "invalid_arguments"),
    )
    return next((kind for marker, kind in patterns if marker in message), "")


def _normalize_target_value(value: Any, *, path_like: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_target_value(item, path_like=str(key).lower() in {
                "cwd", "dir", "dst_dir", "dst_path", "path", "root", "zip_path", "msg_path"
            })
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_target_value(item, path_like=path_like) for item in value]
    if isinstance(value, str):
        normalized = " ".join(value.strip().split())
        if path_like:
            normalized = normalized.replace("\\", "/").rstrip("/") or "/"
            if re.match(r"^[a-zA-Z]:/", normalized):
                normalized = normalized.casefold()
        return normalized
    return value


def _command_base(command: Any) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    raw = str(tokens[0] if tokens else "").strip().strip("\"'").replace("\\", "/")
    return raw.rsplit("/", 1)[-1].casefold()


def _target_fingerprint(
    *,
    tool_name: str,
    error_kind: str,
    category: str,
    normalized_arguments: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    if category == "environment_blocked":
        return ""
    name = str(tool_name or "").strip()
    arguments = _mapping(normalized_arguments)
    material: dict[str, Any] = {}
    if name in {"exec_command", "write_stdin"}:
        command = arguments.get("cmd") or arguments.get("command") or payload.get("command")
        if error_kind == "command_not_allowed":
            material = {"command_base": _command_base(command)}
        else:
            material = {
                "command": command,
                "cwd": arguments.get("cwd") or payload.get("cwd"),
                "session_id": arguments.get("session_id"),
            }
    elif name in {
        "search_codebase",
        "search_contents_in_file",
        "search_contents_in_file_multi",
        "glob_file_search",
        "read_file",
        "read_section",
        "list_dir",
    }:
        material = {
            key: value
            for key, value in {
                "path": arguments.get("path"),
                "root": arguments.get("root"),
                "cwd": arguments.get("cwd") or payload.get("cwd"),
                "query": arguments.get("query"),
                "queries": arguments.get("queries"),
                "pattern": arguments.get("pattern"),
                "file_glob": arguments.get("file_glob"),
                "heading": arguments.get("heading"),
            }.items()
            if value not in (None, "", [])
        }
    else:
        target_fields = {
            key: arguments.get(key)
            for key in (
                "path", "root", "cwd", "query", "queries", "pattern", "url", "dst_path",
                "dst_dir", "zip_path", "msg_path", "cmd", "command", "session_id",
            )
            if arguments.get(key) not in (None, "", [])
        }
        material = target_fields or arguments
    normalized = _normalize_target_value({key: value for key, value in material.items() if value not in (None, "")})
    if not normalized:
        return ""
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8", errors="ignore")).hexdigest()[:16]


def classify_tool_failure(
    *,
    tool_name: str,
    payload: dict[str, Any] | None,
    event_status: str = "",
    validation_result: dict[str, Any] | None = None,
    normalized_arguments: dict[str, Any] | None = None,
    is_verification: bool = False,
) -> dict[str, Any] | None:
    """Return a content-free failure classification suitable for model feedback and reports."""

    result = _mapping(payload)
    validation = _mapping(validation_result)
    nested_error = _mapping(result.get("error"))
    returncode = _returncode(result)
    status = str(event_status or "").strip().lower()
    validation_denied = validation.get("allowed") is False
    primary_kind = (
        nested_error.get("kind")
        or result.get("error_kind")
        or result.get("code")
        or (validation.get("code") if validation_denied else None)
        or result.get("type")
    )
    normalized_primary_kind = _safe_code(primary_kind, fallback="")
    if status in _NON_FAILURE_STATUSES or normalized_primary_kind in _NON_FAILURE_KINDS:
        return None
    explicitly_failed = bool(
        result.get("ok") is False
        or status in _FAILED_STATUSES
        or (returncode is not None and returncode != 0)
        or validation_denied
    )
    if not explicitly_failed:
        return None

    raw_kind = primary_kind or _infer_error_kind(result, nested_error)
    if not raw_kind and returncode is not None and returncode != 0:
        raw_kind = "command_exit_nonzero"
    error_kind = _safe_code(raw_kind, fallback="tool_error")
    observation_type = _safe_code(result.get("type"), fallback="")
    outcome = (
        "rejected"
        if validation_denied
        or status == "rejected"
        or str(result.get("failure_outcome") or "").strip().lower() == "rejected"
        or error_kind in _POLICY_KINDS
        else "failed"
    )
    failure_phase = (
        "policy"
        if outcome == "rejected" and error_kind in _POLICY_KINDS
        else ("validation" if outcome == "rejected" else "execution")
    )

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

    target_fingerprint = _target_fingerprint(
        tool_name=tool_name,
        error_kind=error_kind,
        category=category,
        normalized_arguments=_mapping(normalized_arguments),
        payload=result,
    )
    return {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "tool": str(tool_name or "tool").strip() or "tool",
        "outcome": outcome,
        "failure_phase": failure_phase,
        "category": category,
        "error_kind": error_kind,
        **({"target_fingerprint": target_fingerprint} if target_fingerprint else {}),
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
                "outcome",
                "failure_phase",
                "category",
                "error_kind",
                "target_fingerprint",
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
        normalized_arguments=_mapping(item.get("normalized_arguments") or item.get("input")),
        is_verification=is_verification,
    )


def failure_key(failure: dict[str, Any] | None) -> str:
    item = _mapping(failure)
    if not item:
        return ""
    parts = [
        _safe_code(item.get("tool"), fallback="tool"),
        _safe_code(item.get("outcome"), fallback="failed"),
        _safe_code(item.get("failure_phase"), fallback="execution"),
        _safe_code(item.get("category"), fallback="tool_execution_failure"),
        _safe_code(item.get("error_kind"), fallback="tool_error"),
    ]
    target_fingerprint = _safe_code(item.get("target_fingerprint"), fallback="")
    if target_fingerprint:
        parts.append(target_fingerprint)
    return ":".join(parts)
