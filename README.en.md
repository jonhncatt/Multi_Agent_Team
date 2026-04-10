# Vintage Programmer

[中文 README](README.md)
[Windows Guide](README.windows.md)

This repo now runs as a single-agent workstation built around `vintage_programmer`.

## How To Run

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`. The minimum working setup is:

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=your_key
```

Then start the app:

```bash
./run.sh
```

Open:

- <http://127.0.0.1:8080>

### Windows PowerShell

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

After editing `.env`, start:

```powershell
.\run.ps1
```

### Quick Check

```bash
curl http://127.0.0.1:8080/api/health
```

If the server starts but chat requests fail, the usual cause is missing model auth in `.env`.

## Minimal Env Profiles

The root [.env.example](.env.example) was simplified to three common profiles.

### 1. OpenAI API key

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=your_key
```

### 2. OpenAI with Codex auth

Use this if `~/.codex/auth.json` already exists:

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
MULTI_AGENT_TEAM_LLM_AUTH_MODE=codex_auth
```

### 3. Local Ollama

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=ollama
MULTI_AGENT_TEAM_PROVIDER_OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
MULTI_AGENT_TEAM_DEFAULT_MODEL=qwen2.5-coder:7b
```

### 4. OpenAI-compatible / enterprise gateway

If you are using an OpenAI-compatible company gateway, the recommended setup is:

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=your_gateway_key
MULTI_AGENT_TEAM_PROVIDER_OPENAI_BASE_URL=https://your-gateway.example.com/v1
MULTI_AGENT_TEAM_PROVIDER_OPENAI_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
```

Meaning:

- `MULTI_AGENT_TEAM_PROVIDER_OPENAI_BASE_URL`
  - base URL for the OpenAI-compatible gateway
- `MULTI_AGENT_TEAM_PROVIDER_OPENAI_CA_CERT_PATH`
  - path to the corporate root or intermediate CA certificate

Compatible aliases also work, but are not the preferred form:

- `OPENAI_BASE_URL`
- `SSL_CERT_FILE`

## Product Shape

- one main agent: `vintage_programmer`
- one default chat path: `POST /api/chat` and `POST /api/chat/stream`
- one agent spec set: `agents/vintage_programmer/soul.md`, `agent.md`, `tools.md`
- one Codex-style UI: threads, chat, collapsible inspector

Reusable foundations kept in place:

- session storage
- uploads and attachments
- SSE streaming
- local tool execution
- token accounting

Removed from the default public surface:

- `GET /api/agent-plugins`
- `POST /api/agent-plugins/run`
- the `role_agent_lab` product entry

## Agent Specs

The main agent is now defined by markdown specs instead of JSON plugin manifests:

- [soul.md](agents/vintage_programmer/soul.md)
- [agent.md](agents/vintage_programmer/agent.md)
- [tools.md](agents/vintage_programmer/tools.md)

`agent.md` frontmatter keeps the minimum runtime metadata:

- `id`
- `title`
- `default_model`
- `tool_policy`
- `max_tool_rounds`

## Main APIs

- `GET /api/health`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/session/new`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `PATCH /api/session/{session_id}/title`
- `DELETE /api/session/{session_id}`
- `POST /api/upload`

## Layout

```text
agents/vintage_programmer/   # main agent specs
app/main.py                  # FastAPI entrypoint
app/vintage_programmer_runtime.py
app/static/                  # zero-build React UI
app/storage.py               # session and upload persistence
app/tool_providers/          # local tool surface
tests/                       # smoke and integration coverage
```

## Notes

- `kernel/shadow` maintenance endpoints still exist in the backend, but are not part of the main UI
- legacy multi-agent and swarm assets are now replacement-era code, not the default execution path
