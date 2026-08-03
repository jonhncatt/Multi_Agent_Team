#!/usr/bin/env python
"""Probe whether the configured Chat Completions provider supports developer messages.

The probe sends four small, side-effect-free requests:

1. a legacy system-message control request;
2. a non-conflicting developer-message text request;
3. a developer-versus-user precedence request;
4. a forced function call that verifies developer messages coexist with tools.

No credential, base URL, raw provider error, or unrestricted model output is written
to the report. Exit status is 0 only when all checks pass, 1 when the provider was
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


SCHEMA_VERSION = 2
DEFAULT_PROVIDER = "openai_compatible"
SYSTEM_MARKER = "VP_SYSTEM_CONTROL_OK_3A17"
DEVELOPER_TEXT_MARKER = "VP_DEVELOPER_TEXT_OK_8C42"
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


def _probe_exact_text(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    expected_marker: str,
    success_result: str,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=timeout_sec,
        )
        choices = list(getattr(response, "choices", None) or [])
        message = getattr(choices[0], "message", None) if choices else None
        text = _content_from_message(message).strip()
        if not choices:
            result = "missing_choice"
        elif text == expected_marker:
            result = success_result
        else:
            result = "unexpected_reply"
        return {
            "ok": result == success_result,
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


def probe_system_control(
    client: Any,
    *,
    model: str,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    return _probe_exact_text(
        client,
        model=model,
        messages=[
            {
                "role": "system",
                "content": f"Return exactly {SYSTEM_MARKER} and no other text.",
            },
            {"role": "user", "content": "Run the provider control check."},
        ],
        expected_marker=SYSTEM_MARKER,
        success_result="system_control_ok",
        timeout_sec=timeout_sec,
        secrets=secrets,
    )


def probe_developer_text(
    client: Any,
    *,
    model: str,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    return _probe_exact_text(
        client,
        model=model,
        messages=[
            {
                "role": "developer",
                "content": f"Return exactly {DEVELOPER_TEXT_MARKER} and no other text.",
            },
            {"role": "user", "content": "Run the developer-message text check."},
        ],
        expected_marker=DEVELOPER_TEXT_MARKER,
        success_result="developer_text_ok",
        timeout_sec=timeout_sec,
        secrets=secrets,
    )


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
                        "For this compatibility test, the complete response token is fixed as "
                        f"{DEVELOPER_MARKER}. Return that token alone."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "For this compatibility test, use "
                        f"{USER_MARKER} as the complete response token."
                    ),
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
    system_ok = bool((checks.get("system_control") or {}).get("ok"))
    developer_text_ok = bool((checks.get("developer_text") or {}).get("ok"))
    precedence_ok = bool((checks.get("developer_precedence") or {}).get("ok"))
    tools_ok = bool((checks.get("developer_with_tools") or {}).get("ok"))
    if not system_ok:
        diagnosis = "system_control_failed"
    elif not developer_text_ok:
        diagnosis = "developer_text_request_failed"
    elif not precedence_ok:
        diagnosis = "developer_precedence_not_confirmed"
    elif not tools_ok:
        diagnosis = "developer_with_tools_not_confirmed"
    else:
        diagnosis = "safe_to_migrate"
    return {
        "system_control_confirmed": system_ok,
        "developer_role_observed": developer_text_ok or precedence_ok or tools_ok,
        "developer_text_confirmed": developer_text_ok,
        "developer_precedence_confirmed": precedence_ok,
        "developer_with_tools_confirmed": tools_ok,
        "safe_to_migrate_to_developer": system_ok and developer_text_ok and precedence_ok and tools_ok,
        "diagnosis": diagnosis,
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
    system_control = dict(checks.get("system_control") or {})
    developer_text = dict(checks.get("developer_text") or {})
    precedence = dict(checks.get("developer_precedence") or {})
    tools = dict(checks.get("developer_with_tools") or {})
    print("Developer role probe")
    print(f"  provider: {provider.get('name', '')}")
    print(f"  model: {provider.get('model', '')}")
    print(
        "  API key configured: "
        f"{'yes' if provider.get('auth_available') else 'no'} "
        f"({provider.get('api_key_env', '')})"
    )
    print(
        "  base URL configured: "
        f"{'yes' if provider.get('base_url_configured') else 'no'} "
        f"({provider.get('base_url_env', '')})"
    )
    print(
        "  custom CA configured: "
        f"{'yes' if provider.get('custom_ca_configured') else 'no'} "
        f"({provider.get('ca_cert_env', '')})"
    )
    print(f"  system baseline: {system_control.get('result', 'not_run')}")
    print(f"  developer text: {developer_text.get('result', 'not_run')}")
    print(f"  developer > user precedence: {precedence.get('result', 'not_run')}")
    print(f"  developer + function tools: {tools.get('result', 'not_run')}")
    print(f"  diagnosis: {summary.get('diagnosis', 'not_run')}")
    print(f"  safe to migrate: {'YES' if summary.get('safe_to_migrate_to_developer') else 'NO'}")
    print(f"  report: {report.get('report_path', '')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe developer-role precedence through the configured Chat Completions provider.",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help="Provider profile. Default: openai_compatible (the VP_OPENAI_COMPAT_* configuration).",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional model override. Defaults to VP_OPENAI_COMPAT_DEFAULT_MODEL for the default provider.",
    )
    parser.add_argument("--timeout-sec", type=float, default=60.0, help="Timeout per request. Default: 60.")
    parser.add_argument("--output", default="", help="Optional JSON report path under your chosen location.")
    parser.add_argument("--dry-run", action="store_true", help="Validate local configuration without API requests.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    base_config = load_config()
    selected_provider = str(args.provider or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER
    config = build_provider_config(base_config, selected_provider)
    auth = OpenAIAuthManager(config).resolve()
    model = str(args.model or config.default_model or "").strip()
    output_path = Path(args.output).expanduser().resolve() if args.output else _default_report_path()
    provider_payload = {
        "name": str(config.llm_provider or ""),
        "model": model,
        "auth_mode": str(auth.mode or ""),
        "auth_available": bool(auth.available),
        "api_key_env": (
            "VP_OPENAI_COMPAT_API_KEY"
            if selected_provider == DEFAULT_PROVIDER
            else str(config.llm_primary_api_key_env or "")
        ),
        "base_url_env": (
            "VP_OPENAI_COMPAT_BASE_URL"
            if selected_provider == DEFAULT_PROVIDER
            else f"VP_PROVIDER_{selected_provider.upper()}_BASE_URL"
        ),
        "ca_cert_env": (
            "VP_OPENAI_COMPAT_CA_CERT_PATH"
            if selected_provider == DEFAULT_PROVIDER
            else f"VP_PROVIDER_{selected_provider.upper()}_CA_CERT_PATH"
        ),
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
            "system_control": probe_system_control(
                client,
                model=model,
                timeout_sec=max(1.0, float(args.timeout_sec)),
                secrets=secrets,
            ),
            "developer_text": probe_developer_text(
                client,
                model=model,
                timeout_sec=max(1.0, float(args.timeout_sec)),
                secrets=secrets,
            ),
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
