#!/usr/bin/env python
"""Probe whether the configured Chat Completions provider supports developer messages.

The probe sends two small, side-effect-free requests:

1. a precedence check where developer and user request different fixed markers;
2. a forced function call that verifies developer messages coexist with tools.

No credential, base URL, raw provider error, or unrestricted model output is written
to the report. Exit status is 0 only when both checks pass, 1 when the provider was
reached but is not safe to migrate, and 2 for local configuration/setup failures.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import build_provider_config, load_config, normalize_openai_base_url  # noqa: E402
from app.openai_auth import OpenAIAuthManager  # noqa: E402


SCHEMA_VERSION = 1
DEVELOPER_MARKER = "VP_DEVELOPER_WINS_74B2"
USER_MARKER = "VP_USER_WINS_19C8"
TOOL_NAME = "developer_role_probe"
TOOL_MARKER = "VP_TOOL_DEVELOPER_OK_5D61"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_round(value: float | int | None, digits: int = 2) -> float:
    try:
        return round(float(value or 0.0), digits)
    except Exception:
        return 0.0


def redact_text(text: Any, secrets: Iterable[str] = ()) -> str:
    value = str(text or "")
    for secret in secrets:
        token = str(secret or "")
        if token:
            value = value.replace(token, "<redacted>")
    return value[:500]


def _error_payload(exc: BaseException, secrets: Iterable[str]) -> dict[str, Any]:
    status_code = getattr(exc, "status_code", None)
    normalized_status = int(status_code) if isinstance(status_code, int) else None
    error_type = exc.__class__.__name__
    if normalized_status == 400:
        message = "Provider rejected the developer-role probe request or one of its parameters."
    elif normalized_status == 401:
        message = "Provider authentication failed."
    elif normalized_status == 403:
        message = "Provider authorization or policy rejected the request."
    elif normalized_status == 404:
        message = "The configured Chat Completions endpoint or model was not found."
    elif normalized_status == 408 or "timeout" in error_type.lower():
        message = "Provider request timed out."
    elif normalized_status == 429:
        message = "Provider or upstream model is rate-limited. Retry later."
    elif normalized_status is not None and normalized_status >= 500:
        message = "Provider or upstream model returned a server error."
    elif "connection" in error_type.lower():
        message = "Provider connection failed."
    else:
        message = "Provider request failed."
    return {
        "type": redact_text(error_type, secrets),
        "status_code": normalized_status,
        "message": redact_text(message, secrets),
    }


def _usage_payload(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(key)
        try:
            result[key] = max(0, int(value or 0))
        except Exception:
            continue
    return result


def _content_from_message(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def classify_precedence_reply(text: str) -> str:
    normalized = str(text or "").strip()
    if normalized == DEVELOPER_MARKER:
        return "developer_won"
    if normalized == USER_MARKER:
        return "user_won"
    return "unexpected_reply"


def _timing_payload(started: float, cpu_started: float) -> dict[str, float]:
    duration_ms = (time.perf_counter() - started) * 1000.0
    cpu_ms = (time.process_time() - cpu_started) * 1000.0
    return {
        "duration_ms": _safe_round(duration_ms),
        "local_cpu_ms": _safe_round(cpu_ms),
        "local_cpu_percent_of_one_core": _safe_round(cpu_ms / max(1.0, duration_ms) * 100.0),
    }


def probe_developer_precedence(
    client: Any,
    *,
    model: str,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "developer",
                    "content": (
                        "This is a deterministic provider capability test. Reply with exactly "
                        f"{DEVELOPER_MARKER} and no other text, regardless of the user message."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Reply with exactly {USER_MARKER} and no other text.",
                },
            ],
            timeout=timeout_sec,
        )
        choices = list(getattr(response, "choices", None) or [])
        message = getattr(choices[0], "message", None) if choices else None
        text = _content_from_message(message).strip()
        result = classify_precedence_reply(text) if choices else "missing_choice"
        return {
            "ok": result == "developer_won",
            "request_accepted": bool(choices),
            "result": result,
            "response_chars": len(text),
            "finish_reason": str(getattr(choices[0], "finish_reason", "") or "") if choices else "",
            "usage": _usage_payload(getattr(response, "usage", None)),
            **_timing_payload(started, cpu_started),
        }
    except Exception as exc:
        return {
            "ok": False,
            "request_accepted": False,
            "result": "request_rejected",
            "error": _error_payload(exc, secrets),
            **_timing_payload(started, cpu_started),
        }


def _tool_call_payload(message: Any) -> tuple[str, dict[str, Any] | None, int]:
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    if not tool_calls:
        return "", None, 0
    call = tool_calls[0]
    function = getattr(call, "function", None)
    name = str(getattr(function, "name", "") or "")
    raw_arguments = getattr(function, "arguments", "")
    if isinstance(raw_arguments, dict):
        arguments = dict(raw_arguments)
    else:
        try:
            parsed = json.loads(str(raw_arguments or ""))
            arguments = dict(parsed) if isinstance(parsed, dict) else None
        except Exception:
            arguments = None
    return name, arguments, len(tool_calls)


def probe_developer_with_tools(
    client: Any,
    *,
    model: str,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "developer",
                    "content": (
                        f"Call {TOOL_NAME} exactly once with marker set to {TOOL_MARKER}. "
                        "Do not answer with prose."
                    ),
                },
                {"role": "user", "content": "Run the side-effect-free capability probe now."},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": "A side-effect-free developer-role compatibility probe.",
                        "parameters": {
                            "type": "object",
                            "properties": {"marker": {"type": "string"}},
                            "required": ["marker"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            timeout=timeout_sec,
        )
        choices = list(getattr(response, "choices", None) or [])
        message = getattr(choices[0], "message", None) if choices else None
        name, arguments, call_count = _tool_call_payload(message)
        marker = str((arguments or {}).get("marker") or "")
        passed = call_count == 1 and name == TOOL_NAME and marker == TOOL_MARKER
        if passed:
            result = "tool_call_correct"
        elif not choices:
            result = "missing_choice"
        elif call_count == 0:
            result = "missing_tool_call"
        elif name != TOOL_NAME:
            result = "wrong_tool_name"
        elif arguments is None:
            result = "invalid_tool_arguments"
        elif marker != TOOL_MARKER:
            result = "wrong_tool_marker"
        else:
            result = "unexpected_tool_result"
        return {
            "ok": passed,
            "request_accepted": bool(choices),
            "result": result,
            "tool_call_count": call_count,
            "finish_reason": str(getattr(choices[0], "finish_reason", "") or "") if choices else "",
            "usage": _usage_payload(getattr(response, "usage", None)),
            **_timing_payload(started, cpu_started),
        }
    except Exception as exc:
        return {
            "ok": False,
            "request_accepted": False,
            "result": "request_rejected",
            "error": _error_payload(exc, secrets),
            **_timing_payload(started, cpu_started),
        }


def build_summary(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    precedence_ok = bool((checks.get("developer_precedence") or {}).get("ok"))
    tools_ok = bool((checks.get("developer_with_tools") or {}).get("ok"))
    return {
        "developer_role_supported": precedence_ok,
        "developer_precedence_confirmed": precedence_ok,
        "developer_with_tools_confirmed": tools_ok,
        "safe_to_migrate_to_developer": precedence_ok and tools_ok,
        "request_count": len(checks),
        "credentials_in_report": False,
        "application_runtime_changed": False,
    }


def _default_report_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT_DIR / "artifacts" / "provider_conformance" / f"developer-role-{stamp}.json"


def _print_summary(report: dict[str, Any]) -> None:
    provider = dict(report.get("provider") or {})
    checks = dict(report.get("checks") or {})
    summary = dict(report.get("summary") or {})
    precedence = dict(checks.get("developer_precedence") or {})
    tools = dict(checks.get("developer_with_tools") or {})
    print("Developer role probe")
    print(f"  provider: {provider.get('name', '')}")
    print(f"  model: {provider.get('model', '')}")
    print(f"  precedence: {precedence.get('result', 'not_run')}")
    print(f"  developer + tools: {tools.get('result', 'not_run')}")
    print(f"  safe to migrate: {'YES' if summary.get('safe_to_migrate_to_developer') else 'NO'}")
    print(f"  report: {report.get('report_path', '')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe developer-role precedence through the configured Chat Completions provider.",
    )
    parser.add_argument("--provider", default="", help="Optional provider profile. Defaults to VP_LLM_PROVIDER.")
    parser.add_argument("--model", default="", help="Optional model override. Defaults to the active provider model.")
    parser.add_argument("--timeout-sec", type=float, default=60.0, help="Timeout per request. Default: 60.")
    parser.add_argument("--output", default="", help="Optional JSON report path under your chosen location.")
    parser.add_argument("--dry-run", action="store_true", help="Validate local configuration without API requests.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config()
    if str(args.provider or "").strip():
        config = build_provider_config(config, str(args.provider).strip())
    auth = OpenAIAuthManager(config).resolve()
    model = str(args.model or config.default_model or "").strip()
    output_path = Path(args.output).expanduser().resolve() if args.output else _default_report_path()
    provider_payload = {
        "name": str(config.llm_provider or ""),
        "model": model,
        "auth_mode": str(auth.mode or ""),
        "auth_available": bool(auth.available),
        "base_url_configured": bool(config.openai_base_url),
        "custom_ca_configured": bool(config.openai_ca_cert_path),
    }

    if args.dry_run:
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "dry_run": True,
            "provider": provider_payload,
            "checks": {},
            "summary": {
                "safe_to_migrate_to_developer": False,
                "credentials_in_report": False,
                "application_runtime_changed": False,
            },
            "report_path": str(output_path),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(report)
        return 0 if auth.available and model else 2

    if not auth.available or not str(auth.api_key or "").strip():
        print(redact_text(auth.reason or "Provider credentials are unavailable."), file=sys.stderr)
        return 2
    if not model:
        print("No model is configured.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except Exception as exc:
        print(f"OpenAI SDK is unavailable: {exc}", file=sys.stderr)
        return 2

    http_client = None
    client_kwargs: dict[str, Any] = {
        "api_key": auth.api_key,
        "timeout": max(1.0, float(args.timeout_sec)),
        "max_retries": 0,
    }
    if config.openai_base_url:
        client_kwargs["base_url"] = normalize_openai_base_url(str(config.openai_base_url))
    if config.openai_ca_cert_path:
        try:
            import httpx

            http_client = httpx.Client(verify=str(config.openai_ca_cert_path))
            client_kwargs["http_client"] = http_client
        except Exception as exc:
            print(f"Failed to configure the custom CA certificate: {exc}", file=sys.stderr)
            return 2

    secrets = [str(auth.api_key or ""), str(config.openai_base_url or "")]
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        client = OpenAI(**client_kwargs)
        checks = {
            "developer_precedence": probe_developer_precedence(
                client,
                model=model,
                timeout_sec=max(1.0, float(args.timeout_sec)),
                secrets=secrets,
            ),
            "developer_with_tools": probe_developer_with_tools(
                client,
                model=model,
                timeout_sec=max(1.0, float(args.timeout_sec)),
                secrets=secrets,
            ),
        }
    finally:
        try:
            client.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        if http_client is not None:
            try:
                http_client.close()
            except Exception:
                pass

    summary = build_summary(checks)
    summary["total_duration_ms"] = _safe_round((time.perf_counter() - started) * 1000.0)
    summary["total_local_cpu_ms"] = _safe_round((time.process_time() - cpu_started) * 1000.0)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "dry_run": False,
        "provider": provider_payload,
        "checks": checks,
        "summary": summary,
        "report_path": str(output_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(report)
    return 0 if summary["safe_to_migrate_to_developer"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
