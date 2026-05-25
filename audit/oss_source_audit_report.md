# OSS Source-Origin Audit Report
## Scope
This audit reviewed Vintage Programmer source, docs, dependency metadata, and working-tree secrets indicators for possible relationships to:

- `openai/codex`
- `openclaw/openclaw`

The review goal was evidence-based attribution readiness, not legal finality.

## Commands Run
- `git status`
- `git checkout main`
- `git pull --ff-only`
- `git checkout -b oss-audit/source-attribution-review`
- `git grep -n -i "codex|openclaw|responses|chatgpt-account-id|backend-api/codex|auth.openai.com|apply_patch|browser_fallback|openclaw_inspired|codex_core" > audit/keyword_source_hits.txt || true`
- `git grep -l -i "codex|openclaw|responses|chatgpt-account-id|backend-api/codex|auth.openai.com|apply_patch|browser_fallback|openclaw_inspired|codex_core" -- '*.py' '*.js' '*.ts' '*.css' '*.json' '*.yml' '*.yaml' > audit/keyword_source_files.txt || true`
- `git grep -l -i "codex|openclaw|responses|chatgpt-account-id|backend-api/codex|auth.openai.com|apply_patch|browser_fallback|openclaw_inspired|codex_core" -- '*.md' 'NOTICE' > audit/keyword_doc_files.txt || true`
- `jscpd vp codex --no-gitignore --pattern "**/*.{py,js,ts,css,md}" --min-lines 8 --min-tokens 50 --max-size 500kb --max-lines 5000 --skipLocal --absolute --reporters console,json,html --output /tmp/vp-oss-audit/report-vp-vs-codex`
- `jscpd vp openclaw ...` from `/tmp/vp-oss-audit` for a full-tree comparison attempt
- `jscpd /Users/dalizhou/Desktop/new_validation_agent/app/local_tools.py /tmp/vp-oss-audit/openclaw/src/agents/apply-patch.ts /tmp/vp-oss-audit/openclaw/src/agents/tool-catalog.ts /tmp/vp-oss-audit/openclaw/src/agents/tools --no-gitignore --min-lines 8 --min-tokens 50 ...`
- `jscpd /Users/dalizhou/Desktop/new_validation_agent/app/static/app.js /Users/dalizhou/Desktop/new_validation_agent/app/static/styles.css /tmp/vp-oss-audit/openclaw/ui/src/ui --no-gitignore --min-lines 8 --min-tokens 50 ...`
- `python -m pip install pip-licenses`
- `pip-licenses --format=markdown --with-urls --with-description > THIRD_PARTY_LICENSES.md`
- `python -m pip freeze > audit/pip_freeze_snapshot.txt`
- `git grep -n -i "api_key|token|secret|password|bearer|refresh_token|access_token|id_token|account_id|proxy|internal|corp|kioxia|zeus|base_url|ca_cert" > audit/secret_internal_keyword_hits.txt || true`
- `python -m compileall app packages tests`
- `python -m pytest -q`

## Keyword Scan Results
- `audit/keyword_source_hits.txt`: 713 hit lines
- `audit/keyword_source_files.txt`: 31 source/config files
- `audit/keyword_doc_files.txt`: 14 documentation files

Top hit files:

| File | Hit count |
|---|---:|
| `app/static/styles.css` | 246 |
| `app/config.py` | 82 |
| `app/openai_auth.py` | 51 |
| `tests/integration/test_chat_vintage_programmer_api.py` | 35 |
| `packages/office_modules/office_agent_runtime.py` | 27 |
| `app/workbench.py` | 26 |
| `app/codex_runner.py` | 22 |
| `docs/internal_design_manual.md` | 21 |
| `app/static/locales.js` | 15 |
| `app/vintage_programmer_runtime.py` | 12 |

Interpretation:

- Many hits are explicit naming or attribution labels rather than source-copy signals.
- `app/openai_auth.py`, `app/config.py`, and `app/codex_runner.py` are the main Codex compatibility files.
- `app/workbench.py`, `app/local_tools.py`, `app/main.py`, `app/static/app.js`, and `app/static/styles.css` are the main OpenClaw-inspired files.

