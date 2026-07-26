# Vintage Programmer 文档索引

这里仅保留能够帮助使用、维护或验证当前 Vintage Programmer 的文档。当前实现以代码和测试为最终事实来源；发布说明和审计记录只描述对应时间点，不应覆盖当前架构文档。

## 公司 GitLab 建议

建议把本页列出的全部当前文档随 Vintage Programmer 仓库共享。它们不包含凭证、公司 URL、业务文件内容或个人绝对路径。

不要提交以下运行时或本机材料：

- `.env`、token、证书私钥和公司接口地址；
- `app/data/` 下的 Thread、Turn Trace、上传文件和运行缓存；
- `artifacts/evals/` 下未经脱敏的本机报告和隔离工作区；
- 浏览器 profile、下载文件、测试生成物和个人截图。

## 从这里开始

| 文档 | 用途 | 读者 |
| --- | --- | --- |
| [内部设计手册](internal_design_manual.md) | 当前系统全景、模块职责、持久化和模型请求 | 所有维护者 |
| [Session = Thread 架构](thread_transcript_architecture.md) | Thread V4、typed transcript、压缩、暂停恢复和 Turn Trace | Runtime / 数据维护者 |
| [Runtime 可靠性](runtime_reliability.md) | 压缩、工具失败恢复、审批边界、Eval 和前端可靠性基线 | Runtime / 测试维护者 |
| [Agent 工作流](agent_workflow_runtime.md) | 运行中追加指令、单层并行 Subagent 和后台 Eval | Agent / 前端维护者 |
| [Project Profiles](project_profiles.md) | 共享项目说明、显式绑定、目录和 Runtime 加载规则 | Runtime / 项目维护者 |

## Skills 与工具

| 文档 | 用途 |
| --- | --- |
| [Skill 架构](skill_architecture.md) | Built-in / Team 目录、渐进披露、写入边界和迁移 |
| [Skill Runtime Contract](skill_runtime_contract.md) | Skill、业务 Project、脚本路径和凭证变量的明确契约 |
| [Native Tool Metadata](native_tool_metadata.md) | 工具能力、来源、权限要求和验证顺序 |
| [模型工具契约审计](tool_contract_audit.md) | 当前 33 个模型工具的 schema 与非显然语义审计快照 |

## 排障

| 文档 | 用途 |
| --- | --- |
| [Turn Trace 指南](observability/trace_guide.md) | Thread 历史、工具事务、Trace 和 System Prompt 如何对应 |
| [Troubleshooting](observability/troubleshooting.md) | Provider、工具、附件、等待和前端显示问题的排查顺序 |

## Eval

Eval 的案例定义和运行说明保留在 [`evals/`](../evals/) 目录，避免把测试 fixture 与架构文档混在一起：

- [Eval 运行说明](../evals/README.md)：命令、报告、退出码和公司编译器适配；
- [Eval 测试内容说明](../evals/TEST_CONTENT.zh-CN.md)：每个案例实际测试什么，以及通过结果能够证明什么。

## 发布记录

[`releases/`](releases/) 保存历史发布说明。它们用于回答“某个版本改了什么”，不是当前设计规范。判断当前行为时优先看本页的架构文档和源码。

## 已移除的旧材料

以下材料已被当前架构取代，因此不再放在当前文档集中：

- 早期 Codex 对标研究路线图；
- 依赖 `task_state`、`work_cursor` 和旧 checkpoint 的任务可靠性草案；
- v3.1.6 旧 compaction 设计；
- 旧 Kernel Robot / Role-Agent Lab 截图和 MAT 品牌图。

其中曾被 Git 跟踪的材料仍可通过 Git 历史查阅。不要从历史文档恢复旧 Session 六要素、system/workspace Skill 或 Agent OS trace 结构。
