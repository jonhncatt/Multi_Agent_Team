#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import OfficeAgent
from app.config import load_config
from app.models import ChatSettings
from app.storage import now_iso


def _resolve_value(value: Any) -> Any:
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        path_like = Path(expanded)
        if expanded.startswith("./") or expanded.startswith("../") or expanded.startswith("evals/") or expanded.startswith("app/"):
            return str((ROOT / expanded).resolve())
        return expanded
    if isinstance(value, list):
        return [_resolve_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_value(item) for key, item in value.items()}
    return value


def _get_path(obj: Any, path: str) -> Any:
    current = obj
    for raw_part in path.split("."):
        part = raw_part.strip()
        if part == "":
            continue
        if isinstance(current, list):
            try:
                idx = int(part)
            except Exception as exc:
                raise KeyError(f"Expected list index at {part}") from exc
            current = current[idx]
            continue
        if isinstance(current, dict):
            current = current[part]
            continue
        raise KeyError(f"Cannot traverse {part} in non-container {type(current).__name__}")
    return current


def _ensure_generated_fixtures() -> None:
    generated_dir = ROOT / "evals" / "fixtures" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = generated_dir / "opcode_table.xlsx"
    if not xlsx_path.exists():
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "OpcodeTable"
        ws.append(["Value", "Description"])
        ws.append(["0Ah", "Invalid Format"])
        ws.append(["0Ch", "Command Sequence Error"])
        ws.append(["15h", "Operation Denied"])
        ws.append(["20h", "Namespace is Write Protected"])
        wb.save(xlsx_path)
        wb.close()


def _prepare_case(case: dict[str, Any]) -> None:
    fixture = str((case.get("prepare") or {}).get("fixture") or "").strip()
    if not fixture:
        return
    if fixture == "opcode_xlsx":
        _ensure_generated_fixtures()


def _skip_reason(case: dict[str, Any]) -> str | None:
    env_keys = [str(item).strip() for item in case.get("skip_if_missing_env") or [] if str(item).strip()]
    for key in env_keys:
        if not str(os.environ.get(key) or "").strip():
            return f"missing env {key}"
    return None


def _assertions(payload: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for path, expected in (spec.get("equals") or {}).items():
        actual = _get_path(payload, path)
        if actual != expected:
            errors.append(f"{path}: expected {expected!r}, got {actual!r}")

    for path, expected in (spec.get("min_value") or {}).items():
        actual = _get_path(payload, path)
        try:
            if float(actual) < float(expected):
                errors.append(f"{path}: expected >= {expected!r}, got {actual!r}")
        except Exception:
            errors.append(f"{path}: expected numeric >= {expected!r}, got {actual!r}")

    for path, expected in (spec.get("max_value") or {}).items():
        actual = _get_path(payload, path)
        try:
            if float(actual) > float(expected):
                errors.append(f"{path}: expected <= {expected!r}, got {actual!r}")
        except Exception:
            errors.append(f"{path}: expected numeric <= {expected!r}, got {actual!r}")

    for path, snippets in (spec.get("contains") or {}).items():
        actual = str(_get_path(payload, path))
        for snippet in snippets:
            if str(snippet) not in actual:
                errors.append(f"{path}: missing snippet {snippet!r}")

    for path, snippets in (spec.get("contains_any") or {}).items():
        actual = str(_get_path(payload, path))
        if not any(str(snippet) in actual for snippet in snippets):
            errors.append(f"{path}: missing any of {snippets!r}")

    return errors


def _attachment_meta(entry: dict[str, Any]) -> dict[str, Any]:
    path = Path(_resolve_value(entry.get("path")))
    return {
        "id": f"eval-{path.name}",
        "original_name": str(entry.get("original_name") or path.name),
        "safe_name": path.name,
        "mime": str(entry.get("mime") or "application/octet-stream"),
        "suffix": path.suffix.lower(),
        "kind": str(entry.get("kind") or "document"),
        "size": path.stat().st_size,
        "path": str(path.resolve()),
        "created_at": now_iso(),
    }


def run_tool_case(case: dict[str, Any], executor: Any) -> dict[str, Any]:
    tool_name = str(case["tool"])
    args = _resolve_value(case.get("args") or {})
    fn = getattr(executor, tool_name)
    t0 = time.perf_counter()
    result = fn(**args)
    dt = time.perf_counter() - t0
    payload = result if isinstance(result, dict) else {"result": result}
    payload["elapsed_sec"] = round(dt, 3)
    return payload


def run_agent_case(case: dict[str, Any], agent: OfficeAgent) -> dict[str, Any]:
    message = str(case.get("message") or "")
    attachments = [_attachment_meta(item) for item in case.get("attachments") or []]
    settings = ChatSettings(**(case.get("settings") or {}))
    t0 = time.perf_counter()
    (
        text,
        tool_events,
        attachment_note,
        execution_plan,
        execution_trace,
        debug_flow,
        agent_panels,
        token_usage,
        effective_model,
    ) = agent.run_chat(
        history_turns=[],
        summary="",
        user_message=message,
        attachment_metas=attachments,
        settings=settings,
        session_id="eval-harness",
    )
    dt = time.perf_counter() - t0
    return {
        "text": text,
        "attachment_note": attachment_note,
        "execution_plan": execution_plan,
        "execution_trace": execution_trace,
        "debug_flow_count": len(debug_flow),
        "agent_panels": agent_panels,
        "tool_events": [item.model_dump() for item in tool_events],
        "tool_events_count": len(tool_events),
        "token_usage": token_usage,
        "effective_model": effective_model,
        "elapsed_sec": round(dt, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run regression evals for tools and agents.")
    parser.add_argument("--cases", default=str(ROOT / "evals" / "cases.json"))
    parser.add_argument("--name", default="", help="Run only cases whose name contains this substring.")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()

    cases_path = Path(args.cases).resolve()
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    cfg = load_config()
    agent = OfficeAgent(cfg)
    tools = agent.tools

    results: list[dict[str, Any]] = []
    passes = 0
    failures = 0
    skips = 0

    for case in cases:
        name = str(case.get("name") or "")
        if args.name and args.name not in name:
            continue
        if bool(case.get("optional")) and not args.include_optional:
            results.append({"name": name, "status": "skipped", "reason": "optional"})
            skips += 1
            continue
        reason = _skip_reason(case)
        if reason:
            results.append({"name": name, "status": "skipped", "reason": reason})
            skips += 1
            continue

        _prepare_case(case)
        kind = str(case.get("kind") or "tool")
        try:
            payload = run_tool_case(case, tools) if kind == "tool" else run_agent_case(case, agent)
            errors = _assertions(payload, case.get("assert") or {})
            if errors:
                results.append({"name": name, "status": "failed", "errors": errors, "payload": payload})
                failures += 1
            else:
                results.append({"name": name, "status": "passed", "payload": payload})
                passes += 1
        except Exception as exc:
            results.append({"name": name, "status": "failed", "errors": [str(exc)]})
            failures += 1

    summary = {
        "passed": passes,
        "failed": failures,
        "skipped": skips,
        "total": passes + failures + skips,
        "results": results,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in results:
        status = item["status"].upper()
        line = f"[{status}] {item['name']}"
        if item["status"] == "skipped":
            line += f" - {item.get('reason', '')}"
        elif item["status"] == "failed":
            line += f" - {'; '.join(item.get('errors') or [])}"
        print(line)

    print(
        f"\nSummary: passed={summary['passed']} failed={summary['failed']} skipped={summary['skipped']} total={summary['total']}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
