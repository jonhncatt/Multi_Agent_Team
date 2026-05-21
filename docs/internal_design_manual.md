# 内部设计手册（v2.9.20）

本文档面向项目 owner 与后续维护者，记录当前源码可确认的内部设计。本文只描述当前实现，不调整 runtime 行为，不推测未公开的 Codex 私有实现。

## 1. 项目定位

本项目是一个本地运行的单主 agent 工作台，默认主 agent 为 `vintage_programmer`。它采用一种接近 Codex 的架构风格，但不是复制私有实现。

当前稳定主路径可以概括为：

- 模型负责提出下一步动作（model-led，模型主导）
- harness（执行控制层）负责边界校验、工具执行、事件翻译与状态收口
- 前端把原始事件投影成用户可读的进度与状态

必须明确：

- 本项目当前稳定主路径以 Chat Completions（聊天补全接口）风格的消息循环为主。
- 本项目不是以 Responses API（响应接口）作为当前稳定主路径。
- 仓库中确实存在 `app/codex_runner.py` 这样的 Responses runner（响应式 runner）代码，但它不是本文描述的主线运行路径；本文聚焦 `VintageProgrammerRuntime` 的当前稳定行为。
- 项目通过自建 harness（执行控制层）实现 tool loop（工具循环）、Tool Guard（工具守卫）、progress UI（进度界面）、runtime stats（运行统计）和 context compaction（上下文压缩）。

为什么说它“Codex-like（类 Codex 风格）”：

- 工具由模型选择，不是 runtime 预先写死固定流程。
- harness 负责执行边界，而不是替模型做完整任务规划。
- 工具结果会回灌给模型，形成循环，而不是一次性静态计划。
- UI 默认展示的是投影后的可读进度，而不是直接把底层 trace 原样铺给用户。

## 2. 核心概念速查

### User turn（用户一轮请求）

一次用户消息从进入 runtime 到最终产出结果、阻塞、取消或失败的完整处理周期。

### Model round（模型轮次）

同一个 user turn 内，模型的一次“读当前消息上下文并生成输出”的过程。一个 user turn 可以包含多个 model round。

### Tool call（工具调用）

模型在某一轮里要求执行的一个工具动作，例如 `read_file(path="README.md")`。

### Tool result（工具结果）

工具执行后的返回值。它会被包装后写回消息序列，供下一轮模型继续使用。

### Final answer（最终回答）

一个 user turn 最终返回给用户的自然语言结果。它可能是直接回答，也可能建立在多轮工具调用之后。

### Harness（执行控制层）

负责组织 turn、校验工具边界、执行工具、记录 trace、做 context compaction，并向前端输出稳定事件。

### Tool Guard（工具守卫）

负责校验工具是否存在、参数是否可接受、当前工具是否允许执行，以及是否越界。它不是任务规划器。

### Progress projection（进度投影）

前端把 trace event（跟踪事件）、tool item（工具条目）、plan update（计划更新）投影成默认进度区，避免直接暴露大量原始内部事件。

### Context compaction（上下文压缩）

为了控制上下文长度，在长期任务中把较早的工具结果和历史 turn 压缩成摘要，同时保留最近必要上下文。

### update_plan（更新计划工具）

一个真实存在的工具，用来同步当前 turn 的轻量 checklist（检查清单）。

## 3. Turn 设计

当前实现中，一个 user turn（用户一轮请求）可以包含多个 model round（模型轮次）。

关系如下：

- 一个 user turn 可以有多个 model round
- 一个 model round 可以产生 0 个或多个 tool call
- 每个 tool call 都必须先经过 Tool Guard
- 工具结果会写回消息序列
- 模型再进入下一轮
- 直到产生 final answer 或进入 blocked / cancelled / failed

ASCII 图：

```text
User message
  ↓
Model round 1
  ↓ tool_call
Tool Guard
  ↓
Tool execution
  ↓ tool_result
Model round 2
  ↓
...
  ↓
Final answer
```

常见误解需要澄清：

- 在同一个任务里看到多次“模型开始分析”，通常不是多个 user turn。
- 它更常见地表示：同一个 user turn 内发生了多个 model round。

## 4. Tool Result Loop（工具结果回灌循环）

当前主路径的 Tool Result Loop（工具结果回灌循环）是：

```text
model output / tool call
→ tool guard
→ accepted / normalized / rejected
→ execute or return tool error
→ append tool result to messages
→ model continues
```

这里的关键点是：

- accepted（接受）：工具名、参数、权限都通过，直接执行
- normalized（归一化后接受）：参数经过保守修正后执行
- rejected（拒绝）：不执行工具，而是构造结构化 tool error（工具错误）回灌给模型

为什么 rejected（拒绝）不应该直接让整个 turn 崩掉：

- 因为模型仍然可以基于明确错误继续修正下一步
- 这让系统更接近“工具循环”，而不是“一次出错就整轮失败”

当前 runtime 会把工具结果作为 `ToolMessage` 追加回消息序列，再继续下一轮模型推理。

## 5. Tool Guard（工具守卫）

Tool Guard（工具守卫）当前做的是执行边界检查，不做任务级规划。

它当前检查的核心内容包括：

