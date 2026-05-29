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
from app.tool_metadata import get_tool_metadata
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
    "glob_file_search": ("path",),
    "search_codebase": ("path", "root"),
    "search_contents_in_file": ("path",),
    "search_contents_in_file_multi": ("path",),
    "read_section": ("path",),
    "table_extract": ("path",),
    "fact_check_file": ("path",),
    "image_read": ("path",),
    "image_inspect": ("path",),
}

_WRITE_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "web_download": ("dst_path", "path"),
}

_NETWORK_TOOLS = {"web_search", "web_fetch", "web_download"}
_SHELL_TOOLS = {"exec_command", "write_stdin"}

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

_REDACTION_PLACEHOLDER_FIELDS: dict[str, tuple[str, ...]] = {
    "glob_file_search": ("pattern", "path"),
    "search_codebase": ("query", "file_glob", "root"),
    "search_contents_in_file": ("query", "path"),
    "search_contents_in_file_multi": ("queries", "path"),
    "read_file": ("path",),
    "list_dir": ("path",),
    "read_section": ("path", "heading"),
    "table_extract": ("path",),
    "fact_check_file": ("path",),
}

_REDACTION_PLACEHOLDER_MESSAGE = (
    "*** is a UI redaction placeholder, not a real file name, path, glob pattern, function name, or search query. "
    "Use a concrete relative path or inspect the directory again with list_dir/glob_file_search using a narrower pattern."
)

