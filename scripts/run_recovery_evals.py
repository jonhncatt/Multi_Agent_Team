#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "tool_failure_recovery_cases.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "evals" / "runtime-recovery-summary.json"


class RecoveryEvalConfigurationError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Runtime tool-failure recovery evals.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Recovery eval case manifest.")
    parser.add_argument("--name", default="", help="Run only cases whose name contains this text.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Safe JSON summary path.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the manifest without running pytest.")
    return parser


def _load_cases(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryEvalConfigurationError("Recovery eval manifest is unreadable or invalid JSON.") from exc
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
        raise RecoveryEvalConfigurationError("Recovery eval manifest must use schema_version 1.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RecoveryEvalConfigurationError("Recovery eval manifest must contain at least one case.")
    names: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise RecoveryEvalConfigurationError("Every recovery eval case must be an object.")
        name = str(item.get("name") or "").strip()
        node = str(item.get("test_node") or "").strip()
        if not name or name in names:
            raise RecoveryEvalConfigurationError("Recovery eval case names must be present and unique.")
        if not node.startswith("tests/") or "::test_" not in node or ".." in node:
            raise RecoveryEvalConfigurationError(f"Recovery eval case {name!r} has an invalid test node.")
        test_file = ROOT / node.split("::", 1)[0]
        if not test_file.is_file():
            raise RecoveryEvalConfigurationError(f"Recovery eval case {name!r} references a missing test file.")
        names.add(name)
    return payload


def _safe_result(case: dict[str, Any], *, returncode: int, elapsed_ms: float) -> dict[str, Any]:
    return {
        "name": str(case.get("name") or ""),
        "status": "passed" if returncode == 0 else "failed",
        "failure_category": str(case.get("failure_category") or ""),
        "expected_turn_status": str(case.get("expected_turn_status") or ""),
        "expected_replan_trigger": str(case.get("expected_replan_trigger") or ""),
        "max_tool_calls": int(case.get("max_tool_calls") or 0),
        "elapsed_ms": round(elapsed_ms, 2),
    }


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

    results: list[dict[str, Any]] = []
    for case in selected:
        print(f"[RUN] {case['name']}")
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(case["test_node"])],
            cwd=str(ROOT),
            check=False,
        )
        result = _safe_result(
            case,
            returncode=int(completed.returncode),
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )
        results.append(result)
        print(f"[{result['status'].upper()}] {result['name']}")

    passed = sum(1 for item in results if item["status"] == "passed")
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": str(manifest.get("suite") or ""),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "success_rate_percent": round(passed * 100.0 / len(results), 2),
            "real_model_calls": 0,
        },
        "results": results,
        "sensitive_content_omitted": True,
    }
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
