# Codex 对齐：运行中追加指令与 Subagent

本轮保持 `Session = Thread`：Session 仍是持久 Thread，Runtime 每次只运行一个主模型请求链。Harness 只负责消息排队、工具边界、子上下文隔离、事件记录和权限边界，不通过关键词判断任务语义。

## 运行中追加指令

- 前端在当前 Turn 运行期间保留输入能力；发送按钮显示“追加指令”。
- `POST /api/chat/runs/{run_id}/steer` 将文本加入当前 Turn 的队列，并立即返回 `queued`。
- Runtime 只在安全边界取走队列：一轮模型回复准备结束时，或一组工具调用全部回灌完成后。
- 追加指令作为真实 `user` 消息插入 Thread transcript；不启动第二条并行模型链，也不改变已有工具调用顺序。
- 前端先显示“已排队”，收到 `turn/steer/accepted` 后显示“Agent 已接收”。当前版本的运行中追加仅支持文本，不携带附件。
- Runtime 在最终空队列检查时原子关闭接收窗口，避免 Turn 已结束后仍接受消息。

## 单层 Subagent

- `spawn_subagent` 是普通模型工具。是否使用、委派什么任务由主模型决定，不存在关键词路由。
- 第一版面向文件探索、测试、日志分析和总结；每次调用同步运行一个独立上下文，所以不会出现多个 Subagent 同时修改同一文件。
- 子上下文不继承主 Thread 历史，只接收自包含任务、当前项目、附件和 RuntimeBoundary。
- 子 Agent 没有 `spawn_subagent`、`apply_patch`、`save_skill` 或用户询问工具；工作区写入能力关闭。它可以使用文件读取工具和 `exec_command` 做聚焦测试，但提示词明确禁止通过命令修改工作区。
- 子 Agent 的完整上下文不会回灌主 Thread。主 Agent 只收到状态、精简摘要、工具数量和 token 统计。
- 前端将 `subagent` stream item 显示为主任务内的折叠卡片；没有独立聊天页或递归子 Agent。

## 兼容性

- 原有 `/api/chat`、`/api/chat/stream`、Session JSON 和历史消息读取保持兼容。
- `SessionStore.append_turn` 新增的 `record_transcript` 参数默认为 `true`，旧调用行为不变。
- Subagent 继续使用公司已有 Chat Completions provider 和原生 tool calling，不要求 Responses API。

## 验证

离线结构检查不会调用模型：

```bash
python scripts/run_evals.py --cases evals/codex_alignment_cases.json --validate-only
```

公司 PowerShell 的必要 live baseline：

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py `
  --cases evals\codex_alignment_cases.json `
  --live `
  --repeat 3 `
  --provider openai_compatible `
  --model gpt-5.4 `
  --output artifacts\evals\company-gpt54-codex-alignment.json
```

新套件包含运行中追加指令、Subagent 分工、压缩后的长 Thread、修改真实隔离 Team Skill，以及首次测试失败后恢复五类场景。`input_modalities` 已允许 `pdf`、`excel`、`markdown`、`c` 和 `cpp`，后续可以沿用同一 schema 增加混合文件案例。
