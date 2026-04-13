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

env_first() {
  local key value
  for key in "$@"; do
    value="${!key:-}"
    if [ -n "$value" ]; then
      printf '%s' "$value"
      return 0
    fi
  done
  return 1
}

LLM_PROVIDER_RAW="$(env_first VP_LLM_PROVIDER VP_MODEL_PROVIDER || printf 'openai')"
LLM_PROVIDER="$(printf '%s' "$LLM_PROVIDER_RAW" | tr '[:upper:]' '[:lower:]')"
case "$LLM_PROVIDER" in
  ""|default) LLM_PROVIDER="openai" ;;
  "openai-compatible") LLM_PROVIDER="openai_compatible" ;;
esac

APP_MODULE="$(env_first VP_APP_MODULE || printf 'app.main:app')"
APP_PORT="$(env_first VP_APP_PORT || printf '8080')"
CODEX_HOME_DIR="$(env_first VP_CODEX_HOME || printf '%s/.codex' "$HOME")"
CODEX_AUTH_FILE="$(env_first VP_CODEX_AUTH_FILE || printf '%s/auth.json' "$CODEX_HOME_DIR")"

EXPECTED_API_KEY_ENV=""
case "$LLM_PROVIDER" in
  openai) EXPECTED_API_KEY_ENV="VP_OPENAI_API_KEY" ;;
  openai_compatible) EXPECTED_API_KEY_ENV="VP_OPENAI_COMPAT_API_KEY" ;;
  openrouter) EXPECTED_API_KEY_ENV="VP_OPENROUTER_API_KEY" ;;
  deepseek) EXPECTED_API_KEY_ENV="VP_DEEPSEEK_API_KEY" ;;
  qwen) EXPECTED_API_KEY_ENV="VP_DASHSCOPE_API_KEY" ;;
  moonshot) EXPECTED_API_KEY_ENV="VP_MOONSHOT_API_KEY" ;;
  groq) EXPECTED_API_KEY_ENV="VP_GROQ_API_KEY" ;;
  ollama) EXPECTED_API_KEY_ENV="VP_OLLAMA_API_KEY" ;;
  *) EXPECTED_API_KEY_ENV="VP_LLM_API_KEY" ;;
esac

API_KEY_VALUE="$(env_first "$EXPECTED_API_KEY_ENV" VP_LLM_API_KEY || true)"
has_api_key=false
has_codex_auth=false
supports_codex_auth=false

if [ -n "${API_KEY_VALUE:-}" ]; then
  has_api_key=true
fi
if [ "$LLM_PROVIDER" = "ollama" ]; then
  has_api_key=true
fi
if [ "$LLM_PROVIDER" = "openai" ]; then
  supports_codex_auth=true
fi
if [ -f "$CODEX_AUTH_FILE" ]; then
  has_codex_auth=true
fi

if [ "$has_api_key" = false ]; then
  if [ "$supports_codex_auth" = true ] && [ "$has_codex_auth" = true ]; then
    :
  elif [ "$supports_codex_auth" = true ]; then
    echo "WARN: No API key found and Codex auth.json was not found. /api/chat requests will fail until one auth source is available." >&2
  else
    echo "WARN: No API key found for provider=$LLM_PROVIDER. Expected env: $EXPECTED_API_KEY_ENV (or VP_LLM_API_KEY)." >&2
  fi
fi

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  exec "$ROOT_DIR/.venv/bin/python" -m uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
fi

exec uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$APP_PORT" --reload
