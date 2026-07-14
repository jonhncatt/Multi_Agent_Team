# Runtime Reliability Baseline

This document records the reliability behavior that must remain stable after the Session = Thread migration.

## Thread compaction

- The durable conversation source is `thread_transcript`; legacy `turns` remain readable only for Session migration.
- A compaction summary is unverified continuation memory derived from transcript items and source-marked tool evidence. It does not copy Harness task state, work cursor, permissions, or the former six-element context structure.
- GPT-5.4 uses a 272,000-token default usable window and a 90% automatic compaction threshold. A verified company deployment may override the usable window with `VP_CONTEXT_WINDOW_TOKENS` or the threshold with `VP_CONTEXT_AUTO_COMPACT_TOKEN_LIMIT`.
- The latest provider-reported `input_tokens` is preferred. When it is unavailable, the Runtime estimates the complete request, including the system prompt, project instructions, compacted summary, transcript, attachments, current request, tool transactions, and selected tool schemas.
- Retained history is selected as complete user-started transactions and is also token-bounded, so a single large tool result cannot silently defeat compaction.

## Turn completion and task completion

`turn_status=completed` means the Runtime produced a response for the current turn. It does not by itself mean the user's multi-step task is complete.

The additive `task_completion` result records:

- whether the turn ended;
- whether a plan is tracked and fully complete;
- whether post-change verification passed, failed, is missing, or is still running;
- whether the task is completed, still in progress, blocked, or not explicitly tracked.

An active plan has exactly one `in_progress` step. A fully complete plan contains only `completed` steps. If the model marks every step complete after a failed or missing post-change check, the Runtime reopens the last step and adds an explicit runtime note to the answer.

The quality Eval suite in `evals/agent_quality_cases.json` covers three real task shapes: C-style `.cpp` implementation, multi-file protocol analysis, and Markdown integration documentation. Validation-only mode never calls a model:

```bash
python scripts/run_evals.py --cases evals/agent_quality_cases.json --validate-only
```

## Frontend run visibility

Plan state and execution activity are separate UI layers. A plan never replaces current tool/model activity. During a run the UI shows the current step, tool, wait state, action, command, elapsed time, last semantic progress, and connection state.

SSE `heartbeat` events update transport liveness only. They do not update semantic progress or make a stalled task appear active. Heartbeats arrive at low frequency and the existing streaming text update path is unchanged, avoiding a new per-token rendering cost.
