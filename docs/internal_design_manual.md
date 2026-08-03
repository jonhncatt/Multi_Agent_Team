# Vintage Programmer 内部设计手册

本文描述当前 `main` 的稳定架构。它面向项目维护者，不承担版本流水账；历史变化请查看 [`releases/`](releases/) 和 Git 历史。

## 1. 产品定位

Vintage Programmer 是本地运行的单主 Agent 工作台。当前稳定路径使用 OpenAI-compatible Chat Completions 消息循环：模型选择工具和工作策略，Harness 管理边界、执行、Thread 生命周期和事实记录，前端展示真实进度。

```text
用户请求
  -> 主模型回复或 tool calls
  -> Harness 校验并执行工具
  -> ToolMessage 回灌模型
  -> 继续模型循环
  -> 当前 Turn 最终回答、等待、失败或取消
```

Harness 不通过业务关键词替模型规划，也不维护第二份长期任务语义。

## 2. 核心对象

### Thread

产品中的 Session 就是 Thread。磁盘和兼容 API 仍使用 `session` 名称，持久文件位于：

```text
app/data/sessions/<thread_id>.json
```

Thread 保存身份、Project、cwd、typed transcript、压缩切点、附件引用和暂停交互。`thread_transcript.items` 是可继续对话的唯一历史事实源。

### Turn

Turn 是一条用户请求从进入 Runtime 到本轮结束的生命周期。同一个 Turn 可以包含多次模型调用、多组工具调用、Plan、审批等待和运行中追加指令。

### Model call

Model call 是 Turn 内的一次 provider 请求。一个 Turn 通常会因为工具回灌而包含多个 model call；这不等于创建了多个 Thread 或 Turn。

### Turn Trace

Turn Trace 保存某个 Turn 的技术执行事实：模型上下文快照、工具校验、耗时、错误和恢复。新记录位于：

```text
app/data/turn_traces/<thread_id>/<turn_id>.json
```

Trace 不是第二份聊天历史，也不参与下轮模型记忆。旧 `app/data/runs/` 只用于兼容读取，不再是新执行的主要记录。

## 3. 实际发送给模型的内容

一次模型请求由以下两部分组成：

```text
messages = [
  ChatMessage(role="developer", agent spec + RuntimeBoundary),
  optional project instructions,
  optional compaction summary,
  uncompressed typed transcript,
  optional attachment context,
  current user request
]

tools = 当前 Runtime 暴露的 structured tool schemas
```

Developer Message 只有一个。项目说明、压缩摘要和附件带来源进入上下文，不能覆盖 Developer Message 或 RuntimeBoundary。工具结果必须使用原 `tool_call_id` 形成 ToolMessage。

详细结构见 [Session = Thread 架构](thread_transcript_architecture.md)。

## 4. Harness 与模型的职责

Harness 负责：

- Thread / Turn 生命周期和消息顺序；
- tool schema、参数、路径、命令、网络和权限校验；
- 工具执行、tool call/result 配对和审批恢复；
- context 估算、压缩和附件解析；
- 运行中追加指令、取消、Subagent 收束；
- Turn Trace、SSE 事件和兼容迁移。

模型负责：

- 理解用户目标和当前上下文；
- 决定是否计划、读取、修改、验证或询问；
- 选择工具、参数和失败后的替代策略；
- 判断用户任务的语义完成度并给出最终交付。

`update_plan` 是模型维护的当前 Turn checklist。Harness 校验其结构，但不把 Plan 变成另一套持久任务状态。

## 5. 持久化边界

| 数据 | 位置 | 作用 | 是否发给模型 |
| --- | --- | --- | --- |
| Thread | `app/data/sessions/` | 可继续的对话历史 | transcript 的有效部分会发送 |
| Turn Trace | `app/data/turn_traces/` | 技术调试和 UI 按需详情 | 不作为历史发送 |
| 旧 Run | `app/data/runs/` | 老 Session 兼容读取 | 否 |
| Session metadata | `app/data/session_meta/` | 列表和标题快速读取 | 否 |
| Skill runtime cache | `app/data/runtime/skills/` | 索引、开关和迁移状态 | 只派生轻量 Skill 列表 |
| Eval artifacts | `artifacts/evals/` | 本机基线和失败证据 | 否 |

`app/data/` 与 `artifacts/` 是本机运行数据，不应提交到团队 Git 仓库。

## 6. Context 与压缩

