from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent_evals import EvalConfigurationError
from app.eval_jobs import EvalJobError, EvalJobManager


def _suite(path: str | Path) -> dict:
    return {
        "suite": "ui_eval_suite",
        "_cases_path": str(path),
        "cases": [
            {"name": "subagent_case"},
            {"name": "steer_case"},
        ],
    }


def _manager(tmp_path: Path, *, runner=None) -> EvalJobManager:
    (tmp_path / "evals").mkdir(parents=True, exist_ok=True)
    suite_path = tmp_path / "evals" / "cases.json"
    suite_path.write_text("{}", encoding="utf-8")

    def load_suite(path: str | Path) -> dict:
        return _suite(path)

    def default_runner(suite, *, repeat, name_filter, progress_cb, **_kwargs):
        selected = [
            item["name"]
            for item in suite["cases"]
            if not name_filter or name_filter.lower() in item["name"].lower()
        ]
        results = []
        completed = 0
        for case_name in selected:
            for attempt in range(1, repeat + 1):
                progress_cb({"event": "attempt_started", "case": case_name, "attempt": attempt})
                completed += 1
                results.append({"case": case_name, "attempt": attempt, "status": "passed"})
                progress_cb(
                    {
                        "event": "attempt_finished",
                        "case": case_name,
                        "attempt": attempt,
                        "completed_attempts": completed,
                    }
                )
        return {
            "summary": {
                "total_attempts": len(results),
                "passed": len(results),
                "failed": 0,
                "blocked": 0,
            },
            "results": results,
        }

    return EvalJobManager(
        repo_root=tmp_path,
        load_suite_fn=load_suite,
        run_suite_fn=runner or default_runner,
    )


def test_eval_job_runs_in_background_and_persists_report(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    job = manager.submit(
        {
            "cases": "evals/cases.json",
            "name": "subagent",
            "repeat": 3,
            "provider": "openai_compatible",
            "model": "gpt-test",
            "live": True,
        }
    )

    assert job["status"] == "queued"
    assert job["total_attempts"] == 3
    assert manager.wait_for_idle(timeout=3)
    completed = manager.get(job["id"])
    assert completed is not None
    assert completed["status"] == "passed"
    assert completed["completed_attempts"] == 3
    report_path = tmp_path / completed["report_path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 3
    assert manager.catalog()[0]["cases"] == ["subagent_case", "steer_case"]


def test_eval_job_rejects_non_live_and_paths_outside_eval_roots(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(EvalJobError, match="explicitly enabled"):
        manager.submit({"cases": "evals/cases.json", "live": False})
    with pytest.raises(EvalJobError, match="under evals"):
        manager.submit({"cases": "../cases.json", "live": True})
    with pytest.raises(EvalJobError, match="under artifacts/evals"):
        manager.submit(
            {
                "cases": "evals/cases.json",
                "live": True,
                "output": "outside.json",
            }
        )


def test_eval_job_marks_active_record_interrupted_after_restart(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    job_path = manager.jobs_root / "eval-old.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "eval-old",
                "status": "running",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    restored = _manager(tmp_path)

    job = restored.get("eval-old")
    assert job is not None
    assert job["status"] == "interrupted"
    assert job["error_kind"] == "app_restarted"


def test_recovery_eval_is_visible_and_runs_without_live_provider_calls(tmp_path: Path) -> None:
    evals_root = tmp_path / "evals"
    tests_root = tmp_path / "tests"
    evals_root.mkdir(parents=True)
    tests_root.mkdir(parents=True)
    (tests_root / "test_runtime.py").write_text(
        "def test_recovery_strategy():\n    assert True\n",
        encoding="utf-8",
    )
    (evals_root / "tool_failure_recovery_cases.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "tool_failure_recovery",
                "cases": [
                    {
                        "name": "replan_allows_new_strategy",
                        "test_node": "tests/test_runtime.py::test_recovery_strategy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def reject_live_suite(_path: str | Path) -> dict:
        raise EvalConfigurationError("not a live suite")

    def recovery_runner(suite, *, repo_root, name_filter, progress_cb):
        assert repo_root == tmp_path.resolve()
        assert name_filter == "replan"
        progress_cb({"event": "attempt_started", "case": suite["cases"][0]["name"], "attempt": 1})
        progress_cb(
            {
                "event": "attempt_finished",
                "case": suite["cases"][0]["name"],
                "attempt": 1,
                "completed_attempts": 1,
            }
        )
        return {
            "summary": {
                "total_attempts": 1,
                "passed": 1,
                "failed": 0,
                "blocked": 0,
                "real_model_calls": 0,
            },
            "results": [{"name": suite["cases"][0]["name"], "status": "passed"}],
        }

    manager = EvalJobManager(
        repo_root=tmp_path,
        load_suite_fn=reject_live_suite,
        run_recovery_suite_fn=recovery_runner,
    )

    catalog = manager.catalog()
    assert catalog == [
        {
            "path": "evals/tool_failure_recovery_cases.json",
            "suite": "tool_failure_recovery",
            "cases": ["replan_allows_new_strategy"],
            "case_count": 1,
            "run_mode": "deterministic_recovery",
            "requires_live": False,
            "supports_repeat": False,
            "supports_provider": False,
            "supports_model": False,
            "supports_workspaces": False,
        }
    ]

    job = manager.submit(
        {
            "cases": "evals/tool_failure_recovery_cases.json",
            "name": "replan",
            "repeat": 9,
            "provider": "must-not-be-used",
            "model": "must-not-be-used",
            "live": False,
            "keep_workspaces": True,
        }
    )
    assert job["run_mode"] == "deterministic_recovery"
    assert job["live"] is False
    assert job["repeat"] == 1
    assert job["provider"] == ""
    assert job["model"] == ""
    assert job["keep_workspaces"] is False
    assert manager.wait_for_idle(timeout=3)
    completed = manager.get(job["id"])
    assert completed is not None
    assert completed["status"] == "passed"
    assert completed["summary"]["real_model_calls"] == 0
