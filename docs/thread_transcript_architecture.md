# Session = Thread：Transcript-first 架构

## 结论

在产品概念中，原来的 `Session` 现在就是 `Thread`。磁盘目录仍保留为 `app/data/sessions/`，避免破坏旧数据路径和已有 API；其中每个 JSON 文件保存一条最小 Thread，而不是以前的 Harness 语义状态集合。

```text
Thread（长期、可重放）
  ├─ metadata / project / cwd
  ├─ thread_transcript
  ├─ compaction
  ├─ active_attachment_ids
  └─ pending_interaction

Turn Trace（按 Turn 保存的执行事实）
  ├─ contexts / Developer Prompt（兼容历史 System Prompt）
  ├─ steps（引用 transcript item_id）
  └─ timing / validation / error / terminal

UI
  ├─ Thread transcript
  ├─ 当前 SSE 事件
  ├─ pending interaction
  └─ 按需读取工具 Trace
```

`task_state`、`work_cursor`、`thread_memory`、`artifact_memory`、`current_task_focus`、`task_checkpoint` 和 `route_state` 不再是持久状态，也不参与模型输入。Plan 由模型通过 `update_plan` 形成 transcript 中的真实工具事务；Harness 不再另建一份长期任务真相。

## 独立的 Task 快照

产品里的 `Task` 与这里移除的 Thread 内部 `task_state` 不是同一概念。Task 是用户显式创建的、项目级的可续接快照，单独保存在 `app/data/tasks/`；它不拥有聊天记录，也不绑定创建它的 Thread。快照包含目标、当前进展、关键决策、下一步、阻塞项和相关产物。

用户在 Tasks 面板点击“加载”时，前端仍向当前 Thread 发送一条普通用户消息，并附带 `task_id`。服务端把当时的 Task 快照作为该用户 transcript item 的隐藏 `task_context` 保存并注入模型输入。Runtime 会明确要求模型在当前 Thread 继续，不打开或切换到来源 Thread；可见聊天内容仍只是用户发出的“加载当前任务”。这样，历史重放可复现当时加载的上下文，而 Task 本身之后仍可被 `save_task` 独立更新。

## 磁盘上的 Thread V4

一个新 Thread 文件只允许保存以下结构：

```json
{
  "thread_record_schema_version": 4,
  "id": "thread-id",
  "created_at": "...",
  "updated_at": "...",
  "activity_at": "...",
  "activity_revision": 3,
  "activity_kind": "turn_completed",
  "title": "...",
  "project_id": "...",
  "project_title": "...",
  "project_root": "...",
  "git_branch": "main",
  "cwd": "...",
  "thread_transcript": {
    "schema_version": 2,
    "items": []
  },
  "thread_schema_version": 2,
  "active_attachment_ids": [],
  "attachment_context_cleared": false,
  "compaction": {},
  "pending_interaction": {}
}
```

`turns` 不再写入磁盘。为了兼容现有前端和 API，加载 Thread 后可以从 transcript 临时投影出 `turns`；它不是第二份历史，也不会反向覆盖 transcript。

## Transcript 保存什么

`thread_transcript.items` 是模型历史的唯一事实源，保存 typed message：

```json
[
  {"id": "u1", "turn_id": "t1", "role": "user", "content": "读取 README"},
  {
    "id": "a1",
    "turn_id": "t1",
    "role": "assistant",
    "content": "",
    "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}]
  },
  {
    "id": "tool-1",
    "turn_id": "t1",
    "role": "tool",
    "tool_call_id": "call-1",
    "name": "read_file",
    "content": "..."
  },
  {"id": "a2", "turn_id": "t1", "role": "assistant", "content": "读取完成。"}
]
```

最终 Assistant item 可带一个很小的 `trace` 引用，用于 UI 定位本轮 Trace；执行耗时、校验和错误不会复制进 Thread。

## Compaction 和附件给谁用

`compaction` 不是仅供显示。它首先服务于下一次模型输入：

```json
{
  "generation": 2,
  "summary": "较早历史的压缩摘要",
  "compacted_until_item_id": "item-123",
  "compacted_at": "..."
}
```

Runtime 用切点跳过较早 transcript，发送 summary 和切点后的完整消息事务。Harness 还用 generation、切点和时间判断压缩生命周期；UI 只展示其诊断信息。压缩不创建聊天消息，也不改变 Thread 身份。

附件内容不是永久复制进 transcript。用户消息可保存当轮附件引用；`active_attachment_ids` 保存当前 Thread 的 sticky 附件上下文。下一轮构造请求时，Runtime 根据这些 ID 读取附件元数据或预览并形成来源明确的 contextual message。用户显式清除后，`attachment_context_cleared` 记录该状态。

## 每次实际发送给模型的内容

一次 provider 请求大致为：

