#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

AUTH_MODE="${MULTI_AGENT_TEAM_LLM_AUTH_MODE:-${MULTI_AGENT_TEAM_OPENAI_AUTH_MODE:-auto}}"
LLM_PROVIDER_RAW="${MULTI_AGENT_TEAM_LLM_PROVIDER:-${MULTI_AGENT_TEAM_MODEL_PROVIDER:-openai}}"
LLM_PROVIDER="$(printf '%s' "$LLM_PROVIDER_RAW" | tr '[:upper:]' '[:lower:]')"
case "$LLM_PROVIDER" in
  ""|default|openai_compatible|openai-compatible) LLM_PROVIDER="openai" ;;
esac
LLM_PROVIDER_TOKEN="$(printf '%s' "$LLM_PROVIDER" | sed 's/[^a-z0-9]/_/g' | tr '[:lower:]' '[:upper:]')"
if [ -z "$LLM_PROVIDER_TOKEN" ]; then
  LLM_PROVIDER_TOKEN="OPENAI"
fi
APP_MODULE="${MULTI_AGENT_TEAM_APP_MODULE:-app.main:app}"
APP_PORT="${MULTI_AGENT_TEAM_APP_PORT:-8080}"
CODEX_HOME_DIR="${MULTI_AGENT_TEAM_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}"
CODEX_AUTH_FILE="${MULTI_AGENT_TEAM_CODEX_AUTH_FILE:-$CODEX_HOME_DIR/auth.json}"
PROVIDER_API_KEY_VAR="MULTI_AGENT_TEAM_PROVIDER_${LLM_PROVIDER_TOKEN}_API_KEY"
EXPECTED_API_KEY_ENV="$PROVIDER_API_KEY_VAR"
NATIVE_PROVIDER_API_KEY_VAR=""

case "$LLM_PROVIDER" in
  openai) NATIVE_PROVIDER_API_KEY_VAR="OPENAI_API_KEY" ;;
  deepseek) NATIVE_PROVIDER_API_KEY_VAR="DEEPSEEK_API_KEY" ;;
  qwen) NATIVE_PROVIDER_API_KEY_VAR="DASHSCOPE_API_KEY" ;;
  moonshot) NATIVE_PROVIDER_API_KEY_VAR="MOONSHOT_API_KEY" ;;
  openrouter) NATIVE_PROVIDER_API_KEY_VAR="OPENROUTER_API_KEY" ;;
  groq) NATIVE_PROVIDER_API_KEY_VAR="GROQ_API_KEY" ;;
  ollama) NATIVE_PROVIDER_API_KEY_VAR="OLLAMA_API_KEY" ;;
esac
API_KEY_HINT="$EXPECTED_API_KEY_ENV (or MULTI_AGENT_TEAM_LLM_API_KEY / OPENAI_API_KEY)"
if [ -n "$NATIVE_PROVIDER_API_KEY_VAR" ] && [ "$NATIVE_PROVIDER_API_KEY_VAR" != "OPENAI_API_KEY" ]; then
  API_KEY_HINT="$EXPECTED_API_KEY_ENV (or MULTI_AGENT_TEAM_LLM_API_KEY / $NATIVE_PROVIDER_API_KEY_VAR / OPENAI_API_KEY)"
fi

has_api_key=false
has_codex_auth=false
supports_codex_auth=false

provider_api_key="${!PROVIDER_API_KEY_VAR:-}"
native_provider_api_key=""
if [ -n "$NATIVE_PROVIDER_API_KEY_VAR" ]; then
  native_provider_api_key="${!NATIVE_PROVIDER_API_KEY_VAR:-}"
fi

if [ -n "$provider_api_key" ] || [ -n "${MULTI_AGENT_TEAM_LLM_API_KEY:-}" ] || [ -n "$native_provider_api_key" ] || [ -n "${OPENAI_API_KEY:-}" ]; then
  has_api_key=true
fi
if [ "$LLM_PROVIDER" = "ollama" ]; then
  has_api_key=true
fi

if [ -f "$CODEX_AUTH_FILE" ]; then
  has_codex_auth=true
fi

if [ "$LLM_PROVIDER" = "openai" ]; then
  supports_codex_auth=true
fi

case "$AUTH_MODE" in
  api_key)
    if [ "$has_api_key" = false ]; then
      echo "WARN: AUTH_MODE=api_key but no API key found. Expected env: $API_KEY_HINT." >&2
    fi
    ;;
  codex_auth)
    if [ "$supports_codex_auth" = false ]; then
      echo "WARN: AUTH_MODE=codex_auth is only supported when MULTI_AGENT_TEAM_LLM_PROVIDER=openai. Current provider=$LLM_PROVIDER." >&2
    fi
    if [ "$has_codex_auth" = false ]; then
      echo "WARN: AUTH_MODE=codex_auth but Codex auth file was not found at $CODEX_AUTH_FILE." >&2
    fi
    ;;
  *)
    if [ "$has_api_key" = false ]; then
      if [ "$supports_codex_auth" = true ] && [ "$has_codex_auth" = true ]; then
        :
      elif [ "$supports_codex_auth" = true ]; then
        echo "WARN: No API key found and Codex auth.json was not found. /api/chat requests will fail until one auth mode is available." >&2
      else
        echo "WARN: No API key found for provider=$LLM_PROVIDER. Expected env: $API_KEY_HINT." >&2
      fi
    fi
    ;;
esac

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  exec "$ROOT_DIR/.venv/bin/python" -m uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
fi

exec uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
