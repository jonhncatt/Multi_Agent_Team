# Native Tool Metadata

## Purpose
Vintage Programmer uses tool metadata to describe tool capability, implementation origin, permission requirements, and risk level.

这份 metadata 是当前原生工具的单一事实来源。它不改变工具名，也不直接改变工具实现，只用于补足 UI 展示、权限解释和保守型验证。

## Group
`group` describes what the tool does.

Allowed groups:
- `control`
- `shell`
- `edit`
- `file`
- `document`
- `web`
- `browser`
- `media`
- `session`
- `archive`
- `unknown`

`group` 只描述能力类别，不描述历史来源或灵感。

## Source
`source` describes where the implementation belongs.

Allowed sources:
- `native`
- `adapter`
- `optional`
- `legacy`
- `unknown`

`source` must not describe design inspiration.
Codex/OpenClaw inspiration is documented only in attribution files and audit history, not in runtime metadata.

## Permission Relationship
Permission mode defines allowed capabilities.
Tool metadata defines required capabilities.
Harness compares them before tool execution.

ActionValidator still performs argument-level checks such as:
- path boundary validation
- command allowlist
- dangerous command blocking
- URL/network checks
- `apply_patch` file path extraction
- schema validation

## Validation Order
The intended validation order is:
1. tool exists?
2. tool allowed by current runtime?
3. tool metadata requires capability?
4. permission mode / RuntimeBoundary allows those capabilities?
5. schema validation
6. argument-level path / URL / command validation
7. execute tool

当前实现将第 3 步和第 4 步合并为一次保守检查：metadata 读取工具所需能力，然后立即和 `RuntimeBoundary` 对比；之后再进入 schema 与参数级校验。

## Stability Policy
Tool names remain stable.
Metadata may evolve, but must not silently change tool behavior.

当前策略是：
- 缺失 metadata 时回退到安全的 `unknown` metadata，而不是中断运行。
- `ActionValidator` 继续保留现有硬编码边界表和参数级防护。
- 可选依赖 `optional_dependency` 目前仅作说明，不在这一轮强制阻断。
