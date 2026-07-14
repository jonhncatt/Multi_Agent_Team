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
  -> save_skill(...) validates and writes only Team
```

Full bodies are never included merely because a Skill exists. This keeps model context stable as the shared catalog grows.

The initial `load_skill({key})` result lists up to 200 relative resource names under the selected Skill. A second call can read one resource without exposing a physical directory or granting general filesystem access to the VP installation. Traversal, absolute paths, binary content, and resources over 2 MB are rejected.

## Write Boundary

- Built-in Skill source is read-only through Runtime and Workbench APIs.
- Team Skill creation/update goes through `save_skill` or the Team management API.
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
