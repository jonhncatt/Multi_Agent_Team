"""Bounded content search: direct rg, or an isolated no-ripgrep Python worker.

The worker uses only the standard library so starting a search does not import
the Agent runtime. The parent can stop even a blocked file read or regex.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

SEARCH_TIMEOUT_SECONDS = 20.0
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_MATCH_TEXT_CHARS = 2000
RG_AUTO_THREADS = "0"
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}
RUNTIME_SEARCH_EXCLUDED_PATHS = tuple(f"app/data/{name}" for name in (
    "tool_results", "turn_traces", "sessions", "session_backups", "runs", "session_meta",
    "tasks", "uploads", "browser_artifacts", "browser_profile", "desktop_browser_profile",
    "desktop_webview2_profile", "document_cache", "web_cache", "evolution", "shadow_logs",
    "subagents", "runtime", "apps",
))


def runtime_search_scope(root: Path) -> tuple[list[str], bool]:
    """VA-only relative exclusions, never generic 'data' basename exclusions.

    Explicit roots inside a runtime subtree opt in to its ignored files.
    Markers are filesystem checks only, usable by the isolated stdlib worker.
    """
    for project in (root, *root.parents):
        if not ((project / "app/local_tools.py").is_file()
                and (project / "app/validation_assistant_runtime.py").is_file()
                and (project / "project_profiles/builtin/validation-assistant/AGENTS.md").is_file()):
            continue
        paths = [project / path for path in RUNTIME_SEARCH_EXCLUDED_PATHS]
        if any(root == path or path in root.parents for path in paths):
            return [], True
        return [path.relative_to(root).as_posix() for path in paths if root in path.parents], False
    return [], False


def _child_creation_kwargs() -> dict[str, Any]:
    # The search worker has no console in the EXE build. Do not let Git/rg
    # allocate visible console windows when it starts its own children.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _match_payload(path: Path, line: int, text: str) -> dict[str, Any]:
    text = text.strip()
    return {"resolved_path": str(path), "line": line, "text": text[:MAX_MATCH_TEXT_CHARS],
            "text_truncated": len(text) > MAX_MATCH_TEXT_CHARS, "original_text_chars": len(text)}


def _process_lines(argv: list[str], *, cwd: Path, separator: bytes = b"\n"):
    # stderr goes to disk to avoid pipe deadlock without buffering unbounded
    # diagnostics in memory. All children inherit the worker's process group.
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=errors, **_child_creation_kwargs())
        try:
            assert proc.stdout is not None
            pending = b""
            while chunk := proc.stdout.read1(8192):
                pending += chunk
                while separator in pending:
                    line, pending = pending.split(separator, 1)
                    yield line
            if pending:
                yield pending
            if proc.wait() not in (0, 1):
                errors.seek(0)
                raise RuntimeError(errors.read(4096).decode("utf-8", "replace"))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()


def _worker(request: dict[str, Any]) -> None:
    root = Path(request["root"])
    query = request["query"]
    limit = request["limit"] + 1
    rg = request.get("rg")
    glob = request["file_glob"]
    flags = 0 if request["case_sensitive"] else re.IGNORECASE
    pattern = re.compile(query, flags) if request["use_regex"] else None
    needle = query if request["case_sensitive"] else query.lower()
    contents = 0
    skipped = 0
    size_skipped = 0
    excluded, explicit_runtime = runtime_search_scope(root)

    def selected(path: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        return (not any(relative == prefix or relative.startswith(prefix + "/") for prefix in excluded)
                and not any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])
                and (not glob or fnmatch.fnmatch(relative, glob)
                     or (glob.startswith("**/") and fnmatch.fnmatch(relative, glob[3:]))))

    if rg:
        lines = _process_lines(_rg_argv(request), cwd=root)
        try:
            for raw in lines:
                event = json.loads(raw)
                if event.get("type") != "match":
                    continue
                data = event["data"]
                name = data.get("path", {}).get("text")
                text = data.get("lines", {}).get("text")
                if name is None or text is None:
                    skipped += 1
                    continue
                contents += 1
                _emit({"match": _match_payload(root / name, data["line_number"], text)})
                if contents >= limit:
                    break
        finally:
            lines.close()
        # rg silently omits files over --max-filesize; never claim exhaustive
        # coverage of all bytes when a size cap is in effect.
        _emit({"done": True, "limited": contents >= limit,
               "skipped_files": skipped, "size_limit_applied": True})
        return

    def candidates():
        # In Git worktrees use Git's ignore rules without requiring ripgrep.
        git = shutil.which("git")
        if git and not explicit_runtime:
            check = subprocess.run([git, "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_child_creation_kwargs())
            if check.returncode == 0 and check.stdout.strip() == b"true":
                yield from (root / os.fsdecode(raw) for raw in _process_lines(
                    [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
                    cwd=root, separator=b"\0"))
                return
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not any(
                (Path(directory) / name).relative_to(root).as_posix() == prefix for prefix in excluded)]
            for name in names:
                yield Path(directory) / name

    for path in candidates():
        if not selected(path) or path.is_symlink():
            continue
        if contents >= limit:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped += 1
                size_skipped += 1
                continue
            with path.open("rb") as source:
                if b"\0" in source.read(8192):
                    continue
                source.seek(0)
                line_number = 0
                while raw := source.readline(MAX_LINE_BYTES + 1):
                    line_number += 1
                    if len(raw) > MAX_LINE_BYTES:
                        skipped += 1
                        break
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    hay = line if request["case_sensitive"] else line.lower()
                    if (bool(pattern.search(line)) if pattern else needle in hay):
                        contents += 1
                        _emit({"match": _match_payload(path, line_number, line)})
                        if contents >= limit:
                            break
        except OSError:
            skipped += 1
    _emit({"done": True, "limited": contents >= limit, "skipped_files": skipped,
           "runtime_excluded_paths": excluded,
           "size_limit_applied": bool(size_skipped), "size_skipped_files": size_skipped})


def _rg_argv(request: dict[str, Any]) -> list[str]:
    argv = [request["rg"], "--no-config", "--json", "--threads", RG_AUTO_THREADS,
            "--max-count", str(request["limit"] + 1), "--max-filesize", str(MAX_FILE_BYTES),
            "-s" if request["case_sensitive"] else "-i"]
    if not request["use_regex"]:
        argv.append("-F")
    for directory in sorted(SKIP_DIRS):
        argv += ["-g", f"!**/{directory}/**"]
    if request["file_glob"]:
        argv += ["-g", request["file_glob"]]
    scope = request.get("runtime_scope")
    excluded, explicit_runtime = scope if scope is not None else runtime_search_scope(Path(request["root"]))
    if explicit_runtime:
        argv += ["--hidden", "--no-ignore"]
    # Last globs win: a broad user file_glob must not re-include historical evidence.
    for prefix in excluded:
        argv += ["-g", f"!/{prefix}/**"]
    return [*argv, "-e", request["query"], "--", "."]


def run_search(request: dict[str, Any], *, cancelled: Callable[[], bool],
               creation_kwargs: dict[str, Any], terminate: Callable[..., None]) -> dict[str, Any]:
    started = time.monotonic()
    if cancelled():
        return {"matches": [], "stop_reason": "cancelled"}
    events: queue.Queue[Any] = queue.Queue(maxsize=256)
    reader_stop = threading.Event()
    direct = bool(request.get("rg"))
    if direct:
        request = {**request, "runtime_scope": runtime_search_scope(Path(request["root"]))}
    errors = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(
            _rg_argv(request) if direct else [sys.executable, "-u", str(Path(__file__).resolve())],
            cwd=request["root"] if direct else None,
            stdin=subprocess.DEVNULL if direct else subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=errors, **creation_kwargs)
    except BaseException:
        errors.close()
        raise
    def publish(event: Any) -> None:
        while not reader_stop.is_set():
            try:
                events.put(event, timeout=0.05)
                return
            except queue.Full:
                pass
    def read() -> None:
        try:
            for line in proc.stdout:
                if reader_stop.is_set():
                    break
                publish(json.loads(line))
        except (ValueError, OSError) as exc:
            publish({"error": str(exc)})
        finally:
            publish(None)
    reader = threading.Thread(target=read, name="va-code-search-output", daemon=True)
    result: dict[str, Any] = {"matches": [], "stop_reason": "worker_failed"}
    try:
        if not direct:
            proc.stdin.write(json.dumps(request).encode("utf-8"))
            proc.stdin.close()
        reader.start()
        while True:
            if cancelled():
                result["stop_reason"] = "cancelled"
                break
            if time.monotonic() - started >= SEARCH_TIMEOUT_SECONDS:
                result["stop_reason"] = "timeout"
                break
            try:
                event = events.get(timeout=0.05)
            except queue.Empty:
                continue
            if event is None:
                if direct:
                    code = proc.poll()
                    if code is None:
                        # EOF can precede process exit. Stay in the cancellation
                        # loop instead of blocking the parent on wait().
                        try:
                            code = proc.wait(timeout=0.05)
                        except subprocess.TimeoutExpired:
                            events.put(None)
                            continue
                    if code in (0, 1):
                        result["stop_reason"] = ""
                    else:
                        errors.seek(0)
                        result["error"] = errors.read(4096).decode("utf-8", "replace")
                break
            if direct and event.get("type") == "match":
                data = event["data"]
                name = data.get("path", {}).get("text")
                text = data.get("lines", {}).get("text")
                if name is None or text is None:
                    result["skipped_files"] = result.get("skipped_files", 0) + 1
                    continue
                result["matches"].append(_match_payload(Path(request["root"]) / name, data["line_number"], text))
                if len(result["matches"]) > request["limit"]:
                    result["stop_reason"] = "limit"
                    break
            elif "match" in event:
                result["matches"].append(event["match"])
            elif event.get("done"):
                result.update(event)
                result["stop_reason"] = "limit" if event["limited"] else ""
                break
            elif "error" in event:
                result.update(event)
                break
    finally:
        reader_stop.set()
        terminate(proc, force=True)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        if reader.ident is not None:
            reader.join(timeout=1)
        proc.stdout.close()
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        errors.close()
    if direct:
        result["size_limit_applied"] = True
        result["runtime_excluded_paths"] = request["runtime_scope"][0]
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


if __name__ == "__main__":
    try:
        _worker(json.load(sys.stdin))
    except Exception as exc:
        _emit({"error": str(exc)})
