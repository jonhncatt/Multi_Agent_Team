# Runtime Reliability Baseline

This document records the reliability behavior that must remain stable after the Session = Thread migration.

## Thread compaction

- The durable conversation source is `thread_transcript`; legacy `turns` remain readable only for Session migration.
- A compaction summary is unverified continuation memory derived from transcript items and source-marked tool evidence. It does not copy Harness task state, work cursor, permissions, or the former six-element context structure.
- GPT-5.4 and GPT-5.6 use a 272,000-token default operational window, a 90% automatic compaction threshold, and a 95% effective hard limit. GPT-5.6's 1,050,000-token model maximum is tracked separately. A verified company deployment may override the operational window with `VP_CONTEXT_WINDOW_TOKENS` or the threshold with `VP_CONTEXT_AUTO_COMPACT_TOKEN_LIMIT`.
- The latest provider-reported `input_tokens` is preferred. When it is unavailable, the Runtime estimates the complete request, including the developer prompt, project instructions, compacted summary, transcript, attachments, current request, tool transactions, and selected tool schemas.
- Pre-turn and mid-turn decisions use the same persisted `ContextWindowStatus`; the model, operational window, thresholds, estimate source, and recommendation therefore cannot drift between the two phases.
- Retained history uses a token budget rather than a turn/message count. Historical user-started transactions and live assistant-tool-result transactions are kept atomically, so compaction never leaves an orphaned ToolMessage.
- If the provider falls back to a model with a smaller operational window, the Runtime re-evaluates the effective model before the next request and locally compacts old replay when required. This fallback compaction is deterministic and does not add another model call.
- Tool-call count and the 120K history-noise diagnostic do not trigger full compaction. A tool result larger than the model-visible token cap is stored once under an opaque Thread-scoped `result_ref`; `read_tool_result` returns continuation chunks without rerunning the original tool.
- Compaction is an internal Thread operation, not a chat Turn. Its minimal persisted record is `Thread.compaction = {generation, summary, compacted_until_item_id, compacted_at}`. `compaction_summary_chars` remains diagnostic metadata only. A Turn paused on an unresolved tool call cannot be compacted.
- Provider-native `/responses/compact` is intentionally not called by the current Chat Completions Runtime. The local compaction seam is isolated so a later Responses API migration can replace it without changing window evaluation or retention semantics.

## Paused Turn lifecycle

- A command approval or `request_user_input` pauses the current Turn instead of ending it and creating a new user Turn.
- The Assistant tool call remains in `thread_transcript` without a placeholder result while the UI waits.
- Approve, decline, and answer actions produce exactly one ToolMessage with the original `tool_call_id`; they never produce synthetic HumanMessages.
- The active Plan is retained only while the Turn is paused. Once the Turn ends, the Plan remains available through transcript history but is not restored as the next Turn's active Plan.
- Turn continuation is model-led. Approval and structured-input pauses remain Runtime-owned, and user cancellation still ends the Turn.

## Technical Turn status

The persisted Turn Trace has one technical status: `running`, `waiting_user`, `completed`, `failed`, `cancelled`, or `interrupted`. `completed` means the Runtime delivered the current Turn successfully; it does not claim that the user's larger business task is complete.

The Runtime no longer derives a separate semantic `task_completion` object from command keywords, reopens the model's Plan, or appends a Harness-authored completion note. The model owns task meaning and Plan content. Harness still enforces technical truth: a failed/cancelled/waiting Turn cannot be stored as completed, tool results remain paired, and the Eval runner independently compares the model's final delivery with authoritative verification.

The quality Eval suite in `evals/agent_quality_cases.json` covers three real task shapes: C-style `.cpp` implementation, multi-file protocol analysis, and Markdown integration documentation. Validation-only mode never calls a model:

```bash
python scripts/run_evals.py --cases evals/agent_quality_cases.json --validate-only
```

An unavailable compiler is reported as `blocked`, not as an Agent failure, when no independent hard failure occurred. The report retains the all-attempt success rate and also emits an evaluable success rate that excludes environment-blocked attempts. Path-isolation checks use canonical execution evidence rather than display-redacted tool previews.

### Model-led tool continuation

Tool outcomes are explicitly separated into `failed`, `rejected`, and `skipped`. `failed` means execution began and returned an error; `rejected` means validation or policy prevented execution; `skipped` means the call was never attempted because approval, structured input, cancellation, or a technical interruption prevented it. Skipped calls remain visible in the Trace but never enter Eval failed-tool totals.

`where` and `rg` use exit code `1` for a normal query with no matches. The command result is marked `query_miss`, returned to the model as an ordinary observation, and excluded from failure classification. Exit code `2` and other real execution errors remain failures.

