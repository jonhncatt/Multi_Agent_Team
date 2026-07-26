# Vintage Programmer

Vintage Programmer is a local-first coding Agent application. Keep the Runtime model-led: application code enforces permissions, tool contracts, persistence, approvals, observability, and completion evidence without guessing user intent from keywords.

## Repository layout

- `app/` contains the API, Runtime, persistence, tool execution, and web UI.
- `agents/vintage_programmer/locales/` contains the main Agent prompt in supported languages.
- `agents/builtin/` contains independent built-in Subagent role definitions.
- `skills/builtin/` and `skills/team/` are the global Skill registries.
- `project_profiles/` contains shared project descriptions selected explicitly by users.
- `evals/` contains behavioral evaluation suites and fixtures.
- `tests/` contains deterministic regression and integration tests.

## Working conventions

- Preserve the typed Thread transcript and the single-SystemMessage request structure.
- Keep project paths, Session data, approvals, caches, and credentials out of version-controlled shared resources.
- Treat skipped, rejected, and executed failures as different Runtime outcomes.
- Do not add keyword-based intent routing when an explicit state, API field, or user choice can express the same decision.
- Keep Built-in resources read-only through ordinary Runtime tools; Team resources are the editable shared layer.

## Verification

- Run focused tests for the changed subsystem first.
- Run the relevant integration and frontend regression tests for API or UI changes.
- Use `python -m pytest` for the complete Python suite when the change is broad enough to justify it.
- Confirm `git diff --check` and review the final diff before declaring the work complete.