```text
messages = [
  ChatMessage(role="developer", agent spec + runtime boundary),
  HumanMessage([project_instructions] ...),       # 仅在当前项目显式绑定 Project Profile 时
  HumanMessage([compaction_summary] ...),         # 仅在发生过压缩时
  ...未被压缩的 typed transcript messages,
  HumanMessage([attachments] ...),                # 仅在当前上下文有附件时
  HumanMessage(当前用户原始请求)                   # 新 Turn 时位于最后
]

tools = provider 绑定的工具 schema
```

恢复一个暂停的 Turn 时，不再伪造新的用户请求；Runtime 保留原 Assistant tool call，追加同一 `tool_call_id` 的真实 ToolMessage 后继续模型循环。

开发者调试不再显示容易误解的 `architecture`、`replayed_message_count`、`roles` 和 `compaction_summary_chars` 摘要。UI 直接展示持久 Thread 历史；Developer Prompt 作为本轮 Trace 的上下文快照按需查看。

## Turn Trace 为什么保留

Turn Trace 不是第二份历史，也不是任务记忆。它只解释 Thread Item 是怎样产生的：

- 模型生成哪个 Assistant Item、使用哪个 Developer Prompt；
- 工具调用由哪个 Assistant Item 发起、生成哪个 Tool Item；
- 工具耗时、边界检查、错误类型、重试与恢复结果；
- Turn 最终以完成、失败、取消还是等待结束。

Trace 只有一个技术状态：`running`、`waiting_user`、`completed`、`failed`、`cancelled` 或 `interrupted`。`completed` 只表示本 Turn 正常结束，不是 Harness 对业务任务完成度的判断。

新 Trace 位于 `app/data/turn_traces/<thread_id>/<turn_id>.json`，使用稳定 Turn ID，而不是一次 HTTP 执行的临时 `run_id`。旧 `app/data/runs/` 只读兼容，不再接收新记录。Thread 的最终 Assistant Item 只保存 `trace_ref`、状态、耗时和工具数。

执行详情采用两级读取，避免为了普通进度展示加载完整调试记录：

- 普通 Thread 页面不读取 Trace；
- 展开执行过程时按需读取本 Turn 的技术记录；
- 展开“开发者调试”后，首先显示截至该 Assistant Item 的完整 Thread 历史；
- 工具结果旁的“查看 Trace”只展开该工具的耗时、校验、错误和恢复信息；
- Developer Prompt 通过一个独立的小入口按需展开；不再展示 Runtime Inspector 和大块 Raw JSON。

Trace 的 `steps` 按 transcript 顺序保存 `item_id`。例如 Assistant `a1` 发起 `call-1`，Tool Item `tool-1` 返回结果，Trace 会同时保存 `requested_by_item_id=a1`、`tool_call_id=call-1` 和 `item_id=tool-1`。调试人员不需要在两套无关时间线之间猜测对应关系。

## 暂停和恢复

- 命令审批与 `request_user_input` 属于原 Turn，不创建新 Turn。
- 等待时只把最小恢复信息保存在 `pending_interaction`；Plan 快照只在这里为恢复当前 Turn 而保留。
- 用户批准时执行原 tool call，写入真实 ToolMessage；用户拒绝时写入一个 `user_declined` ToolMessage。
- 用户决定不是 HumanMessage，Harness 检查点也不是 HumanMessage。
- Turn 正常结束后清空 `pending_interaction`。旧 Plan 仍作为 `update_plan` 工具事务留在 transcript 中；新 Turn 是否重建 Plan 由模型决定。

## 旧 Session 自动迁移

- `app/data/sessions/` 不改名，原 URL、Session ID 和聊天入口继续使用。
- 首次读取 V1/V2 文件时，从旧 `turns` 生成 transcript；已有 transcript 时始终以 transcript 为准。
- 保留标题、项目、cwd、附件、压缩摘要、待审批状态和可定位的旧 Run 证据。
- 旧 `agent_state.pending_*` 迁入 `pending_interaction`；旧 Plan 只在存在暂停 Turn 时作为恢复快照迁入。
- 迁移完成后统一写成 V4，并移除旧 Harness 语义字段和 `latest_run_id`。
- 第一次改写前自动把原文件备份到 `app/data/session_backups/<thread_id>.v2.json`；已有备份不会覆盖。
- 迁移幂等；之后重复加载不会再次改写或重复生成消息。

用户不需要运行迁移脚本。升级后正常打开旧聊天即可触发迁移；旧聊天记录和 Session ID 不变。

## Harness 最终职责

Harness 只负责模型不应自行决定的技术边界：

- Thread/Turn 生命周期和消息顺序；
- 工具 schema、tool call/result 配对与执行；
- 文件、命令、网络、权限和审批边界；
- pending interaction、运行中追加指令和取消；
- context 估算与 compaction；
- Turn Trace 和实时事件。

任务理解、计划内容、工具策略和“用户目标是否真正完成”的语义判断仍交给模型。这样既保留可恢复、可调试的产品能力，也避免 Harness 用多套状态替模型管理任务。
