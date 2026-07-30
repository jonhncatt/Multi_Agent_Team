---
name: update-task
description: Use when the user asks to update, refresh, checkpoint, revise, or save new progress into an existing durable Task. Resolve the Task safely, prepare a complete replacement snapshot, and submit it through save_task for mandatory human approval before the existing Task is changed.
---

# Update Task

Update only a Task identified by `[current_task_context]` or resolved unambiguously through `list_tasks`. Treat its `task_id` as immutable identity and its existing fields as the baseline.

## Workflow

1. Use the non-empty `task_id` and complete baseline from `[current_task_context]` when present.
2. Otherwise call `list_tasks` with topic terms from the conversation. Search `current_project` first, then `all_projects` only when the current project has no match or the user indicates another project.
3. If several candidates remain plausible, show their titles, projects, statuses, and ids and ask the user to choose. Do not guess an id or create a replacement Task.
4. Once one Task is identified, call `list_tasks` again with its exact id, the same `project_scope` used to find it, `detail_level: full`, and `limit: 1`; use that complete snapshot as the baseline.
5. Combine the baseline with verified progress from the current Thread.
6. Prepare a complete replacement containing `title`, `goal`, `summary`, `progress`, `next_steps`, `decisions`, `blockers`, `artifacts`, and `status`.
7. Preserve still-valid existing details. Do not turn omitted fields into empty lists merely because the latest work did not mention them.
8. Call `save_task` once with the same `task_id` and the complete proposed snapshot.
9. Wait for the Runtime approval flow. The Runtime shows the current and proposed Task to the user and does not write before approval.
10. After approval, use the returned tool result to report that the Task was updated. After cancellation, report that the Task remains unchanged; do not retry, create a duplicate, or claim success.

## Snapshot Rules

- Base claims about completed work on current tool results and verification, not plans or earlier assistant promises.
- Keep `summary` self-contained enough to resume without the source Thread.
- Keep `progress` for completed or verified work and `next_steps` for unfinished actions.
- Preserve decisions that still constrain future work.
- Set `blocked` only when a concrete blocker remains, and `completed` only when the stated goal is actually complete.
- Never bypass approval with direct file, shell, API, or `apply_patch` writes.
