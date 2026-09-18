import json
from pathlib import Path
import random

from scripts.benchmark_local_search import Driver, canonical_hits, cohort, eligible_paths, hit_category, stats


def test_stats_preserve_raw_samples_and_nearest_rank_p95():
    values = list(range(1, 21))
    result = stats(values)
    assert result == {"count": 20, "median_ms": 10.5, "p95_ms": 19, "total_ms": 210, "raw_ms": values}


def test_cohort_separates_warmup_profiles_and_compares_full_hits(tmp_path):
    class Fake:
        def __init__(self, text):
            self.text = text
        def call(self, request):
            return {"wall_ms": 1, "result": {"ok": True, "matches": [{"path": "app/a.py", "line": 3, "text": self.text}]}}
    result = cohort({"baseline": Fake("old"), "current": Fake("new")}, tmp_path, "search_codebase", {"query": "x"},
                    warmup=2, rounds=10, profiles=3, rng=random.Random(1701))
    assert not result["comparison_valid"]  # Equal counts do not imply equal evidence.
    assert result["summary"]["baseline"]["count"] == 10
    assert len(result["warmup"]["baseline"]) == 2
    assert len(result["samples"]["baseline"]) == 13
    assert {tuple(item["order"]) for item in result["order"]} == {("baseline", "current"), ("current", "baseline")}
    assert canonical_hits({"matches": [{"path": "a\\b", "line": 1, "text": "x"}]}) == [("a/b", 1, "x", None)]
    assert hit_category("scripts/benchmark_local_search.py") == "benchmark_source"
    assert hit_category("app/data/tool_results/a.json") == "runtime_data"


def test_driver_imports_version_helpers_not_current_app(tmp_path):
    harness = Path(__file__).resolve().parents[1] / "scripts/search_benchmark_driver.py"
    identities = []
    for name in ("baseline", "current"):
        root = tmp_path / name
        app = root / "app"
        app.mkdir(parents=True)
        (app / "__init__.py").write_text("", encoding="utf-8")
        (app / "config.py").write_text("from types import SimpleNamespace\ndef load_config(): return SimpleNamespace()\n", encoding="utf-8")
        (app / "code_search.py").write_text("# isolated fixture\n", encoding="utf-8")
        (app / "filename_search.py").write_text("def _walk(corpus): pass\n", encoding="utf-8")
        (app / "helper.py").write_text(f"VALUE = {name!r}\n", encoding="utf-8")
        (app / "local_tools.py").write_text(
            "from app.helper import VALUE\nclass LocalToolExecutor:\n"
            " def __init__(self, config): pass\n def set_runtime_context(self, **kwargs): pass\n"
            " def search_codebase(self, query): return {'ok': True, 'matches': [{'path': 'a.py', 'line': 1, 'text': VALUE}]}\n", encoding="utf-8")
        driver = Driver(harness, root, tmp_path / f"config-{name}")
        try:
            sample = driver.call({"tool": "search_codebase", "root": str(root), "arguments": {"query": "x"}})
            assert sample["result"]["matches"][0]["text"] == name
            identity = driver.call({"action": "identity"})
            assert not identity["shared_current_app_helpers"]
            identities.append(identity["app_sources_sha256"]["app/helper.py"])
        finally:
            driver.close()
    assert identities[0] != identities[1]


def test_eligibility_diagnostic_preserves_ignore_flags_and_exact_paths(monkeypatch):
    from types import SimpleNamespace
    import scripts.benchmark_local_search as benchmark
    commands = []
    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"./app/b.py\0./app/a.py\0", stderr=b"")
    monkeypatch.setattr(benchmark.subprocess, "run", run)
    result = eligible_paths({"argv": ["rg", "--json", "--no-config", "--threads", "0", "-g", "*.py",
                                      "-g", "!app/data/tool_results/**", "--hidden", "--no-ignore", "--", "needle", "."],
                             "cwd": "repository"})
    assert result["paths"] == ["app/a.py", "app/b.py"]
    assert commands[0][0] == ["rg", "--files", "-0", "--no-config", "-g", "*.py", "-g",
                               "!app/data/tool_results/**", "--hidden", "--no-ignore", "--", "."]
    assert commands[0][1]["cwd"] == "repository"