_PATH_VALUE_FLAGS = {"-C", "--rootdir", "--prefix", "--cwd", "--config", "-f", "--file"}
_READ_COMMANDS = {"rg", "find", "ls", "cat", "head", "tail", "wc", "pytest", "node", "python", "python3", "py"}
_WRITE_COMMANDS = {"cp", "mv", "mkdir", "touch", "tee"}
_COMMON_PATH_SUFFIXES = (
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".css",
    ".html",
    ".sh",
)
_SHELL_CONNECTORS = {"&&", "||", "|"}
_SHELL_REDIRECT_WRITE_OPERATORS = {">", ">>", "1>", "1>>", "2>", "2>>"}
_SHELL_REDIRECT_READ_OPERATORS = {"<", "0<"}
_UNSUPPORTED_SHELL_PATTERNS = (
    (re.compile(r"\$\("), "command substitution"),
    (re.compile(r"`"), "command substitution"),
    (re.compile(r"<<<?"), "heredoc"),
    (re.compile(r"(^|(?:&&|\|\||;|\|)\s*)(for|while|until)\b"), "for/while loop"),
    (re.compile(r"(^|(?:&&|\|\||;|\|)\s*)if\b"), "if"),
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


def _contains_redaction_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip()
        if text == "***":
            return True
        normalized = text.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        return "***" in parts
    if isinstance(value, list):
        return any(_contains_redaction_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_redaction_placeholder(item) for item in value.values())
    return False


def split_command_safely(command: str) -> tuple[list[str], str | None]:
    raw = str(command or "").strip()
    if not raw:
        return [], "Empty command"
    try:
        return shlex.split(raw), None
    except Exception as exc:
        return [], f"Command parse failed: {safe_error_message(exc)}"


def is_dangerous_command(command: str) -> bool:
    try:
        normalized = " ".join(shlex.split(command, posix=True)) if command.strip() else ""
    except Exception:
        normalized = ""
    text = normalized or command
    return any(pattern.search(text) for pattern in _DANGEROUS_COMMAND_PATTERNS)


def shell_command_uses_compound_syntax(command: str) -> bool:
    raw = str(command or "").strip()
    if not raw:
        return False
    return any(token in raw for token in ("&&", "||", "|", ";", ">", "<", "$(", "`"))


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _is_path_like_token(token: str) -> bool:
    text = str(token or "").strip()
    if not text or _looks_like_url(text):
        return False
    if text in {".", ".."}:
        return True
    if text.startswith(("/", "./", "../", "~")):
        return True
    if "\\" in text or "/" in text:
        return True
    lowered = text.lower()
    return any(lowered.endswith(suffix) for suffix in _COMMON_PATH_SUFFIXES)


def _command_base(argv0: str) -> str:
    text = str(argv0 or "").replace("\\", "/").strip()
    return text.rsplit("/", 1)[-1].lower()


def _shell_parse_error(
    summary: str,
    *,
    error_kind: str = "unsupported_shell_structure",
    unsupported_structure: str = "",
    parsed_subcommands: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error_kind": error_kind,
        "summary": str(summary or "").strip(),
        "message": str(summary or "").strip(),
    }
    if unsupported_structure:
        payload["unsupported_structure"] = str(unsupported_structure)
    if parsed_subcommands is not None:
        payload["parsed_subcommands"] = [str(item) for item in list(parsed_subcommands or []) if str(item or "").strip()]
    return payload


def _unsupported_shell_structure(command: str) -> str:
    raw = str(command or "").strip()
    for pattern, label in _UNSUPPORTED_SHELL_PATTERNS:
        if pattern.search(raw):
            return str(label)
    return ""


def _tokenize_shell_command(command: str) -> list[str]:
    lexer = shlex.shlex(str(command or ""), posix=True, punctuation_chars="|&;<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _build_parsed_shell_subcommand(tokens: list[str]) -> dict[str, Any]:
    argv: list[str] = []
    redirects: list[dict[str, Any]] = []
    render_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index] or "").strip()
        if not token:
            index += 1
            continue
        if token in {";", "&", "(", ")", "<<", "<<<"}:
            return _shell_parse_error(
                f"Compound command contains shell structure that is not currently supported for safe validation: {token}. "
                "Please split it into simpler commands or use cwd/workdir explicitly.",
                unsupported_structure=token,
            )
        if token in _SHELL_REDIRECT_READ_OPERATORS:
            return _shell_parse_error(
                "Compound command contains current unsupported shell structure: input redirection. "
                "Please split it into simpler commands or use cwd/workdir explicitly.",
                unsupported_structure="input redirection",
            )
        if token in _SHELL_REDIRECT_WRITE_OPERATORS:
            if not argv:
                return _shell_parse_error("Shell redirection requires a command before the redirect operator.", error_kind="compound_shell_parse_failed")
            next_index = index + 1
            if next_index >= len(tokens):
                return _shell_parse_error("Shell redirection is missing a target path.", error_kind="compound_shell_parse_failed")
            target = str(tokens[next_index] or "").strip()
            if not target or target in _SHELL_CONNECTORS or target in _SHELL_REDIRECT_WRITE_OPERATORS | _SHELL_REDIRECT_READ_OPERATORS:
                return _shell_parse_error("Shell redirection target could not be parsed safely.", error_kind="compound_shell_parse_failed")
            redirects.append({"operator": token, "target": target, "access": "write"})
            render_tokens.extend([token, target])
            index += 2
            continue
        argv.append(token)
        render_tokens.append(token)
        index += 1
    if not argv:
        return _shell_parse_error("Compound command contains an empty subcommand.", error_kind="compound_shell_parse_failed")
    first = str(argv[0] or "").strip()
    if len(argv) > 1 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", first):
        return _shell_parse_error(
            "Compound command contains current unsupported shell structure: environment assignment prefix. "
            "Please split it into simpler commands or use explicit tool arguments instead.",
            unsupported_structure="environment assignment",
        )
    return {
        "ok": True,
        "subcommand": {
            "argv": list(argv),
            "text": " ".join(render_tokens).strip(),
            "base_command": _command_base(argv[0]),
            "redirects": redirects,
        },
    }