1. tool exists（工具是否存在）
2. schema / arguments（参数 schema 与参数形状）
3. permission / mode（权限与当前允许执行的工具边界）
4. forbidden or unsafe actions（越界或不允许动作）
5. rejection reason（拒绝原因）

它不是 planner（规划器），也不决定用户任务到底该怎么完成。

例子：

- 有效调用：`read_file(path="README.md")`
- 旧名字：`read(...)` 会被当 unknown tool（未知工具）拒绝
- schema error（参数不符合 schema）：会返回结构化错误
- forbidden operation（越界或不允许动作）：会被硬拒绝

当前 guard 产出的是结构化的 `ToolGuardResult`，包含：

- `status`: `accepted | normalized | rejected`
- `raw_tool_name`
- `tool_name`
- `raw_arguments`
- `normalized_arguments`
- `normalization_notes`
- `checks`
- `schema_validation`
- `reason`

## 6. Canonical Tools（标准工具体系）

当前模型可见的 canonical tools（标准工具名）来自实际 tool registry（工具注册表）。

### 文件发现（File discovery）

- `list_dir`
- `glob_file_search`
- `search_codebase`

### 文件读取（File reading）

- `read_file`
- `read_section`

补充说明：

- 当前源码里没有独立 `read_range` 工具。
- 局部读取是通过 `read_file` 的 `start_char / max_chars / start_line / max_lines` 参数完成的。

### 内容搜索（Content search）

- `search_contents_in_file`
- `search_contents_in_file_multi`

### 文件修改（Editing）

- `apply_patch`

### 命令执行（Execution）

- `exec_command`
- `write_stdin`

### 计划与交互（Planning / input）

- `update_plan`
- `request_user_input`

### 网页与浏览器（Web / browser）

- `web_search`
- `web_fetch`
- `web_download`
- `browser_open`
- `browser_click`
- `browser_type`
- `browser_wait`
- `browser_snapshot`
- `browser_screenshot`

### 图片、文档、证据（Image / document / evidence）

- `image_inspect`
- `image_read`
- `table_extract`
- `fact_check_file`
- `archive_extract`
- `mail_extract_attachments`
- `sessions_list`
- `sessions_history`

### 使用原则

- `read_file`：适合小文件或需要完整上下文
- `list_dir / glob_file_search`：适合先定位文件
- `search_contents_in_file`：适合在已知文件内搜文本
- `read_section`：适合 Markdown / 文档按章节读取
- `apply_patch`：适合结构化修改文件
- `update_plan`：适合多步任务维护 checklist

必须强调：

- 工具说明是选择原则，不是固定流程。
- 当前系统不要求 agent 永远按某个固定顺序读代码。

## 7. update_plan 和 checklist 设计

`update_plan` 是一个真实工具，不是纯文档约定。

它的作用是：

- 同步当前 turn 的轻量计划
- 约束 plan item（计划项）结构
- 保证状态值只使用 `pending / in_progress / completed`

checklist（检查清单）相关状态的来源分两层：

### 第一来源：update_plan

优先来源于 `update_plan`。

流程是：

1. 模型调用 `update_plan`
2. 工具返回规范化后的 `plan`
3. runtime 更新 `plan_state`
4. runtime 发出 `plan_update`
5. SSE 翻译成 `turn/plan/updated`
6. 前端把它写入 `activity.plan`
7. 默认进度区优先用这份 plan 画 checklist

### 第二来源：fallback projection（回退投影）

如果没有 `update_plan`，前端才会从 tool event（工具事件）生成 fallback progress projection（回退进度投影）。

两者差别：

- `update_plan`：更接近模型维护的 intended plan（意图中的计划）
- tool events：更接近 actual execution history（实际执行历史）

## 8. Progress Projection（进度投影）

当前前端默认进度区遵循一个重要原则：

- 不显示 runtime guess（运行时预判）作为默认事实
- 只显示安全中性状态或已经观察到的真实动作

默认进度里常见的文案有：

- 开始处理请求
- 正在思考
- 读取文件
- 搜索文件内容
- 列出目录
- 查找文件
- 应用补丁
- 结果已准备完成

为什么 early runtime_fallback（早期运行时回退预判）会被隐藏：

- 因为它只是 harness hint（控制层提示），不是最终确认事实
- 如果在模型真正决定前就显示“无需工具”“直接生成结果”，会误导用户

因此，当前默认层会优先展示：

- 中性占位状态
- 实际 tool action（真实工具动作）
- 最终 answer state（最终回答状态）

而 runtime hint / runtime guess 会保留在 debug detail（调试详情）里。

## 9. Runtime Stats / 背景信息窗口

右下角背景信息窗口当前采用“简洁默认层 + 折叠详细信息”的设计。

### 默认紧凑层

默认只展示 4 行左右的概览：

- context used / remaining（上下文已用 / 剩余）
- used tokens / total window（已用 token / 总窗口）
- elapsed time / tool count（本轮用时 / 工具次数）
- automatic compaction（自动压缩）状态

如果 token 或 context window 不可可靠获得：

- 不伪造数字
- 会显示“未知”或退回到保守估算说明

### 详细信息折叠区

同一个浮窗底部有 `详细信息` 折叠区，默认折叠。

展开后会显示：

