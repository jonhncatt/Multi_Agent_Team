---
name: create-team-skill
description: Use when the user asks to create, update, refine, summarize, or turn a reusable company workflow into a Team Skill using save_skill.
enabled: true
---

# Create Team Skill

Use this built-in skill when the user wants Vintage Programmer to create or update a reusable Team Skill.

Team Skills are shared through the Vintage Programmer Git repository. Their physical location is resolved by the Skill Registry and must never be derived from the active business project. Always use `save_skill`; do not create `SKILL.md` with ordinary file or shell tools.

## When To Create A Skill

Create a Team Skill for a reusable company workflow, domain procedure, tool routine, review checklist, investigation method, coding rule, or document convention that should be available across projects.

Do not create a skill for a one-off answer, temporary project detail, secret, credential, broad personality preference, or behavior that Runtime/Harness must enforce on every turn.

## Workflow

1. Identify the reusable behavior and its concrete future trigger.
2. Choose a short action-oriented lowercase name using letters, digits, hyphens, or underscores.
3. Write the description as a routing contract that starts with `Use when...`.
4. Write a concise Markdown body containing reusable steps, decisions, checks, and validation expectations.
5. Call `save_skill` with `overwrite: false` unless the user clearly requested an update to an existing Team Skill.
6. Report the logical key, enabled state, and whether the Team Skill was created or replaced. Do not report or guess a physical filesystem path.

## Script And Secret Contract

- Resolve bundled files from the Skill itself, never from the active business project's current directory. In Python use `Path(__file__).resolve()`; use the equivalent script-location primitive in Shell, Node, or PowerShell.
- Treat `VP_SKILL_ROOT` as the Skill package root and `VP_PROJECT_ROOT` / `VP_PROJECT_CWD` as the selected business project. Runtime injects these only when an enabled Skill script is executed directly.
- Read credentials only from inherited environment variables such as `os.environ["REDMINE_API_KEY"]`. Never search for, open, parse, print, return, or log `.env` files or secret values.
- Keep secret values out of `SKILL.md`, scripts, references, examples, command arguments, and Git. Document only the required environment-variable names.
- If a required variable is missing, fail with the variable name and setup guidance, never with a guessed file path or the contents of the environment.

## Tool Call Shape

```json
{
  "name": "protocol-spec-analysis",
  "description": "Use when the user wants to extract messages, fields, constraints, and open questions from a company protocol specification.",
  "body": "# Protocol Spec Analysis\n\n## Workflow\n\n1. Read the supplied specification and rules.\n2. Extract messages, fields, constraints, and uncertainties.\n3. Cross-check references.\n4. Report findings and validation evidence.",
  "enabled": true,
  "overwrite": false
}
```

If the name already exists, do not mechanically retry. Ask whether to overwrite or propose a different name.
