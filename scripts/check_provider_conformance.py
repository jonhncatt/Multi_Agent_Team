#!/usr/bin/env python
"""Probe the configured Chat Completions provider without exposing credentials.

The probe uses three small requests:

1. a minimal non-streaming completion;
2. a short streaming completion used to measure chunk cadence and local CPU cost;
3. a forced, side-effect-free function call.

It does not enable streaming in the Vintage Programmer application. Reports contain
only capability metadata, timings, character counts, dummy probe output, and errors
with configured secrets redacted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import build_provider_config, load_config, normalize_openai_base_url  # noqa: E402
from app.openai_auth import OpenAIAuthManager  # noqa: E402


SCHEMA_VERSION = 1
DEFAULT_BATCH_INTERVALS_MS = (16, 33, 50, 100)
PROBE_TOOL_NAME = "provider_probe"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, float(percentile))) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


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
    return value[:2000]


def _error_payload(exc: BaseException, secrets: Iterable[str]) -> dict[str, Any]:
    status_code = getattr(exc, "status_code", None)
    normalized_status = int(status_code) if isinstance(status_code, int) else None
    error_type = exc.__class__.__name__
    if normalized_status == 400:
        message = "Provider rejected the probe request or one of its parameters."
    elif normalized_status == 401:
        message = "Provider authentication failed."
    elif normalized_status == 403:
        message = "Provider authorization or policy rejected the request."
    elif normalized_status == 404:
        message = "The configured endpoint or model was not found."
    elif normalized_status == 408 or "timeout" in error_type.lower():
        message = "Provider request timed out."
    elif normalized_status == 429:
        message = "Provider or upstream model is rate-limited. Retry later or select another configured model."
    elif normalized_status is not None and normalized_status >= 500:
        message = "Provider or upstream model returned a server error."
    elif "connection" in error_type.lower():
        message = "Provider connection failed."
    else:
        message = "Provider request failed."
    return {
        "type": error_type,
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


def simulate_frontend_batching(
    samples: list[dict[str, Any]],
    *,
    duration_ms: float,
    intervals_ms: Iterable[int] = DEFAULT_BATCH_INTERVALS_MS,
    state_updates_per_flush: int = 1,
) -> list[dict[str, Any]]:
    """Estimate render/update pressure when text deltas are coalesced by time."""

    content_samples = [
        {
            "at_ms": max(0.0, float(item.get("at_ms") or 0.0)),
            "chars": max(0, int(item.get("chars") or 0)),
        }
        for item in samples
        if int(item.get("chars") or 0) > 0
    ]
    naive_flushes = len(content_samples)
    normalized_duration_ms = max(1.0, float(duration_ms or 0.0))
    results: list[dict[str, Any]] = []

    for raw_interval in intervals_ms:
        interval_ms = max(1, int(raw_interval))
        flushes = 0
        pending_chars = 0
        last_flush_at = 0.0
        max_pending_chars = 0

        for sample in content_samples:
            pending_chars += sample["chars"]
            max_pending_chars = max(max_pending_chars, pending_chars)
            if sample["at_ms"] - last_flush_at < interval_ms:
                continue
            flushes += 1
            pending_chars = 0
            last_flush_at = sample["at_ms"]

        if pending_chars:
            flushes += 1

        reduction = 0.0
        if naive_flushes:
            reduction = 1.0 - (flushes / naive_flushes)
        results.append(
            {
                "interval_ms": interval_ms,
                "flushes": flushes,
                "flushes_per_sec": _safe_round(flushes * 1000.0 / normalized_duration_ms),
                "estimated_state_updates": flushes * max(1, int(state_updates_per_flush)),
                "flush_reduction_percent": _safe_round(reduction * 100.0),
                "max_added_display_latency_ms": interval_ms,
                "max_pending_chars": max_pending_chars,
            }
        )
    return results


def build_stream_recommendation(
    *,
    content_chunk_count: int,
    duration_ms: float,
    batching: list[dict[str, Any]],
    state_updates_per_delta: int,
    target_ui_updates_per_sec: float,
) -> dict[str, Any]:
    normalized_duration_ms = max(1.0, float(duration_ms or 0.0))
    chunks_per_sec = content_chunk_count * 1000.0 / normalized_duration_ms
    naive_state_updates_per_sec = chunks_per_sec * max(1, int(state_updates_per_delta))

    if naive_state_updates_per_sec > 200:
        risk = "high"
    elif naive_state_updates_per_sec > 80:
        risk = "medium"
    else:
        risk = "low"

    recommended = None
    for candidate in batching:
        if float(candidate.get("flushes_per_sec") or 0.0) <= max(1.0, target_ui_updates_per_sec):
            recommended = candidate
            break
    if recommended is None and batching:
        recommended = batching[-1]

    return {
        "naive_render_risk": risk,
        "content_chunks_per_sec": _safe_round(chunks_per_sec),
        "estimated_naive_state_updates_per_sec": _safe_round(naive_state_updates_per_sec),
        "target_ui_flushes_per_sec": _safe_round(target_ui_updates_per_sec),
        "recommended_flush_interval_ms": int((recommended or {}).get("interval_ms") or 0),
        "recommended_flushes_per_sec": _safe_round((recommended or {}).get("flushes_per_sec") or 0.0),
        "guidance": (
            "Keep provider streaming disabled in the product until UI delta updates are coalesced. "
            "When enabled, append incoming text to a mutable buffer and publish at most one UI update "
            "per selected interval; always flush immediately on tool calls, errors, cancellation, and completion."
        ),
    }


def _stream_intervals_ms(samples: list[dict[str, Any]]) -> list[float]:
    times = [float(item.get("at_ms") or 0.0) for item in samples]
    return [max(0.0, right - left) for left, right in zip(times, times[1:])]


def _content_from_message(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _base_request(model: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max(1, int(max_tokens)),
    }


def probe_non_stream(
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
            **_base_request(model, 32),
            messages=[
                {"role": "system", "content": "Follow the probe instruction exactly."},
                {"role": "user", "content": "Reply with exactly VP_OK and nothing else."},
            ],
            timeout=timeout_sec,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cpu_ms = (time.process_time() - cpu_started) * 1000.0
        choices = list(getattr(response, "choices", None) or [])
        message = getattr(choices[0], "message", None) if choices else None
        text = _content_from_message(message).strip()
        return {
            "ok": bool(choices),
            "duration_ms": _safe_round(elapsed_ms),
            "local_cpu_ms": _safe_round(cpu_ms),
            "local_cpu_percent_of_one_core": _safe_round(cpu_ms / max(1.0, elapsed_ms) * 100.0),
            "response_chars": len(text),
            "exact_probe_reply": text == "VP_OK",
            "finish_reason": str(getattr(choices[0], "finish_reason", "") or "") if choices else "",
            "usage": _usage_payload(getattr(response, "usage", None)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "duration_ms": _safe_round((time.perf_counter() - started) * 1000.0),
            "error": _error_payload(exc, secrets),
        }


def _collect_stream_attempt(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    timeout_sec: float,
    include_usage: bool,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        **_base_request(model, max_tokens),
        "messages": [
            {
                "role": "user",
                "content": (
                    "For a transport benchmark, output the integers 1 through 80 in order, "
                    "separated only by commas. Do not add prose or markdown."
                ),
            }
        ],
        "stream": True,
        "timeout": timeout_sec,
    }
    if include_usage:
        request["stream_options"] = {"include_usage": True}

    started = time.perf_counter()
    cpu_started = time.process_time()
    tracemalloc.start()
    samples: list[dict[str, Any]] = []
    first_event_ms: float | None = None
    first_content_ms: float | None = None
    chunk_count = 0
    content_chars = 0
    finish_reasons: list[str] = []
    usage: dict[str, int] = {}

    try:
        stream = client.chat.completions.create(**request)
        for chunk in stream:
            now_ms = (time.perf_counter() - started) * 1000.0
            chunk_count += 1
            if first_event_ms is None:
                first_event_ms = now_ms

            choices = list(getattr(chunk, "choices", None) or [])
            delta_text = ""
            if choices:
                delta = getattr(choices[0], "delta", None)
                delta_text = _content_from_message(delta)
                finish_reason = str(getattr(choices[0], "finish_reason", "") or "")
                if finish_reason and finish_reason not in finish_reasons:
                    finish_reasons.append(finish_reason)
            if delta_text:
                if first_content_ms is None:
                    first_content_ms = now_ms
                content_chars += len(delta_text)
                samples.append({"at_ms": _safe_round(now_ms, 3), "chars": len(delta_text)})

            chunk_usage = _usage_payload(getattr(chunk, "usage", None))
            if chunk_usage:
                usage = chunk_usage

        duration_ms = (time.perf_counter() - started) * 1000.0
        cpu_ms = (time.process_time() - cpu_started) * 1000.0
        _, peak_bytes = tracemalloc.get_traced_memory()
        intervals = _stream_intervals_ms(samples)
        return {
            "ok": chunk_count > 0,
            "include_usage_requested": include_usage,
            "duration_ms": _safe_round(duration_ms),
            "time_to_first_event_ms": _safe_round(first_event_ms),
            "time_to_first_content_ms": _safe_round(first_content_ms),
            "local_cpu_ms": _safe_round(cpu_ms),
            "local_cpu_percent_of_one_core": _safe_round(cpu_ms / max(1.0, duration_ms) * 100.0),
            "python_peak_memory_kib": _safe_round(peak_bytes / 1024.0),
            "chunk_count": chunk_count,
            "content_chunk_count": len(samples),
            "content_chars": content_chars,
            "all_chunks_per_sec": _safe_round(chunk_count * 1000.0 / max(1.0, duration_ms)),
            "content_chunks_per_sec": _safe_round(len(samples) * 1000.0 / max(1.0, duration_ms)),
            "average_chars_per_content_chunk": _safe_round(content_chars / max(1, len(samples))),
            "content_interval_ms": {
                "median": _safe_round(statistics.median(intervals) if intervals else 0.0),
                "p95": _safe_round(_percentile(intervals, 0.95)),
                "max": _safe_round(max(intervals) if intervals else 0.0),
            },
            "finish_reasons": finish_reasons,
            "usage": usage,
            "usage_in_stream_supported": bool(usage),
            "samples": samples,
        }
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()


def probe_stream(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    try:
        return _collect_stream_attempt(
            client,
            model=model,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            include_usage=True,
        )
    except Exception as first_exc:
        message = str(first_exc or "").lower()
        can_retry_without_options = any(
            token in message
            for token in ("stream_options", "include_usage", "unknown parameter", "extra_forbidden")
        )
        if not can_retry_without_options:
            return {"ok": False, "error": _error_payload(first_exc, secrets)}
        try:
            result = _collect_stream_attempt(
                client,
                model=model,
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                include_usage=False,
            )
            result["compatibility_notes"] = ["stream_options.include_usage is not supported; plain streaming succeeded."]
            return result
        except Exception as second_exc:
            return {
                "ok": False,
                "first_error": _error_payload(first_exc, secrets),
                "error": _error_payload(second_exc, secrets),
            }


def probe_tool_calling(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    timeout_sec: float,
    secrets: list[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            **_base_request(model, max(96, int(max_tokens))),
            messages=[
                {
                    "role": "user",
                    "content": "Call provider_probe exactly once with value set to VP_TOOL_OK. Do not answer in prose.",
                }
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": PROBE_TOOL_NAME,
                        "description": "A side-effect-free provider compatibility probe.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": PROBE_TOOL_NAME}},
            timeout=timeout_sec,
        )
        choices = list(getattr(response, "choices", None) or [])
        message = getattr(choices[0], "message", None) if choices else None
        tool_calls = list(getattr(message, "tool_calls", None) or []) if message is not None else []
        parsed_arguments: dict[str, Any] = {}
        observed_name = ""
        call_id_present = False
        if tool_calls:
            call = tool_calls[0]
            call_id_present = bool(str(getattr(call, "id", "") or "").strip())
            function = getattr(call, "function", None)
            observed_name = str(getattr(function, "name", "") or "")
            raw_arguments = str(getattr(function, "arguments", "") or "")
            try:
                decoded = json.loads(raw_arguments)
                if isinstance(decoded, dict):
                    parsed_arguments = decoded
            except Exception:
                parsed_arguments = {}
        tool_contract_ok = bool(
            tool_calls
            and observed_name == PROBE_TOOL_NAME
            and call_id_present
            and parsed_arguments.get("value") == "VP_TOOL_OK"
        )
        return {
            "ok": tool_contract_ok,
            "duration_ms": _safe_round((time.perf_counter() - started) * 1000.0),
            "response_choice_count": len(choices),
            "tool_call_count": len(tool_calls),
            "tool_name_matches": observed_name == PROBE_TOOL_NAME,
            "tool_call_id_present": call_id_present,
            "arguments_are_json_object": bool(parsed_arguments),
            "probe_argument_matches": parsed_arguments.get("value") == "VP_TOOL_OK",
            "assistant_text_chars": len(_content_from_message(message)),
            "finish_reason": str(getattr(choices[0], "finish_reason", "") or "") if choices else "",
            "usage": _usage_payload(getattr(response, "usage", None)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "duration_ms": _safe_round((time.perf_counter() - started) * 1000.0),
            "error": _error_payload(exc, secrets),
        }


def _default_report_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT_DIR / "artifacts" / "provider_conformance" / f"provider-{stamp}.json"


def _print_summary(report: dict[str, Any]) -> None:
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    stream = checks.get("stream") if isinstance(checks.get("stream"), dict) else {}
    recommendation = report.get("stream_recommendation") if isinstance(report.get("stream_recommendation"), dict) else {}
    print("Provider conformance probe")
    print(f"  provider: {report['provider']['name']}")
    print(f"  model: {report['provider']['model']}")
    print(f"  auth configured: {'yes' if report['provider'].get('auth_available') else 'no'}")
    print(f"  base URL configured: {'yes' if report['provider'].get('base_url_configured') else 'no'}")
    print(f"  custom CA configured: {'yes' if report['provider'].get('custom_ca_configured') else 'no'}")
    for key, label in (("non_stream", "non-stream"), ("stream", "stream"), ("tool_calling", "tool calling")):
        payload = checks.get(key)
        if not isinstance(payload, dict):
            print(f"  {label}: skipped")
        else:
            print(f"  {label}: {'supported' if payload.get('ok') else 'failed'}")
    if stream.get("ok"):
        print(f"  stream TTFC: {stream.get('time_to_first_content_ms', 0)} ms")
        print(f"  stream content chunks/sec: {stream.get('content_chunks_per_sec', 0)}")
        print(f"  probe local CPU: {stream.get('local_cpu_percent_of_one_core', 0)}% of one core")
        print(f"  naive UI update risk: {recommendation.get('naive_render_risk', 'unknown')}")
        print(f"  recommended UI flush interval: {recommendation.get('recommended_flush_interval_ms', 0)} ms")
    print(f"  report: {report.get('report_path', '')}")
    print("  note: local CPU excludes provider-side CPU and does not measure a real browser render.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe the configured Chat Completions provider and estimate streaming UI update pressure.",
    )
    parser.add_argument("--provider", default="", help="Optional configured provider profile. Defaults to VP_LLM_PROVIDER.")
    parser.add_argument("--model", default="", help="Optional model override. Defaults to the active provider model.")
    parser.add_argument("--timeout-sec", type=float, default=45.0, help="Per-request timeout. Default: 45 seconds.")
    parser.add_argument("--stream-max-tokens", type=int, default=256, help="Small streaming probe output cap. Default: 256.")
    parser.add_argument("--tool-max-tokens", type=int, default=384, help="Tool-call probe output cap. Default: 384.")
    parser.add_argument("--output", default="", help="JSON report path. Defaults under artifacts/provider_conformance/.")
    parser.add_argument("--skip-non-stream", action="store_true")
    parser.add_argument("--skip-stream", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    parser.add_argument(
        "--frontend-state-updates-per-delta",
        type=int,
        default=5,
        help="Estimated frontend state operations triggered per raw text delta. Default: 5 for the current UI path.",
    )
    parser.add_argument(
        "--target-ui-updates-per-sec",
        type=float,
        default=20.0,
        help="Target maximum published UI text updates per second. Default: 20.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate local configuration without sending API requests.")
    parser.add_argument("--strict-exit", action="store_true", help="Exit 1 when any requested capability check fails.")
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
    checks: dict[str, Any] = {}
    stream_recommendation: dict[str, Any] = {}

    try:
        client = OpenAI(**client_kwargs)
        if not args.skip_non_stream:
            checks["non_stream"] = probe_non_stream(
                client,
                model=model,
                timeout_sec=args.timeout_sec,
                secrets=secrets,
            )
        if not args.skip_stream:
            stream_result = probe_stream(
                client,
                model=model,
                max_tokens=max(32, int(args.stream_max_tokens)),
                timeout_sec=args.timeout_sec,
                secrets=secrets,
            )
            checks["stream"] = stream_result
            if stream_result.get("ok"):
                batching = simulate_frontend_batching(
                    list(stream_result.get("samples") or []),
                    duration_ms=float(stream_result.get("duration_ms") or 0.0),
                    state_updates_per_flush=max(1, int(args.frontend_state_updates_per_delta)),
                )
                stream_result["frontend_batching_simulation"] = batching
                stream_recommendation = build_stream_recommendation(
                    content_chunk_count=int(stream_result.get("content_chunk_count") or 0),
                    duration_ms=float(stream_result.get("duration_ms") or 0.0),
                    batching=batching,
                    state_updates_per_delta=max(1, int(args.frontend_state_updates_per_delta)),
                    target_ui_updates_per_sec=max(1.0, float(args.target_ui_updates_per_sec)),
                )
        if not args.skip_tools:
            checks["tool_calling"] = probe_tool_calling(
                client,
                model=model,
                max_tokens=max(96, int(args.tool_max_tokens)),
                timeout_sec=args.timeout_sec,
                secrets=secrets,
            )
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

    requested_checks = [payload for payload in checks.values() if isinstance(payload, dict)]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "dry_run": False,
        "provider": provider_payload,
        "checks": checks,
        "stream_recommendation": stream_recommendation,
        "summary": {
            "requested_check_count": len(requested_checks),
            "passed_check_count": sum(1 for payload in requested_checks if payload.get("ok")),
            "all_requested_checks_passed": bool(requested_checks) and all(payload.get("ok") for payload in requested_checks),
            "credentials_in_report": False,
            "application_runtime_changed": False,
        },
        "report_path": str(output_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(report)

    if args.strict_exit and not report["summary"]["all_requested_checks_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