- 运行状态
- 工具统计
- 上下文
- 保护机制
- 诊断（如果当前 runtime status 有 provider diagnostics）

为什么默认折叠：

- 这些信息对调试很重要
- 但默认全展示会让背景信息窗口太像内部监控面板，不够紧凑

### 阶段耗时诊断

从 `v2.7.8` 开始，assistant activity debug details（助手活动调试详情）会附带 `phase_timings`（阶段耗时）。

它的用途是帮助区分慢点主要出现在：

- frontend submit 到 backend receive（前端提交到后端接收）
- session load / session ready（会话加载 / 会话就绪）
- runtime context preparation（运行时上下文准备）
- provider auth summary（Provider 鉴权摘要）
- model request start（模型请求发出）
- model first event / first text delta（模型首个事件 / 首个文本增量）
- answer ready（最终答案准备完成）

这些 timing 默认不放进主进度列表，只放在 debug/details（调试详情）里，避免默认 UI 变复杂。

## 10. Long-task Safeguards（长任务保护机制）

设计理念不是“限制 agent 工作”，而是防止：

- 卡死
- 重复空转
- 越界
- 上下文爆炸

当前保护分为几层。

### Hard Limits（硬限制）

- absolute tool call cap（绝对工具调用上限）
- wall-clock timeout（墙钟时间上限）
- user stop/cancel（用户停止 / 取消）
- forbidden action rejection（危险或越界动作拒绝）

### Progress Guard（进展保护）

当前 runtime 不是简单按“工具调用次数”判断，而是对每次工具结果生成 `ProgressSignal`（进展信号）。

当前源码里，下面这些通常会被视为“有进展”：

- new file read（读到了新文件或新内容）
- new directory entries（看到了新目录条目）
- new glob matches（找到了新的路径匹配）
- new search hits（找到了新的搜索命中）
- new section read（读到了新的章节内容）
- patch applied（补丁应用成功）
- command result changed / test result changed（命令或测试结果出现新变化）
- plan updated（`update_plan` 有新 completed 项）
- new error type（发现了新的错误类型）

### 什么算“无进展”

当前源码里，下列情况通常算无进展：

- same action same result（同动作、同结果重复）
- same empty search（同样的空搜索重复）
- same repeated error（同一种错误反复出现）
- same rejected call（同样被拒绝的调用反复出现）

### Repeat Guard（重复动作保护）

当前重复检测不是“同工具重复”，而是 same-action repeat（相同动作重复）。

action fingerprint（动作指纹）定义为：

```text
tool_name + stable_hash(normalized_arguments)
```

这意味着：

- `read_file(path=A)` 和 `read_file(path=B)` 不算重复
- `search_contents_in_file(path=A, query=x)` 和 `search_contents_in_file(path=A, query=y)` 不算重复
- 同一个 `read_file(path=A)` 一直重复，才会累计成重复动作

### No-progress Recovery（无进展恢复）

当前实现中，连续无进展不会立刻硬停。

流程是：

1. 先累计 no progress cycles（无进展轮次）
2. 达到阈值后，触发 replan / checkpoint（复盘 / 检查点恢复）
3. runtime 生成恢复提示，要求模型：
   - 总结已知事实
   - 总结失败或重复动作
   - 提出不同策略
4. replan 后如果仍持续无进展，才会停止

### Context Guard（上下文保护）

长任务还依赖：

- tool output truncation（工具输出裁剪）
- context compaction（上下文压缩）
- checkpoint summary（检查点摘要）

### Failure Recovery（失败恢复）

失败恢复当前不是“一刀切”：

- schema error（参数 / schema 错误）会回灌给模型，允许有限纠偏
- unknown tool（未知工具）会被拒绝，不会静默 alias 回旧名字
- forbidden / boundary（越界或禁止操作）是硬拒绝
- repeated rejection（重复拒绝）可触发 replan，之后仍无效才停止

## 11. Current Safeguard Defaults（当前默认保护值）

以下为当前源码中可确认的默认值：

- `emergency_max_tool_calls_per_turn`: `1000`
- `max_same_action_repeats`: `4`
- `no_progress_threshold_before_replan`: `3`
- `no_progress_threshold_after_replan`: `2`
- `max_guard_rejections`: `2`
- `max_turn_seconds`: `1800` 秒，也就是 `30` 分钟
- `supports_user_cancel`: 开启
- `context_compaction`: 开启
- `long_task_guard`: 开启
- `progress_signal_guard`: 开启
- `same_action_repeat_guard`: 开启
- `automatic_replan`: 开启
- `tool_output_truncation`: 开启

这里必须特别说明：

### emergency_max_tool_calls_per_turn 是什么

`emergency_max_tool_calls_per_turn` 是一个 user turn（用户一轮请求）内的总工具调用绝对兜底上限。

它不是：

- model round（模型轮次）上限
- `max_tool_rounds`
- 某一种工具的单独上限

也就是说，它统计的是：

- 从这一轮用户请求开始
- 到这一轮最终结束
- 整体一共尝试了多少次工具调用

当前默认值 `1000` 是 emergency cap（紧急兜底上限），不是常规长任务保护。长任务的主要保护仍然是 progress-aware guard（进展感知保护）、same-action repeat（重复动作检测）、no-progress replan（无进展复盘）、context compaction（上下文压缩）、tool output truncation（工具输出截断）、wall-clock timeout（连续运行时间上限）、user cancel（用户停止）和 forbidden action rejection（越界/危险操作拒绝）。

