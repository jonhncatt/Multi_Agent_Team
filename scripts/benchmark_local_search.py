"""Full-version, paired search benchmark. Never run alongside tests/builds.

python -m scripts.benchmark_local_search --compare-ref 549c6ff9
Raw samples, exact hits and separate instrumented profiles are saved as JSON.
Harness processes are for measurement only, not persistent runtime workers.
"""
from __future__ import annotations
import argparse
import hashlib
import inspect
import io
import json
import math
import os
from pathlib import Path
import platform
import queue
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

COMMON_RUNTIME_DIRS = (
    "tool_results", "turn_traces", "sessions", "session_backups", "runs", "session_meta", "tasks", "uploads",
    "browser_artifacts", "browser_profile", "desktop_browser_profile", "desktop_webview2_profile",
    "document_cache", "web_cache", "evolution", "shadow_logs", "subagents", "runtime", "apps",
)


def utf8_output(argv, **kwargs):
    return subprocess.check_output(argv, text=True, encoding="utf-8", errors="strict", **kwargs)


def extract_repository_archive(tar, root):
    if "filter" in inspect.signature(tar.extractall).parameters:
        tar.extractall(root, filter="data")
    else:
        # Trusted local git archive only; Python 3.11.2 has no filter API.
        tar.extractall(root)


def stats(values):
    ordered = sorted(values)
    return {"count": len(values), "median_ms": statistics.median(values),
            "p95_ms": ordered[max(0, math.ceil(len(values) * .95) - 1)],
            "total_ms": sum(values), "raw_ms": values}


def canonical_hits(result):
    return sorted((str(item.get("path", "")).replace("\\", "/"), item.get("line", 0),
                   item.get("text", ""), item.get("score")) for item in result.get("matches", []))


def hit_category(path):
    if path.startswith("app/data/"):
        return "runtime_data"
    if path.startswith("scripts/") and "benchmark" in path:
        return "benchmark_source"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("docs/"):
        return "documentation"
    return "application_or_other_source"


class Driver:
    def __init__(self, harness, version, config):
        self.errors = tempfile.TemporaryFile()
        self.proc = subprocess.Popen([sys.executable, "-u", str(harness), str(version), str(config)],
                                     cwd=version, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.errors, text=True, encoding="utf-8", errors="strict")
        self.events = queue.Queue()
        def read():
            try:
                for line in self.proc.stdout:
                    self.events.put(json.loads(line))
            except Exception as exc:
                self.events.put({"harness_error": str(exc)})
            finally:
                self.events.put({"harness_error": "benchmark driver exited"})
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            if not self.receive().get("ready"):
                raise RuntimeError("driver did not initialize")
        except BaseException:
            self.close()
            raise

    def receive(self):
        message = self.events.get(timeout=120)
        if "harness_error" in message:
            self.errors.seek(0)
            raise RuntimeError(message["harness_error"] + "\n" + self.errors.read(8192).decode("utf-8", "replace"))
        return message

    def call(self, request):
        self.proc.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.proc.stdin.flush()
        return self.receive()

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.reader.join(timeout=2)
        self.proc.stdout.close()
        self.errors.close()


def cohort(drivers, root, tool, arguments, *, warmup, rounds, rng, profiles):
    samples = {name: [] for name in drivers}
    warm = {name: [] for name in drivers}
    order_log = []
    for phase, count in (("warmup", warmup), ("measured", rounds), ("profile", profiles)):
        for index in range(count):
            order = list(drivers)
            rng.shuffle(order)
            order_log.append({"phase": phase, "round": index, "order": order})
            for name in order:
                sample = drivers[name].call({"tool": tool, "root": str(root), "arguments": arguments,
                                             "profile": phase == "profile"})
                sample.update(phase=phase, round=index)
                (warm if phase == "warmup" else samples)[name].append(sample)
    summaries, hits = {}, {}
    for name, records in samples.items():
        measured = [s for s in records if s["phase"] == "measured"]
        summaries[name] = stats([s["wall_ms"] for s in measured])
        summaries[name]["all_ok"] = all(s["result"].get("ok") and s["result"].get("stop_reason") not in {
            "timeout", "cancelled", "worker_failed", "walk_timeout", "matcher_failed"} for s in records)
        summaries[name]["walks_complete"] = all(s["result"].get("walk_complete", True) for s in records)
        hits[name] = [canonical_hits(s["result"]) for s in measured]
    all_hits = [items for version in hits.values() for items in version]
    equal = all(items == all_hits[0] for items in all_hits)
    return {"arguments": arguments, "summary": summaries, "order": order_log, "warmup": warm, "samples": samples,
            "exact_hits_equal_across_versions_and_rounds": equal,
            "hit_categories": {name: [{"path": p, "line": line, "category": hit_category(p)} for p, line, text, score in version[0]]
                               for name, version in hits.items()},
            "comparison_valid": equal and all(s["all_ok"] and s["walks_complete"] for s in summaries.values())}


