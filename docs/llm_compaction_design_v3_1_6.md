# LLM Compaction Design (v3.1.6)

> Legacy design record. The current Thread V4 implementation is defined in
> `docs/thread_transcript_architecture.md`. In particular, `task_state`,
> `work_cursor`, `context_manager`, and the expanded `compaction_state` below
> are no longer current persistence or model-input contracts.

## Scope

This document fixes the target contract for a later compaction pass. It does not change runtime behavior in `v3.1.6`.

## Trigger

- Pre-turn, after session load and before the main agent call.
- Optional mid-turn, only when context pressure crosses the active compaction threshold and the runtime is between tool/model phases.
- Never inside the normal tool loop as a tool-visible step.

## Model / Provider Selection

- Use a dedicated compactor call with `enable_tools=False`.
- Default to the active provider when available.
- Allow an internal fallback model profile for providers with smaller context or lower latency.
- Record which provider/model performed compaction in `compaction_state`.

## Input Payload

- Compacted history candidate turns.
- Current `task_state`.
- Current `work_cursor`.
- Current `context_manager`.
- Recent tool evidence and failed attempts.
- Modified files / touched attachments.
- Current thread/project identifiers.

## Output Schema

- `confirmed_facts`
- `files_touched`
- `decisions`
- `failed_attempts`
- `current_state`
- `next_steps`
- `open_questions`
- `do_not_repeat`

## Canonical Writes

- `context_manager`: model-visible cleaned summary and compacted history summary.
- `task_state`: failed attempts, current state summary, next required action, evidence refs when applicable.
- `work_cursor`: only file / attachment / cwd state when explicitly confirmed by the compactor payload.
- `compaction_state`: ledger fields such as generation, source, timestamps, reason, schema version, and fallback notes.

## Fallback

- Deterministic fallback remains mandatory.
- When fallback runs, write `compaction_source=fallback` and `fallback_reason`.
- Keep the same output shape so downstream readers never branch on payload structure.

## Trace Isolation

- Keep the compactor call out of the user-facing tool timeline.
- Preserve raw compaction trace and prompts only in run artifacts / internal diagnostics.
- Do not write raw prompt or raw model exchange into session summary fields.
