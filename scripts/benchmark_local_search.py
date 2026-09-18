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
import inspect
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


def utf8_output(argv, **kwargs):
    # Git source must decode strictly, independent of a cp932 Windows locale.
    return subprocess.check_output(argv, text=True, encoding="utf-8", errors="strict", **kwargs)


def extract_repository_archive(tar, root):
    if "filter" in inspect.signature(tar.extractall).parameters:
        tar.extractall(root, filter="data")
    else:
        # Only used for git archive of a trusted ref in this local repository,
        # never a downloaded/user-supplied tar. Python 3.11.2 lacks filters.
        tar.extractall(root)


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
    parser.add_argument("--compare-ref", help="Compare that revision's public search directly with current code (omit the intermediate worker).")
    args = parser.parse_args()
    if not shutil.which("rg"):
        parser.error("This three-way benchmark needs rg (the application does not).")
    repository = Path(__file__).resolve().parents[1]
    ref = utf8_output(["git", "rev-parse", args.compare_ref or args.baseline_ref], cwd=repository).strip()
    source = utf8_output(["git", "show", f"{ref}:app/local_tools.py"], cwd=repository)
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LocalToolExecutor")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "search_codebase")
    namespace = dict(vars(local_tools))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "baseline_search_codebase", "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="vp-search-benchmark-") as temp:
        work = Path(temp)
        root = work / "repository 日本語 with spaces"
        root.mkdir()
        archive = subprocess.check_output(["git", "archive", ref], cwd=repository)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            extract_repository_archive(tar, root)
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        # Both worker variants use the historical parent process controller.
        worker_source = (root / "app/code_search.py").read_text(encoding="utf-8")
        variants = {}
        baseline_name = "baseline" if args.compare_ref else "old_content_plus_filename"
        for name in ((baseline_name,) if args.compare_ref else (baseline_name, "content_only_worker")):
            worker = work / f"{name}.py"
            worker.write_text(worker_source, encoding="utf-8")
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
                  "rg": utf8_output([shutil.which("rg"), "--version"]).splitlines()[0],
                  "content": {}}
        # The requested query is absent in the original baseline; include a
        # positive query too. Later snapshots may contain both in source/docs.
        for query in ("spawn_child_async", "class LocalToolExecutor"):
            report["content"][query] = {}
            for name, runner in variants.items():
                call = old_method if name == baseline_name else executor.search_codebase
                with patch.object(code_search, "run_search", runner):
                    report["content"][query][name] = measure(lambda: call(query))
        report["filenames"] = {}
        for label, query in (("first", "vprb"), ("second", "vprb"), ("v", "v"), ("vp", "vp"), ("vpr", "vpr"), ("vprb", "vprb")):
            report["filenames"][label] = measure(lambda: executor.search_files(query), count=1)
        # Keep the report printable even on legacy Windows console encodings.
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
