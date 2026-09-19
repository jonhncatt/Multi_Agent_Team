# Local Search portability and correctness follow-up

> The historical timings below came from the former mixed-helper benchmark.
> They do not establish a full-version performance improvement. See
> [the replacement measurement and investigation](local-search-performance-investigation.md)
> for the corrected methodology and remaining Windows investigation.

Based on `549c6ff9` on `codex/rg-local-search-optimizations`. The Python filename
walker/corpus/matcher, direct rg and isolated no-rg fallback remain unchanged
architecturally. No Nucleo, Rust, watcher, database or runtime rewrite.

## Root causes and fixes

| Issue | Root cause | Fix / primary files |
| --- | --- | --- |
| Japanese Windows benchmark decode failure | Subprocess and source-file I/O relied on system encoding | `scripts/benchmark_local_search.py`: strict UTF-8 for Git text, rg version and worker source; ASCII-safe JSON output |
| Python 3.11.2 tar failure | Assumed `extractall(filter=...)` existed | Detect callable signature; use `filter="data"` when supported, otherwise trusted-local-git-archive extraction only |
| Windows symlink test failures | Tests assumed OS privilege | `tests/test_filename_search.py`: attempt actual symlinks and capability-skip on OSError; separate mocked permission-resolver test always runs |
| Historical tool output became source evidence | Missing explicit runtime path exclusions; `.gitignore` incomplete | `app/code_search.py`: shared `RUNTIME_SEARCH_EXCLUDED_PATHS`, applied to rg and fallback; `.gitignore` adds tool_results/subagents; filename walker uses same scope |
| False complete results for files over 16 MiB | `size_limit_applied` was ignored by public result | `app/local_tools.py`: completeness is false, explicit `size_limit` reason and continuation; fallback reports observed size skips |
| Filename snapshots stale after VP writes | No mutation-to-cache invalidation | `FilenameSearch.invalidate(path=None)` drops snapshots without scanning; native writes call it, and next search rebuilds |

VP repository identification uses the combination of `app/local_tools.py`,
`app/vintage_programmer_runtime.py` and the built-in Vintage Programmer profile.
Exclusions are relative paths, not generic `data` or `tool_results` basenames.
Explicit roots inside a runtime subtree are searchable, including ignored files.
Broad `file_glob` filters cannot override runtime exclusions from a parent root.
Other projects' legitimate `data/`, `src/data/` and `app/data/...` remain searchable.

## Completeness policy

rg does not tell this integration how many eligible files `--max-filesize`
omitted. To avoid another directory scan and preserve the one-process fast path,
rg results conservatively report unknown completeness whenever the cap is active:
`size_limit_applied=true`, `size_skipped_files=null`, and
`size_limit_policy="conservative_unknown"`. `stop_reason="size_limit"` applies
unless cancellation, timeout, failure or result limit has priority. This does
**not** claim that a large file definitely exists in every search.

The Python fallback can count actual size skips and reports
`size_limit_policy="observed_skips"`. Neither path claims full coverage when
large eligible files were skipped. `size_limit` continuation recommends inspecting
suspected files with file-specific tools and checking their completeness, not
endlessly narrowing the same capped search.

## Invalidation coverage

- `apply_patch`: additions, updates, deletes, moves, including partial writes;
  affected cached roots only. Validation-only `check=true` does not invalidate.
- Download, archive/mail extraction, screenshots, skill/task writes: conservative
  invalidation because these may have multiple destinations or partial failures.
- Shell invocation/input and command-reader completion invalidate conservatively;
  while commands are still running, queries rebuild rather than trusting snapshots.
- Invalidation notifies other filename services in the same process via weak
  references (subagents have their own executors). Corpus contents are not shared.
- Read-only tools do not invalidate. External or other-process filesystem changes
  still require explicit `refresh=true`. No filesystem watcher was added.

`pathspec==0.12.1` is retained exclusively for filename-walker ignore parsing.
Neither fuzzy scoring nor content search depends on it.

## Verification and Windows assumptions

Full suite: **1045 passed, 1 skipped**, with both the pre-existing local pathspec
and the declared pathspec 0.12.1 in an isolated import path. One existing
Starlette/httpx deprecation warning remains. `git diff --check` passes.

Tests cover both tar API signatures, real extraction of Chinese/Japanese/spaced
paths, UTF-8 output with a simulated cp932 locale, strict invalid-UTF-8 rejection,
no-symlink-privilege behavior, real symlink checks where supported, and an
unconditional cached-path permission resolver test. Child Python tests use
`sys.executable`, not an assumed `python3` command.

Content tests cover direct rg, no-rg fallback, runtime exclusions with and without
Git ignores, explicit runtime subtree roots, normal user data paths, size limits,
timeout, cancellation and owned-process cleanup. Cache tests cover create,
rename/delete, reads reusing the corpus, archive extraction, partial mutations,
scoped invalidation and mutation by another executor.

The full suite is run on macOS/Python 3.11.7. Legacy tar and missing symlink
privileges are simulated; **this is not a claim of executing Windows/Python
3.11.2 itself**. That remains the target-machine validation step.

## Timing comparison

Run `python -m scripts.benchmark_local_search --compare-ref 549c6ff9` to compare
the previous direct-rg implementation and this patch on one frozen repository
snapshot. The temporary repository path contains Japanese characters and spaces.

macOS ARM64 / Python 3.11.7 / rg 15.1.0, warm caches, 20 calls per query:

| Query | Before median / total (ms) | After median / total (ms) | Returned matches |
| --- | ---: | ---: | ---: |
| `spawn_child_async` | 13.228 / 274.656 | 14.469 / 297.123 | 3 / 3 |
| `class LocalToolExecutor` | 13.410 / 275.818 | 14.218 / 290.319 | 3 / 3 |

Unlike the older `df95e26d` snapshot, this snapshot contains benchmark source/docs
mentioning the queries, so both return three real file-content hits. No historical
runtime output is included. Added scope checks cost roughly 0.8–1.2 ms in this
run; there is no second filename scan. Current filename queries: first `vprb`
13.172 ms, second 1.253 ms; incremental `v/vp/vpr/vprb`:
7.163 / 7.095 / 7.679 / 1.254 ms. Timing varies by machine and OS caches.

## Changed files

- Search implementation: `app/code_search.py`, `app/filename_search.py`,
  `app/local_tools.py`.
- Tool guidance: `app/vp_runtime_backend.py`,
  `agents/vintage_programmer/locales/{en,ja-JP,zh-CN}/tools.md`.
- Portability and verification: `scripts/benchmark_local_search.py`,
  `tests/test_code_search.py`, `tests/test_filename_search.py`,
  `tests/test_search_portability.py`.
- Ignore rules and documentation: `.gitignore`, `docs/local-search-benchmark.md`,
  `docs/local-search-correctness.md`.
