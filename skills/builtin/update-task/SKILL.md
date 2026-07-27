---
name: update-task
description: Use when the user asks to update, refresh, checkpoint, revise, or save new progress into the currently loaded durable Task. Prepare a complete replacement snapshot and submit it through save_task for mandatory human approval before the existing Task is changed.
---

# Update Task

Update only the Task identified by `[current_task_context]`. Treat its `task_id` as immutable identity and its existing fields as the baseline.

## Workflow

1. Confirm that `[current_task_context]` contains a non-empty `task_id`. If no Task is loaded, ask the user to load one; do not guess an id or create a replacement Task.
2. Combine the existing snapshot with verified progress from the current Thread.
3. Prepare a complete replacement containing `title`, `goal`, `summary`, `progress`, `next_steps`, `decisions`, `blockers`, `artifacts`, and `status`.
4. Preserve still-valid existing details. Do not turn omitted fields into empty lists merely because the latest work did not mention them.
5. Call `save_task` once with the same `task_id` and the complete proposed snapshot.
6. Wait for the Runtime approval flow. The Runtime shows the current and proposed Task to the user and does not write before approval.
7. After approval, use the returned tool result to report that the Task was updated. After cancellation, report that the Task remains unchanged; do not retry, create a duplicate, or claim success.

## Snapshot Rules

- Base claims about completed work on current tool results and verification, not plans or earlier assistant promises.
- Keep `summary` self-contained enough to resume without the source Thread.
- Keep `progress` for completed or verified work and `next_steps` for unfinished actions.
- Preserve decisions that still constrain future work.
- Set `blocked` only when a concrete blocker remains, and `completed` only when the stated goal is actually complete.
- Never bypass approval with direct file, shell, API, or `apply_patch` writes.
