"""Stdlib-only harness; loads ALL app code from the requested checkout.

Persistent processes are benchmark harnesses only, never application workers.
IPC/import/profiler-install times are excluded from tool wall time. Instrumented
samples are separate from headline samples; overlapping phases are not additive.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch


class Profiler:
    def __init__(self):
        self.values = {}
        self.calls = {}
        self.commands = []
        self.local = threading.local()
        self.lock = threading.Lock()
        self.engine_start = self.engine_end = self.cleanup_start = self.eof = None

    def add(self, key, elapsed):
        with self.lock:
            self.values[key] = self.values.get(key, 0) + elapsed * 1000
            self.calls[key] = self.calls.get(key, 0) + 1

    def timed(self, key, function):
        def run(*args, **kwargs):
            depths = getattr(self.local, "depths", {})
            self.local.depths = depths
            depth = depths.get(key, 0)
            depths[key] = depth + 1
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                depths[key] -= 1
                if not depth:
                    self.add(key, time.perf_counter() - started)
        return run

    @contextmanager
    def install(self, executor, local_tools, code, filenames):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for owner, name, key in (
                (executor, "_resolve_path", "path_processing_ms"),
                (local_tools, "_display_model_path", "path_processing_ms"),
                (local_tools, "_display_resolved_search_path", "path_processing_ms"),
                (local_tools, "_path_payload", "path_processing_ms"),
                (code, "runtime_search_scope", "runtime_scope_ms"),
                (filenames, "fuzzy_score", "fuzzy_score_ms"),
                (filenames.heapq, "nsmallest", "matcher_total_ms"),
            ):
                if hasattr(owner, name):
                    stack.enter_context(patch.object(owner, name, self.timed(key, getattr(owner, name))))
            original_loads = code.json.loads
            def loads(*args, **kwargs):
                if threading.current_thread().name == "vp-code-search-output":
                    return self.timed("json_parse_ms", original_loads)(*args, **kwargs)
                return original_loads(*args, **kwargs)
            stack.enter_context(patch.object(code.json, "loads", loads))
            original_popen = code.subprocess.Popen
            profiler = self
            class Output:
                def __init__(self, stream):
                    self.stream = stream
                def __getattr__(self, key):
                    return getattr(self.stream, key)
                def __iter__(self):
                    return self
                def __next__(self):
                    started = time.perf_counter()
                    try:
                        return next(self.stream)
                    except StopIteration:
                        profiler.eof = time.perf_counter()
                        raise
                    finally:
                        profiler.add("rg_output_read_wait_ms", time.perf_counter() - started)
            def popen(*args, **kwargs):
                self.commands.append({"argv": [str(arg) for arg in args[0]], "cwd": str(kwargs.get("cwd", ""))})
                proc = self.timed("process_start_ms", original_popen)(*args, **kwargs)
                if proc.stdout is not None:
                    proc.stdout = Output(proc.stdout)
                return proc
            stack.enter_context(patch.object(code.subprocess, "Popen", popen))
            original_run = code.run_search
            def engine(*args, **kwargs):
                terminate = kwargs["terminate"]
                def cleanup(*args, **kwargs):
                    if self.cleanup_start is None:
                        self.cleanup_start = time.perf_counter()
                    return terminate(*args, **kwargs)
                kwargs["terminate"] = cleanup
                self.engine_start = time.perf_counter()
                try:
                    return original_run(*args, **kwargs)
                finally:
                    self.engine_end = time.perf_counter()
                    self.add("search_engine_total_ms", self.engine_end - self.engine_start)
                    if self.cleanup_start is not None:
                        self.add("process_cleanup_ms", self.engine_end - self.cleanup_start)
                        if self.eof is not None:
                            self.add("eof_to_cleanup_ms", max(0, self.cleanup_start - self.eof))
            stack.enter_context(patch.object(code, "run_search", engine))
            yield


def main():
    version, config_root = map(Path, sys.argv[1:3])
    sys.path.insert(0, str(version))
    from app.config import load_config
    from app import local_tools, code_search, filename_search
    config_root.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config.workspace_root = config_root
    config.projects_registry_path = config_root / "projects.json"
    config.sessions_dir = config_root / "sessions"
    config.uploads_dir = config_root / "uploads"
    config.token_stats_path = config_root / "token_stats.json"
    config.sessions_dir.mkdir(exist_ok=True)
    config.uploads_dir.mkdir(exist_ok=True)
    config.allowed_roots = [config_root]
    config.permission_profile = "auto"
    executor = local_tools.LocalToolExecutor(config)
    walks = {}
    original_walk = filename_search._walk
    def walk(corpus):
        started = time.perf_counter()
        try:
            return original_walk(corpus)
        finally:
            with corpus.changed:
                walks[str(corpus.root)] = (time.perf_counter() - started) * 1000
                corpus.changed.notify_all()
    filename_search._walk = walk

    def emit(value):
        print(json.dumps(value, ensure_ascii=True), flush=True)

    emit({"ready": True})
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("action") == "identity":
                sources = {}
                for name, module in list(sys.modules.items()):
                    file = getattr(module, "__file__", None)
                    if (name == "app" or name.startswith("app.")) and file and file.endswith(".py"):
                        path = Path(file).resolve()
                        relative = path.relative_to(version.resolve())  # Fail on mixed-version imports.
                        sources[str(relative).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
                emit({"app_sources_sha256": sources, "python": sys.version,
                      "pathspec": importlib.import_module("pathspec").__version__,
                      "shared_current_app_helpers": False})
                continue
            root = Path(request["root"]).resolve()
            executor.set_runtime_context(project_root=str(root), cwd=str(root), runtime_boundary={
                "allowed_roots": [str(root)], "permission_profile": "auto"})
            if request.get("action") == "wait_walk":
                corpus = executor._filename_search._corpora.get(root)
                if corpus is None:
                    raise RuntimeError("No initial filename query for this root")
                with corpus.changed:
                    corpus.changed.wait_for(lambda: corpus.finished and str(root) in walks, timeout=25)
                emit({"walk_complete": corpus.complete, "scanned_file_count": len(corpus.paths),
                      "stop_reason": corpus.reason, "walk_ms": walks.get(str(root))})
                continue
            profiler = Profiler()
            tool = getattr(executor, request["tool"])
            arguments = dict(request["arguments"])
            @contextmanager
            def no_profile():
                yield
            context = profiler.install(executor, local_tools, code_search, filename_search) if request.get("profile") else no_profile()
            with context:
                started = time.perf_counter()
                result = tool(**arguments)
                ended = time.perf_counter()
            if profiler.engine_start is not None:
                profiler.add("public_before_engine_ms", profiler.engine_start - started)
                profiler.add("public_after_engine_ms", ended - profiler.engine_end)
            emit({"wall_ms": (ended - started) * 1000, "result": result,
                  "phases_ms": profiler.values, "phase_calls": profiler.calls, "commands": profiler.commands})
        except Exception as exc:
            emit({"harness_error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
