# 内部设计手册（v2.7.2）

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

为什么默认折叠：

- 这些信息对调试很重要
- 但默认全展示会让背景信息窗口太像内部监控面板，不够紧凑

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

前端还做了：

- `AbortController`（中止控制器）取消旧请求
- 相同参数请求复用 in-flight promise（进行中的 promise）

因此 v2.7.x 之后的目标不是“完全不轮询”，而是：

- 在需要时刷新
- 在空闲 / 隐藏场景减速或暂停
- 避免重复 in-flight 请求

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

## 16. 源码依据与待确认点

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
