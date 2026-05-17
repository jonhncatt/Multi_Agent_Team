from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.runtime_boundary import RuntimeBoundary, build_runtime_boundary
from app.serialization import dump_model
from app.tool_trace_summary import normalize_tool_arguments, safe_error_message, safe_preview, validate_tool_arguments


class ValidationResult(BaseModel):
    allowed: bool
    code: str
    message: str
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    approval_reason: str = ""
    severity: str = "info"
    tool_name: str = ""
    raw_tool_name: str = ""
    raw_arguments: Any = None
    normalization_notes: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    schema_validation: dict[str, Any] = Field(default_factory=dict)


_READ_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "list_dir": ("path",),
    "read_file": ("path",),
    "read_text_file": ("path",),
    "glob_file_search": ("path",),
    "search_codebase": ("path",),
    "search_contents_in_file": ("path",),
    "search_contents_in_file_multi": ("path",),
    "read_section": ("path",),
    "table_extract": ("path",),
    "fact_check_file": ("path",),
    "image_read": ("path",),
    "image_inspect": ("path",),
}

_WRITE_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "write_file": ("path",),
    "write_text_file": ("path",),
    "append_file": ("path",),
    "append_text_file": ("path",),
    "replace_in_file": ("path",),
    "copy_file": ("dst_path", "destination", "target_path"),
    "extract_zip": ("dst_dir", "output_dir"),
    "web_download": ("dst_path", "path"),
}

_NETWORK_TOOLS = {"web_search", "web_fetch", "web_download", "search_web", "fetch_web", "download_web_file"}
_SHELL_TOOLS = {"exec_command", "run_shell", "write_stdin"}

_DANGEROUS_COMMAND_PATTERNS = (
    re.compile(r"(^|\s)rm\s+-[^\n;|&]*r[^\n;|&]*\s+/(?:\s|$)"),
    re.compile(r"(^|\s)rm\s+-[^\n;|&]*r[^\n;|&]*\s+~(?:\s|$)"),
    re.compile(r"(^|\s)sudo\s+rm(?:\s|$)"),
    re.compile(r"(^|\s)mkfs(?:\.|\s|$)"),
    re.compile(r"(^|\s)dd\s+if="),
    re.compile(r"(^|\s)chmod\s+-R\s+777\s+/(?:\s|$)"),
    re.compile(r"(^|\s)chown\s+-R(?:\s|$)"),
    re.compile(r"(^|\s)(curl|wget)\b[^\n|&;]*\|\s*(sh|bash|zsh|powershell|pwsh)\b"),
    re.compile(r"powershell\b[^\n]*(invoke-expression|iex)\b", re.IGNORECASE),
)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _resolved_roots(values: list[str]) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            path = Path(text).expanduser().resolve()
        except Exception:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    return roots


