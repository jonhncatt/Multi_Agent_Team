# Local Search performance investigation — 2026-09-18

## Conclusion

The reported Windows regression (spawn_child_async median 106.892 → 206.348 ms)
is **not yet explained or verified fixed**. The macOS runs below did not reproduce
it. Neither these runs nor the old benchmark justify a “4× faster” claim.
`549c6ff9` already uses direct rg; it is not the earlier Python-worker baseline.

We found a benchmark defect: the former harness transplanted baseline methods
into current helper code. That was not a complete historical implementation.
The replacement loads each version's entire app in its own process, verifies
loaded source origins, and records source SHA-256 hashes. Both use the same
installed third-party dependencies and the same stdlib-only measurement harness;
the baseline does **not** import current app helpers. Current app working-tree
changes are overlaid and identified through Git status and loaded-source hashes.

## Reproduce on the company machine

Run from the repository with its normal dependencies, Git and rg installed.
Do not run pytest, builds or other benchmarks concurrently. Fetch the branch
before running, so both baseline commits are available locally.

```sh
python -m scripts.benchmark_local_search --compare-ref 549c6ff9 --rounds 20 --warmup 3 --profiles 3 --large-files 10000 --output output/search-company-549.json
python -m scripts.benchmark_local_search --compare-ref ab118e63 --tree-ref 549c6ff9 --rounds 20 --warmup 3 --profiles 3 --large-files 10000 --output output/search-company-ab118.json
```

Run these sequentially. Return the JSON, not just console medians: it includes
raw samples, exact hits, execution order, commands and diagnostic phase timings.
It also contains source snippets and local paths; share it only where appropriate.
The benchmark requires the search_files/direct-rg API available in these refs;
it no longer offers the old hybrid worker/direct three-way comparison.

Git text and pipes explicitly use UTF-8; JSON console output is ASCII-safe.
Archive extraction detects the available signature rather than assuming that
Python 3.11.2 supports `filter=`. CP932 and old/new tar API regressions are tested.
Actual Windows/Python 3.11.2 execution still needs confirmation on that machine;
the local test host was macOS/Python 3.11.7.

## Measurement contract

- Both implementations search one frozen Git snapshot, with identical arguments,
  result limits and explicit runtime ignore additions. Four historical runtime
  `.gitkeep` files otherwise made candidate sets differ. Added rules are recorded
  in `shared_ignore_additions`; no arbitrary `data` basename is excluded.
- An untimed rg diagnostic compares the exact candidate filename sets under the
  actual glob/ignore flags. Different candidates invalidate the comparison.
  This checks file membership, not binary/size semantics; actual argv and results
  remain in the report for those policies.
- Every measured result is compared by path, line, text and (for filenames) score,
  across versions and rounds. Equal counts alone are insufficient. Timeout,
  cancellation and incomplete filename walks invalidate the comparison.
- Each query has three separate warmups, 20 randomized paired measured rounds,
  and three separate instrumented rounds. Median, nearest-rank P95, total and raw
  timings are retained. Profiler timings are excluded from headline statistics.
- Filename cold-call/walk values are single diagnostic observations, not proof of
  a cold-start improvement. Repeated filename measurements start only after the
  corpus finishes. The large fixture has 10,003 files, including Unicode/spaces.
- Harness startup, imports and IPC are outside tool wall time. These persistent
  processes are benchmark harnesses, **not** new persistent application workers.

On the frozen `549c6ff9` tree, all three spawn_child_async hits are benchmark or
documentation text: docs/local-search-benchmark.md lines 74 and 84, and
scripts/benchmark_local_search.py line 96. There is no application-code hit for
that query in this snapshot. `hit_categories` makes this distinction explicit.

## Local results

macOS 27 ARM64, Python 3.11.7, rg 15.1.0, shared pathspec 0.10.3. Each row is one independently measured
pair; do not combine times from different pairs. The current implementation is
the working-tree patch accompanying this document. No tests ran concurrently.

Content wall time, milliseconds (median / P95 / total for 20 calls):

| Baseline | Query | Baseline | Current |
| --- | --- | --- | --- |
| 549c6ff9 | spawn_child_async | 13.600 / 15.099 / 270.700 | 13.565 / 16.222 / 281.505 |
| 549c6ff9 | class LocalToolExecutor | 12.725 / 13.822 / 258.178 | 13.356 / 14.596 / 273.086 |
| ab118e63 | spawn_child_async | 14.171 / 15.734 / 291.568 | 13.689 / 14.972 / 279.220 |
| ab118e63 | class LocalToolExecutor | 14.256 / 15.604 / 294.417 | 13.713 / 15.175 / 283.528 |

