from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

from app import filename_search
from app.filename_search import FilenameSearch, fuzzy_score
from app.local_tools import LocalToolExecutor
from tests.test_local_tools_public_surface import _config


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symlink capability unavailable: {exc}")


def search(service, root, query="vprb", **kwargs):
    return service.search(root, query, kwargs.pop("limit", 20), refresh=kwargs.pop("refresh", False),
                          cancelled=kwargs.pop("cancelled", lambda: False), **kwargs)


def completed(service, root, query="vprb", **kwargs):
    result = search(service, root, query, **kwargs)
    deadline = time.monotonic() + 3
    while result["stop_reason"] == "walking" and time.monotonic() < deadline:
        time.sleep(0.01)
        result = search(service, root, query)
    return result


@pytest.mark.parametrize("query,path", [
    ("vprb", "app/vp_runtime_backend.py"), ("runtime backend", "app/vp_runtime_backend.py"),
    ("backend runtime", "app/vp_runtime_backend.py"), ("ncm", "src/nvme_controller_manager.cpp"),
    ("nvme ctrl", "src/nvme_controller.cpp"), ("İ", "src/İ.py"),
])
def test_fuzzy_subsequences_and_tokens(query, path):
    assert fuzzy_score(query, path) is not None


def test_fuzzy_ranking_rewards_basename_boundaries_and_adjacency():
    assert fuzzy_score("vprb", "app/vp_runtime_backend.py") > fuzzy_score("vprb", "app/very_poor_random_blah.py")
    assert fuzzy_score("runtime", "app/runtime.py") > fuzzy_score("runtime", "runtime/app/other.py")
    assert fuzzy_score("xyz", "app/runtime.py") is None


def test_corpus_reused_refreshed_and_isolated_by_root(tmp_path, monkeypatch):
    service = FilenameSearch()
    (tmp_path / "vp_runtime_backend.py").touch()
    first = completed(service, tmp_path)
    assert first["walk_complete"] and first["matches"][0]["path"] == "vp_runtime_backend.py"
    (tmp_path / "vp_runtime_backend_new.py").touch()
    original = filename_search._walk
    def forbidden(*args):
        raise AssertionError("warm query must not scan")
    monkeypatch.setattr(filename_search, "_walk", forbidden)
    second = search(service, tmp_path)
    assert second["cache_hit"] and second["matches"] == first["matches"]
    monkeypatch.setattr(filename_search, "_walk", original)
    refreshed = completed(service, tmp_path, refresh=True)
    assert len(refreshed["matches"]) == 2
    other = tmp_path / "other"
    other.mkdir()
    assert completed(service, other)["matches"] == []