## 12. Context Compaction（上下文压缩）

Context compaction（上下文压缩）的目标是：

- 防止长任务把上下文塞满
- 减少旧工具结果对当前推理的干扰
- 保留最近必要上下文与摘要

当前源码中可确认的行为：

- context window（上下文窗口）会按模型信息或保守预算估算
- `auto_compact_token_limit` 当前等于 `context_window * 0.9`
- live loop（运行中循环）在超过预算时会把较早工具结果压缩成系统摘要
- mid-turn compaction（同一轮内压缩）会保留最近一段消息，并把更早的工具结果合并为摘要

当前 live compaction summary（运行中压缩摘要）会记录：

- earlier progress summary（较早进度摘要）
- compacted tool calls（被压缩的工具调用摘要）
- checklist snapshot（当时 checklist 快照）

同时，旧的 tool message（工具消息）在上下文过大时还可能被进一步 prune（裁剪），只保留占位信息。

当前与工具结果裁剪相关的默认配置包括：

- `tool_result_soft_trim_chars = 40000`
- `tool_result_hard_clear_chars = 180000`
- `tool_result_head_chars = 8000`
- `tool_result_tail_chars = 4000`
- `tool_context_prune_keep_last = 3`

不要过度推断的一点：

- 当前源码明确了 compaction 的触发逻辑和 90% 自动压缩预算
- 但并没有定义一个对所有 provider / 所有模型都同样精确的真实 token 计数来源
- 因此 context meter（上下文计量）有时会退回保守估算

## 13. Polling / Runtime Status（轮询和运行状态）

当前前端轮询主要涉及两个接口：

### `/api/projects`

作用：

- 获取项目列表

当前行为：

- 启动后会加载
- 页面重新可见或窗口重新获得焦点时，会在“超过 stale 时间”后刷新
- 空闲时不会持续高频轮询
- 前端有 in-flight dedupe（飞行中请求去重）

当前 stale 判定常量：

- `PROJECTS_REFRESH_STALE_MS = 60000`

### `/api/runtime-status`

作用：

- 获取 runtime status（运行状态）
- 获取 context meter（上下文计量）
- 获取 compaction status（压缩状态）
- 获取 loop safeguards（循环保护配置）

当前轮询策略：

- active turn（活跃运行）时：`5s` 轮询
- idle but visible（空闲但用户正在看 run drawer 或背景信息）时：`30s` 轮询
- 其他空闲场景：不轮询
- 页面隐藏时：暂停

当前 `/api/runtime-status` 还会返回 `provider_diagnostics`（Provider 诊断）字段，用于观察：

- `runtime_status_total_ms`
- `runtime_status_runtime_meta_ms`
- `runtime_status_provider_options_ms`
- `runtime_status_auth_summary_ms`

前端还做了：

- `AbortController`（中止控制器）取消旧请求
- 相同参数请求复用 in-flight promise（进行中的 promise）

因此 v2.7.x 之后的目标不是“完全不轮询”，而是：

- 在需要时刷新
- 在空闲 / 隐藏场景减速或暂停
- 避免重复 in-flight 请求

按当前源码确认：

- `runtime_meta()` 已有约 10 秒缓存
- `auth_summary()` 主要读取本地配置 / token 状态，不直接代表网络刷新
- 因此当前实现不额外叠加新的 readiness TTL cache（短 TTL 缓存），而是先暴露 timing 诊断结果

## 14. Common Questions（常见问题）

### Q1. 为什么一个任务里会多次“模型开始分析”？

因为一个 user turn 可以包含多个 model round。多次“模型开始分析”通常表示同一轮任务里的多次模型往返，不等于多个 user turn。

### Q2. `update_plan` 和工具事件生成的 checklist 有什么区别？

`update_plan` 更接近模型维护的 intended plan（计划意图）；工具事件更接近 actual execution history（实际执行历史）。前端优先使用 `update_plan`，没有时才回退到 tool event projection。

### Q3. Tool Guard 是不是在替模型规划？

不是。Tool Guard 只负责工具执行边界，不负责完整任务规划。

### Q4. 为什么旧工具名 `read / search_file` 不再使用？

因为当前工具体系已经切到 canonical names（标准工具名），语义更明确，也便于 guard 和 UI 统一处理。

### Q5. `emergency_max_tool_calls_per_turn = 1000` 是什么？

它是一个 user turn 内的总工具调用紧急兜底上限，不是 model round 数，也不是 `max_tool_rounds`。

### Q6. 长任务为什么不能完全无限？

因为系统仍然需要：

- 绝对安全兜底
- 上下文控制
- 用户可停止
- 无进展恢复与停止机制

否则容易进入无限重复、越界尝试或上下文爆炸。

### Q7. 为什么会看到“正在执行 0s / Ns”这类实时状态？

因为前端会基于 `started_at / finished_at / run_duration_ms` 做 live timer（实时计时），并且运行中的秒数主要由前端本地定时器驱动。运行中会刷新，结束后冻结，不依赖 `/api/runtime-status` 轮询来推动秒数更新。

