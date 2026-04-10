# Vintage Programmer

[English README](README.en.md)
[Windows 指南](README.windows.md)

这是当前仓库的默认产品形态：一个像 Codex 一样工作的单主 agent 工作台。

## 现在怎么运行

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，最少只需要确认两行：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=你的_key
```

然后启动：

```bash
./run.sh
```

打开：

- <http://127.0.0.1:8080>

### Windows PowerShell

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env` 后启动：

```powershell
.\run.ps1
```

### 启动成功后怎么确认

先看健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

再直接打开浏览器访问：

- <http://127.0.0.1:8080>

如果服务能起来，但聊天失败，通常是 `.env` 里还没有可用的模型认证。

## 最小环境配置

根目录的 [.env.example](.env.example) 已经简化成 3 种常用模式。

### 1. OpenAI API key

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=你的_key
```

### 2. OpenAI + Codex auth

适合你已经有 `~/.codex/auth.json` 的情况：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
MULTI_AGENT_TEAM_LLM_AUTH_MODE=codex_auth
```

### 3. 本地 Ollama

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=ollama
MULTI_AGENT_TEAM_PROVIDER_OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
MULTI_AGENT_TEAM_DEFAULT_MODEL=qwen2.5-coder:7b
```

### 4. OpenAI-compatible / 企业网关

如果你走的是兼容 OpenAI API 的公司网关，当前项目里建议这样配：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=你的网关_key
MULTI_AGENT_TEAM_PROVIDER_OPENAI_BASE_URL=https://your-gateway.example.com/v1
MULTI_AGENT_TEAM_PROVIDER_OPENAI_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
```

这组变量的含义：

- `MULTI_AGENT_TEAM_PROVIDER_OPENAI_BASE_URL`
  - 给 OpenAI-compatible 网关的 base URL
- `MULTI_AGENT_TEAM_PROVIDER_OPENAI_CA_CERT_PATH`
  - 给企业根证书或中间证书文件路径

兼容别名也可用，但不建议优先写：

- `OPENAI_BASE_URL`
- `SSL_CERT_FILE`

## 这次重构后的产品结构

- 单主 agent：`vintage_programmer`
- 单聊天主链：`POST /api/chat` 与 `POST /api/chat/stream`
- 单套 agent 规范：`agents/vintage_programmer/soul.md`、`agent.md`、`tools.md`
- 单工作台界面：左线程栏、中间聊天区、右侧可折叠检查栏

保留的基础设施：

- 会话存储
- 上传与附件
- 流式 SSE 返回
- 本地工具执行
- token 统计

默认不再暴露：

- `GET /api/agent-plugins`
- `POST /api/agent-plugins/run`
- `role_agent_lab` 产品入口

## Agent 规范

`vintage_programmer` 不再由多份 JSON manifest 驱动，而是由 markdown 规范驱动：

- [soul.md](agents/vintage_programmer/soul.md)
- [agent.md](agents/vintage_programmer/agent.md)
- [tools.md](agents/vintage_programmer/tools.md)

`agent.md` frontmatter 里保留最小运行时元数据：

- `id`
- `title`
- `default_model`
- `tool_policy`
- `max_tool_rounds`

## 主要接口

- `GET /api/health`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/session/new`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `PATCH /api/session/{session_id}/title`
- `DELETE /api/session/{session_id}`
- `POST /api/upload`

## 目录

```text
agents/vintage_programmer/   # 单主 agent 规范
app/main.py                  # FastAPI 入口
app/vintage_programmer_runtime.py
app/static/                  # 零构建静态 React 工作台
app/storage.py               # 会话、上传、日志存储
app/tool_providers/          # 本地工具与 provider
tests/                       # 当前产品形态 smoke / integration tests
```

## 备注

- `kernel/shadow` 维护接口仍在后端，但不属于主 UI
- 旧的多 agent / swarm 资产现在属于被替换资产，不再走默认主链
