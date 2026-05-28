from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from app.config import AppConfig


def normalize_model_for_auth_mode(model: str, auth_mode: str) -> str:
    _ = auth_mode
    return str(model or "").strip()


@dataclass(slots=True)
class ResolvedOpenAIAuth:
    mode: str
    source: str
    available: bool
    reason: str = ""
    api_key: str | None = None


class OpenAIAuthManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _llm_provider(self) -> str:
        provider = str(getattr(self.config, "llm_provider", "") or "").strip().lower()
        return provider or "openai"

    def _api_key_env_keys(self) -> list[str]:
        keys = getattr(self.config, "llm_api_key_env_keys", [])
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
        resolved = self._resolve_api_key_auth()
        if resolved.available:
            return resolved
        return ResolvedOpenAIAuth(
            mode="unconfigured",
            source="env",
            available=False,
            reason=(
                f"API key is missing for provider '{provider}'. "
                f"Set {self._primary_api_key_env()} in env or .env."
            ),
        )

    def require(self, *, allow_refresh: bool = True) -> ResolvedOpenAIAuth:
        _ = allow_refresh
        resolved = self.resolve()
        if not resolved.available:
            raise RuntimeError(resolved.reason or "LLM credentials are not available.")
        return resolved

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
            "has_api_key": bool(str(resolved.api_key or "").strip()),
        }

    def _resolve_api_key_auth(self) -> ResolvedOpenAIAuth:
        provider = self._llm_provider()
        if provider == "ollama":
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

        expected = self._primary_api_key_env()
        return ResolvedOpenAIAuth(
            mode="api_key",
            source="env",
            available=False,
            reason=f"API key is missing for provider '{provider}'. Expected env: {expected}.",
        )


__all__ = [
    "OpenAIAuthManager",
    "ResolvedOpenAIAuth",
    "normalize_model_for_auth_mode",
]
