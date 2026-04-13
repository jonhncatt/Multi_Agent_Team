from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import AppConfig

DEFAULT_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_CODEX_CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_CODEX_REFRESH_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CODEX_REFRESH_INTERVAL_DAYS = 8


def normalize_model_for_auth_mode(model: str, auth_mode: str) -> str:
    normalized_model = str(model or "").strip()
    normalized_mode = str(auth_mode or "").strip().lower()
    if normalized_mode == "codex_auth" and normalized_model.lower().endswith("-chat"):
        return normalized_model[:-5]
    return normalized_model


@dataclass(slots=True)
class ResolvedOpenAIAuth:
    mode: str
    source: str
    available: bool
    reason: str = ""
    api_key: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    account_id: str | None = None
    id_token: str | None = None
    auth_file_path: Path | None = None
    chatgpt_base_url: str | None = None
    refresh_url: str | None = None
    client_id: str | None = None
    last_refresh: str | None = None


class OpenAIAuthManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._refresh_lock = threading.Lock()

    def _llm_provider(self) -> str:
        provider = str(getattr(self.config, "llm_provider", "") or "").strip().lower()
        return provider or "openai"

    def _llm_supports_codex_auth(self) -> bool:
        return bool(getattr(self.config, "llm_supports_codex_auth", True))

    def _api_key_env_keys(self) -> list[str]:
        keys = getattr(self.config, "llm_api_key_env_keys", [])
        if isinstance(keys, list):
            normalized = [str(item or "").strip() for item in keys if str(item or "").strip()]
            if normalized:
                return normalized
        return ["VP_LLM_API_KEY"]

    def _api_key_file_keys(self) -> list[str]:
        keys = getattr(self.config, "llm_auth_file_api_key_keys", [])
        if isinstance(keys, list):
            normalized = [str(item or "").strip() for item in keys if str(item or "").strip()]
            if normalized:
                return normalized
        return ["VP_LLM_API_KEY"]

    def _primary_api_key_env(self) -> str:
        configured = str(getattr(self.config, "llm_primary_api_key_env", "") or "").strip()
        if configured:
            return configured
        keys = self._api_key_env_keys()
        return keys[0] if keys else "VP_LLM_API_KEY"

    def resolve(self) -> ResolvedOpenAIAuth:
        provider = self._llm_provider()
        supports_codex_auth = self._llm_supports_codex_auth()

        api_key_auth = self._resolve_api_key_auth()
        codex_auth = self._resolve_codex_auth() if supports_codex_auth else ResolvedOpenAIAuth(
            mode="codex_auth",
            source="disabled",
            available=False,
            reason=f"Provider '{provider}' does not support codex_auth.",
        )

        if api_key_auth.available:
            return api_key_auth
        if supports_codex_auth and codex_auth.available:
            return codex_auth
        unavailable_reason = (
                f"API key is missing for provider '{provider}'. "
                f"Set {self._primary_api_key_env()} in env or .env."
        )
        if supports_codex_auth:
            unavailable_reason = (
                f"{unavailable_reason} "
                "If VP_LLM_PROVIDER=openai and VP_CODEX_AUTH_FILE exists, the app will use Codex auth automatically."
            )
        return ResolvedOpenAIAuth(
            mode="unconfigured",
            source="auto",
            available=False,
            reason=unavailable_reason,
        )

    def require(self, *, allow_refresh: bool = True) -> ResolvedOpenAIAuth:
        resolved = self.resolve()
        if not resolved.available:
            raise RuntimeError(resolved.reason or "LLM credentials are not available.")
        if resolved.mode != "codex_auth" or not allow_refresh:
            return resolved
        if self._codex_refresh_needed(resolved):
            return self.refresh_codex_auth(force=False)
        return resolved

    def refresh_codex_auth(self, *, force: bool = True) -> ResolvedOpenAIAuth:
        if not self._llm_supports_codex_auth():
            raise RuntimeError(f"Provider '{self._llm_provider()}' does not support codex_auth.")
        with self._refresh_lock:
            resolved = self._resolve_codex_auth()
            if not resolved.available:
                raise RuntimeError(resolved.reason or "Codex auth credentials are not available.")
            if not force and not self._codex_refresh_needed(resolved):
                return resolved
            refresh_token = str(resolved.refresh_token or "").strip()
            if not refresh_token:
                raise RuntimeError("Codex refresh token is missing. Please re-run `codex login`.")
            auth_file_path = resolved.auth_file_path or self.config.codex_auth_file
            payload = {
                "client_id": resolved.client_id or self.config.codex_client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            request = Request(
                str(resolved.refresh_url or self.config.codex_refresh_url),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=20) as response:
                    body = response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Codex token refresh failed: HTTP {exc.code}: {detail}") from exc
            except URLError as exc:
                raise RuntimeError(f"Codex token refresh failed: {exc}") from exc

            try:
                refreshed = json.loads(body)
            except Exception as exc:
                raise RuntimeError("Codex token refresh returned invalid JSON.") from exc

            access_token = str(refreshed.get("access_token") or resolved.access_token or "").strip()
            next_refresh_token = str(refreshed.get("refresh_token") or refresh_token).strip()
            id_token = str(refreshed.get("id_token") or resolved.id_token or "").strip()
            if not access_token:
                raise RuntimeError("Codex token refresh did not return an access token.")

            auth_json = self._read_auth_json(auth_file_path)
            tokens = dict(auth_json.get("tokens") or {})
            tokens["access_token"] = access_token
            tokens["refresh_token"] = next_refresh_token
            if id_token:
                tokens["id_token"] = id_token
            if resolved.account_id:
                tokens.setdefault("account_id", resolved.account_id)
            auth_json["tokens"] = tokens
            auth_json["last_refresh"] = datetime.now(timezone.utc).isoformat()
            auth_file_path.parent.mkdir(parents=True, exist_ok=True)
            auth_file_path.write_text(json.dumps(auth_json, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._resolve_codex_auth()

    def auth_summary(self) -> dict[str, Any]:
        resolved = self.resolve()
        return {
            "provider": self._llm_provider(),
            "api_key_env": self._primary_api_key_env(),
            "api_key_env_keys": self._api_key_env_keys(),
            "mode": resolved.mode,
            "source": resolved.source,
            "available": resolved.available,
            "reason": resolved.reason,
            "auth_file_path": str(resolved.auth_file_path) if resolved.auth_file_path else "",
            "chatgpt_base_url": str(resolved.chatgpt_base_url or ""),
            "has_api_key": bool(str(resolved.api_key or "").strip()),
            "has_access_token": bool(str(resolved.access_token or "").strip()),
            "has_refresh_token": bool(str(resolved.refresh_token or "").strip()),
            "has_account_id": bool(str(resolved.account_id or "").strip()),
            "last_refresh": str(resolved.last_refresh or ""),
        }

    def _resolve_api_key_auth(self) -> ResolvedOpenAIAuth:
        provider = self._llm_provider()
        if provider == "ollama":
            # Local Ollama deployments commonly run without credential checks.
            return ResolvedOpenAIAuth(
                mode="api_key",
                source="implicit:ollama_no_key",
                available=True,
                api_key=str(os.environ.get("VP_OLLAMA_API_KEY") or "ollama"),
            )

        for env_key in self._api_key_env_keys():
            api_key = str(os.environ.get(env_key) or "").strip()
            if not api_key:
                continue
            return ResolvedOpenAIAuth(
                mode="api_key",
                source=f"env:{env_key}",
                available=True,
                api_key=api_key,
            )

        auth_json = self._read_auth_json(self.config.codex_auth_file)
        for file_key in self._api_key_file_keys():
            file_api_key = str(auth_json.get(file_key) or "").strip()
            if not file_api_key:
                continue
            return ResolvedOpenAIAuth(
                mode="api_key",
                source=f"file:{self.config.codex_auth_file}:{file_key}",
                available=True,
                api_key=file_api_key,
                auth_file_path=self.config.codex_auth_file,
            )

        expected = self._primary_api_key_env()
        return ResolvedOpenAIAuth(
            mode="api_key",
            source="env",
            available=False,
            reason=f"API key is missing for provider '{provider}'. Expected env: {expected}.",
        )

    def _resolve_codex_auth(self) -> ResolvedOpenAIAuth:
        auth_file_path = self.config.codex_auth_file
        auth_json = self._read_auth_json(auth_file_path)
        if not auth_json:
            return ResolvedOpenAIAuth(
                mode="codex_auth",
                source=f"file:{auth_file_path}",
                available=False,
                reason=f"Codex auth file not found: {auth_file_path}",
                auth_file_path=auth_file_path,
                chatgpt_base_url=self.config.codex_chatgpt_base_url,
                refresh_url=self.config.codex_refresh_url,
                client_id=self.config.codex_client_id,
            )

        tokens = auth_json.get("tokens") or {}
        access_token = str(tokens.get("access_token") or "").strip()
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        account_id = str(tokens.get("account_id") or "").strip()
        id_token = str(tokens.get("id_token") or "").strip()
        available = bool((access_token or refresh_token) and account_id)
        reason = ""
        if not available:
            reason = "Codex auth.json is missing access/refresh token or account_id."
        return ResolvedOpenAIAuth(
            mode="codex_auth",
            source=f"file:{auth_file_path}",
            available=available,
            reason=reason,
            access_token=access_token or None,
            refresh_token=refresh_token or None,
            account_id=account_id or None,
            id_token=id_token or None,
            auth_file_path=auth_file_path,
            chatgpt_base_url=self.config.codex_chatgpt_base_url,
            refresh_url=self.config.codex_refresh_url,
            client_id=self.config.codex_client_id,
            last_refresh=str(auth_json.get("last_refresh") or "").strip() or None,
        )

    def _codex_refresh_needed(self, resolved: ResolvedOpenAIAuth) -> bool:
        if resolved.mode != "codex_auth":
            return False
        if not str(resolved.access_token or "").strip():
            return True
        last_refresh = _parse_iso_datetime(resolved.last_refresh)
        if last_refresh is None:
            return True
        deadline = datetime.now(timezone.utc) - timedelta(days=max(1, int(self.config.codex_refresh_interval_days)))
        return last_refresh < deadline

    def _read_auth_json(self, path: Path) -> dict[str, Any]:
        try:
            if not path.is_file():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