## 15. Version History Notes（版本演进摘要）

- `v2.6.x`：逐步形成 tool loop、tool guard、activity UI 和 tool audit
- `v2.6.9`：完成 canonical tool names（标准工具名）清理
- `v2.7.0`：整理 runtime stats（运行统计）、轮询策略，并移除 `max_tool_rounds` 主路径依赖
- `v2.7.1`：背景信息窗口改成简洁默认层 + 折叠详细信息，并把长任务保护升级为 progress-aware safeguards（进展感知保护）
- `v2.7.2`：新增本内部设计手册，统一记录当前实现
- `v2.7.3`：修复前端 live timer，移除小工具调用数主路径限制，并把绝对工具上限降级为 emergency cap（紧急兜底上限）
- `v2.7.8`：新增 phase timing diagnostics（阶段耗时诊断），并把 no-tool direct answer（无工具直接回答）路径改成“理解问题 / 等待模型 / 生成回答”的更清晰状态词

## 16. v2.9.2 Tool UX Polish Notes

v2.9.2 keeps the v2.9.x stable LangChain runtime policy.
This release makes three practical improvements:

- `printf` is allowed in `exec_command` for small formatted shell output and lightweight file creation.
- Python execution guidance now prefers the project `.venv` interpreter when available and avoids assuming `python3`.
- Failed tool cards show useful failure details such as error, stderr, return code, and cwd by default.

## 17. v2.9.3 Allowlist and Serialization Compatibility Notes

v2.9.3 keeps the v2.9.x stable LangChain runtime policy.
This release makes two practical hardening improvements:

- The recommended safe `VP_ALLOWED_COMMANDS` full list now includes both `printf` and `dir`.
- Frontend/API-facing serialization paths use a defensive `dump_model()` helper so mixed model-like objects do not fail only because they do not implement Pydantic v2 `model_dump()`.

## 18. v2.9.4 Runtime Status Performance Cleanup Notes

v2.9.4 keeps the v2.9.x stable LangChain runtime policy.
This release is a request-time performance cleanup only and does not change agent behavior, prompt behavior, tool execution behavior, or guard behavior.

- `/api/health` is reduced to a lightweight alive check.
- `/api/bootstrap` keeps startup/static metadata work.
- `/api/runtime-status` reuses cached provider payload and cached agent descriptor metadata instead of rebuilding them on every poll.
- Context meter and compaction status reuse the same computed status payload instead of counting tokens twice for the same response.

## 19. v2.9.5 Safe Serialization Fix Notes

v2.9.5 keeps the v2.9.x stable LangChain runtime policy.
This release is a narrow bugfix only and does not change prompt behavior, routing logic, tool execution behavior, or streaming behavior.

- The stable runtime still wraps `office_agent_runtime` under `VintageProgrammerRuntime`, so office/runtime payload construction must use defensive serialization.
- Residual direct `.model_dump()` calls in `packages/office_modules/office_agent_runtime.py` are replaced with `dump_model(...)`.
- This prevents intermittent office-style crashes such as `NoneType object has no attribute model_dump` and `dict object has no attribute model_dump`, especially in meeting-minutes and related task paths.

## 20. v2.9.6 Codex-like Action Runtime Notes

v2.9.6 keeps the v2.9.x stable LangChain runtime line while making the tool loop closer to Codex-style model-led execution.

Core rule:

- The model chooses the next action: final answer or concrete tool call.
- The tool call itself is the model action; no mandatory `model_proposal` schema is required.
- The harness validates tool name, schema, RuntimeBoundary, path, shell/network/write permission, and safety.
- Invalid tool calls become model-facing observations so the model can self-correct.
- `route_state` and `active_task_focus` remain weak historical hints; the current user message has priority.

The new `ContextPack` separates:

- `current_turn`: current user message and attachments, highest priority
- `turn_memory`: short/long task continuity context
- `conversation_window`: recent retained turns after token budget and compaction
- `compaction`: compaction status, phase, and reason
- `route_hints`: weak historical route hints
- `runtime_boundary`: logical validation boundary, not a real OS/container sandbox

v2.9.6 does not add a semantic ToolUseAdvisor, meeting-minutes no-tool rule, translation no-tool rule, or another LLM judge.

## 20.1 v2.9.7 Codex-like Runtime Cleanup Notes

v2.9.7 is a cleanup release on the same stable LangChain runtime line.
It removes the remaining proposal/validated-next-step/guard layering from the execution path.

- The only model actions are `final_answer` and `tool_call`.
- `RuntimeBoundary` is built once per turn and reused by both `ContextPack` and `ActionValidator`.
- `ValidationResult` is the single validation result object for concrete tool calls.
- Invalid tool calls become observations; valid tool calls execute and their results are returned as observations.
- UI activity focuses on model action, boundary validation, tool execution, observation, and final answer.
- No semantic ToolUseAdvisor, inline-content challenge, meeting-minutes exception, or secondary LLM judge is introduced.

## 20.2 v2.9.8 ContextPack and Compaction Cleanup Notes

v2.9.8 keeps the same model-led action loop and removes the parallel `legacy_context` path from the model payload.

