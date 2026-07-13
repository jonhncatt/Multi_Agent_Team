# Session = Thread：Transcript-first 架构

## 结论

`Session` 是持久 Thread，`thread_transcript` 是模型对话历史的唯一事实源。`ModelContext` 六/八要素 JSON 和任务关系分类器已经删除。

```text
Session / Thread
  thread_transcript: user -> assistant(tool_calls) -> tool -> assistant
  task_state: Harness 任务/checklist 状态
  work_cursor: Harness 工作位置
  turns: 现有前端/API 的兼容投影
```

## 每次模型调用看到什么

按以下顺序构造 Chat Completions messages：

1. 静态 agent、工具与运行规则（SystemMessage）。
2. 当前目录和权限边界 `current_runtime_context`（SystemMessage）。
3. 如果发生过压缩，加入替代更早历史的 compaction summary（SystemMessage）。
4. 回放未被压缩的 typed transcript（HumanMessage、AIMessage、ToolMessage）。
5. 当前附件清单或预览（仅当前轮需要时加入 SystemMessage）。
6. 当前用户原始请求（HumanMessage，始终最后）。

工具 schema 仍由 provider/backend 单独绑定，不写进 transcript。

## 持久化结构

```json
{
  "thread_schema_version": 1,
  "thread_transcript": {
    "schema_version": 1,
    "items": [
      {"id": "...", "role": "user", "content": "...", "turn_id": "..."},
      {
        "id": "...",
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}]
      },
      {"id": "...", "role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": "..."},
      {"id": "...", "role": "assistant", "content": "完成。", "turn_id": "..."}
    ]
  }
}
```

`turns` 暂时继续保存 user/assistant UI 消息，保证现有接口和前端兼容；Runtime 不再用它构造模型输入。新消息由 `SessionStore` 同时写入 transcript 与 UI 投影，中间工具消息只写 transcript。

## Harness 状态边界

- `task_state`、`work_cursor`、`route_state`、`thread_memory`、RuntimeTrace 仍可服务于计划、恢复、界面和审计。
- 这些字段不再在每轮拼成 Supporting Context JSON 发给模型。
- 当前工具结果保存在 ToolMessage 和运行记录中，不自动提升为长期 `verified_facts`。
- 权限由 RuntimeBoundary 强制执行，历史消息不能覆盖权限边界。

## 压缩

context meter 只估算实际 transcript、compaction summary 和待发送用户消息，不再把 Harness side state 算成模型上下文。达到阈值时，较早的 transcript 被总结；之后只发送 summary 与未压缩的新消息。summary 不覆盖 Harness 的 task state 或 work cursor。

## 旧 Session 迁移

- 没有 `thread_transcript` 的 Session，从现有 `turns` 生成 user/assistant transcript。
- 保留原 turn id 作为 transcript item id/turn_id，便于 compaction 定位。
- 已存在 transcript 时，以 transcript 为准，不从 UI 投影反向覆盖。
- 迁移幂等，读取旧 Session 后统一写入 schema version 1。

旧 `ContextManager` 数据仍可读取，供历史迁移和诊断兼容；它不再参与正常模型输入，也不再在每轮自动更新事实或对话副本。
