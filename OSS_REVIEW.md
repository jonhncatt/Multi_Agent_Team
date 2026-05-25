# Vintage Programmer OSS Review Summary
## Project
- Name: Vintage Programmer
- Repository: jonhncatt/Multi_Agent_Team
- Review purpose: company-wide internal promotion / OSS compliance preparation

## Review Scope
This review checks:
- Codex-related source usage
- OpenClaw-related source usage
- third-party dependency licenses
- possible secrets/internal information
- attribution and NOTICE readiness

## Executive Summary
This review found Codex-compatible and OpenClaw-inspired components. Based on keyword review, a full `jscpd` scan against `openai/codex`, and targeted `jscpd` scans against relevant `openclaw/openclaw` directories, no direct copied source was identified in this review. `app/openai_auth.py` remains marked as owner-confirmation required because it mirrors Codex CLI auth file semantics and auth endpoint constants closely enough to warrant provenance confirmation even though no copied block was identified.

## Codex-Related Findings
| File | Relationship type | Evidence | Risk level | Required action |
|---|---|---|---|---|
| `app/codex_runner.py` | Interface compatibility / independent implementation | Converts message history into Responses-style input, sends `chatgpt-account-id`, handles `response.output_text.delta` and `response.completed`, and converts tool calls back into local AIMessage objects | Medium | Keep and document as a compatibility adapter |
| `app/openai_auth.py` | Auth interoperability; needs owner confirmation | Reads `~/.codex/auth.json`-style token fields, uses the same refresh URL, client ID, and 8-day refresh cadence seen in Codex upstream behavior; implementation is Python and structurally different from upstream Rust | Medium | Confirm with owner whether this was independently written from observed behavior or adapted from Codex source |
| `app/config.py` | Interface compatibility | Defaults point to `.codex/auth.json`, `https://chatgpt.com/backend-api/codex`, `https://auth.openai.com/oauth/token`, and the Codex client ID | Medium | Keep and document as config compatibility |
| `app/workbench.py` | Naming alignment | Uses `codex_core` group/source labels for shell, patch, planning, and structured-input tools | Low | Keep |
| `app/runtime_contract.py` | Conceptual inspiration | Uses `reason="codex_style_full_auto"` | Low | Keep |
| `app/vintage_programmer_runtime.py` | Conceptual inspiration / interface compatibility | Publishes Codex-style tool contracts such as `apply_patch`, `update_plan`, and `request_user_input` inside the runtime descriptor | Low | Keep |
| `packages/office_modules/office_agent_runtime.py` | Interface compatibility / naming alignment | Selects `CodexResponsesRunner` for `codex_auth` mode, exposes `apply_patch` as `Codex/OpenClaw-style freeform patch`, and defaults to `codex_core_tools` | Medium | Keep and document as an integration bridge |
| `packages/office_modules/tools.py` | Naming alignment | Declares `codex_core_tools` and the expected Codex-style core tool names | Low | Keep |
| `packages/office_modules/legacy_runtime_support.py` | Interface compatibility | Exposes `legacy_codex_input_payload` by wrapping the local Responses input builder | Low | Keep |
| `packages/office_modules/agent_module.py` | Naming alignment | Uses `selected_tool_module_id="codex_core_tools"` as the default bridge identifier | Low | Keep |
| `packages/runtime_core/legacy_host_support.py` | Naming alignment / compatibility bridge | Maps legacy `codex_core_tools` to `workspace_tools` for compatibility | Low | Keep |

## OpenClaw-Related Findings
| File | Relationship type | Evidence | Risk level | Required action |
|---|---|---|---|---|
| `app/workbench.py` | Conceptual inspiration | Explicitly labels several tool groups as `openclaw_inspired` and browser fallbacks as `openclaw_fallback` | Medium | Keep and document as declared inspiration |
| `app/local_tools.py` | Interface compatibility / independent local implementation | Implements a local `apply_patch` parser and executor, and advertises a `Codex/OpenClaw-style freeform patch`; targeted `jscpd` scan against relevant OpenClaw tool files found 0 clones | Medium | Keep and document grammar alignment |
| `app/main.py` | Runtime pattern inspiration | Docstring describes the queue as `OpenClaw-style lane queue` | Low | Keep |
| `app/static/app.js` | UX inspiration / naming alignment | UI empty state says `OpenClaw-first Tools · Codex-style Workspace` | Low | Keep |
| `app/static/styles.css` | UX inspiration | Defines `theme-openclaw` and `.app-shell--openclaw`; targeted scan found only an internal self-duplicate within this file, not an upstream clone | Low | Keep |
| `packages/office_modules/office_agent_runtime.py` | Naming alignment / interface compatibility | Advertises `apply_patch` as `Codex/OpenClaw-style freeform patch` while routing through local tool implementations | Low | Keep |
| `tests/integration/test_chat_vintage_programmer_api.py` | Naming alignment / test fixture compatibility | Test descriptors assert `openclaw_inspired` and `codex_core` source labels | Low | Keep |

## Dependency License Findings
`THIRD_PARTY_LICENSES.md` and `audit/pip_freeze_snapshot.txt` were generated from the active Python environment. Items requiring manual license review include:

- `extract-msg` (`GPL`)
- `pcodedmp` (`GPLv3`)
- `pillow_heif` (`GPLv2`)
- `RTFDE` (`LGPLv3`)
- `certifi` (`MPL 2.0`)
- `orjson` (`MPL-2.0 AND (Apache-2.0 OR MIT)`)
- `tqdm` (`MPL-2.0 AND MIT`)
- `uvloop` (`UNKNOWN` metadata in generated report)

No dependencies were removed automatically.

## Secret/Internal Information Findings
The working-tree keyword scan found many placeholder or documentation-only values in `.env.example`, READMEs, and tests. No live secret value was identified in the reviewed working tree. Two release-hygiene items still need review:

- `docs/internal_design_manual.md` is explicitly labeled internal and is linked from public README files.
- `packages/README.md` marks `packages/office_addons` as internal/experimental.

History-based secret scanning was not completed because `gitleaks` and `trufflehog` were not available in the environment during this review.

## Recommended Actions Before Company-Wide Promotion
- [ ] Confirm whether `app/openai_auth.py` was written independently or adapted from Codex CLI source.
- [ ] Confirm whether `app/codex_runner.py` contains any copied Codex source.
- [ ] Confirm whether OpenClaw-inspired tools are concept-only or adapted source.
- [ ] Review any GPL/AGPL/LGPL/UNKNOWN dependency licenses.
- [ ] Review and redact any internal/company-specific information.
- [ ] Keep `NOTICE`.
- [ ] Keep `THIRD_PARTY_ATTRIBUTIONS.md`.
- [ ] Keep `THIRD_PARTY_LICENSES.md`.