def parse_compound_shell_command(command: str) -> dict[str, Any]:
    raw = str(command or "").strip()
    if not raw:
        return _shell_parse_error("Empty command", error_kind="invalid_arguments")
    unsupported = _unsupported_shell_structure(raw)
    if unsupported:
        return _shell_parse_error(
            f"Compound command contains current unsupported shell structure: {unsupported}. "
            "Please split it into simpler commands or use cwd/workdir explicitly.",
            unsupported_structure=unsupported,
        )
    try:
        tokens = _tokenize_shell_command(raw)
    except Exception as exc:
        return _shell_parse_error(f"Command parse failed: {safe_error_message(exc)}", error_kind="compound_shell_parse_failed")
    if not tokens:
        return _shell_parse_error("Empty command", error_kind="invalid_arguments")
    subcommands: list[dict[str, Any]] = []
    current_tokens: list[str] = []
    operator_before = ""
    compound_shell = False
    for token in tokens:
        text = str(token or "").strip()
        if not text:
            continue
        if text in {";", "&", "(", ")", "<<", "<<<"}:
            return _shell_parse_error(
                f"Compound command contains current unsupported shell structure: {text}. "
                "Please split it into simpler commands or use cwd/workdir explicitly.",
                unsupported_structure=text,
            )
        if text in _SHELL_CONNECTORS:
            if not current_tokens:
                return _shell_parse_error("Compound command contains an empty subcommand before a shell operator.", error_kind="compound_shell_parse_failed")
            built = _build_parsed_shell_subcommand(current_tokens)
            if not built.get("ok"):
                return built
            subcommand = dict(built["subcommand"])
            subcommand["operator_before"] = operator_before
            subcommands.append(subcommand)
            current_tokens = []
            operator_before = text
            compound_shell = True
            continue
        current_tokens.append(text)
    if not current_tokens:
        return _shell_parse_error("Compound command ends with a shell operator and cannot be validated safely.", error_kind="compound_shell_parse_failed")
    built = _build_parsed_shell_subcommand(current_tokens)
    if not built.get("ok"):
        return built
    subcommand = dict(built["subcommand"])
    subcommand["operator_before"] = operator_before
    subcommands.append(subcommand)
    if any(list(item.get("redirects") or []) for item in subcommands):
        compound_shell = True
    return {
        "ok": True,
        "compound_shell": compound_shell,
        "parsed_subcommands": [str(item.get("text") or "").strip() for item in subcommands],
        "subcommands": subcommands,
    }


