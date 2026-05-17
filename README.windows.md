# Vintage Programmer Windows 指南

当前稳定版本：`v2.9.6`。

## Stable Runtime

v2.9.6 是 runtime 行为对齐版本，继续默认使用 LangChain-based stable runtime。
v2.8.x 的 OpenAI native SDK、streaming 与更重的诊断实验暂时后置，不进入这个稳定版的默认路径。v2.9.6 将工具调用明确视为模型行动，由 harness 统一验证 RuntimeBoundary、schema 和权限；无效工具调用会作为观察结果返回给模型自我修正。

项目级 Python 模块命令建议优先使用 `.venv\Scripts\python.exe -m ...`；如果项目没有 `.venv`，再使用 `python -m ...`。如果当前环境没有 `python`，再使用 `py -m ...`。

## Python Version

稳定的 v2.9.x 运行时推荐 Python `3.11`。Python `3.12` 也可接受。Python `3.13` 目前还不是主要测试环境，OCR、ONNXRuntime、图片/PDF 处理等依赖在不同机器上可能出现兼容性差异。

## Max Output Tokens

推荐默认设置：

```env
VP_MAX_OUTPUT_TOKENS=4096
```

这是单次模型调用的输出上限，不是整个任务的总上限。

默认建议：不要激活 `Activate.ps1`，直接使用 `.venv\Scripts\python.exe`。

## Command Safety

`exec_command` 仍然使用保守 allowlist。v2.9.6 推荐的完整安全列表包含 `printf` 和 `dir`，并且 `VP_ALLOWED_COMMANDS` 是完整覆盖，不是增量追加；`rm`、`chmod`、`chown`、`curl`、`wget`、`sudo`、`dd`、`kill`、`pkill`、`brew`、`pip`、`pip3` 等高风险命令仍保持阻止。

## 运行

```powershell
cd C:\path\to\new_validation_agent
py -3.11 -m venv .venv
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

如果你不填 `VP_OPENAI_API_KEY`，但本机存在 `VP_CODEX_AUTH_FILE`，程序会自动切到 Codex auth。

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

- 在 `codex/*` 候选分支完成改动
- 回归通过后合到 `main`
- 在发布提交上打 annotated tag，例如 `v2.9.6`
- 后续新改动从最新 `main` 再切新的 `codex/*` 分支

完整清单见 [RELEASING.md](RELEASING.md)。