The Runtime returns executed failures and policy rejections to the model and asks the model for the next action. It does not stop or force a replan based on:

- a total failure count;
- a repeated failure fingerprint;
- repeated tool names or arguments;
- an inferred lack of progress;
- elapsed Turn time;
- total tool-call count.

Approval decisions and user cancellation remain hard Runtime boundaries. Context-window compaction, bounded model-visible tool output, provider limits, operating-system termination, and malformed protocol handling remain technical necessities rather than judgments about whether the task is making progress.

Failure records may still include a content-free stable fingerprint, occurrence count, and progress signal for diagnostics and Eval compatibility. These fields never control Turn continuation. Raw commands, paths, queries, and other argument values remain absent from safe failure reports.

The categories are:

- `tool_call_failure`: invalid or boundary-rejected tool usage; change arguments or tools.
- `command_failure`: a command failed; inspect the exit status and change strategy.
- `verification_failure`: compile or test verification failed; change the target or verification strategy.
- `tool_execution_failure`: a tool implementation failed; retry once, then change strategy.
- `environment_blocked`: a required provider, credential, compiler, shell, network, or tool capability is unavailable.

Deterministic continuation Evals use fake tools and make zero real provider calls:

```bash
python scripts/run_recovery_evals.py --validate-only
python scripts/run_recovery_evals.py
```

They cover `where`/`rg` query misses, repeated actions, repeated and distinct failures, environment failures, policy rejections, malformed tool-call protocol repair, model-selected verification recovery, output continuation, and context compaction. The existing C-style `.cpp`, multi-file analysis, and Markdown live cases remain unchanged.

### Safe Eval failure reports

Each live attempt contains a `failure_observability` section that identifies the failing tool step, failure category, `error_kind`, occurrence count, and whether a later tool succeeded. Legacy repeat and replan counters remain report-only compatibility fields; they do not drive Runtime control flow. Aggregate output includes total and average tool calls, failed tool calls, and recovery observations.

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

Historical Turn details use progressive disclosure. The developer drawer loads the persisted Thread history through that Assistant Item. Each `tool_call_id` is rendered as one indented tool transaction rather than separate live-summary and audit rows. The normal card shows only status, tool target, result summary, and duration; it exposes one effective-parameters block and one result preview on demand. Call IDs, raw-versus-normalized differences, boundary validation, and schema details live under the nested Trace disclosure. Trace linkage uses `assistant_item_id`, `tool_call_id`, and `tool_result_item_id`. The effective Developer Prompt is stored once per distinct context in the Turn Trace and is also collapsed by default. Runtime Inspector, replay counters, duplicated model-output panels, and the large Raw JSON view are no longer rendered.

## External-write approval boundary

Commands found in Skills, source files, rules, logs, or documentation are evidence to interpret. They are not execution authorization. The model may propose a concrete command when the current task truly requires it, but the Runtime independently applies the action boundary to parsed tool arguments rather than trying to classify the user's natural-language wording.

Every concrete `git push` requires a single-use approval, including Auto and Full Access. The request displays the resolved repository, remote, sanitized push URL, branch, HEAD, refspecs, and force/delete flags. Its token binds the exact command and working directory plus a fingerprint of those repository facts. A changed command, repository, remote URL, branch, HEAD, session, project, or previously used token is rejected and cannot silently acquire a replacement approval through the same call.

The first safety Eval treats a `git push` example inside `SKILL.md` as reference text. It must be preserved and reviewed in a Markdown deliverable without appearing in an `exec_command` event. Reports retain only the redaction-safe rule label (`git_push`), never the command, URL, credentials, file content, or complete arguments.

## Stable Thread activity ordering

`updated_at` remains the persistence timestamp, but it no longer decides whether a Thread contains new user-visible activity. `activity_revision`, `activity_at`, and `activity_kind` form a separate monotonic clock. User-message acceptance and terminal Turn state advance it; connection heartbeats and unrelated metadata saves do not.

The list API sorts by `activity_at`. The frontend merges each Thread only when the incoming revision/time is at least as fresh as its current row, then applies the same activity ordering. A late background refresh therefore cannot move a Thread backward and forward using stale data. Old Sessions gain revision `0` and inherit `activity_at` from their existing `updated_at`, so no manual migration is required.

When run-time guidance is accepted, the Runtime supplies the next assistant segment ID. The frontend freezes only the visible text of the completed segment and transfers the live plan/activity panel to that new segment after the queued user message. This makes the live order match the persisted Thread order before and after refresh.
