# Third-Party Attributions and Source-Origin Notes
## Scope
This file documents known third-party inspiration, interface compatibility, and potential source-origin relationships for Vintage Programmer.
This file is informational and does not replace `LICENSE` or `NOTICE`.

## Summary
| Upstream | License | Relationship | Direct copied source identified? | Notes |
|---|---|---|---|---|
| `openai/codex` | Apache-2.0 | Codex-style tool naming, auth-file compatibility, and Responses/Codex-compatible adapter concepts | No direct copied source identified in this review | `app/openai_auth.py` still needs owner confirmation because it mirrors auth semantics/constants closely |
| `openclaw/openclaw` | MIT | Tool grouping labels, browser fallback naming, `apply_patch` grammar alignment, and OpenClaw-themed UX cues | No direct copied source identified in this review | Full-tree `jscpd` scan hit Node memory limits; targeted scans of relevant local files/directories found no upstream clones |

## File-Level Matrix
| File | Upstream | Relationship Type | Evidence | Copied Source Status | Action |
|---|---|---|---|---|---|
| `app/codex_runner.py` | `openai/codex` / OpenAI Responses API | Interface compatibility / independent implementation | Uses Responses event names, tool-call mapping, local message-to-input conversion, and local response-to-AIMessage conversion | No direct copy identified in review; full `vp` vs `codex` `jscpd` scan found 0 clones | Keep, document |
| `app/openai_auth.py` | `openai/codex` | Auth interoperability; potential derived source needs owner confirmation | Reads Codex-compatible auth file token fields and refreshes them using matching endpoint/client-ID defaults | No direct copied block identified in review; owner confirmation required | Confirm provenance, keep attribution |
| `app/config.py` | `openai/codex` | Interface compatibility | Uses `.codex/auth.json`, backend-api/codex base URL, refresh URL, and client ID defaults aligned with Codex auth behavior | No direct copy identified in review | Keep, document |
| `app/workbench.py` | `openai/codex` | Naming alignment | Uses `codex_core` source/group labels | No direct copy identified in review | Keep |
| `app/runtime_contract.py` | `openai/codex` | Conceptual inspiration | Uses `codex_style_full_auto` as runtime reason text | No direct copy identified in review | Keep |
| `app/vintage_programmer_runtime.py` | `openai/codex` | Conceptual inspiration / interface compatibility | Exposes Codex-style tool contracts such as `apply_patch`, `update_plan`, and `request_user_input` | No direct copy identified in review | Keep |
| `packages/office_modules/office_agent_runtime.py` | `openai/codex` | Interface compatibility / integration bridge | Selects the local `CodexResponsesRunner` for `codex_auth` mode and defaults to `codex_core_tools` | No direct copy identified in review | Keep |
| `packages/office_modules/tools.py` | `openai/codex` | Naming alignment | Declares `codex_core_tools` and the expected core tool names | No direct copy identified in review | Keep |
| `packages/office_modules/legacy_runtime_support.py` | `openai/codex` | Interface compatibility | Bridges legacy message payloads through the local Codex input builder | No direct copy identified in review | Keep |
| `packages/office_modules/agent_module.py` | `openai/codex` | Naming alignment | Defaults `selected_tool_module_id` to `codex_core_tools` | No direct copy identified in review | Keep |
| `packages/runtime_core/legacy_host_support.py` | `openai/codex` | Naming alignment / compatibility bridge | Maps `codex_core_tools` to a legacy workspace tool module name | No direct copy identified in review | Keep |
| `app/workbench.py` | `openclaw/openclaw` | Conceptual inspiration | Uses `openclaw_inspired` and `openclaw_fallback` as explicit source labels | No direct copy identified in review | Keep, document |
| `app/local_tools.py` | `openclaw/openclaw` | Interface compatibility / local independent implementation | Local Python `apply_patch` parser/executor; targeted `jscpd` scan against relevant OpenClaw tool files found 0 clones | No direct copy identified in targeted scan | Keep, document |
| `app/main.py` | `openclaw/openclaw` | Runtime pattern inspiration | Queue docstring says `OpenClaw-style lane queue` | No direct copy identified in review | Keep |
| `app/static/app.js` | `openclaw/openclaw` | UX inspiration / naming alignment | Empty state says `OpenClaw-first Tools · Codex-style Workspace` | No direct copy identified in review | Keep |
| `app/static/styles.css` | `openclaw/openclaw` | UX inspiration | `theme-openclaw` and `.app-shell--openclaw` theme naming | No direct upstream copy identified; targeted scan found only a local self-duplicate | Keep |
| `packages/office_modules/office_agent_runtime.py` | `openclaw/openclaw` | Naming alignment / interface compatibility | Exposes `apply_patch` with `Codex/OpenClaw-style` wording while routing to local tool implementations | No direct copy identified in review | Keep |
| `tests/integration/test_chat_vintage_programmer_api.py` | `openai/codex`, `openclaw/openclaw` | Naming alignment / test fixture compatibility | Test descriptors encode `codex_core` and `openclaw_inspired` source labels | No direct copy identified in review | Keep |

## Notes
- This review did not identify evidence of wholesale vendoring of `openai/codex` or `openclaw/openclaw`.
- `app/openai_auth.py` is the main owner-confirmation item because it closely mirrors Codex auth-file behavior and constants even though the local implementation structure differs from the upstream Rust implementation.
- `app/local_tools.py` aligns with the `apply_patch` grammar family used by Codex/OpenClaw, but the reviewed parser/executor is locally implemented in Python and the targeted clone scan found no copied blocks.
