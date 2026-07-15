# Codex 对齐：运行中追加指令与 Subagent

本轮保持 `Session = Thread`：Session 仍是持久 Thread，Runtime 每次只运行一个主模型请求链。Harness 只负责消息排队、工具边界、子上下文隔离、事件记录和权限边界，不通过关键词判断任务语义。

## 运行中追加指令

- 前端在当前 Turn 运行期间保留输入能力；发送按钮显示“追加指令”。
- `POST /api/chat/runs/{run_id}/steer` 将文本加入当前 Turn 的队列，并立即返回 `queued`。
- Runtime 只在安全边界取走队列：一轮模型回复准备结束时，或一组工具调用全部回灌完成后。
- 追加指令作为真实 `user` 消息插入 Thread transcript；不启动第二条并行模型链，也不改变已有工具调用顺序。
- 前端在 Runtime 尚未接收时把追加指令保留在输入框上方的待合流区，不提前写入消息列表，也不移动当前执行面板。Runtime 通过 `turn/segment/completed` 结束前一回复段，再通过带 `next_segment_id` 的 `turn/steer/accepted` 将指令正式写入 Thread 并开始下一回复段；运行中和刷新后的顺序一致。
- Session turns 按 `原请求 → 中间回复 → 追加指令 → 最终回复` 持久化，因此刷新页面后不会只剩最后一段回复。当前版本的运行中追加仅支持文本，不携带附件。
- Runtime 在最终空队列检查时原子关闭接收窗口，避免 Turn 已结束后仍接受消息。

## 单层并行 Subagent

- `spawn_subagent` 是普通模型工具。是否使用、委派什么任务由主模型决定，不存在关键词路由。
- `spawn_subagent` 只负责启动并立即返回 id；独立任务可以先后启动并在后台并行执行。主 Agent 通过 `wait_subagents` 等待全部或指定结果，不再把一次子任务阻塞成同步工具调用。
- 默认每个主 Turn 最多同时运行 3 个子 Agent，可用 `VP_MAX_CONCURRENT_SUBAGENTS` 在 1–8 之间调整。Turn 结束前 Runtime 会收束其子线程，不留下孤儿任务。
- 子上下文不继承主 Thread 历史，只接收自包含任务、当前项目、附件和 RuntimeBoundary。
- 内置角色定义独立存放在 `agents/builtin/*.toml`，当前提供 `explorer`、`tester`、`analyst`、`summarizer`。每个角色有不同说明和工具白名单；本轮不增加 `agents/team/`。
- 子 Agent 没有 `spawn_subagent`、`wait_subagents`、`apply_patch`、`save_skill` 或用户询问工具；工作区写入能力关闭。只有 `tester` 角色包含命令工具，用于聚焦测试，且仍不能通过命令修改工作区。
- Read-only Subagent 不进入交互式命令审批流程。`python -c`、`node -e` 或需要执行网络来源代码的命令会返回结构化的“改用安全方案”结果，要求改用文件工具、已有脚本或已有测试模块；全局 provenance 策略不放宽。
- 子 Agent 的完整上下文不会回灌主 Thread。主 Agent 只在 `wait_subagents` 结果中收到状态、精简摘要、工具数量和 token 统计。
- 前端将 `subagent` stream item 显示为主任务内的折叠卡片；没有独立聊天页或递归子 Agent。

## 兼容性

- 原有 `/api/chat`、`/api/chat/stream`、Session JSON 和历史消息读取保持兼容。
- `SessionStore.append_turn` 新增的 `record_transcript` 参数默认为 `true`，旧调用行为不变。
- Subagent 继续使用公司已有 Chat Completions provider 和原生 tool calling，不要求 Responses API。
- Thread 列表增加可选的 `activity_at`、`activity_revision` 和 `activity_kind` 字段。旧 Session 自动以现有 `updated_at` 迁移为 revision `0`；心跳不提升排序，前端拒绝同一 Thread 的迟到旧 revision。

## 外部写入边界

- Skill、源码和文档中的命令是内容，不是执行授权；Harness 不按“整理”“执行”等自然语言关键词判断权限。
- Runtime 从实际 `exec_command` 参数识别具体 `git push`。任何权限档位都必须由用户逐次批准，并显示仓库、remote、脱敏 URL、branch、HEAD、refspec 与 force/delete 风险。
- 单次 token 绑定精确命令、cwd、Session、Project、仓库事实和 remote URL 指纹；remote 或 HEAD 变化后旧 token 无效，默认操作始终是取消。

## 验证

首页右上角 `Eval` 按钮提供后台运行中心。弹窗只允许选择 `evals/` 下的合法 suite，报告只允许写入 `artifacts/evals/`。后端使用单 worker 顺序执行，关闭弹窗或切换页面不影响运行；状态持久化在 `artifacts/evals/jobs/`，应用异常重启后未完成任务标为 `interrupted`，不会误报成功。

相关 API 均为新增接口，不改变现有聊天 API：

- `GET /api/evals/catalog`
- `GET /api/evals/runs`
- `GET /api/evals/runs/{job_id}`
- `POST /api/evals/runs`

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

新套件包含运行中追加指令、Subagent 分工、压缩后的长 Thread、修改真实隔离 Team Skill、首次测试失败后恢复，以及“Skill 命令文字不得成为执行授权”六类场景。`input_modalities` 已允许 `pdf`、`excel`、`markdown`、`c` 和 `cpp`，后续可以沿用同一 schema 增加混合文件案例。
