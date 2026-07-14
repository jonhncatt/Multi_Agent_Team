#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_evals import (  # noqa: E402
    DEFAULT_CASES_PATH,
    EvalConfigurationError,
    eval_exit_code,
    load_eval_suite,
    run_eval_suite,
    safe_report_path,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run isolated live Agent quality evals.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Current-schema eval suite JSON.")
    parser.add_argument("--name", default="", help="Run only cases whose name contains this text.")
    parser.add_argument("--repeat", type=int, default=1, help="Attempts per selected case. Default: 1.")
    parser.add_argument("--provider", default="", help="Optional configured provider profile override.")
    parser.add_argument("--model", default="", help="Optional model override.")
    parser.add_argument("--output", default="", help="JSON report path under artifacts/evals by default.")
    parser.add_argument("--keep-workspaces", action="store_true", help="Retain successful attempt workspaces too.")
    parser.add_argument("--validate-only", action="store_true", help="Validate suite and fixtures without model calls.")
    parser.add_argument("--live", action="store_true", help="Explicitly allow provider-backed Agent calls.")
    return parser


def _default_output_path() -> Path:
    return ROOT / "artifacts" / "evals" / "agent-quality-summary.json"


def _print_summary(report: dict) -> None:
    summary = report.get("summary") or {}
    for item in report.get("results") or []:
        line = f"[{str(item.get('status') or '').upper()}] {item.get('case')} attempt={item.get('attempt')}"
        failures = list(item.get("hard_failures") or [])
        if failures:
            line += f" - {'; '.join(failures)}"
        print(line)
    print(
        "Summary: "
        f"passed={summary.get('passed', 0)} "
        f"failed={summary.get('failed', 0)} "
        f"blocked={summary.get('blocked', 0)} "
        f"total={summary.get('total_attempts', 0)} "
        f"success_rate={summary.get('success_rate_percent', 0)}% "
        f"evaluable_success_rate={summary.get('evaluable_success_rate_percent', 0)}%"
    )
    print(f"Report: {report.get('report_path', '')}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        suite = load_eval_suite(args.cases)
        if args.validate_only:
            print(
                f"Eval suite valid: {suite.get('suite')} "
                f"({len(list(suite.get('cases') or []))} case(s))"
            )
            return 0
        if not args.live:
            print("Live Agent evals require --live. No provider request was sent.", file=sys.stderr)
            return 2
        report = run_eval_suite(
            suite,
            repeat=max(1, int(args.repeat)),
            provider=str(args.provider or ""),
            model=str(args.model or ""),
            name_filter=str(args.name or ""),
            keep_workspaces=bool(args.keep_workspaces),
        )
        output_path = Path(args.output).expanduser().resolve() if args.output else _default_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = safe_report_path(output_path, fallback_label="report")
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(report)
        return eval_exit_code(report)
    except EvalConfigurationError as exc:
        print(f"Eval configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
