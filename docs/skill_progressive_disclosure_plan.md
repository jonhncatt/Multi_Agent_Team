# Skill Progressive Disclosure

## Current Design

VP skills are split into two scopes:

```text
agents/vintage_programmer/skills/<skill>/SKILL.md   # system, built-in, read-only
workspace/skills/<skill>/SKILL.md                   # workspace, user-editable
```

The repository ships one enabled built-in system skill for creating workspace skills:

```text
agents/vintage_programmer/skills/create-workspace-skill/SKILL.md
```

The repository also ships one disabled workspace sample:

```text
workspace/skills/sample-workspace-skill/SKILL.md
```

The workspace sample is a narrow `.gitignore` exception; other workspace skills remain local by default.

Every skill gets a stable key:

```text
system:<name>
workspace:<name>
```

If a user writes `$name` without a scope, workspace wins over system. Scoped references such as `$system:name` and `$workspace:name` are exact.

## Skill Format

Only this frontmatter format is valid:

```markdown
---
name: repo-triage
description: Use when the user wants to inspect repository structure, recent changes, risks, or prepare a code investigation plan.
enabled: true
---

# Repo Triage

Full instructions go here.
```

Rules:

- `name` and `description` are required.
- `enabled` is optional and defaults to `true`.
- `id`, `title`, `summary`, and `bind_to` are not supported skill fields.
- All skills bind to `vintage_programmer` in this version.

## Runtime Flow

```text
scan system/workspace skill roots
  -> parse SKILL.md frontmatter only
  -> apply enabled status and system overrides
  -> inject [available_skills] lightweight list
  -> explicit $skill references preload full SKILL.md
  -> model may call load_skill({ key })
  -> runtime validates key and reads full SKILL.md
  -> model may call save_skill(...) to create/update a workspace skill
```

The initial prompt receives only lightweight metadata: `key`, `scope`, `name`, `description`, and `path`. Full `SKILL.md` content is read only after explicit invocation or a `load_skill` tool call.

`save_skill` writes only `workspace/skills/<name>/SKILL.md`, uses the same strict frontmatter validation as the Workbench API, and does not modify built-in system skills. It refuses to overwrite an existing workspace skill unless `overwrite: true` is supplied.

## Local State

Workspace-local runtime files live under `workspace/skills/`, which is ignored by Git:

- `.vp_skill_index.json`: lightweight index snapshot.
- `.vp_skill_overrides.json`: system skill enable/disable overrides.

Source `SKILL.md` files remain the final source of truth; snapshots are runtime cache data.

## Next Steps

P1:

- Add a skill preview/debug command that explains which skills would load and why.
- Surface `available_skills`, `loaded_skill_keys`, and load reasons more clearly in the inspector.

P2:

- Add skill lint for description quality, duplicate names, invalid metadata, and excessive full-body size.
- Add routing evals for important domain skills.

P3:

- Consider additional scopes such as project `.agents/skills`, user home skills, admin skills, or plugin-provided skills after the system/workspace flow is stable.
