from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable


class RecoveryEvalConfigurationError(ValueError):
    pass


def _infer_repo_root(manifest_path: Path) -> Path:
    if manifest_path.parent.name == "evals":
        return manifest_path.parent.parent.resolve()
    return Path.cwd().resolve()


def load_recovery_eval_suite(
    path: str | Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    root = (repo_root or _infer_repo_root(resolved)).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryEvalConfigurationError("Recovery eval manifest is unreadable or invalid JSON.") from exc
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
        raise RecoveryEvalConfigurationError("Recovery eval manifest must use schema_version 1.")
    if not str(payload.get("suite") or "").strip():
        raise RecoveryEvalConfigurationError("Recovery eval manifest must define a suite name.")
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
        test_file = root / node.split("::", 1)[0]
        if not test_file.is_file():
            raise RecoveryEvalConfigurationError(f"Recovery eval case {name!r} references a missing test file.")
        test_name = node.split("::", 1)[1]
        test_source = test_file.read_text(encoding="utf-8")
        if not re.search(rf"^def\s+{re.escape(test_name)}\s*\(", test_source, flags=re.MULTILINE):
            raise RecoveryEvalConfigurationError(
                f"Recovery eval case {name!r} references a missing test function: {test_name}."
            )
        names.add(name)
    return payload


def _safe_result(case: dict[str, Any], *, returncode: int, elapsed_ms: float) -> dict[str, Any]:
    return {
        "name": str(case.get("name") or ""),
        "status": "passed" if returncode == 0 else "failed",
        "failure_category": str(case.get("failure_category") or ""),
        "expected_turn_status": str(case.get("expected_turn_status") or ""),
        "expected_continuation_policy": str(case.get("expected_continuation_policy") or ""),
        "expected_failure_counted": case.get("expected_failure_counted"),
        "max_tool_calls": int(case.get("max_tool_calls") or 0),
        "expected_error_kinds": [str(item) for item in list(case.get("expected_error_kinds") or [])],
        "expected_outcomes": [str(item) for item in list(case.get("expected_outcomes") or [])],
        "expected_recovery_tool": str(case.get("expected_recovery_tool") or ""),
        "elapsed_ms": round(elapsed_ms, 2),
    }


def run_recovery_eval_suite(
    suite: dict[str, Any],
    *,
    repo_root: Path,
    name_filter: str = "",
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    needle = str(name_filter or "").strip().lower()
    selected = [
        dict(item)
        for item in list(suite.get("cases") or [])
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and (not needle or needle in str(item.get("name") or "").lower())
    ]
    if not selected:
        raise RecoveryEvalConfigurationError("No recovery eval cases matched the selected case filter.")

    results: list[dict[str, Any]] = []
    for case in selected:
        case_name = str(case.get("name") or "")
        if progress_cb is not None:
            progress_cb({"event": "attempt_started", "case": case_name, "attempt": 1})
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(case["test_node"])],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
        result = _safe_result(
            case,
            returncode=int(completed.returncode),
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )
        results.append(result)
        if progress_cb is not None:
            progress_cb(
                {
                    "event": "attempt_finished",
                    "case": case_name,
                    "attempt": 1,
                    "completed_attempts": len(results),
                }
            )

    passed = sum(1 for item in results if item["status"] == "passed")
    total = len(results)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": str(suite.get("suite") or ""),
        "summary": {
            "total": total,
            "total_attempts": total,
            "passed": passed,
            "failed": total - passed,
            "blocked": 0,
            "success_rate_percent": round(passed * 100.0 / total, 2),
            "real_model_calls": 0,
        },
        "results": results,
        "sensitive_content_omitted": True,
    }