- `ContextPack` is the only structured context envelope sent to the model.
- Useful legacy fields now live under `current_turn`, `turn_memory`, `conversation_window`, `route_hints`, `compaction`, and `runtime_boundary`.
- `route_state` is exposed only as weak `route_hints`; it must not decide whether tools are required or whether a final answer is acceptable.
- Semantic repair loops such as act-now steering, invalid-final guarding, required-tool blocking, and image auto-rescue are removed from the stable runtime path.
- Compaction remains first-class and exposes `phase` and `reason` fields so pre-turn and mid-turn context management can be tracked without becoming route logic.

## 20.3 v2.9.9 Minimal ContextPack and TurnMemory Notes

v2.9.9 keeps the same model-led action loop and makes ContextPack smaller and non-duplicative.

- ContextPack now contains only `current_turn`, `conversation_window`, `turn_memory`, `plan_state`, `compaction`, and `runtime_boundary`.
- `current_turn` carries a bounded `user_message_preview` instead of duplicating the full active user message.
- `conversation_window` holds recent raw turns; `turn_memory` holds concise task state, compacted summary, and recent observation summaries.
- `plan_state` is a first-class field sourced from valid `update_plan` state, not inferred from natural language.
- `compaction` exposes only minimal model-facing status: active, phase, reason, and summary availability.
- The model-facing RuntimeBoundary view is concise and does not include full `allowed_roots` or `writable_roots`; the full boundary remains internal for ActionValidator.
- `route_hints`, `route_state`, `legacy_context`, `context_injections`, and route-derived memory fields are not sent to the model ContextPack.

## 20.4 v2.9.10 Codex-style Tool Drain Fix Notes

v2.9.10 fixes a protocol-level tool-call transaction bug in the stable LangChain runtime path.

- When a model message contains multiple tool calls, the harness drains every call before the next model request.
- Every assistant `tool_call_id` receives exactly one corresponding ToolMessage, including validation rejection, tool execution failure, skipped calls, and cancellation.
- Execution no longer slices normal tool execution to a preview-sized subset and no hard emergency tool-call count cap blocks call-id closure.
- Compaction only runs at clean assistant/tool transaction boundaries and refuses compacted history that would split a tool-call transaction.
- LLM follow-up failures preserve trace, inspector, and tool event context so the frontend can still inspect partial progress.

## 20.5 v2.9.11 Path Portability and Search Safety Notes

v2.9.11 keeps the v2.9.10 Codex-style all-tool drain behavior and improves model-visible path portability.

- File/path tool outputs prefer project-relative paths such as `app/local_tools.py`; absolute paths remain available as `resolved_path` / `resolved_root` for debug and trace use.
- `list_dir`, `read_file`, `glob_file_search`, and `search_codebase` return model-actionable paths that are easier to reuse after a project folder is moved.
- Broad glob patterns such as `**/*` return guidance on large folders instead of flooding the model context with hundreds or thousands of absolute paths.
- `***` is treated as a UI redaction placeholder, not a real path, glob pattern, filename, function name, or search query. The ActionValidator rejects it with a validation observation, preserving tool-call closure.
- ToolMessage content is compacted for model use without replacing actionable paths with redaction placeholders.
- ContextPack rebases known old/current project-root absolute paths in historical context into portable relative paths before sending them to the model.

## 20.6 v2.9.12 Live Timeline and LLM Diagnostics Notes

v2.9.12 keeps the v2.9.10 Codex-style all-tool drain behavior and the v2.9.11 path portability rules.

- The main assistant card now tracks live run items from SSE `item/started`, `item/completed`, and LLM/answer trace events so users can see model thinking, tool execution, answer generation, and failures without opening debug details.
- Completed turns still collapse back to a clean activity summary while keeping detailed execution data available behind the debug drawer.
- Debug details are grouped into user context, model rounds, tool groups, harness status, final status, and raw JSON instead of a flat event dump.
- Provider/stream event serialization uses `safe_model_dump()` for None-safe diagnostics around partially constructed SDK objects.
- `None` stream events are recorded as `llm.stream_event.none` warnings instead of crashing the run.
- Clean-boundary follow-up LLM failures matching transient patterns such as `NoneType`, `model_dump`, timeout, connection reset, or 5xx errors retry once; retry success/failure is recorded with `llm.retrying`, `llm.retry_succeeded`, and `llm.retry_failed`.
- Final LLM failures preserve exception type, module, traceback tail, message count, last message roles, phase, model, and tool-boundary diagnostics so local logs remain useful when company logs cannot be shared.

## 20.7 v2.9.13 Workspace and Permission Profiles Notes

v2.9.13 keeps the v2.9.10 Codex-style all-tool drain behavior and makes the workspace boundary easier to explain.

- The current `project_root` is the default workspace.
- File reads default to the current project and explicitly imported files; file writes default to the current project.
- Command execution defaults to the current project and validates path arguments such as `rg /etc`, `git -C /tmp`, and `python /tmp/a.py`.
- Downloads, Desktop/workbench, and workspace sibling roots are no longer default accessible scopes.
- Permission profiles separate collaboration style from actual runtime permissions; current product labels are Default, Auto, and Full Access.

## 20.8 v2.9.14 ModelContext-first Context System Notes

v2.9.14 keeps the same model-led tool loop and makes model-facing context explicit.