Both content queries passed candidate-set and exact-hit equality. Relative to
549c6ff9, spawn's median is flat but P95/total are worse; the class query median
is about 5% slower. Relative to ab118e63, both medians are only about 3–4% better.
These small differences are not evidence of a substantial content-search gain.

Warm filename wall time versus ab118e63, milliseconds (median / P95 / total):

| Files | Query | Baseline | Current |
| --- | --- | --- | --- |
| 281 | v | 5.063 / 5.137 / 101.430 | 3.822 / 3.898 / 76.641 |
| 281 | vp | 5.144 / 5.208 / 103.009 | 3.924 / 4.018 / 78.999 |
| 281 | vpr | 5.292 / 5.332 / 106.026 | 4.027 / 4.057 / 80.613 |
| 281 | vprb | 0.889 / 0.897 / 17.780 | 0.787 / 0.800 / 15.766 |
| 10,003 | v | 27.001 / 27.131 / 540.131 | 25.761 / 25.823 / 514.922 |
| 10,003 | vp | 48.509 / 52.317 / 986.188 | 47.318 / 50.054 / 955.839 |
| 10,003 | vpr | 73.811 / 116.244 / 1617.710 | 73.371 / 117.784 / 1660.192 |
| 10,003 | vprb | 87.802 / 91.967 / 1780.273 | 86.557 / 90.297 / 1752.764 |

All warm filename comparisons have complete snapshots and equal exact hits.
Small-corpus v/vp/vpr improved around 24%; large-corpus improvements are small,
and vpr's tail/total worsened. Scanning observations (baseline/current):
281 files 12.754/12.556 ms; 10,003 files 155.379/141.354 ms. These are single
observations, not repeated cold-scan conclusions.

Raw local reports: `output/search-fair-549c6ff9.json` and
`output/search-fair-ab118e63.json` (ignored generated artifacts, not Git sources).
Earlier exploratory reports with unequal candidates are not valid comparisons.

## Phase evidence and limited changes

The profiler records process creation, rg output-read wait (including execution),
JSON parsing, path/permission handling, engine/public-result processing and
process cleanup. Phases overlap across reader/main threads and **must not be
summed**; output-read time is not pure rg CPU time. Public-after-engine time
includes result assembly; some inline engine assembly remains within engine total.
No antivirus, disk or thread cause is inferred from these measurements.

Instrumented spawn medians versus ab118e63, milliseconds:

| Phase | Baseline | Current |
| --- | --- | --- |
| Process start | 2.219 | 2.093 |
| rg output-read wait | 9.843 | 9.746 |
| JSON parsing | 0.084 | 0.076 |
| Runtime-scope checks | 0.729 | 0.404 |
| Path processing | 0.461 | 0.319 |
| Cleanup | 0.064 | 0.068 |

Only confirmed repeated work was removed: calculate runtime exclusions once per
direct-rg call, and format already-resolved result paths without resolving those
paths/display roots repeatedly. Filename results still pass the permission
resolver individually on every call, including cache hits. For warm `v` over
281 files, instrumented path time was 4.168 → 3.319 ms while fuzzy scoring stayed
0.335 → 0.337 ms. At 10,003 files, scoring dominates (vprb about 82.5 ms under
instrumentation); this patch does not rewrite the matcher.

The Windows report could locate a different dominant phase. Its new raw profile
is required before concluding why a roughly 100 ms regression occurred there.

## Correctness and retained boundaries

Content snippets now cap each hit at 2,000 characters and all visible hit text
at 16,000 characters. Paths/line numbers remain; `text_truncated`,
`original_text_chars`, `output_truncated` and explicit limit fields disclose
truncation. Completeness cannot be true when snippet output is truncated.
Existing size/timeout/limit reasons retain priority when several limits apply.

Runtime exclusions and explicit-root historical-data searches remain tested.
Real symlink tests run when privileges permit and capability-skip otherwise;
the permission-resolver regression also runs without symlink privileges.
Cancellation, timeout, process isolation/group cleanup and permission checks
are preserved. No new dependency or Nucleo source was introduced.

The tool split and direct-rg path remain. No glob collection/pagination rewrite,
single-file/multi refactor, watcher, database or persistent runtime worker was
added. Concurrency means at most four outer read-only calls; rg manages its own
internal threads. Multi's keywords still execute sequentially with one shared
document load, not keyword-level parallelism.

Validation: the final full suite passed 1,052 tests with one skip; the focused
search/portability/benchmark suite passed 62 tests. These tests used the project's
pinned pathspec 0.12.1 via a temporary
dependency directory; the benchmark dependency version above is recorded
separately rather than presented as the pinned environment.
