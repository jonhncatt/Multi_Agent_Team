# Runtime Reliability Baseline

This document records the reliability behavior that must remain stable after the Session = Thread migration.

## Thread compaction

- The durable conversation source is `thread_transcript`; legacy `turns` remain readable only for Session migration.
- A compaction summary is unverified continuation memory derived from transcript items and source-marked tool evidence. It does not copy Harness task state, work cursor, permissions, or the former six-element context structure.
- GPT-5.4 uses a 272,000-token default usable window and a 90% automatic compaction threshold. A verified company deployment may override the usable window with `VP_CONTEXT_WINDOW_TOKENS` or the threshold with `VP_CONTEXT_AUTO_COMPACT_TOKEN_LIMIT`.
- The latest provider-reported `input_tokens` is preferred. When it is unavailable, the Runtime estimates the complete request, including the system prompt, project instructions, compacted summary, transcript, attachments, current request, tool transactions, and selected tool schemas.
- Retained history is selected as complete user-started transactions and is also token-bounded, so a single large tool result cannot silently defeat compaction.
- Compaction is an internal Thread operation, not a chat Turn. Its minimal persisted record is `Thread.compaction = {generation, summary, compacted_until_item_id, compacted_at}`. `compaction_summary_chars` remains diagnostic metadata only. A Turn paused on an unresolved tool call cannot be compacted.

## Paused Turn lifecycle

- A command approval or `request_user_input` pauses the current Turn instead of ending it and creating a new user Turn.
- The Assistant tool call remains in `thread_transcript` without a placeholder result while the UI waits.
- Approve, decline, and answer actions produce exactly one ToolMessage with the original `tool_call_id`; they never produce synthetic HumanMessages.
- The active Plan is retained only while the Turn is paused. Once the Turn ends, the Plan remains available through transcript history but is not restored as the next Turn's active Plan.
- Loop safeguards remain Harness-owned, but `[checkpoint_replan]` is telemetry only and is never inserted into model-visible history.

## Technical Turn status

The persisted Turn Trace has one technical status: `running`, `waiting_user`, `completed`, `failed`, `cancelled`, or `interrupted`. `completed` means the Runtime delivered the current Turn successfully; it does not claim that the user's larger business task is complete.

The Runtime no longer derives a separate semantic `task_completion` object from command keywords, reopens the model's Plan, or appends a Harness-authored completion note. The model owns task meaning and Plan content. Harness still enforces technical truth: a failed/cancelled/waiting Turn cannot be stored as completed, tool results remain paired, and the Eval runner independently compares the model's final delivery with authoritative verification.

The quality Eval suite in `evals/agent_quality_cases.json` covers three real task shapes: C-style `.cpp` implementation, multi-file protocol analysis, and Markdown integration documentation. Validation-only mode never calls a model:

```bash
python scripts/run_evals.py --cases evals/agent_quality_cases.json --validate-only
```

An unavailable compiler is reported as `blocked`, not as an Agent failure, when no independent hard failure occurred. The report retains the all-attempt success rate and also emits an evaluable success rate that excludes environment-blocked attempts. Path-isolation checks use canonical execution evidence rather than display-redacted tool previews.

### Tool-failure recovery

The first company baseline exposed the concrete failure pattern for this change: one multi-file analysis attempt made 27 tool calls, encountered 4 tool errors, produced no target-file change, and correctly remained blocked instead of claiming completion. The existing exact-action and no-progress guards protected completion honesty, but they did not group the same error class when arguments changed.

Tool outcomes are explicitly separated into `failed`, `rejected`, and `skipped`. `failed` means execution began and returned an error; `rejected` means validation or policy prevented execution; `skipped` means the call was never attempted because the current tool batch had already reached a stop or cancellation condition. Skipped calls remain visible in the Trace but never enter failure counts, repeat detection, or Eval failed-tool totals.

Repeat detection uses a content-free stable fingerprint: tool name, outcome, failure phase, category, `error_kind`, and a hash of the normalized target or strategy. For `command_not_allowed`, the target is the command executable, so repeating `select-string` matches while changing to `rg` does not. Environment-wide failures intentionally omit the target because changing a path cannot make an unavailable tool or provider available. Raw commands, paths, queries, and other argument values remain absent from failure reports.

The categories are:

- `tool_call_failure`: invalid or boundary-rejected tool usage; change arguments or tools.
- `command_failure`: a command failed; inspect the exit status and change strategy.
- `verification_failure`: compile or test verification failed; change the target or verification strategy.
- `tool_execution_failure`: a tool implementation failed; retry once, then change strategy.
- `environment_blocked`: a required provider, credential, compiler, shell, network, or tool capability is unavailable.