- `ModelContext` is the only normal structure rendered into the model-facing HumanMessage.
- `ModelContext` has six sections: `task`, `workspace`, `memory`, `plan`, `permissions`, and `conversation`.
- `ContextManager` owns clean materials: `clean_summary`, `clean_turns`, `recent_observations`, `active_files`, `plan`, and `context_version`.
- Compaction updates `memory.clean_summary` and trims clean turns; it does not persist raw trace, raw tool output, or model draft.
- Runtime trace remains debug data. Only short factual observation summaries may flow from runtime trace into clean memory.
- Model draft can be shown in UI/debug, but it is not saved as a clean assistant turn or compacted memory.

## 20.9 v2.9.15 Main Card and Debug Cleanup Notes

v2.9.15 keeps the ModelContext-first runtime and cleans the product surface.

- The main assistant card shows live execution cards while a run is active, then folds the details into a concise execution summary after completion.
- Debug Detail uses five normal top-level sections: Sent to Model, Model Output, Tool Execution, Runtime, and Advanced Raw.
- Phase timings and raw payloads stay in Runtime or Advanced Raw rather than becoming separate primary debug sections.
- The old mode control is removed. Permission profiles are the only user-facing runtime mode control.
- Agent specs no longer declare default/plan/execute workflow modes.

## 20.10 v2.9.16 UI Card Hotfix and Permission Profile Relocation Notes

v2.9.16 is a focused UI/runtime-display hotfix.

- Main card live projection treats `tool.started`, `tool.finished`, and `tool.failed` as visible execution cards.
- Tool cards use stable tool-name mapping and target extraction from common fields such as `path`, `query`, `command`, `root`, and `pattern`.
- Main card cards must have non-empty titles and fallback details, so missing locale keys or partial trace payloads do not produce blank cards.
- The active permission profile selector moved from Settings to the composer next to the attachment button.
- The selected permission profile is included in the next chat request immediately.
- Runtime status and Debug Runtime expose `network_reason` so Full Access can distinguish global network disablement from profile-level network disablement.
- Debug Detail keeps the five-section structure and no longer surfaces `phase_timings` as a normal runtime section.

## 20.11 v2.9.17 Permission Selector UI Polish Notes

v2.9.17 is a focused permission selector UI polish release.

- The composer no longer shows the visible engineering label “权限边界”; the selector sits directly next to the attachment button.
- Default, Auto, and Full Access remain the only permission profile choices.
- The selector uses subtle profile-specific styling: neutral for Default, blue for Auto, and a stronger orange accent for Full Access.
- The selector exposes a short hover/title description for the currently selected permission profile.
- Runtime permission semantics, `RuntimeBoundary`, `ModelContext.permissions`, and Debug Runtime behavior are unchanged.

## 20.12 v2.9.19 Hard Cleanup and Manual Update Notes

v2.9.19 combines a scoped hard cleanup with a manual-only self-update button.

- Normal `MessageActivity` and frontend activity projection no longer carry old `current_turn_goal`, `active_task_focus`, `recent_user_messages`, or `phase_timings` fields.
- The run panel derives current task display from `ModelContext.task`, `ModelContext.workspace`, and `ModelContext.memory` instead of old task-focus fields.
- The sidebar Update button calls `/api/app/update` only when clicked; there is no background update polling, startup fetch, scheduler, or watcher.
- The backend update manager targets the Vintage Programmer application git repository, not the selected project root.
- The update command sequence is fixed: `git fetch --tags origin`, `git reset --hard origin/<branch>`, and `git pull --ff-only`.
- The endpoint does not accept arbitrary frontend-provided command strings.
- Cache/generated files remain ignored and are not part of the application architecture.

## 20.13 v2.9.20 Codex-style Permission Modes Notes

v2.9.20 renames the product permission model to Codex-style trust levels: `Default / Auto / Full Access`.

- Canonical runtime values are now `default`, `auto`, and `full_access`.
- Legacy values such as `chat`, `code`, and `full_dev` remain accepted as compatibility aliases.
- `Default` is current-project read-only: read/search tools only, no shell, no writes, and no network.
- `Auto` is the normal development mode: current-project read/write, safe commands inside the project, and network enabled.
- `Full Access` is the maximum-trust mode: broader configured read/write/command scope and network enabled, while dangerous-command protection remains active.
- The composer selector uses neutral box styling with only subtle text color differences by mode.
- The selector remains lightweight: no background polling, no backend hover calls, and no approval prompt system.

## 21. v2.9.0 Stability Decision

v2.9.0 restores the v2.7.8 LangChain-based runtime as the stable baseline.
The v2.8.x series experimented with OpenAI native SDK, streaming, detailed diagnostics, and tool-call canonicalization. These experiments improved low-level visibility but introduced regressions in task continuity, image_read behavior, tool-call stability, CPU usage, and latency.
For v2.9.0, the project prioritizes stable Codex-style execution over experimental streaming.
The stable runtime must preserve:

- long-task continuation
- reliable tool loop behavior
- image/file task completion
- predictable LangChain tool calling
- lightweight timing display

## 22. Runtime Backend Policy

The stable backend for v2.9.0 is the LangChain-based runtime.
OpenAI native SDK and Responses API support are future adapter work. They must not become default until they pass the same regression tests as the LangChain runtime:

- greeting without tools
- file read
- image read
- long task continuation
- tool result continuation
- final deliverable completion

## 23. Streaming Policy

Streaming is postponed for v2.9.0.
Any future streaming implementation must preserve the existing Codex-style loop:

1. tool calls must remain reliable;
2. tool results must return to the model;
3. image/file tasks must complete;
4. the runtime must not stop on intermediate plan-like text;
5. long tasks must continue until final deliverable.

## 24. Max Output Token Policy

v2.9.0 uses a conservative default output cap.
Default:

```env
VP_MAX_OUTPUT_TOKENS=4096
```

This value is a per-call upper bound, not the whole task limit.

Long tasks should be completed through multiple model calls and tool loops, not by setting a very large output cap for every request.

Future dynamic policy may use:

- simple chat: 1024
- default answer: 4096
- plan/design document: 6144
- long report: 8192
- hard upper limit: 12000

## 25. Context Turns

`Context Turns` 对应 `max_context_turns`。
它表示在构建当前模型上下文时，最多可能纳入多少历史 user/assistant turn（历史用户/助手轮次）的上限。
它不是 thread（线程）里的总轮数。

示例：

- Thread total turns: `3000`
- Context Turns: `2000`
- 在 token budget（token 预算）和 compaction（上下文压缩）继续生效之前，runtime 最多考虑最近或最相关的 `2000` 个历史 turn

## 26. Python Command Handling

当 runtime 需要执行 Python 项目命令时，不应假定 `python3` 一定存在。
v2.9.x 的稳定策略是：

- 如果项目根目录存在 `./.venv/bin/python`（Windows 为 `.venv\Scripts\python.exe`），优先使用它执行项目测试、脚本和模块命令
- 如果没有项目 `.venv`，优先使用 runtime 检测到的 `python_command`
- 项目级模块执行优先 `<python_command> -m ...`
- Windows 上如果 `python` 不可用，可退回 `py -m ...`
- 这属于命令提示与轻量兼容处理，不改变稳定 LangChain runtime 的核心 tool loop

推荐示例：

```bash
./.venv/bin/python -m pytest
./.venv/bin/python -m compileall app packages tests
```

如果没有 `.venv`，再使用：

```bash
python -m pytest
python -m compileall app packages tests
```

## 27. Python Version Recommendation

稳定的 v2.9.x 运行时推荐使用 Python `3.11`。
Python `3.12` 也可接受。
Python `3.13` 目前还不是主要测试环境，OCR、ONNXRuntime、图片/PDF 处理等依赖在不同平台上可能出现 native wheel 兼容性问题。

## 28. Shell Command Allowlist

`exec_command` 继续使用保守 allowlist。
从 v2.9.3 开始，推荐的完整安全 `VP_ALLOWED_COMMANDS` 列表包含 `printf` 和 `dir`。
需要注意：`VP_ALLOWED_COMMANDS` 是完整覆盖，不是增量追加；如果自定义它，应包含完整安全列表。
高风险命令如 `rm`、`chmod`、`chown`、`curl`、`wget`、`sudo`、`dd`、`kill`、`pkill`、`brew`、`pip`、`pip3` 仍保持阻止。

## 29. Workspace and Permission Profiles

v2.9.13 将当前 `project_root` 作为默认 workspace。默认可读范围是当前项目与显式导入/上传文件；默认可写范围是当前项目；默认命令执行范围是当前项目。

权限 profile 分为三类：

- `Default`：只读安全模式，仅允许读取/搜索工具，不允许文件写入，不允许 shell，network 关闭。
- `Auto`：默认自动开发模式，允许读写当前项目、在当前项目内运行安全命令，network 开启。
- `Full Access`：最大信任模式，可按系统配置使用更大范围的读写和命令作用域，network 开启；但仍受 path boundary、command allowlist 与危险命令拦截约束。

`VP_EXTRA_ALLOWED_ROOTS` 是显式授权入口；Downloads、Desktop/workbench、workspace sibling root 不再作为默认访问范围。命令安全不只检查 `cwd`，也检查路径参数，例如 `rg /etc`、`git -C /tmp status`、`python /tmp/a.py`、`cp app/main.py /tmp/main.py`。

## 30. 源码依据与待确认点

### 本手册主要依据的源码

- `app/vintage_programmer_runtime.py`
- `app/local_tools.py`
- `app/main.py`
- `app/models.py`
- `app/context_meter.py`
- `app/static/app.js`
- `app/static/locales.js`
- `app/tool_trace_summary.py`
- `app/config.py`
- `agents/vintage_programmer/agent.md`
- `agents/vintage_programmer/tools.md`
- `packages/office_modules/office_agent_runtime.py`
- `packages/office_modules/review_support.py`

### 待确认点

1. `Responses API` 相关代码是否会在未来成为稳定主路径：当前仓库存在可选 runner，但不是本文主线。
2. `1000` 作为 `emergency_max_tool_calls_per_turn` 是否仍然偏高或偏低：当前只记录现状，不做进一步行为调整。
3. 是否需要在未来引入独立 `read_range`：当前源码没有该工具，局部读取由 `read_file` 参数承担。
