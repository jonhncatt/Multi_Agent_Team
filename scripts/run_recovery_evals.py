#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.recovery_evals import (  # noqa: E402
    RecoveryEvalConfigurationError,
    load_recovery_eval_suite,
    run_recovery_eval_suite,
)


DEFAULT_CASES = ROOT / "evals" / "tool_failure_recovery_cases.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "evals" / "runtime-recovery-summary.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Runtime tool-failure recovery evals.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Recovery eval case manifest.")
    parser.add_argument("--name", default="", help="Run only cases whose name contains this text.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Safe JSON summary path.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the manifest without running pytest.")
    return parser


def _load_cases(path: Path) -> dict[str, Any]:
    return load_recovery_eval_suite(path, repo_root=ROOT)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = _load_cases(Path(args.cases).expanduser().resolve())
    except RecoveryEvalConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    selected = [
        dict(item)
        for item in manifest["cases"]
        if not str(args.name or "").strip()
        or str(args.name).strip().lower() in str(item.get("name") or "").lower()
    ]
    if not selected:
        print("No recovery eval cases matched --name.", file=sys.stderr)
        return 2
    if args.validate_only:
        print(f"Recovery eval suite valid: {manifest.get('suite')} ({len(selected)} case(s))")
        return 0

    def progress(event: dict[str, Any]) -> None:
        if event.get("event") == "attempt_started":
            print(f"[RUN] {event.get('case')}")
        elif event.get("event") == "attempt_finished":
            print(f"[DONE] {event.get('case')}")

    report = run_recovery_eval_suite(
        manifest,
        repo_root=ROOT,
        name_filter=str(args.name or ""),
        progress_cb=progress,
    )
    passed = int(report["summary"]["passed"])
    results = list(report["results"])
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Summary: passed={passed} failed={len(results) - passed} total={len(results)} "
        f"success_rate={report['summary']['success_rate_percent']}%"
    )
    print(f"Report: {output.name}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
