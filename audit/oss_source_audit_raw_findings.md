# OSS Source Audit Raw Findings
## Review Context
- Repository under review: `jonhncatt/Multi_Agent_Team`
- Product name: `Vintage Programmer`
- Review branch: `oss-audit/source-attribution-review`
- Review date: 2026-05-26

## Keyword Scan Raw Summary
- `audit/keyword_source_hits.txt`: 713 lines
- `audit/keyword_source_files.txt`: 31 files
- `audit/keyword_doc_files.txt`: 14 files

Top files by keyword-hit count:

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
| `packages/office_modules/tools.py` | 12 |

Documentation files with hits:

- `NOTICE`
- `README.md`
- `README.en.md`
- `README.ja.md`
- `README.zh-CN.md`
- `README.windows.md`
- `RELEASING.md`
- `agents/vintage_programmer/agent.md`
- `agents/vintage_programmer/tools.md`
- localized agent/tool specs under `agents/vintage_programmer/locales/...`
- `docs/internal_design_manual.md`

## Codex-Related Raw Review Notes
### `app/codex_runner.py`
Observed behaviors:

- Builds local Responses-style input payload from system/human/assistant/tool messages.
- Sends `chatgpt-account-id` in default headers.
- Streams `response.output_text.delta`, `response.completed`, and `response.failed`.
- Converts Responses output items and function calls back into local AIMessage objects.

Raw assessment:

- Relationship type: interface compatibility / independent implementation
- No direct copied source identified in this review

### `app/openai_auth.py`
Observed behaviors:

- Reads `.codex/auth.json`-style token fields: `access_token`, `refresh_token`, `account_id`, `id_token`, `last_refresh`
- Uses:
  - client ID `app_EMoamEEZ73f0CkXaXp7hrann`
  - refresh URL `https://auth.openai.com/oauth/token`
  - chat backend family `https://chatgpt.com/backend-api/codex`
  - refresh cadence `8` days
- Writes refreshed token data back to `auth.json`

Comparison nuance against inspected Codex upstream files:

- Upstream Codex stores a richer `AuthDotJson` structure including `auth_mode`, `OPENAI_API_KEY`, `tokens`, `last_refresh`, and `agent_identity`.
- Upstream Rust auth code also supports account-id recovery through parsed JWT claim helpers.
- The local file is Python, structured differently, and does not reuse upstream Rust parsing/layout directly.

Raw assessment:

- Relationship type: Codex-compatible auth interoperability
- Copied source status: no direct copied block identified in review
- Status: needs owner confirmation because constants and file semantics align closely with upstream behavior

### `app/config.py`
Observed behaviors:

- Defaults `VP_CODEX_HOME` to `~/.codex`
- Defaults auth file to `~/.codex/auth.json`
- Defaults chat backend to `https://chatgpt.com/backend-api/codex`
- Defaults refresh URL to `https://auth.openai.com/oauth/token`
- Defaults client ID to `app_EMoamEEZ73f0CkXaXp7hrann`

Raw assessment:

- Relationship type: interface compatibility
- No direct copied source identified in this review

### Other Codex-labeled or Codex-aligned files
- `app/workbench.py`: `codex_core` source/group labels
- `app/runtime_contract.py`: `codex_style_full_auto`
- `app/vintage_programmer_runtime.py`: exposes Codex-style tool contracts in runtime descriptors
- `packages/office_modules/office_agent_runtime.py`: selects the local `CodexResponsesRunner` for `codex_auth` and defaults to `codex_core_tools`
- `packages/office_modules/tools.py`: `codex_core_tools` tool module
- `packages/office_modules/legacy_runtime_support.py`: wraps `build_codex_input_payload`
- `packages/office_modules/agent_module.py`: defaults `selected_tool_module_id="codex_core_tools"`
- `packages/runtime_core/legacy_host_support.py`: legacy compatibility mapping from `codex_core_tools`

These items read as naming alignment, compatibility bridges, or conceptual inspiration rather than copy evidence.

## OpenClaw-Related Raw Review Notes
### `app/workbench.py`
Observed behaviors:

- Several file/session/media tools are explicitly labeled `openclaw_inspired`
- Browser fallback tools are labeled `openclaw_fallback`

Raw assessment:

- Relationship type: conceptual inspiration / self-declared source labeling
- No direct copied source identified in this review

### `app/local_tools.py`
Observed behaviors:

- Defines `_parse_codex_patch(...)`
- Describes `apply_patch` as `Codex/OpenClaw-style freeform patch`
- Implements its own Python parser/executor for add/update/delete patch operations

Comparison nuance against inspected OpenClaw upstream files:

- OpenClaw has an `apply_patch` tool and patch marker grammar in TypeScript.
- The local implementation is Python and structurally different from OpenClaw’s TypeScript implementation.

Raw assessment:

- Relationship type: interface compatibility / local independent implementation
- No direct copied source identified in targeted scan

