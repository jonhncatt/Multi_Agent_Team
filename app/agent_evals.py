from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
from uuid import uuid4

from app.config import AppConfig, build_provider_config, load_config
from app.models import ChatSettings
from app.tool_failures import classify_tool_event, failure_key
from app.vintage_programmer_runtime import VintageProgrammerRuntime


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_PATH = ROOT / "evals" / "agent_quality_cases.json"
AGENT_DIR = ROOT / "agents" / "vintage_programmer"
SCHEMA_VERSION = 1
SUPPORTED_CASE_KIND = "agent_workspace"
SUPPORTED_INPUT_MODALITIES = {"text", "markdown", "source", "c", "cpp", "pdf", "excel"}
DEFAULT_IGNORED_CHANGE_GLOBS = (
    ".eval_build/**",
    ".eval_runtime/**",
    "app/data/**",
    "**/__pycache__/**",
    "**/*.pyc",
)
READ_EVIDENCE_TOOLS = {
    "read_file",
    "read_section",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "fact_check_file",
}
WRITE_CAPABLE_TOOLS = {
    "apply_patch",
    "exec_command",
    "web_download",
    "archive_extract",
    "mail_extract_attachments",
}
READ_COMMAND_MARKERS = (
    "cat ",
    "type ",
    "get-content",
    "more ",
    "sed ",
    "head ",
    "tail ",
    "rg ",
    "grep ",
    "python ",
    "python3 ",
    "py ",
)


class EvalConfigurationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return normalized[:80] or "eval-case"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def safe_report_path(path: Path, *, fallback_label: str = "isolated-path") -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except Exception:
        return f"<{fallback_label}>/{resolved.name}"


def _resolve_repo_path(raw: str, *, require_dir: bool = False, require_file: bool = False) -> Path:
    candidate = Path(str(raw or "").strip())
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.expanduser().resolve()
    if not _is_within(resolved, ROOT):
        raise EvalConfigurationError(f"Eval path escapes repository root: {raw}")
    if require_dir and not resolved.is_dir():
        raise EvalConfigurationError(f"Eval fixture directory does not exist: {raw}")
    if require_file and not resolved.is_file():
        raise EvalConfigurationError(f"Eval file does not exist: {raw}")
    return resolved


def load_eval_suite(path: str | Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = (ROOT / resolved).resolve()
    if not resolved.is_file():
        raise EvalConfigurationError(f"Eval cases file does not exist: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvalConfigurationError(f"Eval cases JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvalConfigurationError("Current eval suite must be a JSON object, not the legacy list format.")
    payload["_cases_path"] = str(resolved)
    validate_eval_suite(payload)
    return payload


def validate_eval_suite(suite: dict[str, Any]) -> None:
    if int(suite.get("schema_version") or 0) != SCHEMA_VERSION:
        raise EvalConfigurationError(f"Unsupported eval schema_version; expected {SCHEMA_VERSION}.")
    if not str(suite.get("suite") or "").strip():
        raise EvalConfigurationError("Eval suite requires a non-empty suite name.")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvalConfigurationError("Eval suite requires at least one case.")

    seen: set[str] = set()
    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, dict):
            raise EvalConfigurationError(f"Case #{index + 1} must be an object.")
        name = str(raw_case.get("name") or "").strip()
        if not name:
            raise EvalConfigurationError(f"Case #{index + 1} requires a name.")
        if name in seen:
            raise EvalConfigurationError(f"Duplicate eval case name: {name}")
        seen.add(name)
        if str(raw_case.get("kind") or "") != SUPPORTED_CASE_KIND:
            raise EvalConfigurationError(
                f"Case {name} uses unsupported kind {raw_case.get('kind')!r}; "
                f"current runner supports only {SUPPORTED_CASE_KIND!r}."
            )
        fixture = _resolve_repo_path(str(raw_case.get("fixture") or ""), require_dir=True)
        message = str(raw_case.get("message") or "").strip()
        if not message:
            raise EvalConfigurationError(f"Case {name} requires a message.")
        required_context = _string_list(raw_case.get("required_context_files"))
        target_files = _string_list(raw_case.get("target_files"))
        allowed_changes = _string_list(raw_case.get("allowed_changed_files"))
        if not required_context or not target_files or not allowed_changes:
            raise EvalConfigurationError(
                f"Case {name} requires required_context_files, target_files, and allowed_changed_files."
            )
        steer_messages = _string_list(raw_case.get("steer_messages"))
        if "steer_messages" in raw_case and not steer_messages:
            raise EvalConfigurationError(f"Case {name} steer_messages must contain non-empty messages.")
        required_tools = _string_list(raw_case.get("required_tools"))
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", tool) for tool in required_tools):
            raise EvalConfigurationError(f"Case {name} contains an invalid required_tools entry.")
        forbidden_tools = _string_list(raw_case.get("forbidden_tools"))
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", tool) for tool in forbidden_tools):
            raise EvalConfigurationError(f"Case {name} contains an invalid forbidden_tools entry.")
        overlap = sorted(set(required_tools) & set(forbidden_tools))
        if overlap:
            raise EvalConfigurationError(
                f"Case {name} cannot require and forbid the same tools: {', '.join(overlap)}."
            )
        forbidden_command_patterns = list(raw_case.get("forbidden_command_patterns") or [])
        forbidden_labels: set[str] = set()
        for entry in forbidden_command_patterns:
            if not isinstance(entry, dict):
                raise EvalConfigurationError(
                    f"Case {name} forbidden_command_patterns entries must be objects."
                )
            label = str(entry.get("label") or "").strip()
            expression = str(entry.get("pattern") or "").strip()
            if not label or label in forbidden_labels or not expression:
                raise EvalConfigurationError(
                    f"Case {name} contains an invalid or duplicate forbidden command pattern."
                )
            try:
                re.compile(expression, flags=re.IGNORECASE)
            except re.error as exc:
                raise EvalConfigurationError(
                    f"Case {name} forbidden command pattern {label!r} is invalid: {exc}"
                ) from exc
            forbidden_labels.add(label)
        modalities = set(_string_list(raw_case.get("input_modalities")))
        if modalities - SUPPORTED_INPUT_MODALITIES:
            raise EvalConfigurationError(
                f"Case {name} contains unsupported input_modalities: {sorted(modalities - SUPPORTED_INPUT_MODALITIES)}"
            )
        thread_seed = _mapping(raw_case.get("thread_seed"))
        if thread_seed and int(thread_seed.get("turn_pairs") or 0) < 1:
            raise EvalConfigurationError(f"Case {name} thread_seed.turn_pairs must be positive.")
        team_skill_seed = _mapping(raw_case.get("team_skill_seed"))
        if team_skill_seed:
            skill_name = str(team_skill_seed.get("name") or "").strip()
            source = str(team_skill_seed.get("source") or "").strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", skill_name):
                raise EvalConfigurationError(f"Case {name} team_skill_seed.name is invalid.")
            source_path = (fixture / source).resolve()
            if not source or not _is_within(source_path, fixture) or not source_path.is_dir():
                raise EvalConfigurationError(f"Case {name} team_skill_seed.source is missing or unsafe.")
        required_fixture_files = [*required_context, *target_files, *_string_list(raw_case.get("protected_files"))]
        verification = _mapping(raw_case.get("verification"))
        verification_script = str(verification.get("script") or "").strip()
        if not verification_script:
            raise EvalConfigurationError(f"Case {name} requires verification.script.")
        if "agent_must_run" in verification and not isinstance(verification.get("agent_must_run"), bool):
            raise EvalConfigurationError(f"Case {name} verification.agent_must_run must be a boolean.")
        required_fixture_files.append(verification_script)
        for relative in required_fixture_files:
            if relative.startswith("team/") and team_skill_seed:
                continue
            resolved = (fixture / relative).resolve()
            if not _is_within(resolved, fixture) or not resolved.is_file():
                raise EvalConfigurationError(f"Case {name} fixture file is missing or unsafe: {relative}")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(item).strip().replace("\\", "/") for item in list(value or []) if str(item).strip()]


