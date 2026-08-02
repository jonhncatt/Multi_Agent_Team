# Vintage Programmer Windows 指南

当前稳定版本：`3.1.5Y`。

## Stable Runtime

当前分支使用全局 Built-in/Team Skill Registry。`save_skill` 只把可复用流程写入 Vintage Programmer 仓库的 `skills\team\<name>\SKILL.md`，不会写入当前业务项目；`skills\builtin` 保持只读。模型从 `[available_skills]` 获得启用 Skill 的路径，用普通 `read_file` 读取完整说明，并用普通 `exec_command` 执行附属脚本。

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
VP_CONTEXT_AUTO_COMPACT_RATIO=0.9
VP_CONTEXT_DANGER_COMPACT_RATIO=0.95
VP_CONTEXT_HISTORY_SOFT_LIMIT_TOKENS=120000
VP_CONTEXT_EXACT_STALE_SEC=60
```

这是单次模型调用的输出上限，不是整个任务的总上限。默认 16384 适合 GPT-5.4 这类大上下文模型的长材料问答；长任务仍应通过多轮 model/tool loop 完成，而不是依赖一次 128K 级别的超大回复。
`VP_MAX_USER_REQUEST_CHARS` 是当前用户输入的安全字符上限；实际进入模型的内容还会按当前模型 context window 和输出预留做 token 预算裁剪。

Context 状态采用轻量常驻显示：聊天主路径只用缓存或 quick 估算，不再每轮阻塞式精算 tokenizer。`/status` 读取当前 Thread 的状态并打开详情；`/compact` 手动整理旧历史。GPT-5.4 默认使用 272K 可用窗口、90% 自动整理线和 95% 危险线，真实 provider `input_tokens` 优先于本地估算。

默认建议：不要激活 `Activate.ps1`，直接使用 `.venv\Scripts\python.exe`。

## Command Safety

`exec_command` 仍然使用保守 allowlist。默认安全列表包含 `printf`、`dir` 和 Windows 程序定位命令 `where`，并且 `VP_ALLOWED_COMMANDS` 是完整覆盖，不是增量追加。默认命令执行仅限当前 project root，且会检查 `rg C:\Windows`、`git -C C:\Temp`、`python C:\Temp\a.py` 这类路径参数；`rm`、`chmod`、`chown`、`curl`、`wget`、`sudo`、`dd`、`kill`、`pkill`、`brew`、`pip`、`pip3` 等高风险命令仍保持阻止。

## Permission Profiles

默认权限 profile 是 `Auto`：读写当前项目并在项目内运行安全命令，网络关闭。`Default` 是当前项目只读模式；`Full Access` 可直接读写所有本机磁盘、在任意本机目录运行安全命令并访问网络，不需要额外路径环境变量。命令 allowlist、危险命令拦截、Builtin Skill 只读和外部写入审批仍然有效。

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

## 独立桌面窗口

仓库提供一个轻量 Windows launcher，用现有 FastAPI 服务打开 WebView2 原生独立窗口，
不显示地址栏和标签栏，并拥有独立的 VP 图标和任务栏身份。它不修改 Agent Runtime、
工具执行、审批或上下文逻辑。

从 GitHub Actions 的 **Windows Desktop Launcher** workflow 下载
`vintage-programmer-windows-launcher`，把其中的 `VintageProgrammer.exe` 放在仓库根目录，
完成上面的 `.venv` 与 `.env` 配置后即可双击启动。Windows 默认使用系统的 Edge WebView2
Runtime；如果 WebView2 不可用，会自动回退到 Chrome App Mode。原生窗口打开期间 EXE 保持运行，
并且只允许一个 VP 窗口；再次双击会唤醒已有窗口。空闲时关闭原生窗口会同时停止后台；如果仍有
Agent 或 Eval 在运行，关闭对话框只提供“停止任务并完全退出”和“取消关闭”。选择完全退出时，
Agent 会先走正常取消流程，再结束后台。Chrome App Mode 只是兼容回退，无法提供完全相同的原生
窗口生命周期保证。

WebView2 使用独立的 `app/data/desktop_webview2_profile`，Chrome 回退使用
`app/data/desktop_browser_profile`；Agent 打开 Redmine 等网站所用的
`VP_BROWSER_USER_DATA_DIR` 保持不变，这些 profile 不能指向同一目录。

在 Mac 上可以用相同核心预览无地址栏的 App Mode 窗口：

```bash
./.venv/bin/python -m desktop.launcher
```

Windows 本地构建和其他配置见 [desktop/windows/README.md](desktop/windows/README.md)。

## 最小 `.env`

OpenAI 官方：

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=你的_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.4
```

Vintage Programmer 现在只使用显式 provider API key 配置，不再从本机账号认证文件自动回退。

OpenAI-compatible 网关：

```env
VP_LLM_PROVIDER=openai_compatible
VP_OPENAI_COMPAT_API_KEY=你的网关_key
VP_OPENAI_COMPAT_BASE_URL=https://your-gateway.example.com/v1
VP_OPENAI_COMPAT_CA_CERT_PATH=C:\certs\your-root-ca.pem
VP_OPENAI_COMPAT_DEFAULT_MODEL=gpt-5.4
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
