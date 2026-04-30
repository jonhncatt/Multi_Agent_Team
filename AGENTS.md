# AGENTS.md

## Project Contract

This repository prefers a model-led, harness-validated execution shape.

- Treat `runtime_context_json.route_state` and other harness hints as weak hints, not as the final task decision.
- Produce an explicit operational turn proposal before acting.
- Keep hidden chain-of-thought private. Any visible planning must stay concise, operational, and user-safe.

## Working Mode

- Follow the `PLAN.md` workflow for substantial changes.
- Use small commits by topic.
- Avoid unrelated refactors and whole-file reformatting.
- Preserve the current high-permission default workflow unless a real harness boundary blocks the action.

## UI Contract

- Default user-facing activity should present `model proposal -> harness validation -> execution result`.
- Keep engineering payloads, runtime guesses, raw diagnostics, and low-level trace detail behind expandable sections.
- Preserve tool audit transparency: raw arguments, preview, schema validation, and result preview remain available.

## Verification Contract

- Prefer direct verification over speculative summaries.
- When streaming is not progressive, report the exact layer where batching remains.
- Keep release-facing summaries factual and concise.
