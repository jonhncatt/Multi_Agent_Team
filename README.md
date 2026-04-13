# Vintage Programmer

[English README](README.en.md)  
[Windows 指南](README.windows.md)  
[发布流程](RELEASING.md)

这是一个本地运行的单主 agent 工作台，默认主 agent 是 `vintage_programmer`。
当前稳定版本是 `v1.0.0`。

当前工作台形态是第三阶段版本：
- 左侧线程栏
- 中间全宽工作平面
- 底部常驻 composer
- 右侧 Workbench 抽屉
- 本地 skills / agent spec 可编辑

## 运行

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
./run.sh
```

默认打开：

- <http://127.0.0.1:8080>

### Windows

Windows 默认建议不要激活脚本，直接调用虚拟环境里的 Python：

```powershell
py -3.11 -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

详细说明见 [README.windows.md](README.windows.md)。

## `.env` 最小配置

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
VP_OPENAI_COMPAT_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
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

如果你看到的是这种 OpenRouter 模型页面链接：

```text
https://openrouter.ai/google/gemma-4-31b-it:free/api
```

它不是 `VP_OPENROUTER_BASE_URL`。正确填写方式是：
- `VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free`

更多示例见 [.env.example](.env.example)。

## 接口说明

下面这些都是这个项目自己的本地 HTTP 接口，不是 OpenAI 官方 API：

- `GET /api/health`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/session/new`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `PATCH /api/session/{session_id}/title`
- `DELETE /api/session/{session_id}`
- `POST /api/upload`
- `GET /api/workbench/tools`
- `GET /api/workbench/skills`
- `POST /api/workbench/skills`
- `PUT /api/workbench/skills/{skill_id}`
- `POST /api/workbench/skills/{skill_id}/toggle`
- `GET /api/workbench/specs`
- `GET /api/workbench/specs/{name}`
- `PUT /api/workbench/specs/{name}`

浏览器页面和前端工作台就是调用这些本地接口。

## Agent 规范

主 agent 由这四份 markdown 规范定义：

- [agents/vintage_programmer/soul.md](agents/vintage_programmer/soul.md)
- [agents/vintage_programmer/identity.md](agents/vintage_programmer/identity.md)
- [agents/vintage_programmer/agent.md](agents/vintage_programmer/agent.md)
- [agents/vintage_programmer/tools.md](agents/vintage_programmer/tools.md)

## 本地 Skills

本地 skills 固定放在：

- `workspace/skills/<skill_id>/SKILL.md`

默认会从 frontmatter 读取：

- `id`
- `title`
- `enabled`
- `bind_to`
- `summary`

只有 `enabled: true` 且 `bind_to` 包含 `vintage_programmer` 的 skill 会注入主 agent。

## 发布

正式发布流程固定为：

- 在 `codex/*` 候选分支完成改动
- 回归通过后合到 `main`
- 在 `main` 的发布提交上打 annotated tag，例如 `v1.0.0`
- 后续新改动始终从最新 `main` 再切新的 `codex/*` 分支

详细步骤见 [RELEASING.md](RELEASING.md)。

## 工具说明

这一版工具层是 `OpenClaw-first`：

- 保留已有的 workspace / files / web / session 工具
- 新增 `browser_*`
- 新增 `view_image`
- 新增 `apply_patch`
- 新增 `skills` 和 `agent_specs` 管理工具

联网仍然是显式工具模式，不是模型隐式“自己上网”。

## Inline 代码

如果你直接把代码、XML、HTML、JSON、YAML 或长文本粘到输入框里，主 agent 会优先把它当作当前消息内容直接分析，不会先默认追问 workspace 路径。