class ActionValidator:
    """Validate concrete model actions without making semantic tool-use decisions."""

    def __init__(
        self,
        *,
        tool_specs: list[dict[str, Any]],
        allowed_tools: list[str] | None = None,
        boundary: RuntimeBoundary | None = None,
        locale: str = "en",
        normalize_tool_name: Callable[[str], str] | None = None,
        argument_rewriter: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._tool_specs_by_name = {
            str(item.get("name") or "").strip(): dict(item)
            for item in list(tool_specs or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        self._allowed_tools = {str(item or "").strip() for item in list(allowed_tools or []) if str(item or "").strip()}
        self._boundary = boundary or RuntimeBoundary()
        self._locale = str(locale or "en")
        self._normalize_tool_name = normalize_tool_name or (lambda value: str(value or "").strip())
        self._argument_rewriter = argument_rewriter

    def validate_tool_call(self, raw_call: dict[str, Any]) -> ValidationResult:
        call = dict(raw_call or {})
        raw_tool_name = str(call.get("raw_name") or call.get("name") or "").strip()
        tool_name = self._normalize_tool_name(str(call.get("name") or raw_tool_name).strip())
        raw_arguments = self._raw_arguments(call)
        parsed_arguments, parse_status, parse_message, parse_notes = self._parse_arguments(raw_arguments)
        checks = {
            "json": "passed" if parse_status in {"valid_object", "empty_object", "missing"} else "failed",
            "tool_exists": "pending",
            "schema": "pending",
            "policy": "pending",
            "permission": "pending",
            "boundary": "pending",
        }
        if parse_status in {"invalid_json", "not_object"}:
            checks.update({"tool_exists": "skipped", "schema": "failed", "policy": "skipped", "permission": "skipped", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="invalid_arguments",
                message=parse_message,
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments={},
                normalization_notes=parse_notes,
                checks=checks,
                schema_validation={"status": "invalid", "checked": False, "summary": parse_message, "errors": [parse_message]},
            )

        checks["tool_exists"] = "passed" if tool_name in self._tool_specs_by_name else "failed"
        if tool_name not in self._tool_specs_by_name:
            checks.update({"schema": "skipped", "policy": "failed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="unknown_tool",
                message=f"Unknown tool: {raw_tool_name or tool_name or '(empty)'}",
                tool_name=tool_name or raw_tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                checks=checks,
                schema_validation={"status": "missing", "checked": False, "summary": "Tool is not available.", "errors": []},
            )

        if self._allowed_tools and tool_name not in self._allowed_tools:
            checks.update({"schema": "skipped", "policy": "failed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="tool_not_allowed",
                message=f"Tool is outside the current runtime boundary: {tool_name}",
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments=parsed_arguments,
                normalization_notes=parse_notes,
                checks=checks,
                schema_validation={"status": "skipped", "checked": False, "summary": "Tool is not allowed.", "errors": []},
            )

        tool_schema = dict((self._tool_specs_by_name.get(tool_name) or {}).get("parameters") or {})
        if tool_name == "update_plan":
            plan_result = self._validate_update_plan(parsed_arguments)
            if not plan_result.allowed:
                plan_result.tool_name = tool_name
                plan_result.raw_tool_name = raw_tool_name
                plan_result.raw_arguments = raw_arguments
                plan_result.normalization_notes = [*parse_notes, *plan_result.normalization_notes]
                return plan_result
            parsed_arguments = plan_result.normalized_arguments
            parse_notes = [*parse_notes, *plan_result.normalization_notes]

        normalization = normalize_tool_arguments(tool_name, parsed_arguments, tool_schema)
        normalized_arguments = dict(normalization.get("arguments") or {})
        notes = [*parse_notes, *[str(item) for item in list(normalization.get("notes") or []) if str(item or "")]]
        if self._argument_rewriter is not None:
            rewritten = self._argument_rewriter(tool_name, normalized_arguments)
            if rewritten != normalized_arguments:
                notes.append("argument_rewriter_applied")
            normalized_arguments = dict(rewritten or {})

        schema_validation = validate_tool_arguments(normalized_arguments, tool_schema, locale=self._locale)
        schema_status = str(schema_validation.get("status") or "")
        if schema_status == "valid":
            checks["schema"] = "normalized" if notes else "passed"
        elif schema_status == "missing":
            checks["schema"] = "missing"
        else:
            checks["schema"] = "failed"
            checks.update({"policy": "passed", "permission": "failed", "boundary": "skipped"})
            code = "missing_required_argument" if "required" in str(schema_validation.get("summary") or "").lower() else "invalid_arguments"
            return self._result(
                allowed=False,
                code=code,
                message=str(schema_validation.get("summary") or "Tool arguments are invalid."),
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments=normalized_arguments,
                normalization_notes=notes,
                checks=checks,
                schema_validation=schema_validation,
            )

        boundary_error = self._validate_boundary(tool_name, normalized_arguments)
        if boundary_error is not None:
            code, message = boundary_error
            checks.update({"policy": "passed", "permission": "failed", "boundary": "failed"})
            return self._result(
                allowed=False,
                code=code,
                message=message,
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments=normalized_arguments,
                normalization_notes=notes,
                checks=checks,
                schema_validation=schema_validation,
            )

        checks.update({"policy": "passed", "permission": "passed", "boundary": "passed"})
        return self._result(
            allowed=True,
            code="allowed",
            message=f"Action allowed: {tool_name}",
            tool_name=tool_name,
            raw_tool_name=raw_tool_name,
            raw_arguments=raw_arguments,
            normalized_arguments=normalized_arguments,
            normalization_notes=notes,
            checks=checks,
            schema_validation=schema_validation,
            severity="info",
        )

    @staticmethod
    def _raw_arguments(call: dict[str, Any]) -> Any:
        if "args" in call:
            return call.get("args")
        if "arguments" in call:
            return call.get("arguments")
        if "raw_args" in call:
            return call.get("raw_args")
        function = call.get("function")
        if isinstance(function, dict) and "arguments" in function:
            return function.get("arguments")
        return None

    @staticmethod
    def _parse_arguments(raw_arguments: Any) -> tuple[dict[str, Any], str, str, list[str]]:
        if raw_arguments is None:
            return {}, "missing", "Tool arguments are missing; using empty object.", []
        if isinstance(raw_arguments, dict):
            return dict(raw_arguments), "valid_object", "", []
        if isinstance(raw_arguments, str):
            text = raw_arguments.strip()
            if not text:
                return {}, "empty_object", "", ["arguments_empty_string"]
            try:
                parsed = json.loads(text)
            except Exception as exc:
                message = f"Tool arguments JSON parse failed: {safe_error_message(exc)}"
                return {}, "invalid_json", message, ["arguments_json_parse_failed"]
            if isinstance(parsed, dict):
                return dict(parsed), "valid_object", "", ["arguments_json_string_parsed"]
            return {}, "not_object", f"Tool arguments must be a JSON object, got {type(parsed).__name__}.", ["arguments_json_not_object"]
        return {}, "not_object", f"Tool arguments must be a JSON object, got {type(raw_arguments).__name__}.", ["arguments_not_object"]

    def _validate_update_plan(self, arguments: dict[str, Any]) -> ValidationResult:
        raw_plan = (
            arguments.get("plan")
            or arguments.get("steps")
            or arguments.get("items")
            or arguments.get("tasks")
            or arguments.get("plan_state")
        )
        checks = {"json": "passed", "tool_exists": "passed", "schema": "pending", "policy": "pending", "permission": "pending", "boundary": "pending"}
        if raw_plan is None:
            checks.update({"schema": "failed", "policy": "passed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="missing_required_argument",
                message="update_plan requires required field `plan`.",
                normalized_arguments=dict(arguments),
                checks=checks,
                schema_validation={"status": "invalid", "checked": True, "summary": "update_plan requires required field `plan`.", "errors": ["missing plan"]},
            )
        if not isinstance(raw_plan, list) or not raw_plan:
            checks.update({"schema": "failed", "policy": "passed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="invalid_arguments",
                message="update_plan `plan` must be a non-empty list.",
                normalized_arguments=dict(arguments),
                checks=checks,
                schema_validation={"status": "invalid", "checked": True, "summary": "update_plan `plan` must be a non-empty list.", "errors": ["plan must be non-empty list"]},
            )
        normalized_plan: list[dict[str, Any]] = []
        for index, item in enumerate(raw_plan):
            if not isinstance(item, dict):
                checks.update({"schema": "failed", "policy": "passed", "permission": "failed", "boundary": "skipped"})
                return self._result(
                    allowed=False,
                    code="invalid_arguments",
                    message=f"update_plan item {index} must be an object.",
                    normalized_arguments=dict(arguments),
                    checks=checks,
                    schema_validation={"status": "invalid", "checked": True, "summary": f"update_plan item {index} must be an object.", "errors": ["plan item must be object"]},
                )
            step = str(item.get("step") or item.get("title") or item.get("content") or "").strip()
            if not step:
                checks.update({"schema": "failed", "policy": "passed", "permission": "failed", "boundary": "skipped"})
                return self._result(
                    allowed=False,
                    code="missing_required_argument",
                    message=f"update_plan item {index} requires `step`.",
                    normalized_arguments=dict(arguments),
                    checks=checks,
                    schema_validation={"status": "invalid", "checked": True, "summary": f"update_plan item {index} requires `step`.", "errors": ["missing step"]},
                )
            status = str(item.get("status") or "pending").strip()
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            normalized = dict(item)
            normalized["step"] = step
            normalized["status"] = status
            normalized_plan.append(normalized)
        normalized_args = dict(arguments)
        normalized_args["plan"] = normalized_plan
        checks["schema"] = "normalized" if "plan" not in arguments else "passed"
        return self._result(
            allowed=True,
            code="allowed",
            message="Action allowed: update_plan",
            normalized_arguments=normalized_args,
            normalization_notes=["plan_alias_normalized"] if "plan" not in arguments else [],
            checks=checks,
            schema_validation={"status": "valid", "checked": True, "summary": "Tool arguments match the schema.", "errors": []},
        )

    def _validate_boundary(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, str] | None:
        if tool_name in _NETWORK_TOOLS:
            if not self._boundary.network_allowed:
                return "network_not_allowed", f"Network access is not allowed for tool: {tool_name}"
            url = str(arguments.get("url") or "").strip()
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"}:
                    return "network_not_allowed", "Only http/https URLs are allowed."
                host = str(parsed.hostname or "").lower()
                if host in {"localhost", "127.0.0.1", "::1"}:
                    return "network_not_allowed", "Localhost network access is not allowed."

        if tool_name in _SHELL_TOOLS:
            if not self._boundary.shell_allowed:
                return "shell_not_allowed", f"Shell execution is not allowed for tool: {tool_name}"
            cwd_error = self._validate_path_value(str(arguments.get("cwd") or "."), roots=self._allowed_roots(), code="path_outside_allowed_roots")
            if cwd_error is not None:
                return cwd_error
            command = str(arguments.get("cmd") or arguments.get("command") or "").strip()
            if command and self._is_dangerous_command(command):
                return "dangerous_command", "Command is blocked by the runtime boundary."

        read_fields = _READ_PATH_FIELDS.get(tool_name, ())
        if read_fields:
            if not self._boundary.workspace_read_allowed:
                return "workspace_read_not_allowed", f"Workspace read is not allowed for tool: {tool_name}"
            for field in read_fields:
                if field in arguments and arguments.get(field) not in ("", None):
                    path_error = self._validate_path_value(arguments.get(field), roots=self._allowed_roots(), code="path_outside_allowed_roots")
                    if path_error is not None:
                        return path_error

        write_fields = _WRITE_PATH_FIELDS.get(tool_name, ())
        if write_fields:
            if not self._boundary.workspace_write_allowed:
                return "workspace_write_not_allowed", f"Workspace write is not allowed for tool: {tool_name}"
            for field in write_fields:
                if field in arguments and arguments.get(field) not in ("", None):
                    path_error = self._validate_path_value(arguments.get(field), roots=self._writable_roots(), code="write_outside_writable_roots")
                    if path_error is not None:
                        return path_error

        if tool_name == "apply_patch":
            if not self._boundary.workspace_write_allowed:
                return "workspace_write_not_allowed", "Workspace write is not allowed for apply_patch."
            patch_text = str(arguments.get("patch") or "")
            for path_text in re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch_text, flags=re.MULTILINE):
                path_error = self._validate_path_value(path_text, roots=self._writable_roots(), code="write_outside_writable_roots")
                if path_error is not None:
                    return path_error

        return None

    def _allowed_roots(self) -> list[Path]:
        roots = _resolved_roots(self._boundary.allowed_roots)
        if roots:
            return roots
        return [Path(self._boundary.project_root or ".").expanduser().resolve()]

    def _writable_roots(self) -> list[Path]:
        roots = _resolved_roots(self._boundary.writable_roots)
        if roots:
            return roots
        return [Path(self._boundary.project_root or ".").expanduser().resolve()]

    def _validate_path_value(self, raw_value: Any, *, roots: list[Path], code: str) -> tuple[str, str] | None:
        raw = str(raw_value or ".").strip() or "."
        try:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                base = Path(self._boundary.cwd or self._boundary.project_root or ".").expanduser()
                if not base.is_absolute():
                    base = Path(self._boundary.project_root or ".").expanduser() / base
                candidate = base / candidate
            resolved = candidate.resolve()
        except Exception as exc:
            return code, f"Path could not be resolved: {safe_error_message(exc)}"
        if any(_is_within(resolved, root) for root in roots):
            return None
        allowed = ", ".join(str(root) for root in roots[:6])
        return code, f"The requested path is outside allowed roots: {raw}. Allowed roots: {allowed}"

    @staticmethod
    def _is_dangerous_command(command: str) -> bool:
        try:
            normalized = " ".join(shlex.split(command, posix=True)) if command.strip() else ""
        except Exception:
            normalized = ""
        text = normalized or command
        return any(pattern.search(text) for pattern in _DANGEROUS_COMMAND_PATTERNS)

    @staticmethod
    def _result(
        *,
        allowed: bool,
        code: str,
        message: str,
        normalized_arguments: dict[str, Any] | None = None,
        tool_name: str = "",
        raw_tool_name: str = "",
        raw_arguments: Any = None,
        normalization_notes: list[str] | None = None,
        checks: dict[str, Any] | None = None,
        schema_validation: dict[str, Any] | None = None,
        severity: str | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            allowed=bool(allowed),
            code=str(code or ("allowed" if allowed else "invalid_arguments")),
            message=str(message or ""),
            normalized_arguments=dict(normalized_arguments or {}),
            requires_approval=False,
            approval_reason="",
            severity=str(severity or ("info" if allowed else "error")),
            tool_name=str(tool_name or ""),
            raw_tool_name=str(raw_tool_name or ""),
            raw_arguments=safe_preview(raw_arguments, limit=4000),
            normalization_notes=[str(item) for item in list(normalization_notes or []) if str(item or "")],
            checks=dict(checks or {}),
            schema_validation=dict(schema_validation or {}),
        )


def validation_observation(result: ValidationResult, *, tool: str | None = None) -> dict[str, Any]:
    code = str(result.code or "invalid_arguments")
    observation_type = "validation_error"
    if code in {
        "path_outside_allowed_roots",
        "write_outside_writable_roots",
        "workspace_read_not_allowed",
        "workspace_write_not_allowed",
        "network_not_allowed",
        "shell_not_allowed",
        "dangerous_command",
        "tool_not_allowed",
    }:
        observation_type = "boundary_denied"
    if code in {"repeated_invalid_tool_call", "loop_limit_exceeded"}:
        observation_type = "loop_safeguard"
    retryable = code not in {"shell_not_allowed", "network_not_allowed", "workspace_write_not_allowed", "dangerous_command"}
    return {
        "ok": False,
        "type": observation_type,
        "tool": str(tool or result.tool_name or result.raw_tool_name or ""),
        "code": code,
        "message": str(result.message or ""),
        "retryable": bool(retryable),
        "suggestion": "Revise the tool call arguments, choose a permitted tool, or answer directly if a tool is unnecessary.",
        "validation_result": dump_model(result),
        "summary": str(result.message or ""),
    }
