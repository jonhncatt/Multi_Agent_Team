from __future__ import annotations

import shutil
import subprocess
import threading
import time

import pytest

from app import code_search
from app.local_tools import LocalToolExecutor
from tests.test_local_tools_public_surface import _config


def _search(tmp_path, monkeypatch, *, rg=False):
    tools = LocalToolExecutor(_config(tmp_path))
    tools.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    if not rg:
        monkeypatch.setattr("app.local_tools.shutil.which", lambda name: None)
    return tools


def test_python_search_skips_dependencies_and_reads_large_text_incrementally(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("needle")
    (tmp_path / "source.py").write_text("line\n" * 250_000 + "needle\n")
    result = tools.search_codebase("needle")
    assert result["parser_mode"] == "python_fallback"
    assert [item["path"] for item in result["matches"]] == ["source.py"]
    assert result["matches"][0]["line"] == 250_001
    explicit = tools.search_codebase("needle", root="node_modules")
    assert explicit["match_count"] == 1


def test_python_search_uses_git_ignore_rules(tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    tools = _search(tmp_path, monkeypatch)
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("needle")
    (tmp_path / "source.py").write_text("needle")
    result = tools.search_codebase("needle")
    assert [item["path"] for item in result["matches"]] == ["source.py"]


def test_stopping_python_search_interrupts_a_stuck_regex(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch)
    (tmp_path / "source.txt").write_text("x" * 100 + "!")
    cancelled = threading.Event()
    tools.set_runtime_context(project_root=str(tmp_path), cancel_event=cancelled)
    workers = []
    original_popen = code_search.subprocess.Popen
    def track_worker(*args, **kwargs):
        worker = original_popen(*args, **kwargs)
        workers.append(worker)
        return worker
    monkeypatch.setattr(code_search.subprocess, "Popen", track_worker)
    timer = threading.Timer(0.4, cancelled.set)
    timer.start()
    start = time.monotonic()
    try:
        result = tools.search_codebase("(x+)+y", use_regex=True)
    finally:
        timer.cancel()
    assert time.monotonic() - start < 4
    assert result["error_kind"] == "cancelled"
    assert result["search_complete"] is False
    assert workers and workers[0].poll() is not None


def test_search_timeout_returns_partial_matches(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch)
    (tmp_path / "source.txt").write_text("xy\n" + "x" * 100 + "!")
    monkeypatch.setattr(code_search, "SEARCH_TIMEOUT_SECONDS", 0.6)
    result = tools.search_codebase("(x+)+y", use_regex=True)
    assert result["stop_reason"] == "timeout"
    assert result["matches"][0]["text"] == "xy"
    assert result["search_complete"] is False


def test_search_reports_skipped_oversize_files(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch)
    with (tmp_path / "large.txt").open("wb") as output:
        output.truncate(code_search.MAX_FILE_BYTES + 1)
    result = tools.search_codebase("needle")
    assert result["skipped_files"] == 1
    assert result["search_complete"] is False


def test_cancelled_search_does_not_start_worker(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch)
    cancelled = threading.Event()
    cancelled.set()
    tools.set_runtime_context(project_root=str(tmp_path), cancel_event=cancelled)
    def forbidden(*args, **kwargs):
        raise AssertionError("cancelled search must not start a process")
    monkeypatch.setattr(code_search.subprocess, "Popen", forbidden)
    assert tools.search_codebase("needle")["error_kind"] == "cancelled"


def test_ripgrep_worker_uses_auto_threads_for_content_and_file_search(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_process_lines(argv, *, cwd, separator=b"\n"):
        assert cwd == tmp_path
        _ = separator
        calls.append(list(argv))
        if False:
            yield b""

    monkeypatch.setattr(code_search, "_process_lines", fake_process_lines)

    code_search._worker(
        {
            "root": str(tmp_path),
            "query": "needle",
            "limit": 20,
            "file_glob": "**/*.py",
            "use_regex": False,
            "case_sensitive": False,
            "rg": "/fake/rg",
        }
    )

    assert len(calls) == 2
    assert all(call[call.index("--threads") + 1] == "0" for call in calls)
    assert ["-g", "**/*.py"] == calls[1][calls[1].index("**/*.py") - 1 : calls[1].index("**/*.py") + 1]


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is not installed")
def test_ripgrep_search_uses_json_fast_path_and_auto_threads(tmp_path, monkeypatch):
    tools = _search(tmp_path, monkeypatch, rg=True)
    (tmp_path / "source.py").write_text("needle\n", encoding="utf-8")

    result = tools.search_codebase("needle")

    assert code_search.RG_AUTO_THREADS == "0"
    assert result["ok"] is True
    assert result["parser_mode"] == "json"
    assert result["matches"][0]["path"] == "source.py"