Two consecutive failures with the same stable fingerprint trigger one explicit replan. The Runtime records that exact pre-replan fingerprint. After replanning, only seeing that same fingerprint again triggers `tool_failure_repeated_after_replan`; a different command, target, tool, phase, or error is allowed to run as a new strategy. A separate five-failure total budget prevents an Agent from evading the repeat guard by generating endlessly different failures. Failure trackers and stop latches are local to one Runtime turn and are recreated for each new user turn. A write-authorized task that runs a failing verification command before any successful mutation is replanned with an instruction to generate or modify the target first.

Deterministic recovery Evals use fake tools and make zero real model calls:

```bash
python scripts/run_recovery_evals.py --validate-only
python scripts/run_recovery_evals.py
```

They cover a recoverable changed-strategy path, an unavailable environment, repeated failure after replanning, verification before mutation, and no progress after replanning. The existing C-style `.cpp`, multi-file analysis, and Markdown live cases remain unchanged.

### Safe Eval failure reports

Each live attempt now contains a `failure_observability` section that identifies the failing tool step, failure category, `error_kind`, occurrence and repeat count, replan trigger, and whether recovery succeeded. Aggregate output includes total and average tool calls, failed tool calls, repeated failures, replan count, and recovery success rate.

Reports deliberately omit tool argument values, tool output, final answer text, verifier output, Runtime error details, file contents, absolute company paths, URLs, and credentials. Existing report fields remain present where compatibility requires them, but sensitive values are empty or replaced by content-free status envelopes.

After this recovery change, the necessary company live regression is the previously unstable multi-file analysis case:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py `
  --cases evals\agent_quality_cases.json `
  --live `
  --name multi_file_protocol_analysis `
  --repeat 5 `
  --provider openai_compatible `
  --model gpt-5.4 `
  --output artifacts\evals\company-gpt54-recovery.json
```

Compare `success_rate_percent`, `failed_tool_calls`, `average_tool_calls_per_attempt`, `recovery_success_rate_percent`, and `completion_state_accuracy_percent` with the earlier baseline. Run this from Developer PowerShell for VS 2022 only when the selected case needs the Visual Studio compiler environment; this multi-file case uses its portable verifier.

## Frontend run visibility

Plan state and execution activity are separate UI layers. A plan never replaces current tool/model activity. During a run the UI shows the current step, tool, wait state, action, command, elapsed time, last semantic progress, and connection state.

SSE `heartbeat` events update transport liveness only. They do not update semantic progress or make a stalled task appear active. Heartbeats arrive at low frequency and the existing streaming text update path is unchanged, avoiding a new per-token rendering cost.

Historical Turn details use progressive disclosure. The developer drawer loads the persisted Thread history through that Assistant Item. Each `tool_call_id` is rendered as one indented tool transaction rather than separate live-summary and audit rows. The normal card shows only status, tool target, result summary, and duration; it exposes one effective-parameters block and one result preview on demand. Call IDs, raw-versus-normalized differences, boundary validation, and schema details live under the nested Trace disclosure. Trace linkage uses `assistant_item_id`, `tool_call_id`, and `tool_result_item_id`. The effective System Prompt is stored once per distinct context in the Turn Trace and is also collapsed by default. Runtime Inspector, replay counters, duplicated model-output panels, and the large Raw JSON view are no longer rendered.

## External-write approval boundary

Commands found in Skills, source files, rules, logs, or documentation are evidence to interpret. They are not execution authorization. The model may propose a concrete command when the current task truly requires it, but the Runtime independently applies the action boundary to parsed tool arguments rather than trying to classify the user's natural-language wording.

Every concrete `git push` requires a single-use approval, including Auto and Full Access. The request displays the resolved repository, remote, sanitized push URL, branch, HEAD, refspecs, and force/delete flags. Its token binds the exact command and working directory plus a fingerprint of those repository facts. A changed command, repository, remote URL, branch, HEAD, session, project, or previously used token is rejected and cannot silently acquire a replacement approval through the same call.

The first safety Eval treats a `git push` example inside `SKILL.md` as reference text. It must be preserved and reviewed in a Markdown deliverable without appearing in an `exec_command` event. Reports retain only the redaction-safe rule label (`git_push`), never the command, URL, credentials, file content, or complete arguments.

## Stable Thread activity ordering

`updated_at` remains the persistence timestamp, but it no longer decides whether a Thread contains new user-visible activity. `activity_revision`, `activity_at`, and `activity_kind` form a separate monotonic clock. User-message acceptance and terminal Turn state advance it; connection heartbeats and unrelated metadata saves do not.

The list API sorts by `activity_at`. The frontend merges each Thread only when the incoming revision/time is at least as fresh as its current row, then applies the same activity ordering. A late background refresh therefore cannot move a Thread backward and forward using stale data. Old Sessions gain revision `0` and inherit `activity_at` from their existing `updated_at`, so no manual migration is required.

When run-time guidance is accepted, the Runtime supplies the next assistant segment ID. The frontend freezes only the visible text of the completed segment and transfers the live plan/activity panel to that new segment after the queued user message. This makes the live order match the persisted Thread order before and after refresh.
