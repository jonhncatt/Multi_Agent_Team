# Skill Progressive Disclosure Plan

## 背景

当前 runtime 会读取已启用 skill 的完整 `SKILL.md`，并直接拼进 agent system prompt。这个方式在 skill 数量少时简单有效，但 skill 增多后会带来三个问题：

- system prompt 变长，挤占用户任务和代码上下文预算。
- 多个 skill 的 instruction 可能互相干扰，调试困难。
- 无法解释“为什么命中这个 skill、为什么没命中那个 skill”。

下一阶段目标是把 skill 从“启用后全文注入”升级为“轻量索引、按需路由、命中后全文加载”。

## 第一性原则

- `description` 是路由契约，不是普通简介。它必须清楚说明什么时候使用、什么时候不要使用。
- 默认不加载完整 skill。只有显式调用或路由命中后，才读取完整 `SKILL.md`。
- runtime 负责扫描、权限过滤、路径解析和全文读取；模型只基于轻量 registry 做选择。
- 每轮默认激活 0-3 个 skill；复杂任务可以提高到硬上限 5 个，但必须能解释原因。
- repo/project skill 优先于 team/personal/global skill；domain-specific skill 优先于 generic skill。

## 当前路径约定

现有实现使用：

```text
workspace/skills/<skill_id>/SKILL.md
```

短期内不迁移目录结构。后续可以增加 category/tag 字段来支持 UI 分组，而不是先改物理路径。

## 推荐 Frontmatter

最小必需字段：

```yaml
---
name: nvme-failure-analysis
description: Use when analyzing NVMe validation failures, SSD firmware test logs, command traces, reset behavior, queue recovery, power state transitions, or PCIe/NVMe error handling. Do not use for general code review without NVMe or SSD validation context.
---
```

建议扩展字段：

```yaml
title: NVMe Failure Analysis
category: debug
tags:
  - nvme
  - ssd
  - validation
tools_required:
  - search_codebase
  - read_file
  - exec_command
priority: 80
version: 0.1.0
owner: dalizhou
last_tested: 2026-07-07
status: experimental # experimental / stable / deprecated
auto_activation: true
```

## MVP Runtime Flow

```text
scan workspace/skills
  -> parse SKILL.md frontmatter only
  -> filter enabled + bind_to/current agent + status
  -> inject lightweight registry into model context
  -> model selects candidate skill ids
  -> runtime validates ids and limits count
  -> runtime reads full SKILL.md only for activated skills
  -> final prompt includes activated skill contents
```

## Activation Rules

Priority order:

1. Explicit user invocation such as `$skill-name`.
2. Project/repo-local skill over broader skill scopes.
3. Domain-specific skill over generic skill.
4. Higher `priority` over lower `priority`.
5. `stable` over `experimental` for automatic activation.

Defaults:

- `default_max_active_skills: 3`
- `hard_limit: 5`
- `experimental + auto_activation: false` can only be activated explicitly.
- Unknown or disabled skill ids are ignored and reported in inspector/debug metadata.

## Skill Preview

Add a preview path before or alongside implementation:

```text
vp skill preview "帮我 review 这个 GitLab MR，重点看 NVMe reset 逻辑"
```

Expected output:

- Activated skills and reasons.
- Not activated high-similarity skills and reasons.
- Token estimate for base prompt, registry, loaded skills, and total input.
- Any conflicts, missing tools, or disabled/experimental status.

This is the main debug surface for routing behavior.

## Skill Lint

P2 lint checks:

- `name` is present and unique.
- `description` is present, specific, and not overly short.
- `when_to_use` / `when_not_to_use` are present for stable skills.
- `status`, `category`, and `priority` are valid.
- `tools_required` exists in the current tool registry.
- Full `SKILL.md` length stays under the configured budget or emits a warning.
- Experimental skills cannot auto-activate unless explicitly allowed.

## Skill Eval

Two eval families are needed once routing exists:

- Routing eval: given an input, expected skills are activated and unrelated skills are not activated.
- Execution eval: after activation, the answer follows the expected workflow and produces the right kind of evidence or artifact.

Routing failures should usually be fixed by improving `description` and boundary metadata before adding more runtime logic.

## Implementation Order

P0:

- Build a lightweight registry loader from existing `workspace/skills/<skill_id>/SKILL.md`.
- Inject registry summaries instead of full enabled skill contents.
- Add activation and full-load only for selected skills.

P1:

- Add skill preview output for routing/debug.
- Expose activated skill ids and reasons in run inspector metadata.

P2:

- Add skill lint.
- Add status/version/owner metadata enforcement.

P3:

- Add routing evals.
- Add execution evals for important domain skills.

P4:

- Consider broader scopes such as project, team, personal, and global skills.
- Consider dependency support only after preview/lint/eval are stable.
