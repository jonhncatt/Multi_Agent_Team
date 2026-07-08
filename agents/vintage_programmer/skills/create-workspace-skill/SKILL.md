---
name: create-workspace-skill
description: Use when the user asks to create, update, refine, summarize, or turn a reusable workflow into a workspace skill using save_skill, including requests like 创建 workspace skill or 把流程总结成 skill.
enabled: true
---

# Create Workspace Skill

Use this built-in skill when the user wants VP to create or update a user-editable workspace skill.

Workspace skills are saved under `workspace/skills/<name>/SKILL.md`. Do not write or modify built-in system skills.

## When To Create A Skill

Create a workspace skill when the request describes a reusable workflow, domain procedure, tool routine, review checklist, investigation method, or repeated project convention.

Do not create a skill for a one-off answer, temporary note, secret, credential, broad personality preference, or information that should stay in ordinary project docs.

## Workflow

1. Identify the reusable behavior.
   - What future task should trigger this skill?
   - What steps, checks, tools, or conventions should VP remember?
   - What should the skill explicitly avoid?

2. Choose a skill name.
   - Use lowercase letters, digits, hyphens, or underscores.
   - Prefer short action-oriented names such as `repo-triage`, `release-checklist`, or `nvme-log-analysis`.

3. Write the description as a routing contract.
   - Start with `Use when...`.
   - Mention concrete trigger situations.
   - Avoid vague descriptions like "helps with coding" or "general workflow".

4. Write the body as reusable instructions only.
   - Do not include YAML frontmatter in `body`.
   - Keep it concise; prefer ordered steps and decision rules.
   - Include validation expectations when relevant.
   - Do not include private credentials, transient thread details, or unsupported claims.

5. Call `save_skill`.
   - Use `overwrite: false` by default.
   - Use `overwrite: true` only when the user clearly asked to replace/update that workspace skill or after confirming the existing skill should be overwritten.

## Tool Call Shape

```json
{
  "name": "repo-triage",
  "description": "Use when the user wants to inspect repository structure, recent changes, risks, or prepare a code investigation plan.",
  "body": "# Repo Triage\n\n## Workflow\n\n1. Inspect the repository layout.\n2. Check recent changes.\n3. Identify risk areas and tests.\n4. Report findings with file references.",
  "enabled": true,
  "overwrite": false
}
```

## Delivery

After saving, report the workspace skill name, path, enabled status, and whether it was created or overwritten. If `save_skill` fails because the skill already exists, ask whether to overwrite or propose a different name.