## Similarity Scan Results
### `vp` vs `openai/codex`
- Full `jscpd` scan completed successfully.
- Result: `Found 0 clones.`
- Output recorded under `/tmp/vp-oss-audit/report-vp-vs-codex`.

### `vp` vs `openclaw/openclaw`
- Full-tree `jscpd` scan attempt failed with Node out-of-memory before a usable report was produced.
- Because that full run was incomplete, it is not sufficient evidence by itself for a blanket zero-clone conclusion.

### Targeted OpenClaw scans
- `app/local_tools.py` vs relevant OpenClaw tool files: `Found 0 clones.`
- `app/static/app.js` and `app/static/styles.css` vs OpenClaw UI sources: one clone was reported, but both ranges were inside local `app/static/styles.css`; no upstream OpenClaw file was involved.

Conclusion from executed scans:

- No direct copied source was identified in the scans that completed successfully.
- OpenClaw full-tree coverage is limited by the failed high-memory run, so the OpenClaw conclusion remains evidence-based but scoped to the reviewed files and targeted scans.

## Codex-Related File Review
| File | Classification | Evidence | Risk |
|---|---|---|---|
| `app/codex_runner.py` | Interface compatibility / independent implementation | Local message-to-Responses conversion, streaming event handling, tool call mapping, and AIMessage reconstruction | Medium |
| `app/openai_auth.py` | Needs owner confirmation | Same auth file family and refresh constants as Codex-compatible auth, but local Python implementation differs from upstream Rust structure | Medium |
| `app/config.py` | Interface compatibility | Codex auth path and endpoint defaults | Medium |
| `app/workbench.py` | Name-only / naming alignment | `codex_core` source labels | Low |
| `app/runtime_contract.py` | Conceptual inspiration | `codex_style_full_auto` label | Low |
| `app/vintage_programmer_runtime.py` | Conceptual inspiration / interface compatibility | Publishes Codex-style core tool contract names | Low |
| `packages/office_modules/office_agent_runtime.py` | Interface compatibility / naming alignment | Selects the local `CodexResponsesRunner` for `codex_auth` and defaults to `codex_core_tools` | Medium |
| `packages/office_modules/tools.py` | Name-only / naming alignment | `codex_core_tools` tool module | Low |
| `packages/office_modules/legacy_runtime_support.py` | Interface compatibility | Legacy payload bridge into local Codex input builder | Low |
| `packages/office_modules/agent_module.py` | Name-only / naming alignment | Default module ID `codex_core_tools` | Low |
| `packages/runtime_core/legacy_host_support.py` | Name-only / compatibility bridge | Legacy mapping from `codex_core_tools` | Low |

Specific conclusion for `app/openai_auth.py`:

- Evidence supports a Codex-compatible auth interoperability layer.
- Evidence does not identify a direct copied block from Codex source.
- Owner confirmation is still recommended because the constants and auth semantics align closely with upstream Codex behavior.

## OpenClaw-Related File Review
| File | Classification | Evidence | Risk |
|---|---|---|---|
| `app/workbench.py` | Conceptual inspiration | Explicit `openclaw_inspired` and `openclaw_fallback` labels | Medium |
| `app/local_tools.py` | Independent local implementation / interface compatibility | Local Python `apply_patch` parser/executor; targeted clone scan found 0 upstream matches | Medium |
| `app/main.py` | Runtime pattern inspiration | `OpenClaw-style lane queue` docstring | Low |
| `app/static/app.js` | UX inspiration / naming alignment | `OpenClaw-first Tools · Codex-style Workspace` | Low |
| `app/static/styles.css` | UX inspiration | `theme-openclaw` naming and shell styling | Low |
| `packages/office_modules/office_agent_runtime.py` | Naming alignment / interface compatibility | Publishes `apply_patch` as `Codex/OpenClaw-style freeform patch` while delegating to local tool code | Low |
| `tests/integration/test_chat_vintage_programmer_api.py` | Name-only / test fixture compatibility | Encodes `openclaw_inspired` source values in descriptors | Low |

