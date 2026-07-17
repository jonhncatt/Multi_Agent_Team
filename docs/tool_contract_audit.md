# 模型工具契约审计

## 目的

本次审计检查 VintageProgrammer 暴露给模型的全部 33 个工具，重点不是工具能否执行，而是模型在调用前能否从工具名称、描述和参数 schema 中准确知道：

- 该选哪个操作或枚举值；
- 参数的单位、默认值和范围；
- 工具是读取、写入、执行还是等待；
- 是否会覆盖文件、产生外部影响或继承不可信来源；
- 成功返回后还需要执行什么后续动作。

Codex 的公开实现也会把 `apply_patch` 的 Add、Update、Delete 选择规则和完整 patch 语法明确提供给模型，而不是假设模型能从服务端实现中自行推断。参考：[Codex apply_patch instructions](https://github.com/openai/codex/blob/main/codex-rs/core/prompt_with_apply_patch_instructions.md)。VintageProgrammer 使用公司 Chat Completions 接口，因此把这些信息放进模型实际收到的工具 description 和参数 schema，同时由 Runtime 做严格校验。

## 设计原则

1. 工具契约描述通用能力，不写具体 Skill 名称、公司业务词或任务关键词。
2. 模型负责选择工具和参数；Harness 只校验权限、参数、文件边界和真实执行结果。
3. 非显然的选择规则必须靠近工具 schema，不能只藏在服务端代码或独立文档里。
4. Runtime 仍然拒绝错误操作。例如，已存在文件使用 `Add File` 时返回结构化错误，不允许静默覆盖。
5. locale `tools.md` 只保留简短使用原则；详细参数契约以模型实际收到的 Structured Tool schema 为准。

## 逐项结果

| 工具 | 审计结果 | 本轮结论或改进 |
|---|---|---|
| `exec_command` | 已修正 | 明确 cwd、等待时间、输出上限；说明 `tty` 当前只是兼容标记，不会分配 PTY。审批与命令边界继续由 Runtime 决定。 |
| `write_stdin` | 已补充 | 明确只能使用仍在运行的 session id；空 `chars` 表示轮询，时间单位为毫秒。 |
| `apply_patch` | 关键修复 | 明确 Add 只用于不存在的文件、Update 用于已存在或已读取文件、Delete 只用于已存在文件；补全 Begin/End、hunk、Move 和路径语法。 |
| `read_file` | 已补充 | 明确字符模式为 0-based，行模式首行为 1-based，`max_lines > 0` 才启用行模式。 |
| `list_dir` | 行为修复 | 修正只读工具错误检查写权限的问题；现在 read-only Runtime 和只读 Subagent 可以正常列目录。 |
| `glob_file_search` | 已补充 | 明确 glob 示例、搜索根目录和结果上限，并提示大目录使用较窄 pattern。 |
| `search_contents_in_file` | 已补充 | 明确它搜索已知单个文件的抽取文本，返回匹配片段而不是完整阅读结论。 |
| `search_contents_in_file_multi` | 已补充 | 明确多个 query 共享同一文件，以及每个 query 的片段上限。 |
| `read_section` | 已补充 | 明确按标题或章节号匹配，并受最大字符数限制。 |
| `table_extract` | 已修正 | 不再笼统声称支持所有文档；明确支持 PDF 与 OpenXML Excel（`.xlsx/.xlsm/.xltx/.xltm`），PDF page hint 为 1-based。 |
| `fact_check_file` | 已修正 | 不再把启发式检索包装成权威事实判断；明确 verdict 仍需模型结合证据判断。 |
| `search_codebase` | 已补充 | 明确默认 literal、可选 regex、大小写开关和 file glob。 |
| `web_search` | 已确认 | query、结果上限和秒级超时均已显式提供。返回候选来源，不等于来源已被完整读取。 |
| `web_fetch` | 已确认 | 明确 HTTP/HTTPS URL、字符上限和秒级超时。 |
| `web_download` | 已修正 | 明确目标路径、覆盖和大小限制；下载文件标记为不可信，后续执行可能要求审批。 |
| `sessions_list` | 行为修复 | 明确只列当前项目；修正先截断再按项目过滤的问题，现在数量上限应用在过滤之后。 |
| `sessions_history` | 已补充 | 明确 session id 来源和只返回最近 `max_turns` 轮。 |
| `image_inspect` | 已确认 | 只返回图像格式、尺寸和模式等元数据，不声称理解图像内容。 |
| `image_read` | 已补充 | 明确读取可见内容、可给分析重点，并限制输出字符数。 |
| `archive_extract` | 已修正 | 明确只支持 ZIP、解压上限和覆盖语义；下载 ZIP 的不可信来源会传递给解压文件。 |
| `mail_extract_attachments` | 已补充 | 明确输入为 Outlook `.msg`，以及附件数量、总大小、目标目录和覆盖语义。 |
| `spawn_subagent` | 已修正 | role 改为显式枚举；明确返回 id，独立任务可并行，结果需要通过 `wait_subagents` 收集。 |
| `wait_subagents` | 已补充 | 明确省略 id 时等待当前全部子任务，超时单位为秒且可能仍返回 running ids。 |
| `update_plan` | 关键修复 | 从泛型 `list[dict]` 改为模型可见的嵌套结构；status 为固定枚举，并明确每次同步完整 checklist。 |
| `request_user_input` | 关键修复 | 从泛型字典改为完整嵌套 schema；明确 1–3 个问题、2–3 个选项、header 长度和 Other 由客户端补充。 |
| `save_skill` | 已修正 | 明确只创建 Team `SKILL.md`，`overwrite=true` 才替换；body 不含 YAML frontmatter；脚本、references 和局部修改使用 `apply_patch`；Builtin 只读。 |
| `browser_open` | 已补充 | 明确 HTTP/HTTPS、复用当前浏览器 session，超时单位为毫秒。 |
| `browser_click` | 已补充 | 明确 CSS selector 且点击第一个匹配元素。 |
| `browser_type` | 已补充 | 明确 CSS selector、clear/append 差异和 submit 会按 Enter。 |
| `browser_wait` | 已修正 | state 改为固定枚举；selector 为空时只等待指定毫秒数。 |
| `browser_scroll` | 已修正 | direction 改为固定枚举；selector 存在时忽略 direction/amount，改为滚动到元素。 |
| `browser_snapshot` | 已补充 | 明确返回标题、URL、文本摘要和主要链接，并受字符上限约束。 |
| `browser_screenshot` | 已补充 | 明确空路径自动生成位置，`full_page=false` 时只截 viewport。 |

## 自动回归保护

新增测试会验证：

- Runtime 注册工具与模型可见工具一一对应，当前必须正好是 33 个；
- 每个模型可见工具和每个参数都有说明；
- 模型 schema 中的字段都能被对应 Runtime wrapper 接收；
- `apply_patch` 的 Add/Update/Delete 与完整语法不会从 schema 中消失；
- plan、用户提问、Subagent role 和浏览器状态的嵌套结构与枚举不会退化为泛型字典；
- 不可信下载、Skill 覆盖、当前项目会话等非显然语义保持可见；
- `list_dir` 在只读边界下可用；
- `sessions_list` 在项目过滤后再应用 limit。

## 保留的兼容层

代码中仍有两套工具表示：`VPRuntimeBackend` 构造模型实际收到的 Structured Tools，`LocalToolExecutor.tool_specs` 服务于 Runtime 校验和应用展示。两者包含少量有意差异，例如 Runtime 还接受审批 token 和旧 plan 参数别名，但这些字段不直接交给模型。本轮没有大规模重写注册架构，而是用共享的 `apply_patch` 契约和全工具一致性测试防止两套表示继续漂移。
