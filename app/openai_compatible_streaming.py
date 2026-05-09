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


def _chunk_content_len(chunk: Any) -> tuple[int, str]:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return len(content), "content_str"
    if isinstance(content, list):
        total = 0
        fields: list[str] = []
        for item in content:
            if isinstance(item, str):
                total += len(item)
                fields.append("str")
            elif isinstance(item, dict):
                for key in ("text", "content", "reasoning"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        total += len(value)
                        fields.append(key)
            else:
                text = str(item or "")
                total += len(text)
                if text:
                    fields.append(type(item).__name__)
        return total, "+".join(fields[:4]) or "content_list_empty"
    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        reasoning = additional_kwargs.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            return len(reasoning), "additional_kwargs.reasoning"
    return len(str(content or "")), type(content).__name__


def message_stats(messages: list[Any] | tuple[Any, ...] | None) -> tuple[int, int]:
    rows = list(messages or [])
    total_chars = 0
    for message in rows:
        if isinstance(message, dict):
            total_chars += _message_content_chars(message.get("content"))
        else:
            total_chars += _message_content_chars(getattr(message, "content", ""))
    return len(rows), total_chars


def debug_payload_enabled(provider: str | None = None) -> bool:
    normalized_provider = str(provider or _provider_from_env() or "").strip()
    prefix = _provider_prefix(normalized_provider)
    if prefix:
        return _env_bool(f"{prefix}_DEBUG_PAYLOAD", False)
    return False


def _emit_debug_line(message: str) -> None:
    logger.warning(message)
    # Some local uvicorn/logging setups do not show non-root package loggers.
    # Print only when the explicit debug flag is enabled; never print prompt text.
    try:
        print(message, flush=True)
    except Exception:
        pass


def log_provider_config_summary(
    stage: str,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    stream: Any = None,
    max_tokens: Any = None,
    local_base_url: Any = None,
) -> None:
    resolved_provider = str(provider or _provider_from_env() or "").strip()
    if not debug_payload_enabled(resolved_provider):
        return
    resolved_base_url = str(
        base_url
        or os.environ.get("VP_OPENAI_COMPAT_BASE_URL")
        or os.environ.get("VP_OLLAMA_BASE_URL")
        or os.environ.get("VP_LLM_BASE_URL")
        or ""
    )
    resolved_model = str(
        model
        or os.environ.get("VP_OPENAI_COMPAT_DEFAULT_MODEL")
        or os.environ.get("VP_OLLAMA_DEFAULT_MODEL")
        or os.environ.get("VP_DEFAULT_MODEL")
        or ""
    )
    local_flag = is_local_base_url(resolved_base_url) if local_base_url is None else bool(local_base_url)
    _emit_debug_line(
        "provider config summary: "
        f"stage={stage} provider={resolved_provider} base_url={resolved_base_url} "
        f"model={resolved_model} stream={stream} max_tokens={max_tokens} local_base_url={local_flag}"
    )


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
    stage: str,
    provider: str,
    base_url: str,
    model: str,
    stream: bool,
    max_tokens: Any,
    messages: list[Any] | tuple[Any, ...] | None,
) -> dict[str, Any]:
    messages_count, total_chars = message_stats(messages)
    return {
        "stage": str(stage or ""),
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


def _log_payload_summary(
    instance: Any,
    messages: list[Any] | tuple[Any, ...] | None,
    *,
    stream: bool,
    stage: str,
) -> None:
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
        stage=stage,
        provider=provider,
        base_url=base_url,
        model=model,
        stream=stream,
        max_tokens=max_tokens,
        messages=messages,
    )
    _emit_debug_line(
        "provider payload summary: "
        f"stage={summary['stage']} provider={summary['provider']} base_url={summary['base_url']} "
        f"model={summary['model']} stream={summary['stream']} max_tokens={summary['max_tokens']} "
        f"messages_count={summary['messages_count']} total_chars={summary['total_chars']}"
    )


def _log_chunk_summary(*, provider: str, chunk_index: int, delta_chars: int, field: str) -> None:
    prefix = _provider_prefix(provider)
    if prefix and not _env_bool(f"{prefix}_DEBUG_PAYLOAD", False):
        return
    if chunk_index <= 8 or chunk_index in {16, 32, 64, 128, 256, 512, 1024}:
        _emit_debug_line(
            "provider chunk summary: "
            f"provider={provider} chunk_index={chunk_index} delta_chars={delta_chars} field={field}"
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
        log_provider_config_summary(
            "chatopenai.init.before",
            provider=str(diagnostics.get("provider") or ""),
            base_url=str(diagnostics.get("base_url") or _coerce_base_url(adjusted_kwargs)),
            model=str(diagnostics.get("model") or _coerce_model(adjusted_kwargs)),
            stream=adjusted_kwargs.get("streaming"),
            max_tokens=adjusted_kwargs.get("max_tokens"),
            local_base_url=diagnostics.get("local_base_url"),
        )
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
        log_provider_config_summary(
            "chatopenai.init.after",
            provider=str(meta.get("provider") or ""),
            base_url=str(meta.get("base_url") or ""),
            model=str(meta.get("model") or ""),
            stream=meta.get("stream"),
            max_tokens=meta.get("max_tokens"),
            local_base_url=meta.get("local_base_url"),
        )

    def patched_generate(self: Any, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        _log_payload_summary(self, messages, stream=False, stage="chatopenai._generate")
        return original_generate(self, messages, *args, **kwargs)

    def patched_stream(self: Any, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        provider_meta = getattr(self, "_vp_provider_meta", {}) or {}
        provider = str(provider_meta.get("provider") or _provider_from_env())
        _log_payload_summary(self, messages, stream=True, stage="chatopenai._stream")
        chunk_count = 0
        text_char_count = 0
        for chunk in original_stream(self, messages, *args, **kwargs):
            chunk_count += 1
            delta_chars, field = _chunk_content_len(chunk)
            text_char_count += max(0, int(delta_chars or 0))
            _log_chunk_summary(provider=provider, chunk_index=chunk_count, delta_chars=delta_chars, field=field)
            yield chunk
        prefix = _provider_prefix(provider)
        if not prefix or _env_bool(f"{prefix}_DEBUG_PAYLOAD", False):
            _emit_debug_line(
                "provider stream summary: "
                f"provider={provider} chunks={chunk_count} text_chars={text_char_count}"
            )

    ChatOpenAI.__init__ = patched_init
    if callable(original_generate):
        ChatOpenAI._generate = patched_generate
    if callable(original_stream):
        ChatOpenAI._stream = patched_stream
    setattr(ChatOpenAI, _PATCH_MARKER, True)
    return True
