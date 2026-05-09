from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("multi_agent_team.provider")

_PATCH_MARKER = "_vp_openai_compatible_stream_patch_installed"

_PRIVATE_NETWORK_PREFIXES = ("192.168.", "10.")
_OPENAI_COMPAT_ENV_KEYS = (
    "VP_OPENAI_COMPAT_API_KEY",
    "VP_OPENAI_COMPAT_BASE_URL",
    "VP_OPENAI_COMPAT_DEFAULT_MODEL",
    "VP_OPENAI_COMPAT_STREAM",
    "VP_OPENAI_COMPAT_MAX_OUTPUT_TOKENS",
    "VP_OPENAI_COMPAT_DEBUG_PAYLOAD",
)
_OLLAMA_ENV_KEYS = (
    "VP_OLLAMA_API_KEY",
    "VP_OLLAMA_BASE_URL",
    "VP_OLLAMA_DEFAULT_MODEL",
    "VP_OLLAMA_STREAM",
    "VP_OLLAMA_MAX_OUTPUT_TOKENS",
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    return value if value > 0 else default


def _has_any_env(keys: tuple[str, ...]) -> bool:
    return any(str(os.environ.get(key) or "").strip() for key in keys)


def is_local_base_url(base_url: str | None) -> bool:
    text = str(base_url or "").strip()
    if not text:
        return False
    try:
        host = (urlparse(text).hostname or "").strip().lower()
    except Exception:
        return False
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    if host.startswith(_PRIVATE_NETWORK_PREFIXES):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
            except Exception:
                return False
            return 16 <= second <= 31
    return False


def _provider_from_env() -> str:
    raw = str(os.environ.get("VP_LLM_PROVIDER") or os.environ.get("VP_MODEL_PROVIDER") or "").strip().lower()
    normalized = raw.replace("-", "_")
    if normalized:
        return normalized
    # Users often configure only the provider-specific env profile in `.env`.
    # In that case, infer the provider so VP_OPENAI_COMPAT_* and VP_OLLAMA_* are actually honored.
    if _has_any_env(_OPENAI_COMPAT_ENV_KEYS):
        return "openai_compatible"
    if _has_any_env(_OLLAMA_ENV_KEYS):
        return "ollama"
    return "openai"


def _provider_prefix(provider: str) -> str:
    if provider == "openai_compatible":
        return "VP_OPENAI_COMPAT"
    if provider == "ollama":
        return "VP_OLLAMA"
    return ""


def _coerce_base_url(kwargs: dict[str, Any]) -> str:
    for key in ("base_url", "openai_api_base", "api_base"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return str(os.environ.get("VP_OPENAI_COMPAT_BASE_URL") or os.environ.get("VP_OLLAMA_BASE_URL") or os.environ.get("VP_LLM_BASE_URL") or "")


def _coerce_model(kwargs: dict[str, Any]) -> str:
    for key in ("model", "model_name"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return str(os.environ.get("VP_OPENAI_COMPAT_DEFAULT_MODEL") or os.environ.get("VP_OLLAMA_DEFAULT_MODEL") or os.environ.get("VP_DEFAULT_MODEL") or "")


def _message_content_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += len(item)
            elif isinstance(item, dict):
                total += len(str(item.get("text") or item.get("content") or ""))
            else:
                total += len(str(item or ""))
        return total
    if content is None:
        return 0
    return len(str(content))


def message_stats(messages: list[Any] | tuple[Any, ...] | None) -> tuple[int, int]:
    rows = list(messages or [])
    total_chars = 0
    for message in rows:
        if isinstance(message, dict):
            total_chars += _message_content_chars(message.get("content"))
        else:
            total_chars += _message_content_chars(getattr(message, "content", ""))
    return len(rows), total_chars


def apply_local_provider_defaults(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    provider = _provider_from_env()
    prefix = _provider_prefix(provider)
    base_url = _coerce_base_url(kwargs)
    local_base_url = is_local_base_url(base_url)
    adjusted = dict(kwargs)

    diagnostics = {
        "provider": provider,
        "base_url": base_url,
        "model": _coerce_model(kwargs),
        "local_base_url": local_base_url,
        "stream_configured": None,
        "max_tokens_cap": None,
    }

    if not prefix:
        return adjusted, diagnostics

    stream_env = f"{prefix}_STREAM"
    default_stream = local_base_url
    stream_enabled = _env_bool(stream_env, default_stream)
    diagnostics["stream_configured"] = stream_enabled
    adjusted["streaming"] = bool(stream_enabled)
    if stream_enabled:
        # LangChain may disable streaming for some tool-call paths unless explicitly told otherwise.
        adjusted.setdefault("disable_streaming", False)

    max_tokens_env = f"{prefix}_MAX_OUTPUT_TOKENS"
    default_cap = 2048 if local_base_url else None
    max_tokens_cap = _env_int(max_tokens_env, default_cap)
    diagnostics["max_tokens_cap"] = max_tokens_cap
    if max_tokens_cap:
        current = adjusted.get("max_tokens")
        try:
            current_int = int(current) if current is not None else 0
        except Exception:
            current_int = 0
        if current_int <= 0 or current_int > max_tokens_cap:
            adjusted["max_tokens"] = int(max_tokens_cap)

    return adjusted, diagnostics


def provider_payload_summary(
    *,
    provider: str,
    base_url: str,
    model: str,
    stream: bool,
    max_tokens: Any,
    messages: list[Any] | tuple[Any, ...] | None,
) -> dict[str, Any]:
    messages_count, total_chars = message_stats(messages)
    return {
        "provider": str(provider or ""),
        "base_url": str(base_url or ""),
        "model": str(model or ""),
        "stream": bool(stream),
        "max_tokens": max_tokens,
        "messages_count": messages_count,
        "total_chars": total_chars,
    }


def _instance_value(instance: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(instance, name, default)
    except Exception:
        return default
    return value if value is not None else default


def _log_payload_summary(instance: Any, messages: list[Any] | tuple[Any, ...] | None, *, stream: bool) -> None:
    provider_meta = getattr(instance, "_vp_provider_meta", {}) or {}
    provider = str(provider_meta.get("provider") or _provider_from_env())
    prefix = _provider_prefix(provider)
    if prefix and not _env_bool(f"{prefix}_DEBUG_PAYLOAD", False):
        return
    base_url = str(provider_meta.get("base_url") or _instance_value(instance, "openai_api_base", "") or "")
    model = str(provider_meta.get("model") or _instance_value(instance, "model_name", "") or _instance_value(instance, "model", "") or "")
    max_tokens = provider_meta.get("max_tokens")
    if max_tokens is None:
        max_tokens = _instance_value(instance, "max_tokens", None)
    summary = provider_payload_summary(
        provider=provider,
        base_url=base_url,
        model=model,
        stream=stream,
        max_tokens=max_tokens,
        messages=messages,
    )
    logger.info(
        "provider payload summary: provider=%s base_url=%s model=%s stream=%s max_tokens=%s messages_count=%s total_chars=%s",
        summary["provider"],
        summary["base_url"],
        summary["model"],
        summary["stream"],
        summary["max_tokens"],
        summary["messages_count"],
        summary["total_chars"],
    )


def install_langchain_openai_patch() -> bool:
    try:
        from langchain_openai import ChatOpenAI
    except Exception:
        return False

    if getattr(ChatOpenAI, _PATCH_MARKER, False):
        return True

    original_init = ChatOpenAI.__init__
    original_generate = getattr(ChatOpenAI, "_generate", None)
    original_stream = getattr(ChatOpenAI, "_stream", None)

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        adjusted_kwargs, diagnostics = apply_local_provider_defaults(kwargs)
        original_init(self, *args, **adjusted_kwargs)
        meta = {
            "provider": diagnostics.get("provider"),
            "base_url": diagnostics.get("base_url") or _coerce_base_url(adjusted_kwargs),
            "model": diagnostics.get("model") or _coerce_model(adjusted_kwargs),
            "stream": adjusted_kwargs.get("streaming"),
            "max_tokens": adjusted_kwargs.get("max_tokens"),
            "local_base_url": diagnostics.get("local_base_url"),
            "max_tokens_cap": diagnostics.get("max_tokens_cap"),
        }
        try:
            object.__setattr__(self, "_vp_provider_meta", meta)
        except Exception:
            pass

    def patched_generate(self: Any, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        _log_payload_summary(self, messages, stream=False)
        return original_generate(self, messages, *args, **kwargs)

    def patched_stream(self: Any, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        _log_payload_summary(self, messages, stream=True)
        yield from original_stream(self, messages, *args, **kwargs)

    ChatOpenAI.__init__ = patched_init
    if callable(original_generate):
        ChatOpenAI._generate = patched_generate
    if callable(original_stream):
        ChatOpenAI._stream = patched_stream
    setattr(ChatOpenAI, _PATCH_MARKER, True)
    return True