def extract_command_path_args(argv: list[str]) -> list[dict[str, Any]]:
    if not argv:
        return []
    base = _command_base(argv[0])
    items: list[dict[str, Any]] = []
    skip_next = False
    positional_count = 0
    write_indexes: set[int] = set()
    if base in {"cp", "mv"} and len(argv) >= 3:
        write_indexes.add(len(argv) - 1)
    elif base in {"mkdir", "touch"}:
        write_indexes.update(range(1, len(argv)))

    for index, token in enumerate(argv[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        text = str(token or "").strip()
        if not text:
            continue
        if text in _PATH_VALUE_FLAGS:
            next_index = index + 1
            if next_index < len(argv):
                items.append({"argument": argv[next_index], "index": next_index, "access": "read", "source": text})
                skip_next = True
            continue
        if any(text.startswith(flag + "=") for flag in _PATH_VALUE_FLAGS if flag.startswith("--")):
            flag, value = text.split("=", 1)
            items.append({"argument": value, "index": index, "access": "read", "source": flag})
            continue
        if text.startswith("-"):
            continue
        if base in {"python", "python3", "py"} and text == "-m":
            skip_next = True
            continue
        if base == "npm" and text == "--prefix":
            next_index = index + 1
            if next_index < len(argv):
                items.append({"argument": argv[next_index], "index": next_index, "access": "read", "source": "--prefix"})
                skip_next = True
            continue
        positional_count += 1
        treat_as_path = _is_path_like_token(text)
        if not treat_as_path:
            if base in {"ls", "find", "cat", "head", "tail", "wc", "pytest", "node", "tee"}:
                treat_as_path = True
            elif base == "rg" and positional_count >= 2:
                treat_as_path = True
        if not treat_as_path:
            continue
        access = "write" if index in write_indexes else "read"
        if base in _WRITE_COMMANDS and base not in {"cp", "mv"}:
            access = "write"
        items.append({"argument": text, "index": index, "access": access, "source": base})
    return items


def _resolve_command_arg_path(raw: str, *, cwd: Path) -> Path:
    candidate = Path(str(raw or "")).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        return candidate.resolve(strict=False)
    except Exception:
        return candidate.absolute()


def _parent_for_boundary(path: Path) -> Path:
    if path.exists():
        return path
    return path.parent if str(path.parent) else path


def _validate_command_path_item(
    raw_arg: str,
    *,
    access: str,
    cwd: Path,
    command_allowed_roots: list[Path],
    writable_roots: list[Path],
) -> tuple[bool, dict[str, Any]]:
    command_roots = [root.expanduser().resolve() for root in command_allowed_roots if str(root or "").strip()]
    write_roots = [root.expanduser().resolve() for root in writable_roots if str(root or "").strip()]
    resolved = _resolve_command_arg_path(raw_arg, cwd=cwd)
    boundary_path = _parent_for_boundary(resolved)
    if not any(_is_within(boundary_path, root) for root in command_roots):
        return False, {
            "kind": "command_path_outside_allowed_roots",
            "message": "Command path argument is outside command allowed roots.",
            "argument": raw_arg,
            "resolved_path": str(resolved),
            "command_allowed_roots": [str(root) for root in command_roots],
        }
    if access == "write" and not any(_is_within(boundary_path, root) for root in write_roots):
        return False, {
            "kind": "command_path_outside_allowed_roots",
            "message": "Command write path argument is outside writable command roots.",
            "argument": raw_arg,
            "resolved_path": str(resolved),
            "command_allowed_roots": [str(root) for root in command_roots],
            "writable_roots": [str(root) for root in write_roots],
        }
    return True, {}


def validate_command_path_args(
    argv: list[str],
    *,
    cwd: Path,
    command_allowed_roots: list[Path],
    writable_roots: list[Path],
) -> tuple[bool, dict[str, Any]]:
    for item in extract_command_path_args(argv):
        raw_arg = str(item.get("argument") or "").strip()
        if not raw_arg:
            continue
        ok, detail = _validate_command_path_item(
            raw_arg,
            access=str(item.get("access") or "read"),
            cwd=cwd,
            command_allowed_roots=command_allowed_roots,
            writable_roots=writable_roots,
        )
        if not ok:
            return False, detail
    return True, {}


def validate_single_command_for_compound_shell(
    argv: list[str],
    *,
    cwd: Path,
    command_allowed_roots: list[Path],
    writable_roots: list[Path],
    redirects: list[dict[str, Any]] | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not argv:
        return False, {
            "kind": "compound_shell_parse_failed",
            "message": "Compound command contains an empty subcommand.",
        }
    ok, detail = validate_command_path_args(
        argv,
        cwd=cwd,
        command_allowed_roots=command_allowed_roots,
        writable_roots=writable_roots,
    )
    if not ok:
        return False, detail
    for redirect in list(redirects or []):
        target = str(redirect.get("target") or "").strip()
        if not target:
            continue
        ok, detail = _validate_command_path_item(
            target,
            access=str(redirect.get("access") or "write"),
            cwd=cwd,
            command_allowed_roots=command_allowed_roots,
            writable_roots=writable_roots,
        )
        if not ok:
            return False, detail
    return True, {}


def _compound_subcommand_rejection(
    *,
    index: int,
    subcommand: str,
    reason: str,
    parsed_subcommands: list[str],
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error_kind": "compound_shell_subcommand_rejected",
        "summary": f"Compound command subcommand #{index} did not pass validation.",
        "message": f"Compound command subcommand #{index} did not pass validation.",
        "failed_subcommand": str(subcommand or "").strip(),
        "failed_index": int(index),
        "reason": str(reason or "").strip(),
        "parsed_subcommands": [str(item) for item in list(parsed_subcommands or []) if str(item or "").strip()],
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def validate_compound_shell_command(
    command: str,
    *,
    cwd: Path,
    command_allowed_roots: list[Path],
    writable_roots: list[Path],
    allowed_commands: list[str] | set[str] | tuple[str, ...] | None = None,
) -> tuple[bool, dict[str, Any]]:
    parsed = parse_compound_shell_command(command)
    if not parsed.get("ok"):
        return False, dict(parsed)
    subcommands = [dict(item) for item in list(parsed.get("subcommands") or []) if isinstance(item, dict)]
    parsed_subcommands = [str(item) for item in list(parsed.get("parsed_subcommands") or []) if str(item or "").strip()]
    effective_cwd = cwd.resolve()
    command_roots = [root.expanduser().resolve() for root in command_allowed_roots if str(root or "").strip()]
    allowed_base_commands = {_command_base(str(item or "")) for item in list(allowed_commands or []) if str(item or "").strip()}
    for index, subcommand in enumerate(subcommands, start=1):
        argv = [str(item) for item in list(subcommand.get("argv") or []) if str(item or "").strip()]
        text = str(subcommand.get("text") or "").strip()
        if not argv:
            return False, _compound_subcommand_rejection(
                index=index,
                subcommand=text,
                reason="Subcommand is empty.",
                parsed_subcommands=parsed_subcommands,
            )
        base = _command_base(argv[0])
        if base == "cd":
            if len(argv) != 2:
                return False, _compound_subcommand_rejection(
                    index=index,
                    subcommand=text,
                    reason="Only simple `cd <path>` subcommands are supported.",
                    parsed_subcommands=parsed_subcommands,
                )
            target = str(argv[1] or "").strip()
            resolved = _resolve_command_arg_path(target, cwd=effective_cwd)
            boundary_path = _parent_for_boundary(resolved)
            if not any(_is_within(boundary_path, root) for root in command_roots):
                return False, _compound_subcommand_rejection(
                    index=index,
                    subcommand=text,
                    reason="cd target is outside command allowed roots.",
                    parsed_subcommands=parsed_subcommands,
                    detail={
                        "kind": "command_path_outside_allowed_roots",
                        "message": "cd target is outside command allowed roots.",
                        "argument": target,
                        "resolved_path": str(resolved),
                        "command_allowed_roots": [str(root) for root in command_roots],
                    },
                )
            effective_cwd = resolved
            continue
        if allowed_base_commands and base not in allowed_base_commands:
            return False, _compound_subcommand_rejection(
                index=index,
                subcommand=text,
                reason=f"Command not allowed: {base}. Allowed: {', '.join(sorted(allowed_base_commands))}",
                parsed_subcommands=parsed_subcommands,
                detail={
                    "kind": "command_not_allowed",
                    "message": f"Command not allowed: {base}. Allowed: {', '.join(sorted(allowed_base_commands))}",
                    "base_command": base,
                    "allowed_commands": sorted(allowed_base_commands),
                },
            )
        ok, detail = validate_single_command_for_compound_shell(
            argv,
            cwd=effective_cwd,
            command_allowed_roots=command_allowed_roots,
            writable_roots=writable_roots,
            redirects=list(subcommand.get("redirects") or []),
        )
        if not ok:
            return False, _compound_subcommand_rejection(
                index=index,
                subcommand=text,
                reason=str(detail.get("message") or "Subcommand validation failed."),
                parsed_subcommands=parsed_subcommands,
                detail=detail,
            )
    return True, {
        "ok": True,
        "compound_shell": bool(parsed.get("compound_shell")),
        "parsed_subcommands": parsed_subcommands,
        "subcommands": subcommands,
    }


class ActionValidator:
    """Validate concrete model actions without making semantic tool-use decisions."""

    def __init__(
        self,
        *,
        tool_specs: list[dict[str, Any]],
        allowed_tools: list[str] | None = None,
        allowed_commands: list[str] | None = None,
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
        self._allowed_commands = {_command_base(str(item or "")) for item in list(allowed_commands or []) if str(item or "").strip()}
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

        metadata_error = self._validate_metadata_capabilities(tool_name)
        if metadata_error is not None:
            code, message = metadata_error
            checks.update({"schema": "skipped", "policy": "passed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code=code,
                message=message,
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments=parsed_arguments,
                normalization_notes=parse_notes,
                checks=checks,
                schema_validation={"status": "skipped", "checked": False, "summary": "Blocked by tool capability policy.", "errors": []},
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

        redaction_field = self._redaction_placeholder_field(tool_name, normalized_arguments)
        if redaction_field:
            checks.update({"policy": "passed", "permission": "failed", "boundary": "skipped"})
            return self._result(
                allowed=False,
                code="redaction_placeholder_used",
                message=_REDACTION_PLACEHOLDER_MESSAGE,
                tool_name=tool_name,
                raw_tool_name=raw_tool_name,
                raw_arguments=raw_arguments,
                normalized_arguments=normalized_arguments,
                normalization_notes=[*notes, f"redaction_placeholder_field:{redaction_field}"],
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

    def _validate_metadata_capabilities(self, tool_name: str) -> tuple[str, str] | None:
        metadata = get_tool_metadata(tool_name)
        requires = dict(metadata.get("requires") or {})
        if bool(requires.get("workspace_read")) and not self._boundary.workspace_read_allowed:
            return "workspace_read_not_allowed", f"Workspace read is not allowed for tool: {tool_name}"
        if bool(requires.get("workspace_write")) and not self._boundary.workspace_write_allowed:
            return "workspace_write_not_allowed", f"Workspace write is not allowed for tool: {tool_name}"
        if bool(requires.get("shell")) and not self._boundary.shell_allowed:
            return "shell_not_allowed", f"Shell execution is not allowed for tool: {tool_name}"
        if bool(requires.get("network")) and not self._boundary.network_allowed:
            return "network_not_allowed", f"Network access is not allowed for tool: {tool_name}"
        browser_allowed = bool(getattr(self._boundary, "browser_allowed", self._boundary.network_allowed))
        if bool(requires.get("browser")) and not browser_allowed:
            return "browser_not_allowed", f"Browser access is not allowed for tool: {tool_name}"
        return None

    @staticmethod
    def _redaction_placeholder_field(tool_name: str, arguments: dict[str, Any]) -> str:
        for field in _REDACTION_PLACEHOLDER_FIELDS.get(tool_name, ()):
            if field in arguments and _contains_redaction_placeholder(arguments.get(field)):
                return field
        return ""

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
            command_roots = self._command_roots()
            cwd_error = self._validate_path_value(str(arguments.get("cwd") or "."), roots=command_roots, code="command_path_outside_allowed_roots")
            if cwd_error is not None:
                return cwd_error
            command = str(arguments.get("cmd") or arguments.get("command") or "").strip()
            if command and self._is_dangerous_command(command):
                return "dangerous_command", "Command is blocked by the runtime boundary."
            if command and tool_name != "write_stdin":
                cwd_path = self._resolve_path_for_validation(str(arguments.get("cwd") or "."))
                if shell_command_uses_compound_syntax(command):
                    ok, detail = validate_compound_shell_command(
                        command,
                        cwd=cwd_path,
                        command_allowed_roots=command_roots,
                        writable_roots=self._writable_roots(),
                        allowed_commands=self._allowed_commands,
                    )
                    if not ok:
                        error_kind = str(detail.get("error_kind") or detail.get("kind") or "invalid_arguments")
                        if error_kind == "command_path_outside_allowed_roots":
                            return "command_path_outside_allowed_roots", str(detail.get("message") or "Command path argument is outside command allowed roots.")
                        if error_kind == "compound_shell_subcommand_rejected":
                            nested = detail.get("detail")
                            if isinstance(nested, dict) and str(nested.get("kind") or "") == "command_path_outside_allowed_roots":
                                return "command_path_outside_allowed_roots", str(detail.get("reason") or detail.get("message") or "Command path argument is outside command allowed roots.")
                            if isinstance(nested, dict) and str(nested.get("kind") or "") == "command_not_allowed":
                                return "command_not_allowed", str(detail.get("reason") or detail.get("message") or "Command is not allowed.")
                            return "invalid_arguments", str(detail.get("reason") or detail.get("message") or "Compound shell command could not be validated safely.")
                        return "invalid_arguments", str(detail.get("message") or "Compound shell command could not be validated safely.")
                else:
                    argv, split_error = split_command_safely(command)
                    if split_error:
                        return "invalid_arguments", split_error
                    ok, detail = validate_command_path_args(
                        argv,
                        cwd=cwd_path,
                        command_allowed_roots=command_roots,
                        writable_roots=self._writable_roots(),
                    )
                if not ok:
                    return "command_path_outside_allowed_roots", str(detail.get("message") or "Command path argument is outside command allowed roots.")

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

    def _command_roots(self) -> list[Path]:
        roots = _resolved_roots(getattr(self._boundary, "command_allowed_roots", []))
        if roots:
            return roots
        return [Path(self._boundary.project_root or ".").expanduser().resolve()]

    def _resolve_path_for_validation(self, raw_value: Any) -> Path:
        raw = str(raw_value or ".").strip() or "."
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            base = Path(self._boundary.cwd or self._boundary.project_root or ".").expanduser()
            if not base.is_absolute():
                base = Path(self._boundary.project_root or ".").expanduser() / base
            candidate = base / candidate
        return candidate.resolve(strict=False)

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
        return is_dangerous_command(command)

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
        "browser_not_allowed",
        "shell_not_allowed",
        "dangerous_command",
        "tool_not_allowed",
        "command_path_outside_allowed_roots",
    }:
        observation_type = "boundary_denied"
    if code in {"repeated_invalid_tool_call", "loop_limit_exceeded"}:
        observation_type = "loop_safeguard"
    retryable = code not in {"shell_not_allowed", "network_not_allowed", "browser_not_allowed", "workspace_write_not_allowed", "dangerous_command"}
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
