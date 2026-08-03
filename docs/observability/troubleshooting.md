# Troubleshooting Guide

## 先从产品路径复现

macOS / Linux：

```bash
./run.sh
```

Windows：

```powershell
.\run.ps1
```

记录 Thread、用户操作、权限模式、模型和可见错误。不要先复制整个 Session 或 Trace。

## 推荐排查顺序

1. 查看 Assistant 消息下的“执行过程”：当前步骤、工具、等待状态和最后进展。
2. 查看完整 Thread 历史，确认 user / assistant / tool 顺序和追加指令位置。
3. 从有问题的 Tool Item 展开 Trace，检查 schema、边界、`error_kind` 和恢复。
4. 只有怀疑上下文错误时查看 Developer Prompt 和 RuntimeBoundary。
5. 查看 `/api/runtime-status` 的 provider、权限、cwd、context 和 compaction 状态。
6. 最后再使用浏览器 Network 面板确认 SSE 或 API 传输问题。

详见 [Turn Trace Guide](trace_guide.md)。

## 常见问题

### Provider 或模型不可用

检查：

- Settings 中选中的 provider 和 model；
- VP 安装目录 `.env` 中的认证变量是否存在；
- 自定义 Base URL 和 CA 路径是否由启动进程读取；
- `/api/runtime-status` 的 provider/auth 摘要。

不要让 Agent 读取或搜索 `.env`。修改环境后重启 VP。

### Agent 说路径不可访问

先看本轮 RuntimeBoundary：

- Default：当前 Project 只读；
- Auto：当前 Project 读写和安全命令；
- Full Access：完整本机文件系统读写和命令范围。

Full Access 不需要额外环境变量。如果模型仍声称不可访问，检查它收到的 `file_read_scope` 是否为 `full filesystem`，再查看工具 Trace 中是否真的发生 `path_outside_allowed_roots`。

### 工具调用失败后停止

在 Trace 中区分：

- `tool_call_failure`：工具名、schema、参数或边界不正确；
- `command_failure`：命令已经执行但返回非零；
- `verification_failure`：编译或测试未通过；
- `environment_blocked`：provider、编译器、网络或凭证不可用；
- repeated/no-progress：同类失败重复且没有新进展。

不要只提高工具次数。确认结构化错误是否回灌模型，以及模型是否换了工具、参数或策略。

### 执行面板看起来卡住

- `heartbeat` 只表示 SSE 连接存活，不是语义进展；
- 检查最后一条真实 progress/tool/model 事件时间；
- 确认 Turn 是 `running`、`waiting_user` 还是已经 terminal；
- 如果答案已出现但面板未收束，检查 `run_finished`、`turn_completed` 和 final payload 顺序；
- 只有传输事件缺失时再查浏览器 Network 面板。

### 附件存在但模型没有使用

- 确认上传成功并属于当前 Thread；
- 检查用户消息中的附件引用和 `active_attachment_ids`；
- 检查是否曾显式清除 sticky 附件上下文；
- 在 debug 模型请求组成中确认 `[attachments]` contextual message 是否出现；
- 对 PDF、Excel、图片和 MSG 使用对应读取工具，不把文件路径本身当内容。

### Plan 与实际执行不一致

Plan 是模型 checklist，不是 Harness 任务真相。以 Thread 中真实 ToolMessage、文件修改和验证结果为准。Turn 结束后旧 Plan 留在历史，但不会自动恢复为下一 Turn 的活动 Plan。

## 可安全共享的最小证据

公司内部排障优先提供：

- 版本、平台、provider/model 和权限模式；
- Thread ID / Turn ID；
- 工具名、`error_kind`、return code 和发生次数；
- 已脱敏的最终状态与最小复现步骤；
- Eval 安全摘要（如果问题来自 Eval）。

不要提交 `.env`、完整 Developer Prompt、原始工具参数、用户业务文件、公司 URL、token、完整绝对路径或整个 `app/data/`。