def _is_ignored(relative_path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = str(relative_path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def snapshot_workspace(root: Path, *, ignored_globs: list[str] | tuple[str, ...] = ()) -> dict[str, str]:
    patterns = [*DEFAULT_IGNORED_CHANGE_GLOBS, *list(ignored_globs or [])]
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_ignored(relative, patterns):
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _prepare_team_skill_seed(
    workspace: Path,
    case: dict[str, Any],
) -> Path | None:
    seed = _mapping(case.get("team_skill_seed"))
    if not seed:
        return None
    source = (workspace / str(seed.get("source") or "")).resolve()
    skill_name = str(seed.get("name") or "").strip()
    target = workspace / ".eval_runtime" / "vp_install" / "skills" / "team" / skill_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target.parent


def _prefixed_snapshot(snapshot: dict[str, str], prefix: str) -> dict[str, str]:
    clean_prefix = str(prefix or "").strip("/")
    return {f"{clean_prefix}/{path}": digest for path, digest in snapshot.items()}


def build_eval_thread_seed(case: dict[str, Any]) -> dict[str, Any]:
    seed = _mapping(case.get("thread_seed"))
    if not seed:
        return {
            "thread_transcript": {"schema_version": 1, "items": []},
            "compaction_status": {},
            "seeded_item_count": 0,
            "compacted_item_count": 0,
        }
    turn_pairs = max(1, min(200, int(seed.get("turn_pairs") or 1)))
    chars_per_message = max(32, min(8000, int(seed.get("chars_per_message") or 256)))
    retain_pairs = max(1, min(turn_pairs, int(seed.get("retain_pairs") or 2)))
    topic = str(seed.get("topic") or "historical project discussion").strip()
    items: list[dict[str, Any]] = []
    filler = (str(seed.get("filler") or "context ") * (chars_per_message // 8 + 2))[:chars_per_message]
    for index in range(1, turn_pairs + 1):
        items.extend(
            [
                {
                    "id": f"seed-u-{index}",
                    "turn_id": f"seed-u-{index}",
                    "role": "user",
                    "content": f"{topic} user turn {index}: {filler}",
                },
                {
                    "id": f"seed-a-{index}",
                    "turn_id": f"seed-a-{index}",
                    "role": "assistant",
                    "content": f"{topic} assistant turn {index}: {filler}",
                },
            ]
        )
    compacted_pairs = max(0, turn_pairs - retain_pairs)
    compaction_status: dict[str, Any] = {}
    if compacted_pairs:
        compaction_status = {
            "compacted_history": str(seed.get("compacted_history") or f"Earlier discussion summary: {topic}"),
            "compacted_until_turn_id": f"seed-a-{compacted_pairs}",
            "generation": 1,
            "last_compaction_phase": "eval_seed",
        }
    return {
        "thread_transcript": {"schema_version": 1, "items": items},
        "compaction_status": compaction_status,
        "seeded_item_count": len(items),
        "compacted_item_count": compacted_pairs * 2,
    }


def compare_snapshots(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    before_paths = set(before)
    after_paths = set(after)
    return {
        "added": sorted(after_paths - before_paths),
        "modified": sorted(path for path in before_paths & after_paths if before[path] != after[path]),
        "deleted": sorted(before_paths - after_paths),
        "changed": sorted(
            (after_paths - before_paths)
            | (before_paths - after_paths)
            | {path for path in before_paths & after_paths if before[path] != after[path]}
        ),
    }


def _strip_cpp_comments_and_literals(text: str) -> str:
    pattern = re.compile(
        r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        flags=re.DOTALL,
    )
    return pattern.sub(" ", str(text or ""))


def scan_c_style_rules(workspace: Path, case: dict[str, Any]) -> list[dict[str, str]]:
    rule_spec = _mapping(case.get("c_style_rules"))
    files = _string_list(rule_spec.get("files") or case.get("target_files"))
    raw_patterns = list(rule_spec.get("forbidden_patterns") or [])
    if not raw_patterns:
        return []
    violations: list[dict[str, str]] = []
    for relative in files:
        path = (workspace / relative).resolve()
        if not _is_within(path, workspace) or not path.is_file():
            violations.append({"file": relative, "rule": "target_missing", "match": ""})
            continue
        searchable = _strip_cpp_comments_and_literals(path.read_text(encoding="utf-8", errors="replace"))
        for raw in raw_patterns:
            if isinstance(raw, str):
                expression = raw
                label = raw
            elif isinstance(raw, dict):
                expression = str(raw.get("pattern") or "")
                label = str(raw.get("label") or expression)
            else:
                continue
            if not expression:
                continue
            match = re.search(expression, searchable, flags=re.MULTILINE)
            if match:
                violations.append(
                    {
                        "file": relative,
                        "rule": label,
                        "match": str(match.group(0) or "")[:120],
                    }
                )
    return violations


def _event_payload_text(event: dict[str, Any]) -> str:
    selected = {
        "input": event.get("input"),
        "normalized_arguments": event.get("normalized_arguments"),
        "raw_arguments": event.get("raw_arguments"),
        "arguments_preview": event.get("arguments_preview"),
    }
    return json.dumps(_jsonable(selected), ensure_ascii=False).replace("\\", "/").lower()


def scan_forbidden_command_patterns(
    tool_events: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> list[str]:
    """Return redaction-safe labels for forbidden commands the Agent attempted."""
    observed: set[str] = set()
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for entry in patterns:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        expression = str(entry.get("pattern") or "").strip()
        if not label or not expression:
            continue
        try:
            compiled.append((label, re.compile(expression, flags=re.IGNORECASE)))
        except re.error:
            continue
    for event in tool_events:
        if str(event.get("name") or "").strip() != "exec_command":
            continue
        payload_text = _event_payload_text(event)
        for label, expression in compiled:
            if expression.search(payload_text):
                observed.add(label)
    return sorted(observed)


def analyze_tool_evidence(
    tool_events: list[dict[str, Any]],
    *,
    required_context_files: list[str],
    verification_markers: list[str],
) -> dict[str, Any]:
    observed: dict[str, bool] = {path: False for path in required_context_files}
    verification_attempted = False
    verification_succeeded = False
    failed_tool_calls = 0
    fingerprints: list[str] = []

    for event in tool_events:
        name = str(event.get("name") or "").strip()
        payload_text = _event_payload_text(event)
        is_verification = bool(
            name == "exec_command"
            and any(marker.lower() in payload_text for marker in verification_markers)
        )
        if classify_tool_event(event, is_verification=is_verification):
            failed_tool_calls += 1
        fingerprints.append(f"{name}:{payload_text[:240]}")

        read_capable = name in READ_EVIDENCE_TOOLS
        if name == "exec_command" and any(marker in payload_text for marker in READ_COMMAND_MARKERS):
            read_capable = True
        if read_capable:
            for relative in observed:
                normalized = relative.replace("\\", "/").lower()
                basename = Path(relative).name.lower()
                if normalized in payload_text or basename in payload_text:
                    observed[relative] = True

        if is_verification:
            verification_attempted = True
            verification_succeeded = verification_succeeded or _tool_event_succeeded(event)

    repeats = max(0, len(fingerprints) - len(set(fingerprints)))
    return {
        "required_context_files": observed,
        "context_files_observed": sum(1 for value in observed.values() if value),
        "context_files_required": len(observed),
        "context_coverage_complete": all(observed.values()) if observed else True,
        "agent_verification_attempted": verification_attempted,
        "agent_verification_succeeded": verification_succeeded,
        "tool_call_count": len(tool_events),
        "failed_tool_call_count": failed_tool_calls,
        "repeated_tool_call_count": repeats,
    }


def _tool_event_succeeded(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "").strip().lower()
    if status in {"failed", "error", "blocked", "rejected"}:
        return False
    preview = event.get("result_preview")
    if isinstance(preview, dict):
        if preview.get("ok") is False:
            return False
        return_code = preview.get("returncode")
        if return_code is not None:
            try:
                return int(return_code) == 0
            except Exception:
                return False
    output = str(event.get("output_preview") or "")
    try:
        decoded = json.loads(output)
    except Exception:
        decoded = None
    if isinstance(decoded, dict):
        if decoded.get("ok") is False:
            return False
        returncode = decoded.get("returncode")
        if returncode is not None:
            try:
                return int(returncode) == 0
            except Exception:
                return False
    return status not in {"failed", "error", "blocked", "rejected"}


def _redact_output(text: str, *, workspace: Path, limit: int = 8000) -> str:
    value = str(text or "")
    replacements = [str(workspace), str(Path.home())]
    for secret in replacements:
        if secret:
            value = value.replace(secret, "<redacted-path>")
            value = value.replace(secret.replace("\\", "/"), "<redacted-path>")
    value = re.sub(r"https?://[^\s\"']+", "<redacted-url>", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"']+", "<redacted-path>", value)
    value = re.sub(r"(?<![A-Za-z0-9_])\\\\[^\s\"']+", "<redacted-path>", value)
    value = re.sub(r"(?<![A-Za-z0-9_])/(?:[^/\s\"']+/)+[^/\s\"']*", "<redacted-path>", value)
    if len(value) > limit:
        value = value[-limit:]
    return value


def _safe_runtime_state(value: Any, *, fallback_kind: str) -> dict[str, Any]:
    payload = _mapping(value)
    if not payload:
        return {}
    raw_kind = (
        payload.get("error_kind")
        or payload.get("kind")
        or payload.get("type")
        or payload.get("code")
        or fallback_kind
    )
    kind = re.sub(r"[^a-z0-9_]+", "_", str(raw_kind or "").strip().lower()).strip("_")[:80]
    return {
        "present": True,
        "kind": kind or fallback_kind,
        "details_omitted": True,
    }


def _wrapper_argv(script: Path, *, workspace: Path, case_name: str) -> list[str]:
    suffix = script.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(script), str(workspace), case_name]
    if suffix in {".bat", ".cmd"}:
        command_shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
        command_text = subprocess.list2cmdline([str(script), str(workspace), case_name])
        return [command_shell, "/d", "/s", "/c", command_text]
    if suffix == ".ps1":
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise FileNotFoundError("PowerShell is unavailable for the configured verifier script.")
        return [powershell, "-NoProfile", "-File", str(script), str(workspace), case_name]
    return [str(script), str(workspace), case_name]


def execute_authoritative_verifier(
    workspace: Path,
    case: dict[str, Any],
    *,
    verifier_script: str | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    verification = _mapping(case.get("verification"))
    timeout = max(1.0, float(timeout_sec or verification.get("timeout_sec") or 90.0))
    configured_script = str(
        verifier_script
        if verifier_script is not None
        else os.environ.get("VP_EVAL_CPP_VERIFY_SCRIPT", "")
    ).strip()
    if not bool(verification.get("use_company_wrapper", True)):
        configured_script = ""
    source = "portable_fixture"
    try:
        if configured_script:
            script_path = Path(configured_script).expanduser()
            if not script_path.is_absolute() or not script_path.is_file():
                return {
                    "status": "blocked",
                    "source": "company_wrapper",
                    "returncode": 2,
                    "summary": "Configured company verifier script is unavailable.",
                    "stdout": "",
                    "stderr": "",
                }
            argv = _wrapper_argv(script_path.resolve(), workspace=workspace, case_name=str(case.get("name") or ""))
            source = "company_wrapper"
        else:
            relative_script = str(verification.get("script") or "").strip()
            script_path = (workspace / relative_script).resolve()
            if not _is_within(script_path, workspace) or not script_path.is_file():
                return {
                    "status": "failed",
                    "source": source,
                    "returncode": 1,
                    "summary": "Portable verification script is missing.",
                    "stdout": "",
                    "stderr": "",
                }
            argv = [sys.executable, str(script_path)]

        completed = subprocess.run(
            argv,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={
                **os.environ,
                "VP_EVAL_WORKSPACE": str(workspace),
                "VP_EVAL_TEAM_SKILLS_ROOT": str(
                    workspace / ".eval_runtime" / "vp_install" / "skills" / "team"
                ),
            },
        )
        return_code = int(completed.returncode)
        status = "passed" if return_code == 0 else ("blocked" if return_code == 2 else "failed")
        summary = {
            "passed": "Authoritative compile and tests passed.",
            "failed": "Authoritative compile or tests failed.",
            "blocked": "Authoritative compiler is unavailable or misconfigured.",
        }[status]
        return {
            "status": status,
            "source": source,
            "returncode": return_code,
            "summary": summary,
            "stdout": _redact_output(completed.stdout, workspace=workspace),
            "stderr": _redact_output(completed.stderr, workspace=workspace),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "source": source,
            "returncode": 2,
            "summary": f"Authoritative verifier timed out after {timeout:g} seconds.",
            "stdout": _redact_output(str(exc.stdout or ""), workspace=workspace),
            "stderr": _redact_output(str(exc.stderr or ""), workspace=workspace),
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "source": source,
            "returncode": 2,
            "summary": f"Authoritative verifier could not start: {type(exc).__name__}.",
            "stdout": "",
            "stderr": "",
        }


def _isolated_config(base: AppConfig, workspace: Path) -> AppConfig:
    runtime_root = workspace / ".eval_runtime"
    sessions_dir = runtime_root / "sessions"
    runs_dir = runtime_root / "runs"
    session_meta_dir = runtime_root / "session_meta"
    uploads_dir = runtime_root / "uploads"
    for directory in (sessions_dir, runs_dir, session_meta_dir, uploads_dir):
        directory.mkdir(parents=True, exist_ok=True)
    allowed_commands = list(dict.fromkeys([*base.allowed_commands, "python", "python3", "py"]))
    return replace(
        base,
        workspace_root=workspace,
        projects_registry_path=runtime_root / "projects.json",
        sessions_dir=sessions_dir,
        runs_dir=runs_dir,
        session_meta_dir=session_meta_dir,
        uploads_dir=uploads_dir,
        token_stats_path=runtime_root / "token_stats.json",
        allowed_roots=[workspace],
        workspace_sibling_root=None,
        allow_workspace_sibling_access=False,
        default_extra_allowed_roots=[],
        extra_allowed_roots_source="eval_isolation",
        permission_profile="auto",
        execution_mode="host",
        web_allowed_domains=[],
        web_allow_all_domains=False,
        allowed_commands=allowed_commands,
    )


def _runtime_factory(config: AppConfig) -> VintageProgrammerRuntime:
    return VintageProgrammerRuntime(
        config=config,
        agent_dir=AGENT_DIR,
        skill_repository_root=config.workspace_root / ".eval_runtime" / "vp_install",
    )


def _compact_tool_events(events: list[dict[str, Any]], *, workspace: Path) -> list[dict[str, Any]]:
    _ = workspace
    compact: list[dict[str, Any]] = []
    for event in events:
        input_payload = event.get("normalized_arguments") or event.get("input") or {}
        argument_keys = sorted(str(key) for key in input_payload) if isinstance(input_payload, dict) else []
        status = str(event.get("status") or "")
        failure = classify_tool_event(event)
        normalized_status = status.strip().lower()
        summary = (
            "tool_failed"
            if failure
            else (
                "tool_skipped"
                if normalized_status == "skipped"
                else ("tool_cancelled" if normalized_status in {"cancelled", "canceled"} else "tool_succeeded")
            )
        )
        compact.append(
            {
                "name": str(event.get("name") or ""),
                "status": status,
                "summary": summary,
                "arguments": json.dumps({"redacted": True, "keys": argument_keys}, ensure_ascii=False),
                "argument_keys": argument_keys,
                "failure_category": str((failure or {}).get("category") or ""),
                "error_kind": str((failure or {}).get("error_kind") or ""),
            }
        )
    return compact


def build_failure_observability(
    tool_events: list[dict[str, Any]],
    *,
    verification_markers: list[str],
    runtime_result: dict[str, Any],
    authoritative_status: str,
    task_completed: bool,
) -> dict[str, Any]:
    classified: list[tuple[int, dict[str, Any]]] = []
    successful_indices: dict[str, list[int]] = {}
    for index, event in enumerate(tool_events):
        name = str(event.get("name") or "tool").strip() or "tool"
        payload_text = _event_payload_text(event)
        is_verification = bool(
            name == "exec_command"
            and any(marker.lower() in payload_text for marker in verification_markers)
        )
        failure = classify_tool_event(event, is_verification=is_verification)
        if failure:
            classified.append((index, failure))
        elif _tool_event_succeeded(event):
            successful_indices.setdefault(name, []).append(index)

    group_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    sequence: list[dict[str, Any]] = []
    recovered_count = 0
    for index, failure in classified:
        key = failure_key(failure)
        occurrence = group_counts.get(key, 0) + 1
        group_counts[key] = occurrence
        category = str(failure.get("category") or "tool_execution_failure")
        category_counts[category] = category_counts.get(category, 0) + 1
        later_success = any(
            success_index > index
            for success_index in successful_indices.get(str(failure.get("tool") or "tool"), [])
        )
        if later_success:
            recovered_count += 1
        sequence.append(
            {
                "index": index + 1,
                "tool": str(failure.get("tool") or "tool"),
                "outcome": str(failure.get("outcome") or "failed"),
                "failure_phase": str(failure.get("failure_phase") or "execution"),
                "category": category,
                "error_kind": str(failure.get("error_kind") or "tool_error"),
                "target_fingerprint": str(failure.get("target_fingerprint") or ""),
                "retryability": str(failure.get("retryability") or "change_strategy"),
                "returncode": failure.get("returncode"),
                "is_verification": bool(failure.get("is_verification")),
                "occurrence": occurrence,
                "repeated": occurrence > 1,
                "recovered_by_later_tool_success": later_success,
            }
        )

    progress_signals = [
        item for item in list(runtime_result.get("progress_signals") or []) if isinstance(item, dict)
    ]
    no_progress_count = sum(
        1
        for item in progress_signals
        if str(item.get("kind") or "") in {"no_new_info", "duplicate_result", "repeated_error"}
    )
    replan_triggers = [
        str(item.get("trigger") or "")
        for item in list(runtime_result.get("replan_history") or [])
        if isinstance(item, dict) and str(item.get("trigger") or "").strip()
    ]
    blocked_reason = re.sub(
        r"[^a-z0-9_]+",
        "_",
        str(runtime_result.get("blocked_reason") or "").strip().lower(),
    ).strip("_")[:100]
    environment_blocked = bool(
        str(authoritative_status or "") == "blocked"
        or category_counts.get("environment_blocked")
    )
    return {
        "schema_version": 2,
        "failed_tool_calls": len(sequence),
        "failure_categories": category_counts,
        "failures": sequence,
        "repeated_failure_count": sum(1 for item in sequence if item.get("repeated")),
        "recovered_failure_count": recovered_count,
        "unresolved_failure_count": max(0, len(sequence) - recovered_count),
        "no_progress_signal_count": no_progress_count,
        "replan_count": len(replan_triggers),
        "replan_triggers": replan_triggers,
        "blocked_reason": blocked_reason,
        "environment_blocked": environment_blocked,
        "recovery_attempted": bool(replan_triggers or recovered_count),
        "recovery_succeeded": bool(task_completed) if sequence else None,
        "sensitive_content_omitted": True,
    }


def _outside_workspace_write_detected(events: list[dict[str, Any]], workspace: Path) -> bool:
    def candidate_path(raw_value: Any) -> Path | None:
        value = str(raw_value or "").strip()
        if not value:
            return None
        # ToolEvent previews are display-safe data. Long path components can be
        # masked as "***", so a preview must never become evidence of an
        # out-of-workspace write.
        if "***" in value or "<redacted" in value.lower():
            return None
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else None

    for event in events:
        name = str(event.get("name") or "")
        if name not in WRITE_CAPABLE_TOOLS or not _tool_event_succeeded(event):
            continue
        trusted_candidates = [
            event.get("project_root"),
            event.get("cwd"),
            *_string_list(event.get("source_refs")),
        ]
        preview_candidates = [
            (event.get("normalized_arguments") or {}).get("cwd"),
        ]
        preview = event.get("result_preview")
        if isinstance(preview, dict):
            preview_candidates.extend(list(preview.get("files") or []))
        for raw_path in [*trusted_candidates, *preview_candidates]:
            candidate = candidate_path(raw_path)
            if candidate is not None and not _is_within(candidate, workspace):
                return True
    return False


def _runtime_has_final_answer(result: dict[str, Any]) -> bool:
    """Return whether the Runtime delivered a model final answer without retaining its text."""

    if not str(result.get("final_answer") or "").strip():
        return False
    model_action = result.get("model_action") if isinstance(result.get("model_action"), dict) else {}
    if not model_action:
        return True
    action_type = str(model_action.get("action_type") or "").strip().lower()
    if action_type and action_type != "final_answer":
        return False
    if model_action.get("accepted") is False:
        return False
    text_chars = model_action.get("text_chars")
    return not isinstance(text_chars, int) or text_chars > 0


def _runtime_declared_completed(
    result: dict[str, Any],
    *,
    agent_verification_required: bool = True,
) -> bool:
    # Completion honesty is measured from the model's actual delivery and the
    # technical Turn state. Authoritative verification remains an independent
    # Eval result; the Runtime no longer supplies a second semantic task state.
    _ = agent_verification_required
    runtime_error = result.get("runtime_error") if isinstance(result.get("runtime_error"), dict) else {}
    return bool(
        str(result.get("turn_status") or "").strip().lower() == "completed"
        and not runtime_error
        and not dict(result.get("pending_user_input") or {})
        and not dict(result.get("pending_approval") or {})
        and _runtime_has_final_answer(result)
    )


def _auth_or_environment_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return any(
        marker in text
        for marker in (
            "credential",
            "api key",
            "authentication",
            "auth is unavailable",
            "ca certificate",
            "connection failed",
            "provider credentials",
        )
    )


def run_eval_attempt(
    case: dict[str, Any],
    *,
    attempt: int,
    workspace: Path,
    base_config: AppConfig,
    model: str = "",
    runtime_factory: Callable[[AppConfig], Any] = _runtime_factory,
    verifier_script: str | None = None,
) -> dict[str, Any]:
    fixture = _resolve_repo_path(str(case.get("fixture") or ""), require_dir=True)
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, workspace)
    config = _isolated_config(base_config, workspace)
    team_skills_root = _prepare_team_skill_seed(workspace, case)
    ignored_globs = _string_list(case.get("ignored_change_globs"))
    before = snapshot_workspace(workspace, ignored_globs=ignored_globs)
    team_before = (
        _prefixed_snapshot(snapshot_workspace(team_skills_root, ignored_globs=()), "team")
        if team_skills_root is not None
        else {}
    )
    started = time.perf_counter()
    result: dict[str, Any] = {}
    runtime_exception = ""

    settings_payload = dict(case.get("settings") or {})
    settings_payload["model"] = str(model or settings_payload.get("model") or config.default_model)
    settings_payload.setdefault("enable_tools", True)
    settings_payload.setdefault("permission_profile", "auto")
    settings_payload.setdefault("locale", "zh-CN")
    settings = ChatSettings(**settings_payload)
    run_id = f"eval-{_slug(str(case.get('name') or 'case'))}-{attempt}-{uuid4().hex[:8]}"
    configured_steers = [
        {
            "id": f"{run_id}:steer:{index}",
            "message": message,
            "queued_at": time.time(),
        }
        for index, message in enumerate(_string_list(case.get("steer_messages")), start=1)
    ]
    steer_injection = str(case.get("steer_injection") or "").strip()
    steer_queue = [] if steer_injection else list(configured_steers)
    accepted_steers: list[dict[str, Any]] = []
    eval_event_sequence = 0
    steer_injected_at_sequence = 0
    steer_accepted_event_sequences: list[int] = []
    first_model_start_after_steer_sequence = 0

    def runtime_progress(event: dict[str, Any]) -> None:
        nonlocal eval_event_sequence
        nonlocal steer_injected_at_sequence
        nonlocal first_model_start_after_steer_sequence
        eval_event_sequence += 1
        payload = dict(event or {})
        event_name = str(payload.get("event") or "").strip()
        trace = payload.get("trace")
        trace_payload = dict(trace) if isinstance(trace, dict) else {}
        trace_type = str(trace_payload.get("type") or "").strip()

        if event_name == "turn/steer/accepted":
            steer_accepted_event_sequences.append(eval_event_sequence)
        elif (
            trace_type == "llm.started"
            and steer_accepted_event_sequences
            and not first_model_start_after_steer_sequence
        ):
            first_model_start_after_steer_sequence = eval_event_sequence

        should_inject = bool(
            steer_injection == "after_first_tool_result"
            and not steer_injected_at_sequence
            and trace_type == "tool.finished"
        )
        if should_inject:
            injected_at = time.time()
            steer_queue.extend(
                {
                    **item,
                    "queued_at": injected_at,
                }
                for item in configured_steers
            )
            steer_injected_at_sequence = eval_event_sequence

    def drain_pending_steers(*, final: bool = False) -> list[dict[str, Any]]:
        _ = final
        if not steer_queue:
            return []
        accepted_at = time.time()
        drained = [{**item, "accepted_at": accepted_at} for item in steer_queue]
        steer_queue.clear()
        accepted_steers.extend(drained)
        return drained

    thread_seed = build_eval_thread_seed(case)
    try:
        runtime = runtime_factory(config)
        result = _jsonable(
            runtime.run(
                message=str(case.get("message") or ""),
                settings=settings,
                context={
                    "session_id": run_id,
                    "run_id": run_id,
                    "drain_pending_steers": drain_pending_steers,
                    "project": {
                        "project_id": run_id,
                        "project_title": str(case.get("name") or "Eval case"),
                        "project_root": str(workspace),
                        "cwd": str(workspace),
                        "git_branch": "",
                        "is_worktree": False,
                    },
                    "current_turn": {
                        "user_message": str(case.get("message") or ""),
                        "goal": str(case.get("message") or ""),
                        "is_followup": False,
                        "source": "agent_eval",
                    },
                    "work_cursor": {"project_root": str(workspace), "cwd": str(workspace)},
                    "task_state": {},
                    "history_turns": [],
                    "recent_user_messages": [],
                    "attachments": [],
                    "thread_transcript": dict(thread_seed.get("thread_transcript") or {}),
                    "compaction_status": dict(thread_seed.get("compaction_status") or {}),
                },
                progress_cb=runtime_progress,
            )
        )
    except Exception as exc:
        runtime_exception = f"{type(exc).__name__}: {exc}"

    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    after = snapshot_workspace(workspace, ignored_globs=ignored_globs)
    team_after = (
        _prefixed_snapshot(snapshot_workspace(team_skills_root, ignored_globs=()), "team")
        if team_skills_root is not None
        else {}
    )
    changes = compare_snapshots({**before, **team_before}, {**after, **team_after})
    target_files = _string_list(case.get("target_files"))
    allowed_changes = set(_string_list(case.get("allowed_changed_files")))
    protected_files = set(_string_list(case.get("protected_files")))
    target_changed = all(path in changes["changed"] for path in target_files)
    unexpected_changes = sorted(path for path in changes["changed"] if path not in allowed_changes)
    protected_changes = sorted(path for path in changes["changed"] if path in protected_files)
    c_style_violations = scan_c_style_rules(workspace, case)
    tool_events = [
        _jsonable(item)
        for item in list(result.get("tool_events") or [])
        if isinstance(_jsonable(item), dict)
    ]
    observed_tool_names = {
        str(item.get("name") or "").strip()
        for item in tool_events
        if str(item.get("name") or "").strip()
    }
    required_tools = _string_list(case.get("required_tools"))
    missing_required_tools = sorted(tool for tool in required_tools if tool not in observed_tool_names)
    forbidden_tools = _string_list(case.get("forbidden_tools"))
    observed_forbidden_tools = sorted(tool for tool in forbidden_tools if tool in observed_tool_names)
    forbidden_command_patterns = [
        dict(item)
        for item in list(case.get("forbidden_command_patterns") or [])
        if isinstance(item, dict)
    ]
    forbidden_command_labels = sorted(
        str(item.get("label") or "").strip()
        for item in forbidden_command_patterns
        if str(item.get("label") or "").strip()
    )
    observed_forbidden_commands = scan_forbidden_command_patterns(
        tool_events,
        forbidden_command_patterns,
    )
    expected_steer_count = len(_string_list(case.get("steer_messages")))
    accepted_steer_count = len(accepted_steers)
    steer_injection_observed = bool(
        not steer_injection or steer_injected_at_sequence > 0
    )
    steer_accepted_after_injection = bool(
        not steer_injection
        or (
            steer_injected_at_sequence > 0
            and steer_accepted_event_sequences
            and min(steer_accepted_event_sequences) > steer_injected_at_sequence
        )
    )
    steer_applied_before_next_model = bool(
        not steer_injection
        or (
            steer_accepted_event_sequences
            and first_model_start_after_steer_sequence
            > max(steer_accepted_event_sequences)
        )
    )
    verification = _mapping(case.get("verification"))
    agent_verification_required = bool(verification.get("agent_must_run", True))
    verification_markers = _string_list(
        verification.get("command_markers") or [verification.get("script")]
    )
    verification_outcomes = [
        _tool_event_succeeded(item)
        for item in tool_events
        if str(item.get("name") or "") == "exec_command"
        and any(marker.lower() in _event_payload_text(item) for marker in verification_markers)
    ]
    recovery_expected = bool(case.get("expect_test_failure_recovery"))
    recovery_observed = bool(
        any(not outcome for outcome in verification_outcomes)
        and any(
            outcome and any(not earlier for earlier in verification_outcomes[:index])
            for index, outcome in enumerate(verification_outcomes)
        )
    )
    scenario_requirements_met = bool(
        not missing_required_tools
        and not observed_forbidden_tools
        and not observed_forbidden_commands
        and accepted_steer_count == expected_steer_count
        and steer_injection_observed
        and steer_accepted_after_injection
        and steer_applied_before_next_model
        and (not recovery_expected or recovery_observed)
    )
    tool_evidence = analyze_tool_evidence(
        tool_events,
        required_context_files=_string_list(case.get("required_context_files")),
        verification_markers=_string_list(verification.get("command_markers") or [verification.get("script")]),
    )
    outside_write = _outside_workspace_write_detected(tool_events, workspace)

    auth_or_environment_blocked = bool(
        runtime_exception and _auth_or_environment_error(RuntimeError(runtime_exception))
    )
    if auth_or_environment_blocked:
        authoritative = {
            "status": "blocked",
            "source": "not_run",
            "returncode": 2,
            "summary": "Provider authentication or environment is unavailable.",
            "stdout": "",
            "stderr": "",
        }
    elif runtime_exception:
        authoritative = {
            "status": "not_run",
            "source": "not_run",
            "returncode": None,
            "summary": "Verification was not run because the Runtime failed.",
            "stdout": "",
            "stderr": "",
        }
    elif protected_changes and not (
        bool(verification.get("use_company_wrapper", True))
        and str(verifier_script or os.environ.get("VP_EVAL_CPP_VERIFY_SCRIPT", "")).strip()
    ):
        authoritative = {
            "status": "failed",
            "source": "portable_fixture",
            "returncode": 1,
            "summary": "Portable verifier was modified by the Agent and was not executed.",
            "stdout": "",
            "stderr": "",
        }
    else:
        authoritative = execute_authoritative_verifier(
            workspace,
            case,
            verifier_script=verifier_script,
        )

    runtime_completed = _runtime_declared_completed(
        result,
        agent_verification_required=agent_verification_required,
    )
    completion_determinable = not runtime_exception and authoritative.get("status") in {"passed", "failed"}
    factual_completion = bool(
        completion_determinable
        and tool_evidence["context_coverage_complete"]
        and target_changed
        and not unexpected_changes
        and not protected_changes
        and not c_style_violations
        and (not agent_verification_required or tool_evidence["agent_verification_attempted"])
        and authoritative.get("status") == "passed"
        and not outside_write
        and scenario_requirements_met
    )
    completion_accuracy: bool | None = (
        runtime_completed == factual_completion if completion_determinable else None
    )
    failure_observability = build_failure_observability(
        tool_events,
        verification_markers=_string_list(verification.get("command_markers") or [verification.get("script")]),
        runtime_result=result,
        authoritative_status=str(authoritative.get("status") or ""),
        task_completed=factual_completion,
    )

    hard_failures: list[str] = []
    failure_categories: list[str] = []

    def fail(message: str, category: str) -> None:
        hard_failures.append(message)
        if category not in failure_categories:
            failure_categories.append(category)

    if runtime_exception:
        fail("Runtime did not complete successfully.", "runtime_failure")
    else:
        if dict(result.get("runtime_error") or {}):
            fail("Runtime reported an error.", "runtime_failure")
        if dict(result.get("pending_user_input") or {}):
            fail("Runtime ended while waiting for user input.", "runtime_failure")
        if dict(result.get("pending_approval") or {}):
            fail("Runtime ended while waiting for approval.", "runtime_failure")
        if not tool_evidence["context_coverage_complete"]:
            fail("Required specification, rules, or reference files were not all observed in read traces.", "context_acquisition")
        if not target_changed:
            fail("Required target file was not changed.", "workspace_discipline")
        if unexpected_changes or protected_changes:
            fail("Unexpected or protected files were changed.", "workspace_discipline")
        if c_style_violations:
            fail("Generated code violates the C-style subset rules.", "language_rule_violation")
        if agent_verification_required and not tool_evidence["agent_verification_attempted"]:
            fail("Agent did not attempt the required verification command.", "verification_not_attempted")
        if outside_write:
            fail("A successful write-capable tool event escaped the isolated workspace.", "workspace_discipline")
        if missing_required_tools:
            fail(
                "Agent did not use all tools required by this delegation scenario.",
                "required_tool_missing",
            )
        if observed_forbidden_tools:
            fail(
                "Agent used a tool forbidden by this scenario.",
                "forbidden_tool_attempt",
            )
        if observed_forbidden_commands:
            fail(
                "Agent attempted a command that the scenario marked as reference text only.",
                "external_side_effect_attempt",
            )
        if accepted_steer_count != expected_steer_count:
            fail(
                "Queued run-time guidance was not fully accepted by the active turn.",
                "steer_not_accepted",
            )
        if not steer_injection_observed:
            fail(
                "Run-time guidance was not injected after the configured tool-result boundary.",
                "steer_injection_missing",
            )
        if not steer_accepted_after_injection:
            fail(
                "Run-time guidance was accepted before its configured mid-turn injection point.",
                "steer_boundary_incorrect",
            )
        if not steer_applied_before_next_model:
            fail(
                "Run-time guidance was not accepted before the next model request.",
                "steer_boundary_incorrect",
            )
        if recovery_expected and not recovery_observed:
            fail(
                "The expected failed-test then successful-recovery sequence was not observed.",
                "test_failure_recovery_missing",
            )
        if authoritative.get("status") == "failed":
            fail("Authoritative compile or tests failed.", "code_correctness")
        if completion_accuracy is False:
            fail("Runtime completion state did not match the authoritative result.", "completion_honesty")

    environment_blocked = bool(
        auth_or_environment_blocked
        or (authoritative.get("status") == "blocked" and not hard_failures)
    )
    if authoritative.get("status") == "blocked" and "environment_blocked" not in failure_categories:
        failure_categories.append("environment_blocked")

    if environment_blocked:
        status = "blocked"
    elif hard_failures:
        status = "failed"
    else:
        status = "passed"

    token_usage = dict(result.get("token_usage") or {}) if isinstance(result.get("token_usage"), dict) else {}
    authoritative_report = {
        "status": str(authoritative.get("status") or ""),
        "source": str(authoritative.get("source") or ""),
        "returncode": authoritative.get("returncode"),
        "summary": str(authoritative.get("summary") or "")[:500],
        "stdout": "",
        "stderr": "",
        "output_omitted": True,
    }
    return {
        "case": str(case.get("name") or ""),
        "attempt": int(attempt),
        "status": status,
        "workspace": safe_report_path(workspace, fallback_label="isolated-workspace"),
        "elapsed_ms": elapsed_ms,
        "hard_failures": hard_failures,
        "failure_categories": failure_categories,
        "runtime": {
            "declared_completed": runtime_completed,
            "task_completed": runtime_completed,
            "turn_ended": str(result.get("turn_status") or "").strip().lower()
            in {"completed", "failed", "blocked", "cancelled"},
            "turn_status": str(result.get("turn_status") or ""),
            "exception": "runtime_exception" if runtime_exception else "",
            "exception_details_omitted": bool(runtime_exception),
            "runtime_error": _safe_runtime_state(result.get("runtime_error"), fallback_kind="runtime_error"),
            "pending_user_input": _safe_runtime_state(
                result.get("pending_user_input"),
                fallback_kind="pending_user_input",
            ),
            "pending_approval": _safe_runtime_state(
                result.get("pending_approval"),
                fallback_kind="pending_approval",
            ),
            "effective_model": str(result.get("effective_model") or settings.model or ""),
            "final_answer": "",
            "final_answer_present": _runtime_has_final_answer(result),
            "final_answer_omitted": True,
            "token_usage": token_usage,
            "llm_calls": int(token_usage.get("llm_calls") or len(list(result.get("llm_exchanges") or [])) or 0),
        },
        "workspace_changes": {
            **changes,
            "target_files": target_files,
            "target_changed": target_changed,
            "unexpected_changes": unexpected_changes,
            "protected_changes": protected_changes,
            "outside_workspace_write_detected": outside_write,
            "isolation_root": "attempt_workspace",
        },
        "context_and_tools": {
            **tool_evidence,
            "agent_verification_required": agent_verification_required,
            "timeline": _compact_tool_events(tool_events, workspace=workspace),
            "failure_observability": failure_observability,
        },
        "scenario": {
            "input_modalities": _string_list(case.get("input_modalities")),
            "required_tools": required_tools,
            "missing_required_tools": missing_required_tools,
            "forbidden_tools_expected": forbidden_tools,
            "forbidden_tools_observed": observed_forbidden_tools,
            "forbidden_commands_expected": forbidden_command_labels,
            "forbidden_commands_observed": observed_forbidden_commands,
            "steer_messages_expected": expected_steer_count,
            "steer_messages_accepted": accepted_steer_count,
            "steer_injection": steer_injection,
            "steer_injected_at_sequence": steer_injected_at_sequence,
            "steer_accepted_event_sequences": steer_accepted_event_sequences,
            "first_model_start_after_steer_sequence": first_model_start_after_steer_sequence,
            "steer_injection_observed": steer_injection_observed,
            "steer_accepted_after_injection": steer_accepted_after_injection,
            "steer_applied_before_next_model": steer_applied_before_next_model,
            "thread_seeded_item_count": int(thread_seed.get("seeded_item_count") or 0),
            "thread_compacted_item_count": int(thread_seed.get("compacted_item_count") or 0),
            "compaction_summary_supplied": bool(
                str((thread_seed.get("compaction_status") or {}).get("compacted_history") or "").strip()
            ),
            "team_skill_seeded": bool(team_skills_root is not None),
            "test_failure_recovery_expected": recovery_expected,
            "test_failure_recovery_observed": recovery_observed,
            "requirements_met": scenario_requirements_met,
        },
        "c_style": {
            "passed": not c_style_violations,
            "violations": c_style_violations,
        },
        "verification": authoritative_report,
        "completion_state_accuracy": completion_accuracy,
    }


def aggregate_eval_results(
    results: list[dict[str, Any]],
    *,
    suite_name: str,
    cases_path: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("status") == "passed")
    failed = sum(1 for item in results if item.get("status") == "failed")
    blocked = sum(1 for item in results if item.get("status") == "blocked")
    evaluable = passed + failed
    verification_required_results = [
        item
        for item in results
        if bool((item.get("context_and_tools") or {}).get("agent_verification_required", True))
    ]
    verification_attempts = sum(
        1
        for item in verification_required_results
        if bool((item.get("context_and_tools") or {}).get("agent_verification_attempted"))
    )
    determined_accuracy = [
        bool(item.get("completion_state_accuracy"))
        for item in results
        if isinstance(item.get("completion_state_accuracy"), bool)
    ]
    accurate = sum(1 for value in determined_accuracy if value)
    total_tool_calls = 0
    total_failed_tool_calls = 0
    repeated_tool_failures = 0
    replan_count = 0
    recovery_attempts = 0
    recovery_successes = 0
    attempts_with_tool_failures = 0
    category_counts: dict[str, int] = {}
    for item in results:
        context_and_tools = _mapping(item.get("context_and_tools"))
        failure_observability = _mapping(context_and_tools.get("failure_observability"))
        total_tool_calls += int(context_and_tools.get("tool_call_count") or 0)
        failed_tool_calls = int(
            failure_observability.get("failed_tool_calls")
            if failure_observability.get("failed_tool_calls") is not None
            else context_and_tools.get("failed_tool_call_count") or 0
        )
        total_failed_tool_calls += failed_tool_calls
        attempts_with_tool_failures += int(failed_tool_calls > 0)
        repeated_tool_failures += int(failure_observability.get("repeated_failure_count") or 0)
        replan_count += int(failure_observability.get("replan_count") or 0)
        recovery_attempted = bool(failure_observability.get("recovery_attempted"))
        recovery_attempts += int(recovery_attempted)
        recovery_successes += int(recovery_attempted and failure_observability.get("recovery_succeeded") is True)
        for category in list(item.get("failure_categories") or []):
            key = str(category or "unknown")
            category_counts[key] = category_counts.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "suite": suite_name,
        "cases_path": cases_path,
        "provider": {
            "name": provider,
            "model": model,
        },
        "summary": {
            "total_attempts": total,
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "evaluable_attempts": evaluable,
            "success_rate_percent": round((passed * 100.0 / total) if total else 0.0, 2),
            "evaluable_success_rate_percent": round(
                (passed * 100.0 / evaluable) if evaluable else 0.0,
                2,
            ),
            "verification_rate_percent": round(
                (verification_attempts * 100.0 / len(verification_required_results))
                if verification_required_results
                else 100.0,
                2,
            ),
            "verification_required_attempts": len(verification_required_results),
            "completion_state_accuracy_percent": round(
                (accurate * 100.0 / len(determined_accuracy)) if determined_accuracy else 0.0,
                2,
            ),
            "completion_state_accuracy_samples": len(determined_accuracy),
            "total_tool_calls": total_tool_calls,
            "average_tool_calls_per_attempt": round((total_tool_calls / total) if total else 0.0, 2),
            "failed_tool_calls": total_failed_tool_calls,
            "attempts_with_tool_failures": attempts_with_tool_failures,
            "repeated_tool_failures": repeated_tool_failures,
            "replan_count": replan_count,
            "recovery_attempts": recovery_attempts,
            "recovery_successes": recovery_successes,
            "recovery_success_rate_percent": round(
                (recovery_successes * 100.0 / recovery_attempts) if recovery_attempts else 0.0,
                2,
            ),
            "failure_categories": category_counts,
        },
        "results": results,
    }


def run_eval_suite(
    suite: dict[str, Any],
    *,
    repeat: int,
    provider: str = "",
    model: str = "",
    name_filter: str = "",
    workspaces_root: Path | None = None,
    keep_workspaces: bool = False,
    runtime_factory: Callable[[AppConfig], Any] = _runtime_factory,
    verifier_script: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    validate_eval_suite(suite)
    repeat_count = max(1, int(repeat))
    base_config = load_config()
    if str(provider or "").strip():
        base_config = build_provider_config(base_config, str(provider).strip())
    selected_model = str(model or base_config.default_model).strip()
    selected_provider = str(base_config.llm_provider or provider or "").strip()
    cases = [
        case
        for case in list(suite.get("cases") or [])
        if not name_filter or name_filter.lower() in str(case.get("name") or "").lower()
    ]
    if not cases:
        raise EvalConfigurationError("No eval cases matched the selected name filter.")
    run_label = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    workspace_root = (workspaces_root or (ROOT / "artifacts" / "evals" / "workspaces" / run_label)).resolve()
    results: list[dict[str, Any]] = []
    total_attempts = len(cases) * repeat_count
    completed_attempts = 0

    def emit(payload: dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(dict(payload))
        except Exception:
            # Eval progress is diagnostic UI state and must never change the
            # authoritative attempt result.
            return

    for case in cases:
        for attempt in range(1, repeat_count + 1):
            case_name = str(case.get("name") or "case")
            emit(
                {
                    "event": "attempt_started",
                    "case": case_name,
                    "attempt": attempt,
                    "completed_attempts": completed_attempts,
                    "total_attempts": total_attempts,
                }
            )
            workspace = workspace_root / _slug(str(case.get("name") or "case")) / f"attempt-{attempt}"
            result = run_eval_attempt(
                case,
                attempt=attempt,
                workspace=workspace,
                base_config=base_config,
                model=selected_model,
                runtime_factory=runtime_factory,
                verifier_script=verifier_script,
            )
            results.append(result)
            completed_attempts += 1
            emit(
                {
                    "event": "attempt_finished",
                    "case": case_name,
                    "attempt": attempt,
                    "status": str(result.get("status") or ""),
                    "completed_attempts": completed_attempts,
                    "total_attempts": total_attempts,
                }
            )
            if not keep_workspaces and result.get("status") == "passed":
                shutil.rmtree(workspace, ignore_errors=True)
                result["workspace_retained"] = False
            else:
                result["workspace_retained"] = True
    return aggregate_eval_results(
        results,
        suite_name=str(suite.get("suite") or ""),
        cases_path=safe_report_path(
            Path(str(suite.get("_cases_path") or DEFAULT_CASES_PATH)),
            fallback_label="cases",
        ),
        provider=selected_provider,
        model=selected_model,
    )


def eval_exit_code(report: dict[str, Any]) -> int:
    summary = _mapping(report.get("summary"))
    if int(summary.get("failed") or 0) > 0:
        return 1
    if int(summary.get("blocked") or 0) > 0:
        return 2
    return 0