def test_walker_ignores_nested_rules_hidden_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_: None)
    (tmp_path / ".gitignore").write_text("*.tmp\nbuild/\n")
    (tmp_path / ".ignore").write_text("*.log\n")
    (tmp_path / ".rgignore").write_text("*.out\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / ".gitignore").write_text("!keep.tmp\n/anchored.py\n")
    for path in ["visible.py", "skip.tmp", "skip.log", "skip.out", ".hidden.py", "sub/keep.tmp", "sub/no.tmp",
                 "sub/anchored.py", "sub/deep/anchored.py", "build/skip.py", "node_modules/skip.py"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    result = completed(FilenameSearch(), tmp_path, "p")
    assert result["walk_complete"]
    assert {m["path"] for m in result["matches"]} == {"visible.py", "sub/keep.tmp", "sub/deep/anchored.py"}


def test_walker_skips_symlinks_when_supported(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "visible.py").touch()
    symlink_or_skip(tmp_path / "linked.py", sub / "visible.py")
    symlink_or_skip(tmp_path / "linked_dir", sub, directory=True)
    result = completed(FilenameSearch(), tmp_path, "py")
    assert {item["path"] for item in result["matches"]} == {"sub/visible.py"}


def test_symlink_permission_failure_is_capability_skip(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("SeCreateSymbolicLinkPrivilege unavailable")
    monkeypatch.setattr(Path, "symlink_to", denied)
    with pytest.raises(pytest.skip.Exception):
        symlink_or_skip(tmp_path / "link", tmp_path / "target")


def test_progressive_walk_can_be_searched_before_finishing(tmp_path, monkeypatch):
    release = threading.Event()
    def slow_walk(corpus):
        with corpus.changed:
            corpus.paths.append("vp_runtime_backend.py")
            corpus.changed.notify_all()
        release.wait(3)
        with corpus.changed:
            corpus.paths.append("vp_runtime_backend_new.py")
            corpus.complete = corpus.finished = True
            corpus.changed.notify_all()
    monkeypatch.setattr(filename_search, "_walk", slow_walk)
    service = FilenameSearch()
    try:
        result = search(service, tmp_path)
        assert result["matches"] and not result["walk_complete"]
        assert result["stop_reason"] == "walking"
        assert result["continuation"] and result["has_more"]
    finally:
        release.set()
    assert len(completed(service, tmp_path)["matches"]) == 2


def test_concurrent_queries_share_one_walk(tmp_path, monkeypatch):
    original = filename_search._walk
    walks = []
    def tracked(corpus):
        walks.append(corpus.root)
        original(corpus)
    monkeypatch.setattr(filename_search, "_walk", tracked)
    (tmp_path / "vp_runtime_backend.py").touch()
    service = FilenameSearch()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: search(service, tmp_path), range(12)))
    assert walks == [tmp_path]


def test_limits_cancellation_and_matcher_timeout_are_explicit(tmp_path, monkeypatch):
    (tmp_path / "a.py").touch()
    (tmp_path / "b.py").touch()
    service = FilenameSearch()
    result = completed(service, tmp_path, "py", limit=1)
    assert result["walk_complete"] and result["stop_reason"] == "limit"
    assert result["truncated"] and not result["search_complete"]
    result = search(service, tmp_path, cancelled=lambda: True)
    assert result["error_kind"] == "cancelled"
    monkeypatch.setattr(filename_search, "SEARCH_TIMEOUT_SECONDS", 0.05)
    release = threading.Event()
    def slow_score(*args):
        release.wait(2)
        return 1
    monkeypatch.setattr(filename_search, "fuzzy_score", slow_score)
    try:
        start = time.monotonic()
        result = search(service, tmp_path, "py")
        assert result["stop_reason"] == "timeout"
        assert time.monotonic() - start < 1
    finally:
        release.set()


def test_walker_caps_and_cache_eviction_do_not_claim_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(filename_search, "MAX_FILES", 1)
    monkeypatch.setattr(filename_search, "MAX_CACHED_ROOTS", 1)
    (tmp_path / "a.py").touch()
    (tmp_path / "b.py").touch()
    service = FilenameSearch()
    result = completed(service, tmp_path, "py")
    assert result["stop_reason"] == "file_limit"
    assert not result["walk_complete"] and result["scanned_file_count"] == 1
    first = service._corpora[tmp_path]
    other = tmp_path / "other"
    other.mkdir()
    search(service, other)
    assert first.stop.is_set() and len(service._corpora) == 1


def test_walker_timeout_and_invalid_ignore_are_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(filename_search, "SEARCH_TIMEOUT_SECONDS", 0)
    corpus = filename_search.Corpus(tmp_path)
    filename_search._walk(corpus)
    assert corpus.finished and corpus.reason == "walk_timeout" and not corpus.complete
    monkeypatch.setattr(filename_search, "SEARCH_TIMEOUT_SECONDS", 20)
    (tmp_path / ".gitignore").write_text("[" * 65537)
    result = completed(FilenameSearch(), tmp_path, "py")
    assert result["stop_reason"] == "walk_errors" and result["skipped_files"] == 1


def test_ignore_fifo_is_not_opened(tmp_path):
    import os
    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes unavailable")
    os.mkfifo(tmp_path / ".ignore")
    (tmp_path / "vp_runtime_backend.py").touch()
    result = completed(FilenameSearch(), tmp_path)
    assert result["walk_complete"] and result["match_count"] == 1


def test_cached_path_is_revalidated_after_symlink_replacement(tmp_path):
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    target = tmp_path / "vp_runtime_backend.py"
    target.touch()
    assert executor.search_files("vprb")["matches"]
    target.unlink()
    symlink_or_skip(target, tmp_path.parent / "outside.py")
    result = executor.search_files("vprb")
    assert not result["ok"]


def test_cached_results_pass_permission_resolver_without_symlink_privilege(tmp_path, monkeypatch):
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    target = tmp_path / "vp_runtime_backend.py"
    target.touch()
    assert executor.search_files("vprb")["matches"]
    original = executor._resolve_path
    checked = []
    def revoked(path):
        checked.append(path)
        if Path(path) == target:
            raise PermissionError("permission revoked")
        return original(path)
    monkeypatch.setattr(executor, "_resolve_path", revoked)
    assert not executor.search_files("vprb")["ok"]
    assert str(target) in checked


def test_patch_create_rename_delete_invalidate_lazily_and_reads_reuse(tmp_path, monkeypatch):
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    executor.search_files("fresh")
    walks = []
    original = filename_search._walk
    def tracked(corpus):
        walks.append(corpus.root)
        original(corpus)
    monkeypatch.setattr(filename_search, "_walk", tracked)
    assert executor.apply_patch("*** Begin Patch\n*** Add File: fresh.py\n+hello\n*** End Patch")["ok"]
    assert not walks
    result = executor.search_files("fresh")
    assert not result["cache_hit"] and result["matches"][0]["path"] == "fresh.py"
    executor.read_file("fresh.py")
    executor.search_codebase("hello")
    assert executor.search_files("fresh")["cache_hit"]
    assert executor.apply_patch("*** Begin Patch\n*** Update File: fresh.py\n*** Move to: renamed.py\n@@\n-hello\n+hello again\n*** End Patch")["ok"]
    assert len(walks) == 1
    assert executor.search_files("renamed")["matches"]
    assert not executor.search_files("fresh")["matches"]
    assert executor.apply_patch("*** Begin Patch\n*** Delete File: renamed.py\n*** End Patch")["ok"]
    assert not executor.search_files("renamed")["matches"]


def test_invalidate_only_affected_roots(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    service = FilenameSearch()
    completed(service, left)
    completed(service, right)
    service.invalidate(left / "new.py")
    assert search(service, right)["cache_hit"]
    assert not search(service, left)["cache_hit"]


def test_mutation_invalidates_other_executor_for_same_project(tmp_path):
    parent = LocalToolExecutor(_config(tmp_path))
    child = LocalToolExecutor(_config(tmp_path))
    for executor in (parent, child):
        executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
        executor.search_files("fresh")
    assert child.apply_patch("*** Begin Patch\n*** Add File: fresh.py\n+hello\n*** End Patch")["ok"]
    result = parent.search_files("fresh")
    assert not result["cache_hit"] and result["matches"][0]["path"] == "fresh.py"


@pytest.mark.parametrize("tool,impl,args", [
    ("web_download", "_web_download_impl", {"url": "https://example.invalid/file", "dst_path": "fresh.py"}),
    ("archive_extract", "_archive_extract_impl", {"zip_path": "source.zip"}),
    ("mail_extract_attachments", "_mail_extract_attachments_impl", {"msg_path": "source.msg"}),
])
def test_native_partial_writes_invalidate_without_scanning(tmp_path, monkeypatch, tool, impl, args):
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    executor.search_files("fresh")
    def partial_write(**kwargs):
        (tmp_path / "fresh.py").write_text("partial", encoding="utf-8")
        return {"ok": False, "error": "simulated interruption after one file"}
    monkeypatch.setattr(executor, impl, partial_write)
    assert not getattr(executor, tool)(**args)["ok"]
    result = executor.search_files("fresh")
    assert not result["cache_hit"] and result["matches"]


def test_archive_extract_invalidates_corpus(tmp_path):
    import zipfile
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("fresh.py", "hello")
    executor.search_files("fresh")
    assert executor.archive_extract(str(archive), dst_dir=str(tmp_path / "out"))["ok"]
    result = executor.search_files("fresh")
    assert not result["cache_hit"] and result["matches"][0]["path"] == "out/fresh.py"


def test_public_surface_and_root_permission_checks(tmp_path):
    from app.action_validator import ActionValidator
    from app.runtime_boundary import RuntimeBoundary

    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    (tmp_path / "vp_runtime_backend.py").touch()
    result = executor.execute("search_files", {"query": "vprb"})
    assert result["ok"] and result["matches"][0]["path"] == "vp_runtime_backend.py"
    assert result["root_ref"] == "project_root"
    assert not executor.search_files("vprb", root=str(tmp_path.parent))["ok"]
    assert not executor.search_files("")["ok"]
    assert not executor.search_files("x" * 257)["ok"]
    validator = ActionValidator(
        tool_specs=executor.tool_specs, allowed_tools=["search_files"], allowed_commands=[],
        boundary=RuntimeBoundary(allowed_roots=[str(tmp_path)], writable_roots=[],
                                 cwd=str(tmp_path), project_root=str(tmp_path)), locale="en")
    assert validator.validate_tool_call({"name": "search_files", "args": {"query": "vprb"}}).allowed
    assert not validator.validate_tool_call({"name": "search_files", "args": {
        "query": "vprb", "root": str(tmp_path.parent)}}).allowed
