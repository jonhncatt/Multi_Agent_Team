"""Reusable, bounded filename snapshots; no rg, Git process or file contents.

The walker publishes paths progressively. Each matcher runs separately against
one immutable snapshot, so a slow walk never holds up a query. Snapshots are
explicitly refreshed (no watcher); cache entries and walk duration are bounded.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import heapq
import os
from pathlib import Path
import threading
import time
from typing import Callable

from pathspec import GitIgnoreSpec

from app.code_search import SEARCH_TIMEOUT_SECONDS, SKIP_DIRS

MAX_CACHED_ROOTS = 8
MAX_FILES = 200_000
INITIAL_WAIT_SECONDS = 0.05
IGNORE_NAMES = (".gitignore", ".ignore", ".rgignore")


@dataclass
class Corpus:
    root: Path
    paths: list[str] = field(default_factory=list)
    changed: threading.Condition = field(default_factory=threading.Condition)
    stop: threading.Event = field(default_factory=threading.Event)
    complete: bool = False
    finished: bool = False
    reason: str = ""
    skipped: int = 0
    created: float = field(default_factory=time.time)


def _walk(corpus: Corpus) -> None:
    deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
    # A rule retains its containing directory, so nested and anchored patterns
    # have Git-style relative semantics. Excluded directories are never entered.
    pending: list[tuple[Path, tuple]] = [(corpus.root, ())]
    try:
        while pending:
            if corpus.stop.is_set() or time.monotonic() >= deadline:
                corpus.reason = "superseded" if corpus.stop.is_set() else "walk_timeout"
                return
            directory, inherited = pending.pop()
            rules = list(inherited)
            for name in IGNORE_NAMES:
                ignore = directory / name
                if ignore.is_symlink() or not ignore.is_file():
                    continue
                try:
                    with ignore.open(encoding="utf-8", errors="replace") as source:
                        text = source.read(65537)
                    if len(text) > 65536:
                        corpus.skipped += 1
                        continue
                    rules.append((directory, GitIgnoreSpec.from_lines(text.splitlines())))
                except FileNotFoundError:
                    pass
                except (OSError, ValueError):
                    corpus.skipped += 1
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if corpus.stop.is_set() or time.monotonic() >= deadline:
                            corpus.reason = "superseded" if corpus.stop.is_set() else "walk_timeout"
                            return
                        if entry.name.startswith(".") or entry.name in SKIP_DIRS or entry.is_symlink():
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            path = Path(entry.path)
                            ignored = False
                            for base, spec in reversed(rules):
                                relative = path.relative_to(base).as_posix() + ("/" if is_dir else "")
                                # Distinguish an explicit negation from no rule;
                                # let GitIgnoreSpec resolve directory precedence.
                                if any(pattern.include is not None and pattern.match_file(relative)
                                       for pattern in spec.patterns):
                                    ignored = spec.match_file(relative)
                                    break
                            if ignored:
                                continue
                            if is_dir:
                                pending.append((path, tuple(rules)))
                            elif entry.is_file(follow_symlinks=False):
                                with corpus.changed:
                                    corpus.paths.append(path.relative_to(corpus.root).as_posix())
                                    corpus.changed.notify_all()
                                if len(corpus.paths) >= MAX_FILES:
                                    corpus.reason = "file_limit"
                                    return
                        except OSError:
                            corpus.skipped += 1
            except OSError:
                corpus.skipped += 1
        corpus.complete = not bool(corpus.skipped)
        if corpus.skipped:
            corpus.reason = "walk_errors"
    except Exception:
        corpus.reason = "walk_failed"
    finally:
        with corpus.changed:
            corpus.finished = True
            corpus.changed.notify_all()


def fuzzy_score(query: str, path: str) -> int | None:
    """Subsequence DP, O(query length * path length), with boundary/gap bonuses.

    Space-separated tokens may appear in any order. A token must match in order;
    unlike an edit-distance matcher, unrelated misspellings aren't made matches.
    Scores are relative ranking weights, not probabilities or percentages.
    """
    hay = path.lower()
    basename = path.rfind("/") + 1
    total = 0
    for token in query.lower().split():
        if len(token) > len(hay):
            return None
        cursor = 0
        for char in token:
            cursor = hay.find(char, cursor)
            if cursor < 0:
                return None
            cursor += 1
        previous: dict[int, int] = {}
        for row, char in enumerate(token):
            current: dict[int, int] = {}
            best = -10**9
            for pos, candidate in enumerate(hay):
                # best stores the best previous match, discounted by distance.
                if pos - 1 in previous:
                    best = max(best, previous[pos - 1] + 2 * (pos - 1))
                if char != candidate:
                    continue
                boundary = pos == 0 or hay[pos - 1] in "/_-. " or (
                    len(hay) == len(path) and path[pos].isupper() and path[pos - 1].islower())
                bonus = 16 + (14 if boundary else 0) + (8 if pos >= basename else 0)
                if row == 0:
                    current[pos] = bonus - min(pos, 20)
                elif best > -10**9:
                    current[pos] = bonus + max(best - 2 * pos, previous.get(pos - 1, -10**9) + 12)
            if not current:
                return None
            previous = current
        total += max(previous.values())
    return total - min(len(path), 100) // 4


class FilenameSearch:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._corpora: OrderedDict[Path, Corpus] = OrderedDict()
        self._match_slots = threading.BoundedSemaphore(4)

    def search(self, root: Path, query: str, limit: int, *, refresh: bool,
               cancelled: Callable[[], bool]) -> dict:
        started = time.monotonic()
        deadline = started + SEARCH_TIMEOUT_SECONDS
        if cancelled():
            return {"ok": False, "error_kind": "cancelled", "stop_reason": "cancelled",
                    "error": "Filename search cancelled by user.", "query": query,
                    "matches": [], "match_count": 0, "max_results": limit,
                    "walk_complete": False, "search_complete": False,
                    "scanned_file_count": 0, "cache_hit": False, "indexed_at": None,
                    "duration_ms": 0, "skipped_files": 0, "truncated": True, "has_more": True,
                    "continuation": {"strategy": "retry", "message": "Search was cancelled; no absence conclusion is possible."}}
        with self._lock:
            hit = root in self._corpora and not refresh
            if not hit:
                old = self._corpora.pop(root, None)
                if old:
                    old.stop.set()
                corpus = Corpus(root)
                self._corpora[root] = corpus
                while len(self._corpora) > MAX_CACHED_ROOTS:
                    _, old = self._corpora.popitem(last=False)
                    old.stop.set()
                threading.Thread(target=_walk, args=(corpus,), daemon=True, name="vp-filename-walker").start()
            else:
                corpus = self._corpora[root]
                self._corpora.move_to_end(root)
        # Only the first query waits briefly to let small projects finish. Later
        # queries use whatever is currently available, without restarting a walk.
        with corpus.changed:
            if not hit:
                corpus.changed.wait_for(lambda: corpus.finished or cancelled(), timeout=INITIAL_WAIT_SECONDS)
            paths = tuple(corpus.paths)
            complete, reason, skipped = corpus.complete, corpus.reason, corpus.skipped
        stop = threading.Event()
        done = threading.Event()
        result: dict = {}

        def match() -> None:
            try:
                def candidates():
                    for index, path in enumerate(paths):
                        if index % 32 == 0 and (stop.is_set() or time.monotonic() >= deadline):
                            result["interrupted"] = True
                            return
                        score = fuzzy_score(query, path)
                        if score is not None:
                            yield {"path": path, "score": score}
                result["matches"] = heapq.nsmallest(limit + 1, candidates(), key=lambda item: (-item["score"], item["path"]))
            except Exception:
                result["failed"] = True
            finally:
                self._match_slots.release()
                done.set()

        acquired = False
        while not acquired and not cancelled() and time.monotonic() < deadline:
            acquired = self._match_slots.acquire(timeout=0.02)
        if acquired:
            threading.Thread(target=match, daemon=True, name="vp-filename-matcher").start()
            while not done.wait(0.02):
                if cancelled() or time.monotonic() >= deadline:
                    stop.set()
                    break
        abort = "cancelled" if cancelled() else ("timeout" if not done.is_set() or result.get("interrupted") else "")
        if result.get("failed"):
            abort = "matcher_failed"
        matches = result.get("matches", []) if not abort else []
        limited = len(matches) > limit
        reason = abort or reason or ("walking" if not complete else "limit" if limited else "")
        return {
            "ok": not bool(abort), "query": query, "matches": matches[:limit],
            "match_count": min(len(matches), limit), "max_results": limit,
            "scanned_file_count": len(paths), "walk_complete": complete,
            "cache_hit": hit, "indexed_at": corpus.created,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "truncated": bool(reason), "has_more": bool(reason),
            "search_complete": not bool(reason), "stop_reason": reason,
            "skipped_files": skipped,
            "continuation": ({"strategy": "retry_or_refresh", "message":
                "Retry while walking; refine query for a result limit. Use refresh=true after filesystem changes or walk errors."}
                if reason else None),
            **({"error_kind": abort, "error": f"Filename search stopped: {abort}"} if abort else {}),
        }
