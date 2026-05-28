# Codex Auth Removal Report

## Removed Runtime Features
- Removed `codex_auth` runtime mode and its config/env compatibility path.
- Removed `.codex/auth.json` lookup and refresh-token flow.
- Removed `VP_CODEX_HOME` and `VP_CODEX_AUTH_FILE` handling from runtime config/startup scripts.
- Removed `DEFAULT_CODEX_CLIENT_ID`, `DEFAULT_CODEX_CHATGPT_BASE_URL`, `DEFAULT_CODEX_REFRESH_URL`, and related refresh interval logic.
- Removed `chatgpt-account-id` header usage.
- Removed `app/codex_runner.py` because it only served the removed Codex auth path.

## Remaining Allowed References
- `audit/post_codex_auth_removal_hits.txt` is empty.
- No `codex_auth`-specific references remain in runtime code, README files, env examples, tests, or evals.
- Generic `codex` strings still appear only in `app/pricing.py` as external model identifiers such as `gpt-5-codex`. These are provider/model names, not auth compatibility code.

## Files Changed
- Runtime/auth/config:
  `app/openai_auth.py`, `app/config.py`, `app/vintage_programmer_runtime.py`, `packages/office_modules/office_agent_runtime.py`
- Tool/runtime metadata wiring:
  `app/tool_metadata.py`, `app/workbench.py`, `app/action_validator.py`, `app/runtime_boundary.py`
- Startup/env/docs:
  `.env.example`, `run.sh`, `run.ps1`, `README*`
- Tests/evals:
  `tests/test_vp_env_config.py`, `tests/test_vintage_programmer_runtime.py`, `tests/integration/test_chat_vintage_programmer_api.py`, `evals/cases.json`, `evals/gate_cases.json`

## Tests Updated
- Replaced Codex auth fallback expectations with explicit provider API-key expectations.
- Updated tool metadata expectations in integration/tool registration tests.
- Added dedicated metadata and validator-order tests.

## Verification Command Results
- `git grep -n "codex_auth|VP_CODEX_AUTH_FILE|VP_CODEX_HOME|DEFAULT_CODEX|backend-api/codex|auth.openai.com|chatgpt-account-id" > audit/post_codex_auth_removal_hits.txt || true`
  Result: `0` lines.
- `git grep -n "codex_core|openclaw_inspired|openclaw_fallback" > audit/post_legacy_tool_label_hits.txt || true`
  Result: `0` lines.

## Owner Confirmation Items
- `OSS_REVIEW.md` and `THIRD_PARTY_ATTRIBUTIONS.md` were not present in this repository snapshot, so they were not updated in this task.
- If the repository later wants repo-level compliance summaries, add those files in a separate compliance-focused change rather than mixing them into runtime cleanup.
