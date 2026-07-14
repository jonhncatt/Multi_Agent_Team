# Global Skill Registry and Progressive Disclosure

## Catalogs

Skills are independent of concrete agents and the active business project:

```text
skills/builtin/<skill>/SKILL.md   # product-maintained, read-only
skills/team/<skill>/SKILL.md      # team-maintained, distributed through VP Git
```

Both catalogs are globally discoverable. Built-in/Team describes ownership and mutability, not which Agent may use a Skill. The current Vintage Programmer runtime loads both. `SkillRegistry.enabled_skills(agent_id, capabilities)` is the extension point for future capability filtering without moving or copying files.

Canonical keys are:

```text
builtin:<name>
team:<name>
```

The legacy `system:` and `workspace:` prefixes remain read-compatible aliases. An unscoped name resolves only when unique; duplicate names require an explicit canonical key.

## Skill Format

```markdown
---
name: protocol-spec-analysis
description: Use when the user wants to extract messages, fields, constraints, and open questions from a protocol specification.
enabled: true
---

# Protocol Spec Analysis

Reusable instructions go here.
```

Only `name`, `description`, and optional `enabled` are valid frontmatter fields. Runtime/Harness policies, credentials, personal paths, and temporary task data do not belong in a Skill.

## Runtime Flow

```text
scan builtin/team roots
  -> parse and cache frontmatter metadata
  -> inject [available_skills] without physical paths
  -> explicit $skill may preload full content
  -> load_skill({key}) reads selected full content
  -> load_skill({key, resource}) reads a listed relative reference/script as UTF-8 text
  -> run_skill_script({key, script, args}) executes a loaded Python script from the active project
  -> save_skill(...) validates and writes only Team
```

Full bodies are never included merely because a Skill exists. This keeps model context stable as the shared catalog grows.

The initial `load_skill({key})` result lists up to 200 relative resource names under the selected Skill. A second call can read one resource without exposing a physical directory or granting general filesystem access to the VP installation. Traversal, absolute paths, binary content, and resources over 2 MB are rejected.

Python resources are executed through `run_skill_script`, never by exposing the Registry directory to general shell execution. The model supplies a canonical Skill key, a relative `.py` path, and literal arguments. The Skill must already be enabled and loaded for the current run. Runtime resolves the private install path, rejects traversal and compound shell syntax, and runs the script with the active business project as `cwd`, so project-relative inputs and outputs behave normally. Public tool results and resumable command state keep only logical Skill identifiers and redact the physical Registry path.

## Write Boundary

- Built-in Skill source is read-only through Runtime and Workbench APIs.
- Team Skill creation/update goes through `save_skill`, the Team management API, or normal reviewed Git maintenance. Team is editable; only Built-in is read-only.
- The model supplies a logical name and content, never a destination path.
- Registry root is derived from the Vintage Programmer installation, not `VP_WORKSPACE_ROOT`, current project, or current working directory.
- Ordinary file/shell tools reject Registry paths and project-level `.agents/skills`, `.codex/skills`, and legacy `workspace/skills` destinations.
- Team and Built-in cannot silently share a name.

## Runtime State

Ignored state lives under:

```text
app/data/runtime/skills/
├── skill_index.json
├── skill_overrides.json
└── skill_migration.json
```

The index is a disposable metadata cache. Built-in enabled overrides are user runtime state. The migration report records copied, already-present, conflicting, and skipped legacy Skills. `SKILL.md` files remain authoritative.

## Legacy Migration

Legacy sources are detected at startup:

```text
agents/vintage_programmer/skills/
workspace/skills/
```

Known replaced product Skills are skipped. Other valid legacy Skills are copied to Team with supporting files intact. Migration is idempotent. Existing targets with different content produce a conflict and are never overwritten.

## Team Contribution

1. After upgrading an older checkout, run `python scripts/migrate_skills.py --json` and resolve any reported conflicts.
2. Create or update the Team Skill through VP Skill management.
3. Run `python scripts/validate_skills.py`.
4. Review the Git diff, including references and scripts.
5. Commit and push the Vintage Programmer branch.
6. Merge through GitLab review; coworkers receive it on pull/update.

The validator checks strict schema, duplicate names, suspected credentials/private keys, personal absolute paths, and excessive body size.