def archive_ref(repository, ref, target):
    target.mkdir()
    data = subprocess.check_output(["git", "archive", ref], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        extract_repository_archive(archive, target)


def eligible_paths(command):
    """Untimed diagnostic of actual rg glob/ignore policies, not another tool scan."""
    argv = command["argv"]
    if "--json" not in argv:
        return {"available": False, "reason": "not a direct-rg invocation"}
    flags = []
    for index, arg in enumerate(argv):
        if arg in {"--no-config", "--hidden", "--no-ignore"}:
            flags.append(arg)
        elif arg == "-g":
            flags.extend((arg, argv[index + 1]))
    proc = subprocess.run([argv[0], "--files", "-0", *flags, "--", "."], cwd=command["cwd"], capture_output=True)
    if proc.returncode not in (0, 1):
        return {"available": False, "error": proc.stderr.decode("utf-8", "replace")}
    paths = sorted(os.fsdecode(path).replace("\\", "/").removeprefix("./") for path in proc.stdout.split(b"\0") if path)
    return {"available": True, "paths": paths, "count": len(paths),
            "sha256": hashlib.sha256(json.dumps(paths, ensure_ascii=True).encode("ascii")).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-ref", "--baseline-ref", dest="baseline", default="549c6ff9")
    parser.add_argument("--tree-ref", help="Frozen search tree (default: baseline ref).")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--profiles", type=int, default=3)
    parser.add_argument("--large-files", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--output")
    args = parser.parse_args()
    if min(args.rounds, args.profiles, args.large_files) < 1 or args.warmup < 0:
        parser.error("rounds/profiles/large-files must be positive; warmup nonnegative")
    if not shutil.which("rg"):
        parser.error("Benchmark needs rg; the application does not.")
    repository = Path(__file__).resolve().parents[1]
    baseline = utf8_output(["git", "rev-parse", args.baseline], cwd=repository).strip()
    tree_ref = utf8_output(["git", "rev-parse", args.tree_ref or baseline], cwd=repository).strip()
    current = utf8_output(["git", "rev-parse", "HEAD"], cwd=repository).strip()
    report = {"baseline": baseline, "current_head": current, "tree_ref": tree_ref,
              "working_tree_status": utf8_output(["git", "status", "--short"], cwd=repository),
              "platform": platform.platform(), "python": sys.version, "parameters": vars(args),
              "rg": utf8_output([shutil.which("rg"), "--version"]).splitlines()[0],
              "method": "isolated full app checkouts; randomized paired rounds; warmup/profile excluded from headline",
              "phases_note": "Overlapping phases MUST NOT be summed. Output read wait includes rg execution and pipe waits, not pure CPU. Instrumentation overhead affects profiles only. No antivirus/disk/thread cause is inferred.",
              "shared_ignore_additions": [f"/app/data/{name}/" for name in COMMON_RUNTIME_DIRS],
              "tree_note": "Frozen tree plus shared runtime ignore rules. The same on-disk tree and arguments serve both versions. Eligibility diagnostic compares glob/ignore file membership; file-size caps/binary behavior remain visible in actual argv/results.",
              "content": {}, "filenames": {}, "cold_filenames": {}}
    rng = random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix="vp-search-benchmark-") as temporary:
        work = Path(temporary)
        versions = {"baseline": work / "baseline", "current": work / "current"}
        archive_ref(repository, baseline, versions["baseline"])
        archive_ref(repository, current, versions["current"])
        # Current app working-tree overlay only. No current app helpers are
        # imported by the baseline process; hashes verify loaded module origins.
        names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "app"], cwd=repository)
        for raw in names.split(b"\0"):
            if raw:
                relative = Path(os.fsdecode(raw))
                source, target = repository / relative, versions["current"] / relative
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                elif target.is_file():
                    target.unlink()
        root = work / "repository 日本語 with spaces"
        archive_ref(repository, tree_ref, root)
        ignore = root / ".gitignore"
        prior = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        ignore.write_text(prior + "\n# Common benchmark scope for BOTH versions\n" +
                          "\n".join(report["shared_ignore_additions"]) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        large = work / "large 测试 tree with spaces"
        large.mkdir()
        for index in range(args.large_files):
            target = large / f"packages/pkg_{index // 100:04d}/vp_runtime_backend_{index:05d}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("def sample(): return 1\n", encoding="utf-8")
        for name in ("测试文件.py", "日本語.txt", "folder with spaces/foo.py"):
            target = large / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("portable fixture\n", encoding="utf-8")
        drivers = {}
        try:
            for name, version in versions.items():
                drivers[name] = Driver(repository / "scripts/search_benchmark_driver.py", version, work / f"config-{name}")
            for query in ("spawn_child_async", "class LocalToolExecutor"):
                report["content"][query] = cohort(drivers, root, "search_codebase", {
                    "query": query, "root": ".", "max_matches": 20, "file_glob": "", "use_regex": False, "case_sensitive": False,
                }, warmup=args.warmup, rounds=args.rounds, rng=rng, profiles=args.profiles)
                section = report["content"][query]
                section["eligibility"] = {}
                for name, samples in section["samples"].items():
                    commands = next(s for s in samples if s["phase"] == "profile")["commands"]
                    section["eligibility"][name] = (eligible_paths(commands[0]) if commands else
                        {"available": False, "reason": "No process command captured; inspect raw tool failure."})
                policies = list(section["eligibility"].values())
                section["eligible_files_equal"] = all(p.get("available") for p in policies) and policies[0]["paths"] == policies[1]["paths"]
                section["comparison_valid"] &= section["eligible_files_equal"]
            for label, tree in (("repository", root), ("large", large)):
                report["cold_filenames"][label] = {}
                for name, driver in drivers.items():
                    cold = driver.call({"tool": "search_files", "root": str(tree), "arguments": {"query": "vprb", "refresh": True, "max_results": 20}})
                    walk = driver.call({"action": "wait_walk", "root": str(tree)})
                    report["cold_filenames"][label][name] = {"initial": cold, "finished_walk": walk}
                if not all(item["finished_walk"]["walk_complete"] for item in report["cold_filenames"][label].values()):
                    report["filenames"][label] = {"skipped": "walk incomplete; no warm speed claim"}
                    continue
                report["filenames"][label] = {}
                for query in ("v", "vp", "vpr", "vprb"):
                    report["filenames"][label][query] = cohort(drivers, tree, "search_files", {"query": query, "max_results": 20, "refresh": False},
                        warmup=args.warmup, rounds=args.rounds, rng=rng, profiles=args.profiles)
            report["implementations"] = {name: driver.call({"action": "identity"}) for name, driver in drivers.items()}
        finally:
            for driver in drivers.values():
                driver.close()
    output = Path(args.output) if args.output else repository / "output" / f"local-search-{time.strftime('%Y%m%d-%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    compact = lambda values: {name: {key: value for key, value in summary.items() if key != "raw_ms"} for name, summary in values.items()}
    print(json.dumps({"report": str(output.resolve()), "baseline": baseline, "tree": tree_ref,
        "content": {q: {"summary": compact(v["summary"]), "exact_hits_equal": v["exact_hits_equal_across_versions_and_rounds"],
                         "eligible_files_equal": v["eligible_files_equal"], "comparison_valid": v["comparison_valid"]} for q, v in report["content"].items()},
        "filenames": {label: {q: compact(v["summary"]) for q, v in values.items() if isinstance(v, dict)} for label, values in report["filenames"].items()}}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
