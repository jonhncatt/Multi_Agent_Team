"""Compare all search paths on one frozen repository snapshot.

Run: python -m scripts.benchmark_local_search --baseline-ref df95e26d
Temporary snapshots/workers are generated outside the checkout and removed on exit.
This measures warm OS caches, not cold disk throughput or an LLM round trip.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tarfile
import tempfile
import time
from types import MethodType
from unittest.mock import patch

from app import code_search, local_tools
from app.config import load_config


def measure(call, count=20):
    times = []
    for _ in range(count):
        started = time.perf_counter()
        result = call()
        times.append((time.perf_counter() - started) * 1000)
        if not result["ok"]:
            raise RuntimeError(result)
    return {"first_ms": round(times[0], 3), "median_ms": round(statistics.median(times), 3),
            "total_ms": round(sum(times), 3), "calls": count, "match_count": result["match_count"],
            **{key: result[key] for key in ("cache_hit", "walk_complete", "scanned_file_count") if key in result}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default="df95e26d")
    args = parser.parse_args()
    if not shutil.which("rg"):
        parser.error("This three-way benchmark needs rg (the application does not).")
    repository = Path(__file__).resolve().parents[1]
    ref = subprocess.check_output(["git", "rev-parse", args.baseline_ref], cwd=repository, text=True).strip()
    source = subprocess.check_output(["git", "show", f"{ref}:app/local_tools.py"], cwd=repository, text=True)
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LocalToolExecutor")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "search_codebase")
    namespace = dict(vars(local_tools))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "baseline_search_codebase", "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="vp-search-benchmark-") as temp:
        work = Path(temp)
        root = work / "repository"
        root.mkdir()
        archive = subprocess.check_output(["git", "archive", ref], cwd=repository)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        # Both worker variants use the historical parent process controller.
        worker_source = (root / "app/code_search.py").read_text()
        variants = {}
        for name in ("old_content_plus_filename", "content_only_worker"):
            worker = work / f"{name}.py"
            worker.write_text(worker_source)
            spec = importlib.util.spec_from_file_location(name, worker)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if name == "content_only_worker":
                module.__file__ = code_search.__file__
            variants[name] = module.run_search
        variants["direct_rg"] = code_search.run_search
        config_root = work / "config"
        config_root.mkdir()
        config = load_config()
        config.workspace_root = config_root
        config.projects_registry_path = config_root / "projects.json"
        config.sessions_dir = config_root / "sessions"
        config.uploads_dir = config_root / "uploads"
        config.token_stats_path = config_root / "token_stats.json"
        config.sessions_dir.mkdir()
        config.uploads_dir.mkdir()
        config.allowed_roots = [root, config_root]
        executor = local_tools.LocalToolExecutor(config)
        executor.set_runtime_context(project_root=str(root), cwd=str(root))
        old_method = MethodType(namespace["search_codebase"], executor)
        report = {"platform": platform.platform(), "python": platform.python_version(), "snapshot": ref,
                  "rg": subprocess.check_output([shutil.which("rg"), "--version"], text=True).splitlines()[0],
                  "content": {}}
        # The requested query is absent in this snapshot; include a positive
        # query as well, so an empty scan isn't the sole performance evidence.
        for query in ("spawn_child_async", "class LocalToolExecutor"):
            report["content"][query] = {}
            for name, runner in variants.items():
                call = old_method if name == "old_content_plus_filename" else executor.search_codebase
                with patch.object(code_search, "run_search", runner):
                    report["content"][query][name] = measure(lambda: call(query))
        report["filenames"] = {}
        for label, query in (("first", "vprb"), ("second", "vprb"), ("v", "v"), ("vp", "vp"), ("vpr", "vpr"), ("vprb", "vprb")):
            report["filenames"][label] = measure(lambda: executor.search_files(query), count=1)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
