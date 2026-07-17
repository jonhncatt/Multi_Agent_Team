from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import threading
from typing import Any, Callable
from uuid import uuid4

from app.agent_evals import (
    EvalConfigurationError,
    load_eval_suite,
    run_eval_suite,
    safe_report_path,
)


TERMINAL_JOB_STATUSES = {"passed", "failed", "blocked", "interrupted"}
ACTIVE_JOB_STATUSES = {"queued", "running"}


class EvalJobError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


class EvalJobManager:
    """Single-lane, persisted background runner for live Agent evals."""

    def __init__(
        self,
        *,
        repo_root: Path,
        run_suite_fn: Callable[..., dict[str, Any]] = run_eval_suite,
        load_suite_fn: Callable[[str | Path], dict[str, Any]] = load_eval_suite,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve()
        self.evals_root = (self.repo_root / "evals").resolve()
        self.artifacts_root = (self.repo_root / "artifacts" / "evals").resolve()
        self.jobs_root = (self.artifacts_root / "jobs").resolve()
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._run_suite_fn = run_suite_fn
        self._load_suite_fn = load_suite_fn
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._load_existing_jobs()

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except Exception:
            return path.name

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc or exc.__class__.__name__).strip() or exc.__class__.__name__
        for sensitive in (str(self.repo_root), str(Path.home())):
            if sensitive:
                text = text.replace(sensitive, "<local-path>")
        text = re.sub(r"https?://\S+", "<url>", text)
        return text[:600]

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.json"

    def _persist_locked(self, job: dict[str, Any]) -> None:
        path = self._job_path(str(job.get("id") or ""))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _load_existing_jobs(self) -> None:
        for path in sorted(self.jobs_root.glob("eval-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                continue
            if str(payload.get("status") or "") in ACTIVE_JOB_STATUSES:
                payload["status"] = "interrupted"
                payload["finished_at"] = _utc_now()
                payload["error_kind"] = "app_restarted"
                payload["error"] = "The application stopped before this Eval run completed."
                self._persist_locked(payload)
            self._jobs[str(payload["id"])] = payload

    def catalog(self) -> list[dict[str, Any]]:
        suites: list[dict[str, Any]] = []
        for path in sorted(self.evals_root.glob("*.json")):
            try:
                suite = self._load_suite_fn(path)
            except Exception:
                continue
            cases = [
                str(item.get("name") or "").strip()
                for item in list(suite.get("cases") or [])
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            suites.append(
                {
                    "path": self._relative(path),
                    "suite": str(suite.get("suite") or path.stem),
                    "cases": cases,
                    "case_count": len(cases),
                }
            )
        return suites

    def _resolve_suite(self, raw: str) -> tuple[Path, dict[str, Any]]:
        candidate = Path(str(raw or "evals/agent_workflow_cases.json").strip())
        if not candidate.is_absolute():
            candidate = self.repo_root / candidate
        resolved = candidate.expanduser().resolve()
        if not _is_within(resolved, self.evals_root) or resolved.suffix.lower() != ".json":
            raise EvalJobError("Eval suite must be a JSON file under evals/.")
        try:
            suite = self._load_suite_fn(resolved)
        except EvalConfigurationError as exc:
            raise EvalJobError(self._safe_error(exc)) from exc
        return resolved, suite

    def _resolve_output(self, raw: str, *, job_id: str) -> Path:
        text = str(raw or "").strip()
        candidate = Path(text) if text else self.artifacts_root / f"{job_id}.json"
        if not candidate.is_absolute():
            candidate = self.repo_root / candidate
        resolved = candidate.expanduser().resolve()
        if not _is_within(resolved, self.artifacts_root) or resolved.suffix.lower() != ".json":
            raise EvalJobError("Eval report must be a JSON file under artifacts/evals/.")
        return resolved

    @staticmethod
    def _selected_cases(suite: dict[str, Any], name_filter: str) -> list[str]:
        needle = str(name_filter or "").strip().lower()
        return [
            str(item.get("name") or "").strip()
            for item in list(suite.get("cases") or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and (not needle or needle in str(item.get("name") or "").lower())
        ]

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("live")):
            raise EvalJobError("Live Eval must be explicitly enabled before starting provider calls.")
        suite_path, suite = self._resolve_suite(str(payload.get("cases") or ""))
        name_filter = str(payload.get("name") or "").strip()
        selected_cases = self._selected_cases(suite, name_filter)
        if not selected_cases:
            raise EvalJobError("No Eval cases matched the selected case filter.")
        repeat = max(1, min(10, int(payload.get("repeat") or 1)))
        provider = str(payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if len(provider) > 120 or len(model) > 200:
            raise EvalJobError("Provider or model value is too long.")
        job_id = f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        output_path = self._resolve_output(str(payload.get("output") or ""), job_id=job_id)
        now = _utc_now()
        job = {
            "schema_version": 1,
            "id": job_id,
            "status": "queued",
            "suite": str(suite.get("suite") or suite_path.stem),
            "cases_path": self._relative(suite_path),
            "name_filter": name_filter,
            "selected_cases": selected_cases,
            "repeat": repeat,
            "provider": provider,
            "model": model,
            "live": True,
            "keep_workspaces": bool(payload.get("keep_workspaces")),
            "report_path": self._relative(output_path),
            "created_at": now,
            "started_at": "",
            "finished_at": "",
            "current_case": "",
            "current_attempt": 0,
            "completed_attempts": 0,
            "total_attempts": len(selected_cases) * repeat,
            "summary": {},
            "error_kind": "",
            "error": "",
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist_locked(job)
            self._queue.put(job_id)
            self._ensure_worker_locked()
            return dict(job)

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="vp-eval-worker", daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise EvalJobError("Eval job was not found.")
            job.update(changes)
            self._persist_locked(job)
            return dict(job)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = dict(self._jobs.get(job_id) or {})
        if not job:
            return
        self._update(job_id, status="running", started_at=_utc_now())
        try:
            suite_path, suite = self._resolve_suite(str(job.get("cases_path") or ""))

            def progress(event: dict[str, Any]) -> None:
                event_type = str(event.get("event") or "")
                if event_type == "attempt_started":
                    self._update(
                        job_id,
                        current_case=str(event.get("case") or ""),
                        current_attempt=int(event.get("attempt") or 0),
                    )
                elif event_type == "attempt_finished":
                    self._update(
                        job_id,
                        current_case=str(event.get("case") or ""),
                        current_attempt=int(event.get("attempt") or 0),
                        completed_attempts=int(event.get("completed_attempts") or 0),
                    )

            report = self._run_suite_fn(
                suite,
                repeat=int(job.get("repeat") or 1),
                provider=str(job.get("provider") or ""),
                model=str(job.get("model") or ""),
                name_filter=str(job.get("name_filter") or ""),
                keep_workspaces=bool(job.get("keep_workspaces")),
                progress_cb=progress,
            )
            output_path = self._resolve_output(str(job.get("report_path") or ""), job_id=job_id)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            report["report_path"] = safe_report_path(output_path, fallback_label="report")
            tmp = output_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(output_path)
            summary = dict(report.get("summary") or {})
            failed = int(summary.get("failed") or 0)
            blocked = int(summary.get("blocked") or 0)
            status = "failed" if failed else ("blocked" if blocked else "passed")
            self._update(
                job_id,
                status=status,
                finished_at=_utc_now(),
                completed_attempts=int(summary.get("total_attempts") or job.get("total_attempts") or 0),
                current_case="",
                current_attempt=0,
                summary=summary,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                finished_at=_utc_now(),
                error_kind=exc.__class__.__name__,
                error=self._safe_error(exc),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id or "").strip())
            return dict(job) if isinstance(job, dict) else None

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(item) for item in self._jobs.values()]
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return rows[: max(1, min(100, int(limit or 20)))]

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        """Test/helper hook; production UI observes persisted job state instead."""
        deadline = datetime.now().timestamp() + max(0.0, float(timeout))
        while datetime.now().timestamp() < deadline:
            with self._lock:
                if not any(str(item.get("status") or "") in ACTIVE_JOB_STATUSES for item in self._jobs.values()):
                    return True
            threading.Event().wait(0.01)
        return False
