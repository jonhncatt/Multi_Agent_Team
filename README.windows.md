# Vintage Programmer Windows 指南

当前稳定版本：`3.1.5T`。

## Stable Runtime

3.1.5T 是一次 Codex 风格 context 与长对话性能发布：Context 状态改为轻量常驻，`/status` 和 `/compact` 成为一等本地命令，长对话里发送短消息不再被 exact tokenizer 阻塞。
它保留 3.1.5S 的 Windows 启动体感、聊天 UX、消息复制、运行中输入、主题色选择、审批弹窗、tainted 文件 hash 校验、Auto 模式选择保持和三语 agent spec 同级化；这不是 OS sandbox，批准后命令会在 host 环境实际执行。

项目级 Python 模块命令建议优先使用 `.venv\Scripts\python.exe -m ...`；如果项目没有 `.venv`，再使用 `python -m ...`。如果当前环境没有 `python`，再使用 `py -m ...`。

## Python Version

稳定的 v2.9.x 运行时推荐 Python `3.11`。Python `3.12` 也可接受。Python `3.13` 目前还不是主要测试环境，OCR、ONNXRuntime、图片/PDF 处理等依赖在不同机器上可能出现兼容性差异。

如果你已经确认当前 `python` 指向的是受支持版本，也可以直接使用 `python -m venv .venv`。如果不确定当前默认版本，优先使用 `py -3.11 -m venv .venv`；没有 `3.11` 时再考虑 `py -3.12 -m venv .venv`。

## Max Output Tokens

推荐默认设置：

```env
VP_MAX_OUTPUT_TOKENS=16384
VP_MAX_USER_REQUEST_CHARS=4000000
VP_MAX_ATTACHMENT_CHARS=1000000
VP_CONTEXT_AUTO_COMPACT_RATIO=0.8
VP_CONTEXT_DANGER_COMPACT_RATIO=0.95
VP_CONTEXT_HISTORY_SOFT_LIMIT_TOKENS=120000
VP_CONTEXT_EXACT_STALE_SEC=60
```

这是单次模型调用的输出上限，不是整个任务的总上限。默认 16384 适合 GPT-5.4 这类大上下文模型的长材料问答；长任务仍应通过多轮 model/tool loop 完成，而不是依赖一次 128K 级别的超大回复。
`VP_MAX_USER_REQUEST_CHARS` 是当前用户输入的安全字符上限；实际进入模型的内容还会按当前模型 context window 和输出预留做 token 预算裁剪。

Context 状态采用轻量常驻显示：聊天主路径只用缓存或 quick 估算，不再每轮阻塞式精算 tokenizer。`/status` 读取当前 thread 的状态并打开详情；`/compact` 手动整理旧历史。自动整理默认在预计使用达到窗口 80% 后 exact 复核，95% 进入危险整理线；`VP_CONTEXT_HISTORY_SOFT_LIMIT_TOKENS` 只用于旧聊天/工具输出噪音。

默认建议：不要激活 `Activate.ps1`，直接使用 `.venv\Scripts\python.exe`。

## Command Safety

`exec_command` 仍然使用保守 allowlist。v2.9.15 推荐的完整安全列表包含 `printf` 和 `dir`，并且 `VP_ALLOWED_COMMANDS` 是完整覆盖，不是增量追加。默认命令执行仅限当前 project root，且会检查 `rg C:\Windows`、`git -C C:\Temp`、`python C:\Temp\a.py` 这类路径参数；`rm`、`chmod`、`chown`、`curl`、`wget`、`sudo`、`dd`、`kill`、`pkill`、`brew`、`pip`、`pip3` 等高风险命令仍保持阻止。

## Permission Profiles

默认权限 profile 是 `Code`：可读当前项目和导入文件、可写当前项目、可在当前项目内运行安全命令，网络关闭。`Chat` 是只读分析模式，不写文件、不运行 shell、不开网络；`Full Dev` 可读取显式配置的额外根，并按全局网络配置启用网络。网络下载或解压得到的代码会被标记为 tainted，执行前需要一次性确认；所有模式仍受路径边界、命令 allowlist 和危险命令拦截约束。

## 运行

```powershell
cd C:\path\to\new_validation_agent
# 推荐：显式指定 Python 3.11
py -3.11 -m venv .venv
# 可选：如果当前 python 已经是受支持版本（推荐 3.11，可接受 3.12）
# python -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

打开：

- <http://127.0.0.1:8080>

## 最小 `.env`

OpenAI 官方：

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=你的_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.1-chat
```

Vintage Programmer 现在只使用显式 provider API key 配置，不再从本机账号认证文件自动回退。

OpenAI-compatible 网关：

```env
VP_LLM_PROVIDER=openai_compatible
VP_OPENAI_COMPAT_API_KEY=你的网关_key
VP_OPENAI_COMPAT_BASE_URL=https://your-gateway.example.com/v1
VP_OPENAI_COMPAT_CA_CERT_PATH=C:\certs\your-root-ca.pem
VP_OPENAI_COMPAT_DEFAULT_MODEL=gpt-5.1-chat
```

OpenRouter：

```env
VP_LLM_PROVIDER=openrouter
VP_OPENROUTER_API_KEY=你的_openrouter_key
VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free
VP_OPENROUTER_MODEL_FALLBACKS=nvidia/nemotron-3-super-120b-a12b:free
```

如果你看到的是这个模型页面：

```text
https://openrouter.ai/google/gemma-4-31b-it:free/api
```

不要把它直接填进 `VP_OPENROUTER_BASE_URL`。正确写法是：
- `VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free`

## 接口说明

`/api/chat`、`/api/health`、`/api/chat/stream` 和 `/api/workbench/*` 都是这个本地应用自己的接口，不是 OpenAI 官方 API。

主工作台现在是：

- 左侧线程栏
- 中间全宽消息平面
- 底部常驻 composer
- 右侧 Workbench 抽屉
- 本地 skills / agent specs 可编辑

## 如果你一定要激活虚拟环境

如果 PowerShell 放行脚本后，也可以这样：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1
```

但默认不推荐，直接调 `.venv\Scripts\python.exe` 更稳。

## 发布

正式发布固定走：

- 在 `cleanup/*` 或其他候选分支完成改动
- 回归通过后合到 `main`
- 在发布提交上打 annotated tag，例如 `v2.9.15`
- 后续新改动从最新 `main` 再切新的候选分支

完整清单见 [RELEASING.md](RELEASING.md)。
