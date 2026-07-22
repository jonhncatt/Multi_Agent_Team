# Evals

The current quality gate targets the active `VintageProgrammerRuntime` directly. It runs each live Agent attempt in an isolated workspace and evaluates the resulting files, tool trace, verification behavior, and completion state.

For a Chinese explanation of what every current suite and case actually tests, how to run it, and how to interpret the result, see [TEST_CONTENT.zh-CN.md](TEST_CONTENT.zh-CN.md).

## Current Agent quality suite

- cases: `evals/agent_quality_cases.json`
- first scenario: specification-driven C-style implementation in a `.cpp` project
- runner: `scripts/run_evals.py`

Validate the suite and fixtures without sending a provider request:

```bash
python scripts/run_evals.py --validate-only
```

Run one live attempt with the active provider configuration:

```bash
python scripts/run_evals.py --live
```

Run the formal company baseline:

```bash
python scripts/run_evals.py \
  --cases evals/agent_quality_cases.json \
  --live \
  --repeat 3 \
  --provider openai_compatible \
  --model gpt-5.4 \
  --output artifacts/evals/c-style-cpp-baseline.json
```

`--live` is mandatory for provider-backed attempts. Without it, the runner does not send model requests. Successful attempt workspaces are removed by default; failed and blocked workspaces are retained under `artifacts/evals/workspaces/`. Use `--keep-workspaces` to retain every attempt.

The home-page `Eval` button exposes the same runner as a persisted background job. The UI submits structured fields rather than a shell command, the server executes one Eval job at a time, and job state is stored under `artifacts/evals/jobs/`. Suite paths are restricted to `evals/` and report paths to `artifacts/evals/`.

## Agent workflow suite

`evals/agent_workflow_cases.json` extends the same isolated runner with scenario hooks that remain deterministic under fake Runtime tests:

- queued guidance accepted at a safe model boundary;
- model-selected parallel `spawn_subagent` delegation, `wait_subagents` collection, and parent summary;
- a long seeded Thread replayed through a compaction summary plus retained turns;
- modification of an existing Team Skill in the isolated VP Skill Registry;
- a failed verification followed by a successful recovery;
- translation-only maintenance of a command-bearing Team Skill where any `exec_command` attempt fails the case;
- review of command text inside a Skill without executing the referenced remote write;
- `input_modalities` metadata reserved for PDF, Excel, Markdown, C, and C++ mixtures.

Validate without provider calls:

```bash
python scripts/run_evals.py --cases evals/agent_workflow_cases.json --validate-only
```

Run the company baseline from PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py `
  --cases evals\agent_workflow_cases.json `
  --live `
  --repeat 3 `
  --provider openai_compatible `
  --model gpt-5.4 `
  --output artifacts\evals\company-gpt54-agent-workflow.json
```

The report's `scenario` section records required and forbidden tools, accepted guidance count, seeded/compacted Thread items, Team Skill isolation, failed-test recovery, and redaction-safe forbidden-command labels without storing message text, company paths, credentials, URLs, commands, or complete tool parameters. A case may set `verification.agent_must_run` to `false` when executing any command would itself violate the task; the runner still performs its private authoritative verifier after the Agent stops. For those cases only, a Runtime `verification_missing` state does not override a normal model final answer and the passing private verifier; unfinished plans and missing final answers still fail completion accuracy.

## Deterministic tool-failure recovery suite

`evals/tool_failure_recovery_cases.json` runs focused Runtime state-machine cases with fake tools and zero provider calls. It covers repeated-failure replanning, environment blocks, verification-before-change, no-progress stops, distinct failure targets, and the regression where repeated `search_codebase/not_a_directory` failures are followed by a skipped batch call, a rejected non-allowlisted command, and a successful `rg` strategy.

This suite is also available from the home-page `Eval` dialog. It is marked as deterministic there, so the Live/provider/model controls are disabled and no provider request is made.

```bash
python scripts/run_recovery_evals.py --validate-only
python scripts/run_recovery_evals.py
```

Use `--name replan_allows_rejected_then_new_command_strategy` to run only the FAILED/REJECTED/SKIPPED regression case.

## Company compiler adapter

Set `VP_EVAL_CPP_VERIFY_SCRIPT` to the absolute path of a company-owned wrapper script when the portable fixture cannot use MSVC, `clang++`, or `g++` locally.

The runner invokes:

```text
<script> <workspace_path> <case_name>
```

The process working directory is the attempt workspace. The wrapper may call a compiler on the same machine or forward the project to a remote compilation service.

Return codes:

- `0`: compile and tests passed;
- `1`: compile or tests failed;
- `2`: compiler unavailable or adapter configuration failed.

The wrapper is executed by the Eval runner after the Agent turn. Its path and environment are not sent to the model or stored in the report.

## Report and exit status

Reports are JSON and contain per-attempt status, workspace changes, context-read evidence, tool counts, C-style rule violations, authoritative verification, token usage, and completion-state accuracy.

`success_rate_percent` keeps the historical all-attempt denominator. `evaluable_success_rate_percent` excludes attempts blocked by authentication, compiler, or environment availability, so environment gaps do not masquerade as Agent quality failures. Workspace-boundary decisions use canonical tool paths; display-redacted previews are never treated as authoritative path evidence.

- exit `0`: every attempt passed;
- exit `1`: at least one real Eval failure;
- exit `2`: no real failure, but at least one attempt was blocked by authentication, compiler, or environment configuration.

## Legacy datasets

The following files belong to the removed legacy platform compatibility layer and are retained only as historical regression material:

- `evals/gate_cases.json`
- `evals/research_gate_cases.json`
- `evals/swarm_gate_cases.json`
- `evals/cases.json`
- `evals/replay_samples/`

They contain legacy `helper`, `conversation`, and `module_task` case kinds and are not accepted by the current runner. Do not use them as active release gates until their useful scenarios are deliberately migrated to the current schema.
