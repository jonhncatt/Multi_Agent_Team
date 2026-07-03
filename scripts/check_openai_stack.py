#!/usr/bin/env python
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as importlib_metadata
import inspect
import json
import os
import sys
import time
import traceback
from typing import Any


def load_env_file(path: str) -> None:
    env_path = str(path or "").strip()
    if not env_path or not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def package_version(package_name: str) -> str:
    try:
        return importlib_metadata.version(package_name)
    except Exception:
        return ""


def short_text(value: Any, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def result(status: str, name: str, **details: Any) -> dict[str, Any]:
    payload = {"status": status, "name": name}
    payload.update(details)
    return payload


def ok(name: str, **details: Any) -> dict[str, Any]:
    return result("ok", name, **details)


def skip(name: str, reason: str, **details: Any) -> dict[str, Any]:
    return result("skip", name, reason=reason, **details)


def fail(name: str, exc: BaseException, *, include_traceback: bool = False, **details: Any) -> dict[str, Any]:
    payload = result(
        "fail",
        name,
        error_type=type(exc).__name__,
        error=short_text(exc, limit=1200),
        **details,
    )
    if include_traceback:
        payload["traceback"] = traceback.format_exc()
    return payload


def build_openai_client(api_key: str, base_url: str = "") -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": api_key or "sk-probe-local-only"}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def probe_openai_sdk(api_key: str, base_url: str) -> dict[str, Any]:
    name = "openai-sdk-import-and-responses-surface"
    try:
        openai = importlib.import_module("openai")
        client = build_openai_client(api_key=api_key, base_url=base_url)
        has_responses = hasattr(client, "responses")
        signature = ""
        if has_responses:
            signature = str(inspect.signature(client.responses.create))
        return ok(
            name,
            package="openai",
            version=package_version("openai") or getattr(openai, "__version__", ""),
            responses_available=has_responses,
            responses_create_signature=signature,
        )
    except Exception as exc:
        return fail(name, exc)


def probe_responses_api_live(api_key: str, base_url: str, model: str, timeout_sec: float) -> dict[str, Any]:
    name = "responses-api-live-text"
    if not api_key:
        return skip(name, "missing OPENAI_API_KEY or VP_OPENAI_API_KEY")
    try:
        client = build_openai_client(api_key=api_key, base_url=base_url)
        started = time.monotonic()
        response = client.responses.create(
            model=model,
            instructions="You are a diagnostic probe. Return exactly PROBE_OK.",
            input="Return exactly PROBE_OK.",
            max_output_tokens=64,
            store=False,
            timeout=timeout_sec,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        output_text = short_text(getattr(response, "output_text", ""), limit=500)
        usage = getattr(response, "usage", None)
        return ok(
            name,
            model=model,
            elapsed_ms=elapsed_ms,
            response_id=str(getattr(response, "id", "") or ""),
            output_text=output_text,
            usage=str(usage) if usage is not None else "",
        )
    except Exception as exc:
        return fail(name, exc)


def probe_langchain_responses_live(api_key: str, base_url: str, model: str, timeout_sec: float) -> dict[str, Any]:
    name = "langchain-openai-use-responses-api-live"
    if not api_key:
        return skip(name, "missing OPENAI_API_KEY or VP_OPENAI_API_KEY")
    try:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "max_completion_tokens": 64,
            "timeout": timeout_sec,
            "use_responses_api": True,
            "store": False,
        }
        if base_url:
            kwargs["base_url"] = base_url
        llm = ChatOpenAI(**kwargs)
        started = time.monotonic()
        message = llm.invoke("Return exactly PROBE_OK.")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ok(
            name,
            model=model,
            elapsed_ms=elapsed_ms,
            content=short_text(getattr(message, "content", message), limit=500),
            response_metadata=getattr(message, "response_metadata", {}),
        )
    except Exception as exc:
        return fail(name, exc)


def probe_agents_sdk_import() -> dict[str, Any]:
    name = "agents-sdk-import-and-surface"
    try:
        agents = importlib.import_module("agents")
        agent_cls = getattr(agents, "Agent")
        runner_cls = getattr(agents, "Runner")
        return ok(
            name,
            package="openai-agents",
            version=package_version("openai-agents"),
            module_file=str(getattr(agents, "__file__", "") or ""),
            agent_signature=str(inspect.signature(agent_cls)),
            runner_run_sync_signature=str(inspect.signature(runner_cls.run_sync)),
            has_function_tool=hasattr(agents, "function_tool"),
            has_run_config=hasattr(agents, "RunConfig"),
        )
    except Exception as exc:
        return fail(name, exc)


def probe_agents_sdk_live(api_key: str, model: str, timeout_sec: float) -> dict[str, Any]:
    name = "agents-sdk-live-agent-with-local-tool"
    if not api_key:
        return skip(name, "missing OPENAI_API_KEY or VP_OPENAI_API_KEY")
    try:
        os.environ.setdefault("OPENAI_API_KEY", api_key)
        os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "true")

        from agents import Agent, RunConfig, Runner, function_tool, set_tracing_disabled

        set_tracing_disabled(True)

        @function_tool
        def local_probe_echo(text: str) -> str:
            return f"TOOL_ECHO:{text}"

        agent = Agent(
            name="openai_stack_probe",
            instructions=(
                "Use the local_probe_echo tool exactly once with text PROBE_OK. "
                "Then return the tool result exactly."
            ),
            model=model,
            tools=[local_probe_echo],
        )
        run_config = RunConfig(tracing_disabled=True, workflow_name="openai_stack_probe")
        started = time.monotonic()
        run_result = Runner.run_sync(
            agent,
            "Run the probe now.",
            max_turns=4,
            run_config=run_config,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        new_items = [
            type(item).__name__
            for item in list(getattr(run_result, "new_items", []) or [])
        ]
        return ok(
            name,
            model=model,
            elapsed_ms=elapsed_ms,
            final_output=short_text(getattr(run_result, "final_output", ""), limit=500),
            last_agent=str(getattr(getattr(run_result, "last_agent", None), "name", "") or ""),
            new_item_types=new_items,
        )
    except Exception as exc:
        return fail(name, exc)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"ok": 0, "skip": 0, "fail": 0}
    for item in results:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return {
        "ok": counts["fail"] == 0,
        "counts": counts,
        "results": results,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe whether this environment can use OpenAI Responses API, langchain-openai Responses transport, and OpenAI Agents SDK."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run real API calls. Without this, the script only checks local imports and SDK surfaces.",
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Exit non-zero if live probes are skipped because credentials are missing.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model for live probes. Defaults to OPENAI_API_PROBE_MODEL, VP_OPENAI_DEFAULT_MODEL, VP_OPENAI_COMPAT_DEFAULT_MODEL, OPENAI_MODEL, or gpt-5-mini.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API key for live probes. Defaults to OPENAI_API_KEY, VP_OPENAI_API_KEY, or VP_OPENAI_COMPAT_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional OpenAI-compatible base URL for SDK probes. Defaults to OPENAI_BASE_URL, VP_OPENAI_BASE_URL, or VP_OPENAI_COMPAT_BASE_URL.",
    )
    parser.add_argument("--env-file", default=".env", help="Optional env file to load before resolving defaults.")
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    args.model = (
        str(args.model or "").strip()
        or env_first("OPENAI_API_PROBE_MODEL", "VP_OPENAI_DEFAULT_MODEL", "VP_OPENAI_COMPAT_DEFAULT_MODEL", "OPENAI_MODEL")
        or "gpt-5-mini"
    )
    args.api_key = str(args.api_key or "").strip() or env_first(
        "OPENAI_API_KEY",
        "VP_OPENAI_API_KEY",
        "VP_OPENAI_COMPAT_API_KEY",
    )
    args.base_url = str(args.base_url or "").strip() or env_first(
        "OPENAI_BASE_URL",
        "VP_OPENAI_BASE_URL",
        "VP_OPENAI_COMPAT_BASE_URL",
    )
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    results = [
        probe_openai_sdk(api_key=args.api_key, base_url=args.base_url),
        probe_agents_sdk_import(),
    ]
    if args.live:
        results.extend(
            [
                probe_responses_api_live(
                    api_key=args.api_key,
                    base_url=args.base_url,
                    model=args.model,
                    timeout_sec=args.timeout_sec,
                ),
                probe_langchain_responses_live(
                    api_key=args.api_key,
                    base_url=args.base_url,
                    model=args.model,
                    timeout_sec=args.timeout_sec,
                ),
                probe_agents_sdk_live(
                    api_key=args.api_key,
                    model=args.model,
                    timeout_sec=args.timeout_sec,
                ),
            ]
        )
    else:
        results.extend(
            [
                skip("responses-api-live-text", "pass --live to run a real API call"),
                skip("langchain-openai-use-responses-api-live", "pass --live to run a real API call"),
                skip("agents-sdk-live-agent-with-local-tool", "pass --live to run a real API call"),
            ]
        )

    payload = summarize(results)
    payload["model"] = args.model
    payload["live"] = bool(args.live)
    payload["base_url_configured"] = bool(args.base_url)
    payload["api_key_configured"] = bool(args.api_key)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"OpenAI stack probe | model={args.model} | live={bool(args.live)}")
        print(f"API key configured: {bool(args.api_key)}")
        print(f"Base URL configured: {bool(args.base_url)}")
        print()
        for item in results:
            status = str(item.get("status") or "").upper()
            print(f"[{status}] {item.get('name')}")
            for key, value in item.items():
                if key in {"status", "name"}:
                    continue
                rendered = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)
                print(f"  {key}: {short_text(rendered, limit=1200)}")
            print()
        print("Summary:", json.dumps(payload["counts"], ensure_ascii=False))

    if any(item.get("status") == "fail" for item in results):
        return 1
    if args.require_live and any(item.get("status") == "skip" and "-live" in str(item.get("name") or "") for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