Important nuance:

- Some names such as `sessions_list`, `sessions_history`, and `apply_patch` align with OpenClaw’s tool catalog.
- Other file-system tool names in Vintage Programmer do not match the canonical OpenClaw tool names one-for-one.
- That pattern is more consistent with inspiration plus local implementation than with wholesale copying.

## Files Requiring Owner Confirmation
- `app/openai_auth.py`
- `app/codex_runner.py`
- `app/workbench.py`
- `app/local_tools.py`

Owner confirmation does not mean copied source was found. It means provenance questions remain worth answering before broader release.

## Files With No Direct Copy Identified
- `app/codex_runner.py`
- `app/config.py`
- `app/workbench.py`
- `app/runtime_contract.py`
- `app/vintage_programmer_runtime.py`
- `app/local_tools.py`
- `app/main.py`
- `app/static/app.js`
- `app/static/styles.css`
- `packages/office_modules/office_agent_runtime.py`
- `packages/office_modules/tools.py`
- `packages/office_modules/legacy_runtime_support.py`
- `packages/office_modules/agent_module.py`
- `packages/runtime_core/legacy_host_support.py`
- `tests/integration/test_chat_vintage_programmer_api.py`

## Dependency License Review
Generated artifacts:

- `THIRD_PARTY_LICENSES.md`
- `audit/pip_freeze_snapshot.txt`

Packages requiring manual review:

- `extract-msg` (`GPL`)
- `pcodedmp` (`GPLv3`)
- `pillow_heif` (`GPLv2`)
- `RTFDE` (`LGPLv3`)
- `certifi` (`MPL 2.0`)
- `orjson` (`MPL-2.0 AND (Apache-2.0 OR MIT)`)
- `tqdm` (`MPL-2.0 AND MIT`)
- `uvloop` (`UNKNOWN` in generated metadata)

These are dependency-license review items, not source-copy findings.

## Secret/Internal Info Review
- `audit/secret_internal_keyword_hits.txt` captured 1457 hit lines.
- Most hits were placeholders, config keys, tests with fake values, or vendor bundle noise.
- No live secret value was identified in the reviewed working tree.
- Internal-only or release-hygiene items were found:
  - `docs/internal_design_manual.md`
  - `packages/README.md`
- `gitleaks` and `trufflehog` were unavailable, so no history-based secret scan or verified-secret scan was completed.

## Validation Results
- `./.venv/bin/python -m compileall app packages tests`: passed
- `pytest -q`: passed, `354 passed in 38.91s`
- `pytest` emitted one `pytest-asyncio` deprecation warning about `asyncio_default_fixture_loop_scope` being unset
- No frontend package manifest or lockfile was present, so no separate frontend syntax-check target was available to run

## Final Risk Classification
Overall source-origin risk classification: Medium

Rationale:

- Low risk evidence: many hits are documentation, naming alignment, or declared conceptual inspiration.
- Medium risk evidence: Codex auth compatibility and `apply_patch` grammar alignment mirror upstream behavior closely enough to deserve provenance confirmation.
- High risk evidence not identified in this review: no successful scan or manual comparison found a direct copied source block, embedded upstream file, or missing adapted-file license header.

Separate non-source-copy risks:

- Dependency license review: Medium to High because GPL/LGPL/MPL/UNKNOWN items are present in the generated dependency report.
- Release-hygiene review: Medium because internal-only docs are present and linked from README files.

## Recommended Next Actions
- Confirm provenance for `app/openai_auth.py`.
- Confirm whether `app/codex_runner.py` was independently implemented from public API behavior.
- Keep `NOTICE`, `THIRD_PARTY_ATTRIBUTIONS.md`, and `THIRD_PARTY_LICENSES.md`.
- Review GPL/LGPL/MPL/UNKNOWN dependency items before broader release.
- Review internal-only documentation before company-wide promotion or external distribution.
