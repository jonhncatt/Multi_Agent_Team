# Tool Metadata Migration Report

## Summary
This change removes Codex auth compatibility from the runtime path, normalizes native tool metadata, adds a single-source metadata registry, and inserts a conservative metadata capability check into `ActionValidator`.

Stability was prioritized over broad refactors:
- tool names stayed stable
- existing path/url/shell safety checks stayed in place
- hardcoded validator tables stayed in place
- optional dependencies stayed advisory

## Files Changed
- Added: `app/tool_metadata.py`, `docs/native_tool_metadata.md`
- Updated runtime/UI wiring: `app/workbench.py`, `app/action_validator.py`, `app/runtime_boundary.py`, `app/vintage_programmer_runtime.py`
- Updated auth/config: `app/openai_auth.py`, `app/config.py`, `.env.example`, `run.sh`, `run.ps1`
- Updated office runtime path: `packages/office_modules/tools.py`, `packages/office_modules/office_agent_runtime.py`, `packages/office_modules/manifest.json`, `packages/office_modules/agent_module.py`
- Updated docs/tests/evals: `README*`, `docs/internal_design_manual.md`, `tests/*`, `evals/*`
- Removed: `app/codex_runner.py`

## Codex Auth Removal Status
- Complete for runtime/auth/config/startup/docs/tests/evals.
- The post-removal grep for Codex auth compatibility terms is empty.

## Legacy Runtime Label Removal Status
- Complete for runtime metadata labels: no `codex_core`, `openclaw_inspired`, or `openclaw_fallback` remain in runtime code.
- Generic `OpenClaw` UI/theme naming was normalized out of app code and CSS.
- Remaining generic `codex` references are limited to external model identifiers in `app/pricing.py`.
- See `audit/post_codex_openclaw_all_hits.txt` for the final repository-wide case-insensitive snapshot.

## Metadata Registry Status
- `app/tool_metadata.py` is now the single source of truth for native tool metadata.
- Actual registered tools: `29`
- Metadata coverage: `29 / 29`
- Metadata-only extras: `0`
- Missing metadata: `0`

See:
- `audit/actual_tool_specs.json`
- `audit/actual_tool_names.txt`
- `audit/tool_registry_report.md`

## ActionValidator Capability Check Status
- Added an additive metadata capability check after:
  1. tool exists
  2. tool is allowed by the current runtime
- The metadata check compares tool requirements against `RuntimeBoundary` for:
  - `workspace_read`
  - `workspace_write`
  - `shell`
  - `network`
  - `browser`
- `browser_allowed` was added to `RuntimeBoundary` with a backward-compatible default and derived conservatively from network policy in the turn builder.

## Validation Order
Current runtime order is:
1. tool exists?
2. tool allowed by current runtime?
3. metadata capability requirement and boundary comparison
4. schema validation
5. argument-level placeholder/path/url/command validation
6. execute tool

This matches the target direction conservatively. The main intentional limitation is that optional dependency enforcement is still advisory rather than blocking.

## Behavior Changes
- Codex auth fallback is gone. Runtime auth now depends on explicit provider configuration only.
- Workbench tool descriptors now read from `app/tool_metadata.py`.
- Tool metadata `group`/`source` labels now use native capability vocabulary instead of legacy inspiration labels.
- Browser capability can now be denied explicitly with `browser_not_allowed`.

## Pending Optional Dependency Enforcement
`optional_dependency` is currently documentation metadata only.

This phase does not block tools when optional dependencies are unavailable, because that would be a behavior change larger than the requested conservative scope.

## Pending Metadata-Driven Permission Integration
The following hardcoded tables remain intentionally:
- `app.action_validator._NETWORK_TOOLS`
- `app.action_validator._SHELL_TOOLS`
- `app.action_validator._READ_PATH_FIELDS`
- `app.action_validator._WRITE_PATH_FIELDS`
- `app.vintage_programmer_runtime._READ_ONLY_TOOL_NAMES`
- `app.vintage_programmer_runtime._WRITE_TOOL_NAMES`

They remain because they still carry path-level and policy-level behavior that was not safe to replace wholesale in this task.

## Tests Run
- Baseline:
  - `python -m compileall app packages tests`
  - `python -m pytest -q`
- Final validation:
  - `python -m compileall app packages tests` -> passed
  - `python -m pytest -q` -> `366 passed in 35.30s`
  - `git grep -n "codex_auth|VP_CODEX_AUTH_FILE|VP_CODEX_HOME|DEFAULT_CODEX|backend-api/codex|auth.openai.com|chatgpt-account-id" || true`
  - `git grep -n "codex_core|openclaw_inspired|openclaw_fallback" || true`

## Manual Smoke Test
Manual browser/UI smoke testing was not performed in this task.

## Remaining Risks
- `app/pricing.py` still includes external model identifiers such as `gpt-5-codex`; these are provider model names, not runtime metadata labels.
- Optional dependency availability is not enforced yet.
- Permission integration is still partly split between metadata capability checks and legacy hardcoded validator/runtime tables.
- `OSS_REVIEW.md` and `THIRD_PARTY_ATTRIBUTIONS.md` were not present in this repository snapshot, so they were not updated.

## Owner Confirmation Items
- Decide whether external model alias catalogs like `gpt-5-codex` should remain in-product or move into a provider-specific pricing file later.
- Decide whether repo-level compliance summary files should be added in a separate change set.
