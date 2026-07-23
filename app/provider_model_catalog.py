from __future__ import annotations

import json
import ssl
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from app.config import AppConfig
from app.openai_auth import OpenAIAuthManager


class ProviderModelRefreshError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_models(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        model = str(value or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        result.append(model)
    return result


def _model_ids_from_payload(payload: Any) -> list[str]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (
                payload.get(key)
                for key in ("data", "models", "items")
                if isinstance(payload.get(key), list)
            ),
            [],
        )
    else:
        rows = []
    values: list[str] = []
    for row in rows:
        if isinstance(row, str):
            values.append(row)
            continue
        if not isinstance(row, dict):
            continue
        values.append(str(row.get("id") or row.get("model") or row.get("name") or ""))
    return _dedupe_models(values)


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _model_profiles_from_payload(payload: Any) -> dict[str, dict[str, int]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (payload.get(key) for key in ("data", "models", "items") if isinstance(payload.get(key), list)),
            [],
        )
    else:
        rows = []
    profiles: dict[str, dict[str, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or row.get("model") or row.get("name") or "").strip()
        if not model_id:
            continue
        truncation = row.get("truncation_policy") if isinstance(row.get("truncation_policy"), dict) else {}
        profile = {
            "operational_context_window": _positive_int(
                row.get("operational_context_window")
                or row.get("context_window")
                or row.get("context_window_tokens")
            ),
            "model_max_context_window": _positive_int(
                row.get("max_context_window")
                or row.get("model_max_context_window")
                or row.get("max_context_window_tokens")
            ),
            "auto_compact_token_limit": _positive_int(row.get("auto_compact_token_limit")),
            "tool_output_token_limit": _positive_int(
                row.get("tool_output_token_limit") or truncation.get("limit")
            ),
        }
        cleaned = {key: value for key, value in profile.items() if value > 0}
        if cleaned:
            profiles[model_id] = cleaned
    return profiles


def _models_endpoint(config: AppConfig) -> str:
    base_url = str(config.openai_base_url or "").strip()
    if not base_url:
        if str(config.llm_provider or "").strip().lower() == "openai":
            base_url = "https://api.openai.com/v1"
        else:
            raise ProviderModelRefreshError("The active provider has no configured base URL.")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderModelRefreshError("The active provider base URL is invalid.")
    path = parsed.path.rstrip("/")
    if not path.lower().endswith("/models"):
        path = f"{path}/models"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ""))


def fetch_provider_models(config: AppConfig, *, timeout_sec: float = 20.0) -> Any:
    auth = OpenAIAuthManager(config).require()
    endpoint = _models_endpoint(config)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {str(auth.api_key or '')}",
        "User-Agent": "VintageProgrammer/model-catalog",
    }
    if str(config.llm_provider or "").strip().lower() == "openai_compatible":
        headers["api-key"] = str(auth.api_key or "")
    request = Request(endpoint, headers=headers, method="GET")
    ca_cert_path = str(config.openai_ca_cert_path or "").strip()
    try:
        ssl_context = ssl.create_default_context(cafile=ca_cert_path) if ca_cert_path else ssl.create_default_context()
    except Exception as exc:
        raise ProviderModelRefreshError(f"Custom CA configuration is invalid: {type(exc).__name__}.") from exc
    try:
        with urlopen(request, timeout=max(1.0, float(timeout_sec)), context=ssl_context) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise ProviderModelRefreshError(f"Provider model endpoint returned HTTP {int(exc.code)}.") from exc
    except URLError as exc:
        raise ProviderModelRefreshError(f"Provider model endpoint is unavailable: {type(exc.reason).__name__}.") from exc
    except TimeoutError as exc:
        raise ProviderModelRefreshError("Provider model endpoint timed out.") from exc
    except json.JSONDecodeError as exc:
        raise ProviderModelRefreshError("Provider model endpoint returned invalid JSON.") from exc
    models = _model_ids_from_payload(payload)
    if not models:
        raise ProviderModelRefreshError("Provider model endpoint returned no model identifiers.")
    # Preserve optional capability metadata when an OpenAI-compatible gateway
    # exposes it. Standard /models responses still keep the legacy list shape.
    return payload if _model_profiles_from_payload(payload) else models


class ProviderModelCatalog:
    def __init__(
        self,
        path: Path,
        *,
        fetcher: Callable[[AppConfig], Any] | None = None,
    ) -> None:
        self.path = path.expanduser().resolve()
        self._fetcher = fetcher or fetch_provider_models
        self._lock = threading.RLock()
        self._payload = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        providers = payload.get("providers") if isinstance(payload, dict) else {}
        return {
            "schema_version": 2,
            "providers": dict(providers) if isinstance(providers, dict) else {},
        }

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def models_for(self, provider: str) -> list[str]:
        key = str(provider or "").strip().lower()
        with self._lock:
            row = (self._payload.get("providers") or {}).get(key)
            if not isinstance(row, dict):
                return []
            return _dedupe_models(list(row.get("models") or []))

    def profile_for(self, provider: str, model: str) -> dict[str, int]:
        key = str(provider or "").strip().lower()
        model_id = str(model or "").strip()
        with self._lock:
            row = (self._payload.get("providers") or {}).get(key)
            profiles = row.get("profiles") if isinstance(row, dict) else {}
            profile = profiles.get(model_id) if isinstance(profiles, dict) else {}
            return {
                str(name): int(value)
                for name, value in dict(profile or {}).items()
                if _positive_int(value) > 0
            }

    def refresh(self, provider: str, config: AppConfig) -> dict[str, Any]:
        key = str(provider or "").strip().lower()
        if not key:
            raise ProviderModelRefreshError("Provider is required.")
        fetched = self._fetcher(config)
        if isinstance(fetched, dict):
            models = _model_ids_from_payload(fetched)
            profiles = _model_profiles_from_payload(fetched)
        else:
            models = _dedupe_models(list(fetched or []))
            profiles = {}
        if not models:
            raise ProviderModelRefreshError("Provider model endpoint returned no model identifiers.")
        updated_at = _utc_now()
        with self._lock:
            providers = self._payload.setdefault("providers", {})
            providers[key] = {
                "models": models,
                "profiles": {model: profiles[model] for model in models if model in profiles},
                "updated_at": updated_at,
            }
            self._save_locked()
        return {
            "provider": key,
            "models": models,
            "profiles": {model: profiles[model] for model in models if model in profiles},
            "updated_at": updated_at,
        }


__all__ = [
    "ProviderModelCatalog",
    "ProviderModelRefreshError",
    "fetch_provider_models",
    "_model_profiles_from_payload",
]
