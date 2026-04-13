# Vintage Programmer

[中文 README](README.md)  
[Windows Guide](README.windows.md)  
[Release Flow](RELEASING.md)

This is a local single-agent workstation. The default main agent is `vintage_programmer`.
The current stable release is `v1.0.0`.

The current UI shape is the third-stage workstation:
- left thread rail
- full-width work plane
- always-visible bottom composer
- bottom status bar
- Workbench drawer on the right
- local skill and agent-spec editing

## Run

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
./run.sh
```

Open:

- <http://127.0.0.1:8080>

### Windows

On Windows, the default recommendation is to skip script activation and call the venv Python directly:

```powershell
py -3.11 -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

More detail: [README.windows.md](README.windows.md)

## Minimal `.env`

OpenAI official:

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=your_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.1-chat
```

If `VP_OPENAI_API_KEY` is absent but `VP_CODEX_AUTH_FILE` exists locally, the app will use Codex auth automatically.

OpenAI-compatible gateway:

```env
VP_LLM_PROVIDER=openai_compatible
VP_OPENAI_COMPAT_API_KEY=your_gateway_key
VP_OPENAI_COMPAT_BASE_URL=https://your-gateway.example.com/v1
VP_OPENAI_COMPAT_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
VP_OPENAI_COMPAT_DEFAULT_MODEL=gpt-5.1-chat
```

OpenRouter:

```env
VP_LLM_PROVIDER=openrouter
VP_OPENROUTER_API_KEY=your_openrouter_key
VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free
VP_OPENROUTER_MODEL_FALLBACKS=nvidia/nemotron-3-super-120b-a12b:free
```

If you are looking at a model page like:

```text
https://openrouter.ai/google/gemma-4-31b-it:free/api
```

that is not the value for `VP_OPENROUTER_BASE_URL`. Use:
- `VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free`

More examples: [.env.example](.env.example)

## API Note

These are this app's own local HTTP endpoints, not OpenAI official APIs:

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

The web UI talks to these local endpoints.

## Agent Specs

The main agent is defined by four markdown specs:

- [agents/vintage_programmer/soul.md](agents/vintage_programmer/soul.md)
- [agents/vintage_programmer/identity.md](agents/vintage_programmer/identity.md)
- [agents/vintage_programmer/agent.md](agents/vintage_programmer/agent.md)
- [agents/vintage_programmer/tools.md](agents/vintage_programmer/tools.md)

## Local Skills

Local skills live in:

- `workspace/skills/<skill_id>/SKILL.md`

Only skills with `enabled: true` and `bind_to` including `vintage_programmer` are injected into the main agent.

## Inline Code

If you paste code, XML, HTML, JSON, YAML, or other long text directly into the composer, the agent should analyze that inline content first instead of forcing a workspace path lookup.

## Release

The release flow is fixed:

- ship work on a `codex/*` candidate branch
- merge to `main` after regression passes
- create an annotated tag on the release commit, for example `v1.0.0`
- start the next change from a fresh `codex/*` branch cut from the latest `main`

See [RELEASING.md](RELEASING.md) for the full checklist.
