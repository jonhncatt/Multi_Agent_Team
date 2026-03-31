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

AUTH_MODE="${OFFICETOOL_LLM_AUTH_MODE:-${OFFCIATOOL_LLM_AUTH_MODE:-${OFFICETOOL_OPENAI_AUTH_MODE:-${OFFCIATOOL_OPENAI_AUTH_MODE:-auto}}}}"
APP_MODULE="${OFFICETOOL_APP_MODULE:-app.multi_agent_robot_main:app}"
APP_PORT="${OFFICETOOL_APP_PORT:-8080}"
CODEX_HOME_DIR="${OFFICETOOL_CODEX_HOME:-${OFFCIATOOL_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}}"
CODEX_AUTH_FILE="${OFFICETOOL_CODEX_AUTH_FILE:-${OFFCIATOOL_CODEX_AUTH_FILE:-$CODEX_HOME_DIR/auth.json}}"

LLM_API_KEY="${OFFICETOOL_LLM_API_KEY:-${OFFCIATOOL_LLM_API_KEY:-}}"
LLM_BASE_URL="${OFFICETOOL_LLM_BASE_URL:-${OFFCIATOOL_LLM_BASE_URL:-}}"

if [ -n "$LLM_API_KEY" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  export OPENAI_API_KEY="$LLM_API_KEY"
fi

if [ -n "$LLM_BASE_URL" ] && [ -z "${OPENAI_BASE_URL:-}" ]; then
  export OPENAI_BASE_URL="$LLM_BASE_URL"
fi

has_api_key=false
has_codex_auth=false

if [ -n "${OPENAI_API_KEY:-}" ]; then
  has_api_key=true
fi

if [ -f "$CODEX_AUTH_FILE" ]; then
  has_codex_auth=true
fi

case "$AUTH_MODE" in
  api_key)
    if [ "$has_api_key" = false ]; then
      echo "WARN: LLM auth mode=api_key but no API key was found. Set OFFICETOOL_LLM_API_KEY (preferred) or OPENAI_API_KEY." >&2
    fi
    ;;
  codex_auth)
    if [ "$has_codex_auth" = false ]; then
      echo "WARN: LLM auth mode=codex_auth but Codex auth file was not found at $CODEX_AUTH_FILE." >&2
    fi
    ;;
  *)
    if [ "$has_api_key" = false ] && [ "$has_codex_auth" = false ]; then
      echo "WARN: Neither API key (OFFICETOOL_LLM_API_KEY / OPENAI_API_KEY) nor Codex auth.json is configured. /api/chat will fail until one auth mode is available." >&2
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
