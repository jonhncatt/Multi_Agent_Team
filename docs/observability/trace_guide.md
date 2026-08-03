# Turn Trace Guide

Turn Trace 用来回答“这一轮为什么这样执行”，不是第二份聊天历史，也不是模型记忆。

## 数据位置

```text
app/data/sessions/<thread_id>.json
app/data/turn_traces/<thread_id>/<turn_id>.json
app/data/runs/<thread_id>/<legacy_run_id>.json   # 仅旧记录兼容
```

- Thread transcript 保存真实的 user / assistant / tool 消息事务。
- Turn Trace 保存模型上下文快照、校验、耗时、错误和恢复。
- 新执行自动写 Turn Trace，不需要启用 `AGENT_OS_TRACE`、`VP_TRACE` 或 shadow logging。

## UI 中如何查看

1. 在 Assistant 消息下展开“执行过程”，先看 Plan、最近活动和工具摘要。
2. 展开“开发者调试”，查看截至该 Assistant Item 的完整 Thread 历史。
3. 找到对应 Tool Item，展开“查看 Trace”。
4. 只有怀疑提示词或权限范围错误时，再展开 Developer Prompt。

UI 通过以下稳定标识建立对应关系：

| 字段 | 含义 |
| --- | --- |
| `item_id` | transcript 中的消息项 |
| `assistant_item_id` / `requested_by_item_id` | 发起工具调用的 Assistant Item |
| `tool_call_id` | provider 工具调用 ID |
| `tool_result_item_id` | 回灌结果对应的 Tool Item |
| `trace_ref` | 当前 Turn Trace 的持久引用 |

一次真实工具调用在 Thread 中表现为 Assistant tool call 加 ToolMessage；UI 默认把它聚合成一个工具事务，不应显示成两个独立执行。

## Trace 能回答什么

- 模型实际看到了哪个 Developer Prompt 和 RuntimeBoundary；
- 哪个 Assistant Item 发起了哪个工具；
- 原始参数如何被归一化，schema 和边界是否通过；
- 工具执行了多久，返回成功、失败还是等待；
- `error_kind`、重复次数、replan 和恢复结果是什么；
- Turn 最终是 `completed`、`waiting_user`、`failed`、`cancelled` 还是 `interrupted`。

`completed` 只表示该 Turn 技术上正常结束，不是 Harness 对用户业务目标的完成判断。

## API 按需读取

普通 Thread 详情不会加载完整 Trace。需要时使用：

```text
GET /api/thread/<thread_id>/turn/<assistant_item_id>?view=activity
GET /api/thread/<thread_id>/turn/<assistant_item_id>?view=debug
```

- `activity` 返回当前 Turn 的执行详情。
- `debug` 额外返回截至该消息的 Thread items 和 Developer Prompt context。

## 分享前检查

Turn Trace 可能含 Developer Prompt、用户内容、工具参数、路径和结果预览。向公司工单或外部人员提供前，应优先发送错误分类、时间、工具名和最小复现；不要直接提交整个 `app/data/turn_traces/`。

Eval 报告采用单独的安全摘要规则，不能用 raw Trace 替代脱敏报告。
