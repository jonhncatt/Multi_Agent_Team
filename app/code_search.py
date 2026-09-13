"""Bounded code search in an owned process, including the no-ripgrep fallback.

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
import threading
import time
from typing import Any, Callable

SEARCH_TIMEOUT_SECONDS = 20.0
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}


def _child_creation_kwargs() -> dict[str, Any]:
    # The search worker has no console in the EXE build. Do not let Git/rg
    # allocate visible console windows when it starts its own children.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _process_lines(argv: list[str], *, cwd: Path, separator: bytes = b"\n"):
    # stderr goes to disk to avoid pipe deadlock without buffering unbounded
    # diagnostics in memory. All children inherit the worker's process group.
    import tempfile
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
    stem_needle = needle.rsplit(".", 1)[0] if "." in needle else needle
    contents = 0
    paths = 0
    skipped = 0

    def selected(path: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        return (not any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])
                and (not glob or fnmatch.fnmatch(relative, glob)
                     or (glob.startswith("**/") and fnmatch.fnmatch(relative, glob[3:]))))

    def path_match(path: Path) -> None:
        nonlocal paths
        if paths >= limit:
            return
        relative = path.relative_to(root).as_posix()
        hay = relative if request["case_sensitive"] else relative.lower()
        stem = path.stem if request["case_sensitive"] else path.stem.lower()
        matched = bool(pattern.search(relative)) if pattern else (needle in hay or needle in stem or bool(stem_needle and stem_needle in stem))
        if matched:
            paths += 1
            _emit({"match": {"resolved_path": str(path), "line": 0, "text": "[filename match]", "match_type": "path"}})

    if rg:
        argv = [rg, "--json", "--threads", "2", "--max-count", str(limit), "--max-filesize", str(MAX_FILE_BYTES)]
        argv += ["-s" if request["case_sensitive"] else "-i"]
        if not pattern:
            argv += ["-F"]
        for directory in sorted(SKIP_DIRS):
            argv += ["-g", f"!**/{directory}/**"]
        if glob:
            argv += ["-g", glob]
        # -e prevents a query beginning with '-' from becoming an option.
        lines = _process_lines([*argv, "-e", query, "--", "."], cwd=root)
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
                _emit({"match": {"resolved_path": str(root / name), "line": data["line_number"], "text": text.strip()[:MAX_LINE_BYTES]}})
                if contents >= limit:
                    break
        finally:
            lines.close()
        files = _process_lines([rg, "--files", "-0", "--", "."], cwd=root, separator=b"\0")
        try:
            for raw in files:
                path = root / os.fsdecode(raw)
                if selected(path):
                    path_match(path)
                if paths >= limit:
                    break
        finally:
            files.close()
        # rg silently omits files over --max-filesize; never claim exhaustive
        # coverage of all bytes when a size cap is in effect.
        _emit({"done": True, "limited": contents >= limit or paths >= limit,
               "skipped_files": skipped, "size_limit_applied": True})
        return

    def candidates():
        # In Git worktrees use Git's ignore rules without requiring ripgrep.
        git = shutil.which("git")
        if git:
            check = subprocess.run([git, "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_child_creation_kwargs())
            if check.returncode == 0 and check.stdout.strip() == b"true":
                yield from (root / os.fsdecode(raw) for raw in _process_lines(
                    [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
                    cwd=root, separator=b"\0"))
                return
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            for name in names:
                yield Path(directory) / name

    for path in candidates():
        if not selected(path) or path.is_symlink():
            continue
        path_match(path)
        if contents >= limit:
            if paths >= limit:
                break
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped += 1
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
                        _emit({"match": {"resolved_path": str(path), "line": line_number, "text": line.strip()}})
                        if contents >= limit:
                            break
        except OSError:
            skipped += 1
    _emit({"done": True, "limited": contents >= limit or paths >= limit, "skipped_files": skipped})


def run_search(request: dict[str, Any], *, cancelled: Callable[[], bool],
               creation_kwargs: dict[str, Any], terminate: Callable[..., None]) -> dict[str, Any]:
    started = time.monotonic()
    if cancelled():
        return {"matches": [], "stop_reason": "cancelled"}
    events: queue.Queue[Any] = queue.Queue(maxsize=256)
    reader_stop = threading.Event()
    proc = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve())],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            **creation_kwargs)
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
        finally:
            publish(None)
    reader = threading.Thread(target=read, name="vp-code-search-output", daemon=True)
    result: dict[str, Any] = {"matches": [], "stop_reason": "worker_failed"}
    try:
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
                break
            if "match" in event:
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
        if not proc.stdin.closed:
            proc.stdin.close()
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


if __name__ == "__main__":
    try:
        _worker(json.load(sys.stdin))
    except Exception as exc:
        _emit({"error": str(exc)})