- 当前上下文来源是 Thread transcript，不是旧 Harness 六要素。
- provider 返回的真实 `input_tokens` 优先于本地估算。
- GPT-5.4 默认使用 272,000 token 的可用窗口；默认自动压缩线为 90%，危险线为 95%。公司部署验证后可覆盖窗口或阈值。
- 压缩是独立内部操作，不创建聊天 Turn，也不会切断尚未闭合的 tool call。
- 持久压缩记录只保存 generation、summary、切点和时间；切点之后仍使用完整 typed transaction。

## 7. 权限模式

| 模式 | 文件 | 命令 | 网络 |
| --- | --- | --- | --- |
| Default | 当前 Project 只读 | 禁止 | 禁止 |
| Auto | 当前 Project 读写 | 当前 Project 内安全命令 | 禁止 |
| Full Access | 完整本机文件系统读写 | 可在任意本机目录执行安全命令 | 允许 |

选择 Full Access 就是本轮完整文件系统授权，不再需要 `VP_ALLOW_ANY_PATH`。

权限放宽不取消其他边界：Builtin Skill 仍然只读；危险命令仍会拒绝；网络来源代码、供应链操作和外部写入继续按策略审批。每一次 `git push` 都需要绑定精确命令、仓库、remote、分支和 HEAD 的一次性批准。

## 8. Skills

Skills 独立于当前业务 Project：

```text
skills/builtin/<name>/SKILL.md   # 产品维护，只读
skills/team/<name>/SKILL.md      # 团队维护，随 VP Git 仓库共享
```

初始上下文只列出启用 Skill 的轻量 metadata 和绝对 `SKILL.md` 路径。模型需要使用时先通过普通 `read_file` 读取完整说明；附属脚本通过普通 `exec_command` 执行。

维护、翻译或审查 Skill 时，Skill 是待处理数据，不会因为文件中出现 Python、Git 或部署命令而自动执行。路径和凭证规则见 [Skill Runtime Contract](skill_runtime_contract.md)。

## 9. 运行中追加指令与 Subagent

- 同一 Thread 同一时刻只有一条主模型请求链。
- 运行中追加的文本先排队，在安全模型边界写入当前 Turn，不启动并行主模型请求。
- Subagent 由模型通过 `spawn_subagent` 按需创建，使用独立精简上下文。
- 第一版 Subagent 为单层、只读、可后台并行；主 Agent 通过 `wait_subagents` 收集精简结果。
- Turn 结束前 Runtime 会收束子任务，不留下孤儿执行。

详见 [Agent 工作流](agent_workflow_runtime.md)。

## 10. 前端观察模型

首页同时展示模型 Plan 和最近执行状态。实时状态来自 SSE，heartbeat 只代表连接存活，不冒充语义进展。

每条 Assistant 消息的“执行过程”按需加载该 Turn 的 activity；“开发者调试”显示截至该消息的 Thread 历史。工具项通过 `item_id`、`assistant_item_id`、`tool_call_id` 和 `tool_result_item_id` 对应到 Turn Trace。Developer Prompt 单独折叠展示。

## 11. Eval 与质量门禁

- `pytest` 和 CI 使用 fake Runtime，不调用真实公司模型。
- `scripts/run_evals.py --validate-only` 只校验案例与 verifier。
- live Eval 只在明确配置 provider 的公司环境手动运行。
- 报告区分 `passed`、`failed`、`blocked`，并记录完成状态准确性、工具错误、恢复结果和权威验证。
- 报告不得保存凭证、完整公司路径、URL、文件内容或完整工具参数。

## 12. 当前源码入口

| 领域 | 主要文件 |
| --- | --- |
| HTTP / SSE / Thread API | `app/main.py` |
| 主模型循环 | `app/vintage_programmer_runtime.py` |
| Provider 和 structured tools | `app/vp_runtime_backend.py` |
| 本地工具实现 | `app/local_tools.py` |
| 工具与路径校验 | `app/action_validator.py`, `app/runtime_boundary.py` |
| Thread / Trace 存储 | `app/storage.py`, `app/thread_record.py`, `app/thread_transcript.py`, `app/turn_trace.py` |
| Context 与压缩 | `app/context_meter.py`, `app/context_pack.py` |
| Skills | `app/workbench.py` |
| 前端 | `app/static/app.js`, `app/static/styles.css`, `app/static/locales.js` |

## 13. 文档维护规则

- 当前架构只在本手册和专题文档中维护，不把版本流水账继续追加到本手册。
- 发布说明描述变化，不定义当前行为。
- 设计提案必须明确标注 Draft；实现完成后更新或删除，不能长期冒充当前规范。
- 任何文档中的命令、路径和权限描述都应由源码或测试验证。