### `app/main.py`
- Contains `OpenClaw-style lane queue` in the queue docstring
- Relationship type: runtime pattern inspiration

### `app/static/app.js`
- Empty state text says `OpenClaw-first Tools · Codex-style Workspace`
- Relationship type: UX inspiration / naming alignment

### `app/static/styles.css`
- Defines `theme-openclaw` and `.app-shell--openclaw`
- Relationship type: UX inspiration

### `tests/integration/test_chat_vintage_programmer_api.py`
- Test descriptors encode `openclaw_inspired` and `codex_core`
- Relationship type: test fixture naming alignment

### `packages/office_modules/office_agent_runtime.py`
- Selects the local `CodexResponsesRunner` when auth mode is `codex_auth`
- Describes `apply_patch` as `Codex/OpenClaw-style freeform patch`
- Defaults `selected_tool_module_id` to `codex_core_tools`
- Relationship type: interface compatibility / naming alignment

## Similarity Scan Raw Results
### Full `vp` vs `codex`
Command family:

- `jscpd vp codex --no-gitignore --pattern "**/*.{py,js,ts,css,md}" --min-lines 8 --min-tokens 50 ...`

Result:

- `Found 0 clones.`

Interpretation:

- No clone block was reported by the completed full-repository Codex comparison.

### Full `vp` vs `openclaw`
Command family:

- `jscpd vp openclaw --no-gitignore --pattern "**/*.{py,js,ts,css,md}" --min-lines 8 --min-tokens 50 ...`

Result:

- Run failed with Node out-of-memory before producing a usable final report.

Interpretation:

- Full-tree OpenClaw clone coverage is incomplete in this review.

### Targeted OpenClaw scan: local tools
Compared:

- local `app/local_tools.py`
- upstream `openclaw/src/agents/apply-patch.ts`
- upstream `openclaw/src/agents/tool-catalog.ts`
- upstream `openclaw/src/agents/tools`

Result:

- `Found 0 clones.`

### Targeted OpenClaw scan: UI and styles
Compared:

- local `app/static/app.js`
- local `app/static/styles.css`
- upstream `openclaw/ui/src/ui`

Result:

- one clone reported
- both file ranges were inside local `app/static/styles.css`
- no upstream OpenClaw file was part of the reported clone

Interpretation:

- targeted UI scan did not identify an upstream copy block

## Dependency License Raw Findings
Generated files:

- `THIRD_PARTY_LICENSES.md`
- `audit/pip_freeze_snapshot.txt`

License-sensitive items identified in generated output:

- `extract-msg` (`GPL`)
- `pcodedmp` (`GPLv3`)
- `pillow_heif` (`GPLv2`)
- `RTFDE` (`LGPLv3`)
- `certifi` (`MPL 2.0`)
- `orjson` (`MPL-2.0 AND (Apache-2.0 OR MIT)`)
- `tqdm` (`MPL-2.0 AND MIT`)
- `uvloop` (`UNKNOWN` metadata in generated report)

## Secret / Internal Information Raw Findings
Keyword scan result:

- `audit/secret_internal_keyword_hits.txt`: 1457 lines

Top hit files:

| File | Hit count |
|---|---:|
| `app/static/vendor/marked.umd.js` | 419 |
| `app/config.py` | 166 |
| `app/openai_auth.py` | 79 |
| `packages/office_modules/office_agent_runtime.py` | 71 |
| `app/static/app.js` | 67 |
| `app/main.py` | 59 |
| `app/local_tools.py` | 53 |

Noise sources:

- vendor bundles under `app/static/vendor`
- configuration key names
- test fixtures with fake values

Curated non-vendor observations:

- `.env.example` uses placeholders only
- README files include example API keys and example base URLs
- `tests/test_vp_env_config.py` and related tests use fake values such as `test-key`, `router-key`, and fake auth JSON
- `docs/internal_design_manual.md` is explicitly labeled internal
- `packages/README.md` marks part of the package tree as internal/experimental

Tool availability:

- `gitleaks`: unavailable
- `trufflehog`: unavailable

Raw assessment:

- No live secret value identified in the reviewed working tree
- Internal-only documentation is present and should be reviewed before broader release

## Validation Raw Results
- `./.venv/bin/python -m compileall app packages tests`: passed
- `pytest -q`: passed, `354 passed in 38.91s`
- `pytest` emitted a `pytest-asyncio` deprecation warning about `asyncio_default_fixture_loop_scope`
- No `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, or `bun.lockb` file was present, so no standalone frontend syntax-check command was available

## Working Conclusion
- No direct copied source identified in this review
- Codex-related behavior is primarily compatibility-oriented, with `app/openai_auth.py` needing owner confirmation
- OpenClaw-related behavior is primarily conceptual, UX, or interface inspiration, with no upstream clone found in targeted scans
- Dependency license review remains required
- Internal-document review remains required
