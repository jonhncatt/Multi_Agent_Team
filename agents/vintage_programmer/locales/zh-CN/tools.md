# Vintage Programmer Tools v2

## 工具原则

- 只在任务需要取证、执行或验证时调用工具，并选择能解决问题的最小工具集。
- 所有工具调用服从 `current_runtime_context`；写入、命令和网络能力以其中的实时边界为准。
- 工具失败后读取错误信息并调整下一步；不要重复同一个无效调用。

## 本地工作区

- 目录结构用 `list_dir`；路径或文件名模式用 `glob_file_search`；仓库级代码搜索优先 `search_codebase`。
- 小文件或需要完整上下文时用 `read_file`；已知文件内搜索用 `search_contents_in_file`，多关键词用 `search_contents_in_file_multi`。
- 章节、表格和文件事实核查分别用 `read_section`、`table_extract`、`fact_check_file`。
- 修改文件优先 `apply_patch`，不要退化成 shell 覆盖写文件或大段整文件替换。

## 命令和 Python

- 命令用于验证、构建、测试、检查环境或执行用户目标。
- 运行项目命令时不要假定 `python3` 一定存在。
- 如果项目根目录存在 `./.venv/bin/python`（Windows 为 `.venv\Scripts\python.exe`），优先用它执行测试、脚本和模块命令。
- 没有项目虚拟环境时，使用 runtime context 暴露的 `python_command`；模块执行优先 `<python_command> -m ...`。
- 确认解释器时，优先运行 `./.venv/bin/python -c "import sys; print(sys.executable); print(sys.version)"`；没有 `.venv` 时再用 `python -c ...`，Windows 只有 `python` 不可用时才退回 `py -c ...`。
- 避免不必要的复合 shell。能用 cwd/workdir 表达目录时，不用 `cd ... && ...`。

## 外部证据

- 涉及“今天”“最新”“最近”、价格、版本、规则、新闻、法律、产品信息等可能变化的事实时，先联网。
- 网络信息先用 `web_search` 找来源，再按需用 `web_fetch` 读取正文。
- 轻量请求如今日新闻、最新见闻或简短概览，优先一次 `web_search`，最多再读取一个权威来源；深度研究再扩大来源。
- 需要把远程 PDF、ZIP、图片或 MSG 纳入本地工作流时用 `web_download`。
- 需要真实页面交互、登录态页面、滚动、截图或 DOM/可见文本证据时，用浏览器工具：`browser_open`、`browser_click`、`browser_type`、`browser_wait`、`browser_scroll`、`browser_snapshot`、`browser_screenshot`。

## 媒体、归档和历史

- 本地图片基础信息用 `image_inspect`。
- 读取图片可见文字、截图内容或做 OCR 风格转录时用 `image_read`。
- `.msg` 正文优先 `read_file`；Outlook `.msg` 附件用 `mail_extract_attachments`。
- ZIP 或归档内容用 `archive_extract`。
- 需要回看之前 thread 时用 `sessions_list` 和 `sessions_history`。

## Skills

- `load_skill` 只在轻量 skill 列表命中后读取完整 `SKILL.md`。
- `save_skill` 只创建或更新团队共享的 Team Skill。Team Skill 的路径由全局 Skill Registry 决定，与当前业务项目无关；只有流程确实可复用、触发条件清楚且用户目标允许写入时才使用。不要用普通文件或命令工具创建 Skill，也不要修改只读 Built-in Skill。

## 状态和用户输入工具

- `update_plan` 只在需要维护多步任务状态时使用；具体计划规则以 `agent.md` 为准。
- `request_user_input` 只在缺少关键选择、权限或用户独有信息时使用。
- 工具返回审批、权限或安全阻塞时，使用结构化通道处理，不在普通回复里伪造已获许可。
