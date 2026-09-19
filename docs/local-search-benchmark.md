# Local search split and direct rg

> Historical timing note: the original benchmark mixed baseline methods with
> current helper code. Its timings are not full-version comparisons and must
> not be used to claim a current or Windows speedup. See
> [the replacement measurement and investigation](local-search-performance-investigation.md).

## Tool contracts

- `search_files(query, root=".", max_results=20, refresh=false)` searches fuzzy
  filenames/paths only. The matcher is original Python code, with ordered
  subsequences, independent whitespace-separated tokens, and scoring for word
  boundaries, adjacency, gap length, filename position and path length. Scores
  are ranking weights, not confidence percentages. No Nucleo code or dependency.
- `search_codebase` searches contents only. With rg installed it launches rg
  directly using `--threads 0` (rg chooses parallelism). Without rg it retains
  the isolated Python worker and existing Git/Python enumeration fallback.
  It no longer runs `rg --files`, merges filename hits, or automatically scans
  other access roots after a zero-result query. `execution_mode` identifies
  `direct_rg` or `isolated_python`; structured results and continuation remain.
- `glob_file_search` remains the exact filename-pattern tool, including its
  existing `include_ignored` option.

Content search still uses the executor's process creation and process-tree kill
helpers, a 20-second timeout, cancellation checks, bounded result queues and
result limits. No shell execution, command validation, permission boundary,
runtime scheduling or transcript protocol was changed.

## Filename snapshot lifecycle and scope

Each executor caches one corpus per resolved search root (at most eight roots,
LRU eviction). A background walker progressively publishes names; a separate
matcher thread takes an immutable snapshot and ranks Top N. Concurrent queries
share the walker; up to four matcher threads may run per executor. There is no
subprocess worker, Rust library, watcher or disk index for filename search.

The first call waits at most 50 ms for the walk, not indefinitely. Partial
snapshots have `walk_complete=false`, `search_complete=false` and a continuation
hint. Later calls use newly collected paths without rescanning. A walk has a
20-second cooperative deadline and a 200,000-file cap. Errors and limits remain
explicit; they never become a definitive “file absent”. An individual query's
cancellation does not cancel a shared walk needed by other queries. Refresh or
LRU eviction signals the old walker to stop. As with filesystem threads in
general, an OS-level blocked filesystem call cannot be forcibly interrupted;
the caller can still return without waiting for that daemon walker.

VP file mutations now invalidate affected snapshots lazily, including snapshots
held by other executors/subagents in the same process. Multi-destination writes
and shell operations invalidate conservatively, including partial failures.
Read-only tools do not invalidate. After external changes or changes from a
different VP process, call with `refresh=true`. `cache_hit`, `indexed_at`,
`scanned_file_count`, `walk_complete` and `duration_ms` describe the snapshot.
Every invocation rechecks its root and returned paths against current read
permissions, including cached paths replaced by symlinks.

The walker does not require rg or Git. It skips symlinks, hidden entries and the
existing dependency-directory exclusions. It reads `.gitignore`, `.ignore` and
`.rgignore` under the selected root, with nested rules and negations. Parent
directories outside that selected root, global Git excludes and
`.git/info/exclude` are not loaded in this version. This is a documented subset,
not a claim of exact parity with every Git/rg ignore setting. Ignore parsing
uses unmodified `pathspec==0.12.1` (MPL-2.0); only the fuzzy matcher is custom.

## Reproduce the comparison

Install the updated requirements, then run from the checkout:

```sh
python -m scripts.benchmark_local_search --baseline-ref df95e26d
```

The script extracts a temporary, frozen copy of the merged baseline repository,
then measures the historical public tool/worker, content-only one-shot worker,
and direct rg against exactly that same tree and queries. Temporary files are
outside the checkout and removed afterward. It reports first-call latency,
20-call median and total, and first/warm/incremental filename queries.

This is a small tracked repository snapshot (277 eligible filenames), warm OS
caches, macOS ARM64, Python 3.11.7, rg 15.1.0. It does not measure LLM latency,
cold disks, ignored build trees, Windows process startup, or a large remote
repository. Repeat locally on the target machine rather than assuming a fixed
speedup. `spawn_child_async` has no content matches in this snapshot, so a
positive query is also included.

## Measured results (2026-09-18)

The following representative run was made with no test suite running alongside
the benchmark. Times are milliseconds; environment noise affects individual runs.

| Query | Matches | Old median / 20-call total | Content-only worker median / total | Direct rg median / total |
| --- | ---: | ---: | ---: | ---: |
| `spawn_child_async` | 0 | 65.714 / 1321.499 | 47.924 / 962.965 | 16.597 / 323.013 |
| `class LocalToolExecutor` | 1 | 57.981 / 1174.338 | 47.018 / 971.168 | 12.150 / 245.427 |

For the requested query, first-call latencies were 72.406 / 45.751 / 13.308 ms
respectively. Removing the extra filename scan saved about 27% of median
latency; direct rg reduced it by about 75% versus the original path (roughly
4x throughput for serial calls on this snapshot). Across repeated runs,
content-only saved about 17–27% and direct rg about 75–78% on this empty query.

| Filename query | Milliseconds | Cache hit | Walk complete |
| --- | ---: | --- | --- |
| First `vprb` | 12.072 | no | yes |
| Second `vprb` | 1.222 | yes | yes |
| `v` | 6.909 | yes | yes |
| `vp` | 6.839 | yes | yes |
| `vpr` | 7.072 | yes | yes |
| `vprb` | 1.155 | yes | yes |

Short broad queries return 20 results and are explicitly truncated. Narrow
`vprb` returns two paths. All warm queries reuse the same filename corpus.

## Verification

For the later portability/correctness fixes and updated test results, see
[Local Search correctness follow-up](local-search-correctness.md). The measurements
above describe the original split implementation, not the follow-up patch.

Full Python suite with pathspec 0.12.1: **1021 passed, 1 skipped**. Search tests
cover no-rg fallback, content-only semantics, direct process count, invalid
regex, cancellation, timeout, fuzzy ranking, progressive results, reuse,
refresh, ignore rules, cache/file limits, concurrent queries and permission
revalidation. Frontend JavaScript syntax checks and `git diff --check` pass.
Windows-specific runtime performance still needs testing on the target machine.
