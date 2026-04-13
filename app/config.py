from __future__ import annotations

import os
import platform as py_platform
import re
from dataclasses import dataclass, replace
from pathlib import Path


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _split_paths(raw: str) -> list[str]:
    if not raw:
        return []
    merged = raw.replace(",", os.pathsep)
    return [item.strip() for item in merged.split(os.pathsep) if item.strip()]


_PRIMARY_ENV_PREFIX = "VP_"


def _env_key_candidates(key: str) -> list[str]:
    normalized = str(key or "").strip()
    if not normalized:
        return []
    upper = normalized.upper()
    if upper.startswith(_PRIMARY_ENV_PREFIX):
        return [upper]
    return [normalized]


def _expand_env_keys(keys: tuple[str, ...] | list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for candidate in _env_key_candidates(key):
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded


def _env(*keys: str, default: str | None = None) -> str | None:
    for key in _expand_env_keys(keys):
        if key in os.environ:
            return os.environ.get(key)
    return default


def _env_is_set(*keys: str) -> bool:
    return any(key in os.environ for key in _expand_env_keys(keys))


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


_LLM_PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    "openai": {
        "api_key_env": "VP_OPENAI_API_KEY",
        "default_model": "gpt-5.1-chat",
        "model_options": ["gpt-5.1-chat", "gpt-5.1", "gpt-5-mini", "gpt-4.1"],
        "base_url": "",
        "use_responses_api": False,
    },
    "openai_compatible": {
        "api_key_env": "VP_OPENAI_COMPAT_API_KEY",
        "default_model": "gpt-5.1-chat",
        "model_options": ["gpt-5.1-chat", "gpt-5.1", "gpt-5-mini", "gpt-4.1"],
        "base_url": "",
        "use_responses_api": False,
    },
    "deepseek": {
        "api_key_env": "VP_DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "model_options": ["deepseek-chat", "deepseek-reasoner"],
        "base_url": "https://api.deepseek.com/v1",
        "use_responses_api": False,
    },
    "qwen": {
        "api_key_env": "VP_DASHSCOPE_API_KEY",
        "default_model": "qwen-plus",
        "model_options": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "use_responses_api": False,
    },
    "moonshot": {
        "api_key_env": "VP_MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-8k",
        "model_options": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "base_url": "https://api.moonshot.cn/v1",
        "use_responses_api": False,
    },
    "openrouter": {
        "api_key_env": "VP_OPENROUTER_API_KEY",
        "default_model": "openai/gpt-5-mini",
        "model_options": [
            "openai/gpt-5-mini",
            "google/gemma-4-31b-it:free",
            "anthropic/claude-3.7-sonnet",
            "google/gemini-2.5-pro-preview",
        ],
        "base_url": "https://openrouter.ai/api/v1",
        "use_responses_api": False,
    },
    "groq": {
        "api_key_env": "VP_GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "model_options": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "base_url": "https://api.groq.com/openai/v1",
        "use_responses_api": False,
    },
    "ollama": {
        "api_key_env": "VP_OLLAMA_API_KEY",
        "default_model": "llama3.2",
        "model_options": ["llama3.2", "qwen2.5-coder:7b", "deepseek-r1:7b"],
        "base_url": "http://127.0.0.1:11434/v1",
        "use_responses_api": False,
    },
}

_LLM_PROVIDER_ALIASES = {
    "default": "openai",
    "openai-compatible": "openai_compatible",
}

_LLM_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "openai_compatible": "OpenAI-compatible",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "moonshot": "Moonshot",
    "groq": "Groq",
    "ollama": "Ollama",
}


def _normalize_llm_provider(raw: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    if not normalized:
        return "openai"
    return _LLM_PROVIDER_ALIASES.get(normalized, normalized)


def _provider_env_token(provider: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(provider or "").strip().lower()).strip("_")
    if not token:
        return "OPENAI"
    return token.upper()


def _provider_specific_api_key_env_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_API_KEY"],
        "openai_compatible": ["VP_OPENAI_COMPAT_API_KEY"],
        "openrouter": ["VP_OPENROUTER_API_KEY"],
        "deepseek": ["VP_DEEPSEEK_API_KEY"],
        "qwen": ["VP_DASHSCOPE_API_KEY"],
        "moonshot": ["VP_MOONSHOT_API_KEY"],
        "groq": ["VP_GROQ_API_KEY"],
        "ollama": ["VP_OLLAMA_API_KEY"],
    }
    return list(mapping.get(provider, []))


def _provider_specific_base_url_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_BASE_URL"],
        "openai_compatible": ["VP_OPENAI_COMPAT_BASE_URL"],
        "openrouter": ["VP_OPENROUTER_BASE_URL"],
        "deepseek": ["VP_DEEPSEEK_BASE_URL"],
        "qwen": ["VP_DASHSCOPE_BASE_URL"],
        "moonshot": ["VP_MOONSHOT_BASE_URL"],
        "groq": ["VP_GROQ_BASE_URL"],
        "ollama": ["VP_OLLAMA_BASE_URL"],
    }
    return list(mapping.get(provider, []))


def _provider_specific_ca_cert_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_CA_CERT_PATH"],
        "openai_compatible": ["VP_OPENAI_COMPAT_CA_CERT_PATH"],
        "openrouter": ["VP_OPENROUTER_CA_CERT_PATH"],
        "deepseek": ["VP_DEEPSEEK_CA_CERT_PATH"],
        "qwen": ["VP_DASHSCOPE_CA_CERT_PATH"],
        "moonshot": ["VP_MOONSHOT_CA_CERT_PATH"],
        "groq": ["VP_GROQ_CA_CERT_PATH"],
        "ollama": ["VP_OLLAMA_CA_CERT_PATH"],
    }
    return list(mapping.get(provider, []))


def _provider_specific_temperature_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_TEMPERATURE"],
        "openai_compatible": ["VP_OPENAI_COMPAT_TEMPERATURE"],
        "openrouter": ["VP_OPENROUTER_TEMPERATURE"],
        "deepseek": ["VP_DEEPSEEK_TEMPERATURE"],
        "qwen": ["VP_DASHSCOPE_TEMPERATURE"],
        "moonshot": ["VP_MOONSHOT_TEMPERATURE"],
        "groq": ["VP_GROQ_TEMPERATURE"],
        "ollama": ["VP_OLLAMA_TEMPERATURE"],
    }
    return list(mapping.get(provider, []))


def _provider_specific_responses_api_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_USE_RESPONSES_API"],
        "openai_compatible": ["VP_OPENAI_COMPAT_USE_RESPONSES_API"],
        "openrouter": ["VP_OPENROUTER_USE_RESPONSES_API"],
        "deepseek": ["VP_DEEPSEEK_USE_RESPONSES_API"],
        "qwen": ["VP_DASHSCOPE_USE_RESPONSES_API"],
        "moonshot": ["VP_MOONSHOT_USE_RESPONSES_API"],
        "groq": ["VP_GROQ_USE_RESPONSES_API"],
        "ollama": ["VP_OLLAMA_USE_RESPONSES_API"],
    }
    return list(mapping.get(provider, []))


def _provider_specific_default_model_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_DEFAULT_MODEL"],
        "openai_compatible": ["VP_OPENAI_COMPAT_DEFAULT_MODEL"],
        "openrouter": ["VP_OPENROUTER_DEFAULT_MODEL"],
        "deepseek": ["VP_DEEPSEEK_DEFAULT_MODEL"],
        "qwen": ["VP_DASHSCOPE_DEFAULT_MODEL"],
        "moonshot": ["VP_MOONSHOT_DEFAULT_MODEL"],
        "groq": ["VP_GROQ_DEFAULT_MODEL"],
        "ollama": ["VP_OLLAMA_DEFAULT_MODEL"],
    }
    token = _provider_env_token(provider)
    return _dedupe_keep_order([*mapping.get(provider, []), f"VP_PROVIDER_{token}_DEFAULT_MODEL"])


def _provider_specific_model_fallback_keys(provider: str) -> list[str]:
    mapping = {
        "openai": ["VP_OPENAI_MODEL_FALLBACKS"],
        "openai_compatible": ["VP_OPENAI_COMPAT_MODEL_FALLBACKS"],
        "openrouter": ["VP_OPENROUTER_MODEL_FALLBACKS"],
        "deepseek": ["VP_DEEPSEEK_MODEL_FALLBACKS"],
        "qwen": ["VP_DASHSCOPE_MODEL_FALLBACKS"],
        "moonshot": ["VP_MOONSHOT_MODEL_FALLBACKS"],
        "groq": ["VP_GROQ_MODEL_FALLBACKS"],
        "ollama": ["VP_OLLAMA_MODEL_FALLBACKS"],
    }
    token = _provider_env_token(provider)
    return _dedupe_keep_order([*mapping.get(provider, []), f"VP_PROVIDER_{token}_MODEL_FALLBACKS"])


def _supports_codex_auth(provider: str, base_url: str | None) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    normalized_base = str(base_url or "").strip().rstrip("/").lower()
    if normalized_provider != "openai":
        return False
    if not normalized_base:
        return True
    return normalized_base in {"https://api.openai.com/v1", "https://api.openai.com"}


def _has_any_env_value(keys: list[str]) -> bool:
    return any(str(os.environ.get(key) or "").strip() for key in keys)


def _should_dotenv_override(key: str) -> bool:
    normalized = key.strip().upper()
    if normalized.startswith(_PRIMARY_ENV_PREFIX):
        return True
    return normalized in {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"}


def _load_dotenv_if_present() -> None:
    skip_raw = str(_env("VP_SKIP_DOTENV", default="") or "").strip().lower()
    if skip_raw in {"1", "true", "yes", "on"}:
        return

    candidates = [
        (Path.cwd() / ".env").resolve(),
        (Path(__file__).resolve().parent.parent / ".env").resolve(),
    ]

    seen: set[str] = set()
    for dotenv_path in candidates:
        key = str(dotenv_path)
        if key in seen or not dotenv_path.is_file():
            continue
        seen.add(key)

        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue

            env_key, env_value = line.split("=", 1)
            env_key = env_key.strip()
            env_value = env_value.strip()
            if not env_key:
                continue

            env_value = _strip_optional_quotes(env_value)
            if " #" in env_value:
                env_value = env_value.split(" #", 1)[0].rstrip()

            if _should_dotenv_override(env_key):
                os.environ[env_key] = env_value
            else:
                os.environ.setdefault(env_key, env_value)


@dataclass(slots=True)
class AppConfig:
    workspace_root: Path
    modules_dir: Path
    capability_modules: list[str]
    runtime_dir: Path
    evolution_dir: Path
    active_manifest_path: Path
    shadow_manifest_path: Path
    rollback_pointer_path: Path
    module_health_path: Path
    overlay_profile_path: Path
    evolution_logs_dir: Path
    projects_registry_path: Path
    sessions_dir: Path
    uploads_dir: Path
    shadow_logs_dir: Path
    token_stats_path: Path
    allowed_roots: list[Path]
    workspace_sibling_root: Path | None
    allow_workspace_sibling_access: bool
    default_extra_allowed_roots: list[Path]
    extra_allowed_roots_source: str
    platform_name: str
    allow_any_path: bool
    web_allowed_domains: list[str]
    web_allow_all_domains: bool
    web_fetch_timeout_sec: int
    web_fetch_max_chars: int
    web_skip_tls_verify: bool
    web_ca_cert_path: str | None
    llm_provider: str
    llm_primary_api_key_env: str
    llm_api_key_env_keys: list[str]
    llm_auth_file_api_key_keys: list[str]
    llm_supports_codex_auth: bool
    openai_base_url: str | None
    openai_ca_cert_path: str | None
    openai_temperature: float | None
    openai_use_responses_api: bool
    codex_home: Path
    codex_auth_file: Path
    codex_chatgpt_base_url: str
    codex_refresh_url: str
    codex_client_id: str
    codex_refresh_interval_days: int
    default_model: str
    model_options: list[str]
    model_fallbacks: list[str]
    model_cooldown_base_sec: int
    model_cooldown_max_sec: int
    summary_model: str
    system_prompt: str
    summary_trigger_turns: int
    max_context_turns: int
    max_attachment_chars: int
    max_upload_mb: int
    tool_result_soft_trim_chars: int
    tool_result_hard_clear_chars: int
    tool_result_head_chars: int
    tool_result_tail_chars: int
    tool_context_prune_keep_last: int
    max_concurrent_runs: int
    run_queue_wait_notice_ms: int
    execution_mode: str
    docker_bin: str
    docker_image: str
    docker_network: str
    docker_memory: str
    docker_cpus: str
    docker_pids_limit: int
    docker_container_prefix: str
    enable_session_tools: bool
    enable_shadow_logging: bool
    allowed_commands: list[str]


def normalize_llm_provider_name(raw: str | None) -> str:
    return _normalize_llm_provider(raw)


def provider_display_name(provider: str) -> str:
    normalized = _normalize_llm_provider(provider)
    return _LLM_PROVIDER_LABELS.get(normalized, normalized.replace("_", " ").title())


def _resolve_provider_runtime_settings(
    provider: str,
    *,
    active_provider: str | None = None,
) -> dict[str, object]:
    normalized_provider = _normalize_llm_provider(provider)
    llm_provider_preset = _LLM_PROVIDER_PRESETS.get(normalized_provider, {})
    llm_provider_token = _provider_env_token(normalized_provider)

    preset_api_key_env = str(llm_provider_preset.get("api_key_env") or "").strip()
    llm_api_key_env_keys = _dedupe_keep_order(
        [
            *_provider_specific_api_key_env_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_API_KEY",
            "VP_LLM_API_KEY",
            preset_api_key_env,
        ]
    )
    llm_primary_api_key_env = llm_api_key_env_keys[0] if llm_api_key_env_keys else "VP_LLM_API_KEY"
    llm_auth_file_api_key_keys = list(llm_api_key_env_keys)

    llm_base_url_keys = [
        *_provider_specific_base_url_keys(normalized_provider),
        f"VP_PROVIDER_{llm_provider_token}_BASE_URL",
        "VP_LLM_BASE_URL",
    ]
    openai_base_url = (
        _env(*llm_base_url_keys, default=str(llm_provider_preset.get("base_url") or "")) or ""
    ).strip() or None
    llm_supports_codex_auth = _supports_codex_auth(normalized_provider, openai_base_url)

    llm_ca_cert_keys = [
        *_provider_specific_ca_cert_keys(normalized_provider),
        f"VP_PROVIDER_{llm_provider_token}_CA_CERT_PATH",
        "VP_LLM_CA_CERT_PATH",
        "VP_CA_CERT_PATH",
        "SSL_CERT_FILE",
    ]
    openai_ca_cert_path = (_env(*llm_ca_cert_keys, default="") or "").strip() or None

    llm_temperature_keys = [
        *_provider_specific_temperature_keys(normalized_provider),
        f"VP_PROVIDER_{llm_provider_token}_TEMPERATURE",
        "VP_LLM_TEMPERATURE",
        "VP_TEMPERATURE",
    ]
    openai_temperature_raw = (_env(*llm_temperature_keys, default="") or "").strip()
    openai_temperature: float | None = None
    if openai_temperature_raw:
        try:
            openai_temperature = float(openai_temperature_raw)
        except Exception:
            openai_temperature = None

    default_use_responses = "true" if bool(llm_provider_preset.get("use_responses_api")) else "false"
    llm_use_responses_keys = [
        *_provider_specific_responses_api_keys(normalized_provider),
        f"VP_PROVIDER_{llm_provider_token}_USE_RESPONSES_API",
        "VP_LLM_USE_RESPONSES_API",
        "VP_USE_RESPONSES_API",
    ]
    use_responses_raw = (
        _env(*llm_use_responses_keys, default=default_use_responses) or default_use_responses
    ).strip().lower()
    openai_use_responses_api = use_responses_raw in {"1", "true", "yes", "on"}

    provider_default_model = (
        str(llm_provider_preset.get("default_model") or "gpt-5.1-chat").strip() or "gpt-5.1-chat"
    )
    include_global_model_keys = normalized_provider == _normalize_llm_provider(active_provider)
    default_model_keys = list(_provider_specific_default_model_keys(normalized_provider))
    fallback_model_keys = list(_provider_specific_model_fallback_keys(normalized_provider))
    if include_global_model_keys:
        default_model_keys.append("VP_DEFAULT_MODEL")
        fallback_model_keys.append("VP_MODEL_FALLBACKS")
    resolved_default_model = (
        _env(*default_model_keys, default=provider_default_model)
        or provider_default_model
    ).strip() or provider_default_model
    model_fallbacks = _split_csv(_env(*fallback_model_keys, default="") or "")
    provider_model_options = [
        str(item or "").strip()
        for item in list(llm_provider_preset.get("model_options") or [])
        if str(item or "").strip()
    ]
    resolved_model_options = _dedupe_keep_order(
        [resolved_default_model, *model_fallbacks, *provider_model_options]
    )

    explicit_env_keys = _dedupe_keep_order(
        [
            *_provider_specific_api_key_env_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_API_KEY",
            *_provider_specific_base_url_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_BASE_URL",
            *_provider_specific_ca_cert_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_CA_CERT_PATH",
            *_provider_specific_temperature_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_TEMPERATURE",
            *_provider_specific_responses_api_keys(normalized_provider),
            f"VP_PROVIDER_{llm_provider_token}_USE_RESPONSES_API",
            *_provider_specific_default_model_keys(normalized_provider),
            *_provider_specific_model_fallback_keys(normalized_provider),
            preset_api_key_env,
        ]
    )
    explicit_current_provider = (
        _env_is_set("VP_LLM_PROVIDER", "VP_MODEL_PROVIDER")
        and _normalize_llm_provider(_env("VP_LLM_PROVIDER", "VP_MODEL_PROVIDER", default="") or "") == normalized_provider
    )
    configured = explicit_current_provider or _has_any_env_value(explicit_env_keys)

    return {
        "provider": normalized_provider,
        "label": provider_display_name(normalized_provider),
        "llm_primary_api_key_env": llm_primary_api_key_env,
        "llm_api_key_env_keys": llm_api_key_env_keys,
        "llm_auth_file_api_key_keys": llm_auth_file_api_key_keys,
        "llm_supports_codex_auth": llm_supports_codex_auth,
        "openai_base_url": openai_base_url,
        "openai_ca_cert_path": openai_ca_cert_path,
        "openai_temperature": openai_temperature,
        "openai_use_responses_api": openai_use_responses_api,
        "default_model": resolved_default_model,
        "model_options": resolved_model_options,
        "model_fallbacks": model_fallbacks,
        "configured": configured,
    }


def list_provider_profiles(base_config: AppConfig) -> list[dict[str, object]]:
    active_provider = _normalize_llm_provider(getattr(base_config, "llm_provider", "") or "openai")
    profiles: list[dict[str, object]] = []
    seen: set[str] = set()
    for provider in _LLM_PROVIDER_PRESETS:
        resolved = _resolve_provider_runtime_settings(provider, active_provider=active_provider)
        normalized = str(resolved.get("provider") or "").strip()
        if not normalized or normalized in seen:
            continue
        if not bool(resolved.get("configured")) and normalized != active_provider:
            continue
        seen.add(normalized)
        profiles.append(
            {
                "provider": normalized,
                "label": str(resolved.get("label") or provider_display_name(normalized)),
                "default_model": str(resolved.get("default_model") or ""),
                "model_options": list(resolved.get("model_options") or []),
            }
        )
    if not profiles:
        resolved = _resolve_provider_runtime_settings(active_provider, active_provider=active_provider)
        profiles.append(
            {
                "provider": active_provider,
                "label": str(resolved.get("label") or provider_display_name(active_provider)),
                "default_model": str(resolved.get("default_model") or ""),
                "model_options": list(resolved.get("model_options") or []),
            }
        )
    return profiles


def build_provider_config(base_config: AppConfig, provider: str) -> AppConfig:
    resolved = _resolve_provider_runtime_settings(
        provider,
        active_provider=getattr(base_config, "llm_provider", "") or provider,
    )
    return replace(
        base_config,
        llm_provider=str(resolved.get("provider") or base_config.llm_provider),
        llm_primary_api_key_env=str(resolved.get("llm_primary_api_key_env") or base_config.llm_primary_api_key_env),
        llm_api_key_env_keys=list(resolved.get("llm_api_key_env_keys") or base_config.llm_api_key_env_keys),
        llm_auth_file_api_key_keys=list(resolved.get("llm_auth_file_api_key_keys") or base_config.llm_auth_file_api_key_keys),
        llm_supports_codex_auth=bool(resolved.get("llm_supports_codex_auth")),
        openai_base_url=resolved.get("openai_base_url") if "openai_base_url" in resolved else base_config.openai_base_url,
        openai_ca_cert_path=resolved.get("openai_ca_cert_path") if "openai_ca_cert_path" in resolved else base_config.openai_ca_cert_path,
        openai_temperature=resolved.get("openai_temperature") if "openai_temperature" in resolved else base_config.openai_temperature,
        openai_use_responses_api=bool(resolved.get("openai_use_responses_api")),
        default_model=str(resolved.get("default_model") or base_config.default_model),
        model_options=list(resolved.get("model_options") or base_config.model_options),
        model_fallbacks=list(resolved.get("model_fallbacks") or base_config.model_fallbacks),
        summary_model=str(resolved.get("default_model") or base_config.summary_model),
    )


DEFAULT_SYSTEM_PROMPT = (
    "你是一个办公室效率助手。优先给可执行结论和下一步动作，输出简洁。"
    "如果用户提供图片或文档，先提炼关键信息再回答。"
    "当需要读取本地信息时可调用工具；调用前先判断是否必要。"
)


def _parse_xdg_user_dir(raw: str, home: Path) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if "=" in value:
        _, value = value.split("=", 1)
        value = value.strip()
    value = _strip_optional_quotes(value)
    value = value.replace("$HOME", str(home))
    if not value:
        return None
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _load_linux_user_dirs(home: Path) -> dict[str, Path]:
    config_path = (home / ".config" / "user-dirs.dirs").resolve()
    if not config_path.is_file():
        return {}

    mapping: dict[str, Path] = {}
    try:
        for raw_line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _ = line.split("=", 1)
            key = key.strip()
            if not key.startswith("XDG_"):
                continue
            parsed = _parse_xdg_user_dir(line, home)
            if parsed is not None:
                mapping[key] = parsed
    except Exception:
        return {}
    return mapping


def _default_extra_allowed_roots_for_platform(home: Path) -> tuple[str, list[Path]]:
    system = (py_platform.system() or "").strip()
    normalized = system.lower()
    desktop_dir = (home / "Desktop").resolve()
    downloads_dir = (home / "Downloads").resolve()

    if normalized == "linux":
        xdg_dirs = _load_linux_user_dirs(home)
        desktop_dir = xdg_dirs.get("XDG_DESKTOP_DIR", desktop_dir)
        downloads_dir = xdg_dirs.get("XDG_DOWNLOAD_DIR", downloads_dir)
        platform_name = "Linux"
    elif normalized == "darwin":
        platform_name = "macOS"
    elif normalized == "windows":
        platform_name = "Windows"
    else:
        platform_name = system or "Unknown"

    roots = [
        (desktop_dir / "workbench").resolve(),
        downloads_dir.resolve(),
    ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return platform_name, deduped


def get_access_roots(config: AppConfig) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    for root in config.allowed_roots:
        add(root)
    if config.allow_workspace_sibling_access:
        add(config.workspace_sibling_root)
    return roots


def load_config() -> AppConfig:
    _load_dotenv_if_present()

    workspace_root = Path(_env("VP_WORKSPACE_ROOT", default=os.getcwd()) or os.getcwd()).resolve()
    modules_dir = Path(
        _env(
            "VP_MODULES_DIR",
            default=str(workspace_root / "app" / "modules"),
        )
        or str(workspace_root / "app" / "modules")
    ).resolve()
    capability_modules = _split_csv(
        _env(
            "VP_CAPABILITY_MODULES",
            default="packages.office_modules",
        )
        or "packages.office_modules"
    )
    runtime_dir = Path(
        _env(
            "VP_RUNTIME_DIR",
            default=str(workspace_root / "app" / "data" / "runtime"),
        )
        or str(workspace_root / "app" / "data" / "runtime")
    ).resolve()
    evolution_dir = Path(
        _env(
            "VP_EVOLUTION_DIR",
            default=str(workspace_root / "app" / "data" / "evolution"),
        )
        or str(workspace_root / "app" / "data" / "evolution")
    ).resolve()
    active_manifest_path = Path(
        _env(
            "VP_ACTIVE_MANIFEST_PATH",
            default=str(runtime_dir / "active_manifest.json"),
        )
        or str(runtime_dir / "active_manifest.json")
    ).resolve()
    shadow_manifest_path = Path(
        _env(
            "VP_SHADOW_MANIFEST_PATH",
            default=str(runtime_dir / "shadow_manifest.json"),
        )
        or str(runtime_dir / "shadow_manifest.json")
    ).resolve()
    rollback_pointer_path = Path(
        _env(
            "VP_ROLLBACK_POINTER_PATH",
            default=str(runtime_dir / "rollback_pointer.json"),
        )
        or str(runtime_dir / "rollback_pointer.json")
    ).resolve()
    module_health_path = Path(
        _env(
            "VP_MODULE_HEALTH_PATH",
            default=str(runtime_dir / "module_health.json"),
        )
        or str(runtime_dir / "module_health.json")
    ).resolve()
    overlay_profile_path = Path(
        _env(
            "VP_OVERLAY_PROFILE_PATH",
            default=str(evolution_dir / "overlay_profile.json"),
        )
        or str(evolution_dir / "overlay_profile.json")
    ).resolve()
    evolution_logs_dir = Path(
        _env(
            "VP_EVOLUTION_LOGS_DIR",
            default=str(evolution_dir / "logs"),
        )
        or str(evolution_dir / "logs")
    ).resolve()
    sessions_dir = Path(
        _env(
            "VP_SESSIONS_DIR",
            default=str(workspace_root / "app" / "data" / "sessions"),
        )
        or str(workspace_root / "app" / "data" / "sessions")
    ).resolve()
    projects_registry_path = Path(
        _env(
            "VP_PROJECTS_REGISTRY_PATH",
            default=str(workspace_root / "app" / "data" / "projects.json"),
        )
        or str(workspace_root / "app" / "data" / "projects.json")
    ).resolve()
    uploads_dir = Path(
        _env(
            "VP_UPLOADS_DIR",
            default=str(workspace_root / "app" / "data" / "uploads"),
        )
        or str(workspace_root / "app" / "data" / "uploads")
    ).resolve()
    token_stats_path = Path(
        _env(
            "VP_TOKEN_STATS_PATH",
            default=str(workspace_root / "app" / "data" / "token_stats.json"),
        )
        or str(workspace_root / "app" / "data" / "token_stats.json")
    ).resolve()
    shadow_logs_dir = Path(
        _env(
            "VP_SHADOW_LOGS_DIR",
            default=str(workspace_root / "app" / "data" / "shadow_logs"),
        )
        or str(workspace_root / "app" / "data" / "shadow_logs")
    ).resolve()

    modules_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    evolution_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    token_stats_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    overlay_profile_path.parent.mkdir(parents=True, exist_ok=True)
    evolution_logs_dir.mkdir(parents=True, exist_ok=True)

    allowed_commands_raw = _env(
        "VP_ALLOWED_COMMANDS",
        default="pwd,ls,cat,rg,head,tail,wc,find,echo,date,python3,git,npm,node,pytest,sed,awk,mkdir,touch,cp,mv",
    ) or "pwd,ls,cat,rg,head,tail,wc,find,echo,date,python3,git,npm,node,pytest,sed,awk,mkdir,touch,cp,mv"

    llm_provider = _normalize_llm_provider(
        _env(
            "VP_LLM_PROVIDER",
            "VP_MODEL_PROVIDER",
            default="openai",
        )
        or "openai"
    )
    llm_provider_preset = _LLM_PROVIDER_PRESETS.get(llm_provider, {})
    llm_provider_token = _provider_env_token(llm_provider)

    preset_api_key_env = str(llm_provider_preset.get("api_key_env") or "").strip()
    llm_api_key_env_keys = _dedupe_keep_order(
        [
            *_provider_specific_api_key_env_keys(llm_provider),
            f"VP_PROVIDER_{llm_provider_token}_API_KEY",
            "VP_LLM_API_KEY",
            preset_api_key_env,
        ]
    )
    llm_primary_api_key_env = llm_api_key_env_keys[0] if llm_api_key_env_keys else "VP_LLM_API_KEY"
    llm_auth_file_api_key_keys = _dedupe_keep_order(
        [
            *_provider_specific_api_key_env_keys(llm_provider),
            f"VP_PROVIDER_{llm_provider_token}_API_KEY",
            "VP_LLM_API_KEY",
            preset_api_key_env,
        ]
    )

    llm_base_url_keys = [
        *_provider_specific_base_url_keys(llm_provider),
        f"VP_PROVIDER_{llm_provider_token}_BASE_URL",
        "VP_LLM_BASE_URL",
    ]
    openai_base_url = (
        _env(*llm_base_url_keys, default=str(llm_provider_preset.get("base_url") or "")) or ""
    ).strip() or None
    llm_supports_codex_auth = _supports_codex_auth(llm_provider, openai_base_url)
    codex_home = Path(
        _env(
            "VP_CODEX_HOME",
            default=str(Path.home() / ".codex"),
        )
        or str(Path.home() / ".codex")
    ).expanduser().resolve()
    codex_auth_file = Path(
        _env(
            "VP_CODEX_AUTH_FILE",
            default=str(codex_home / "auth.json"),
        )
        or str(codex_home / "auth.json")
    ).expanduser().resolve()
    codex_chatgpt_base_url = (
        _env(
            "VP_CODEX_CHATGPT_BASE_URL",
            "VP_CHATGPT_BASE_URL",
            default="https://chatgpt.com/backend-api/codex",
        )
        or "https://chatgpt.com/backend-api/codex"
    ).strip().rstrip("/")
    codex_refresh_url = (
        _env(
            "VP_CODEX_REFRESH_URL",
            default="https://auth.openai.com/oauth/token",
        )
        or "https://auth.openai.com/oauth/token"
    ).strip()
    codex_client_id = (
        _env(
            "VP_CODEX_CLIENT_ID",
            default="app_EMoamEEZ73f0CkXaXp7hrann",
        )
        or "app_EMoamEEZ73f0CkXaXp7hrann"
    ).strip()
    codex_refresh_interval_days = int(
        (
            _env(
                "VP_CODEX_REFRESH_INTERVAL_DAYS",
                default="8",
            )
            or "8"
        ).strip()
    )
    llm_ca_cert_keys = [
        *_provider_specific_ca_cert_keys(llm_provider),
        f"VP_PROVIDER_{llm_provider_token}_CA_CERT_PATH",
        "VP_LLM_CA_CERT_PATH",
        "VP_CA_CERT_PATH",
        "SSL_CERT_FILE",
    ]
    openai_ca_cert_path = (_env(*llm_ca_cert_keys, default="") or "").strip() or None
    llm_temperature_keys = [
        *_provider_specific_temperature_keys(llm_provider),
        f"VP_PROVIDER_{llm_provider_token}_TEMPERATURE",
        "VP_LLM_TEMPERATURE",
        "VP_TEMPERATURE",
    ]
    openai_temperature_raw = (_env(*llm_temperature_keys, default="") or "").strip()
    openai_temperature: float | None = None
    if openai_temperature_raw:
        try:
            openai_temperature = float(openai_temperature_raw)
        except Exception:
            openai_temperature = None

    default_use_responses = "true" if bool(llm_provider_preset.get("use_responses_api")) else "false"
    llm_use_responses_keys = [
        *_provider_specific_responses_api_keys(llm_provider),
        f"VP_PROVIDER_{llm_provider_token}_USE_RESPONSES_API",
        "VP_LLM_USE_RESPONSES_API",
        "VP_USE_RESPONSES_API",
    ]
    use_responses_raw = (
        _env(*llm_use_responses_keys, default=default_use_responses) or default_use_responses
    ).strip().lower()
    openai_use_responses_api = use_responses_raw in {"1", "true", "yes", "on"}

    model_fallbacks = _split_csv(
        _env("VP_MODEL_FALLBACKS", default="") or ""
    )
    model_cooldown_base_sec = int(
        (
            _env(
                "VP_MODEL_COOLDOWN_BASE_SEC",
                default="60",
            )
            or "60"
        ).strip()
    )
    model_cooldown_max_sec = int(
        (
            _env(
                "VP_MODEL_COOLDOWN_MAX_SEC",
                default="3600",
            )
            or "3600"
        ).strip()
    )

    allow_any_raw = (_env("VP_ALLOW_ANY_PATH", default="false") or "false").strip().lower()
    allow_any_path = allow_any_raw in {"1", "true", "yes", "on"}
    sibling_access_raw = (
        _env(
            "VP_ALLOW_WORKSPACE_SIBLING_ACCESS",
            default="true",
        )
        or "true"
    ).strip().lower()
    allow_workspace_sibling_access = sibling_access_raw in {"1", "true", "yes", "on"}
    workspace_sibling_root: Path | None = None
    if allow_workspace_sibling_access:
        parent_root = workspace_root.parent.resolve()
        if parent_root != workspace_root:
            workspace_sibling_root = parent_root

    platform_name, default_extra_root_paths = _default_extra_allowed_roots_for_platform(Path.home())
    default_extra_roots = [str(path) for path in default_extra_root_paths]
    extra_allowed_roots_source = (
        "env_override"
        if _env_is_set("VP_EXTRA_ALLOWED_ROOTS")
        else "platform_default"
    )
    extra_allowed_roots_raw = (
        _env(
            "VP_EXTRA_ALLOWED_ROOTS",
            default=os.pathsep.join(default_extra_roots),
        )
        or ""
    ).strip()
    extra_allowed_roots = [Path(item).resolve() for item in _split_paths(extra_allowed_roots_raw)]

    web_domains_raw = (_env("VP_WEB_ALLOWED_DOMAINS", default="") or "").strip()
    web_allowed_domains = _split_csv(web_domains_raw)
    web_allow_all_domains = len(web_allowed_domains) == 0

    web_fetch_timeout_sec = int(
        (_env("VP_WEB_FETCH_TIMEOUT_SEC", default="12") or "12").strip()
    )
    web_fetch_max_chars = int(
        (_env("VP_WEB_FETCH_MAX_CHARS", default="120000") or "120000").strip()
    )
    web_skip_tls_verify_raw = (
        _env("VP_WEB_SKIP_TLS_VERIFY", default="false") or "false"
    ).strip().lower()
    web_skip_tls_verify = web_skip_tls_verify_raw in {"1", "true", "yes", "on"}
    web_ca_cert_path = (
        _env(
            "VP_WEB_CA_CERT_PATH",
            default=(openai_ca_cert_path or ""),
        )
        or ""
    ).strip() or None

    allowed_roots: list[Path] = []
    seen: set[str] = set()
    for root in [workspace_root, *extra_allowed_roots]:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        allowed_roots.append(root)

    tool_result_soft_trim_chars = int(
        (
            _env(
                "VP_TOOL_RESULT_SOFT_TRIM_CHARS",
                default="40000",
            )
            or "40000"
        ).strip()
    )
    tool_result_hard_clear_chars = int(
        (
            _env(
                "VP_TOOL_RESULT_HARD_CLEAR_CHARS",
                default="180000",
            )
            or "180000"
        ).strip()
    )
    tool_result_head_chars = int(
        (
            _env(
                "VP_TOOL_RESULT_HEAD_CHARS",
                default="8000",
            )
            or "8000"
        ).strip()
    )
    tool_result_tail_chars = int(
        (
            _env(
                "VP_TOOL_RESULT_TAIL_CHARS",
                default="4000",
            )
            or "4000"
        ).strip()
    )
    tool_context_prune_keep_last = int(
        (
            _env(
                "VP_TOOL_CONTEXT_PRUNE_KEEP_LAST",
                default="3",
            )
            or "3"
        ).strip()
    )
    max_concurrent_runs = int(
        (
            _env("VP_MAX_CONCURRENT_RUNS", default="2")
            or "2"
        ).strip()
    )
    run_queue_wait_notice_ms = int(
        (
            _env(
                "VP_RUN_QUEUE_WAIT_NOTICE_MS",
                default="1500",
            )
            or "1500"
        ).strip()
    )
    execution_mode = (
        _env("VP_EXECUTION_MODE", default="host") or "host"
    ).strip().lower()
    if execution_mode not in {"host", "docker"}:
        execution_mode = "host"
    docker_bin = (
        _env("VP_DOCKER_BIN", default="docker") or "docker"
    ).strip()
    docker_image = (
        _env("VP_DOCKER_IMAGE", default="python:3.11-slim")
        or "python:3.11-slim"
    ).strip()
    docker_network = (
        _env("VP_DOCKER_NETWORK", default="none") or "none"
    ).strip()
    docker_memory = (
        _env("VP_DOCKER_MEMORY", default="2g") or "2g"
    ).strip()
    docker_cpus = (
        _env("VP_DOCKER_CPUS", default="1.0") or "1.0"
    ).strip()
    docker_pids_limit = int(
        (_env("VP_DOCKER_PIDS_LIMIT", default="256") or "256").strip()
    )
    docker_container_prefix = (
        _env("VP_DOCKER_CONTAINER_PREFIX", default="multi-agent-team-sbx")
        or "multi-agent-team-sbx"
    ).strip()
    enable_session_tools_raw = (
        _env("VP_ENABLE_SESSION_TOOLS", default="true") or "true"
    ).strip().lower()
    enable_session_tools = enable_session_tools_raw in {"1", "true", "yes", "on"}
    enable_shadow_logging_raw = (
        _env("VP_ENABLE_SHADOW_LOGGING", default="true") or "true"
    ).strip().lower()
    enable_shadow_logging = enable_shadow_logging_raw in {"1", "true", "yes", "on"}
    provider_runtime = _resolve_provider_runtime_settings(llm_provider, active_provider=llm_provider)
    llm_primary_api_key_env = str(provider_runtime.get("llm_primary_api_key_env") or llm_primary_api_key_env)
    llm_api_key_env_keys = list(provider_runtime.get("llm_api_key_env_keys") or llm_api_key_env_keys)
    llm_auth_file_api_key_keys = list(provider_runtime.get("llm_auth_file_api_key_keys") or llm_auth_file_api_key_keys)
    llm_supports_codex_auth = bool(provider_runtime.get("llm_supports_codex_auth"))
    openai_base_url = provider_runtime.get("openai_base_url") if "openai_base_url" in provider_runtime else openai_base_url
    openai_ca_cert_path = provider_runtime.get("openai_ca_cert_path") if "openai_ca_cert_path" in provider_runtime else openai_ca_cert_path
    openai_temperature = provider_runtime.get("openai_temperature") if "openai_temperature" in provider_runtime else openai_temperature
    openai_use_responses_api = bool(provider_runtime.get("openai_use_responses_api"))
    provider_default_model = str(llm_provider_preset.get("default_model") or "gpt-5.1-chat").strip() or "gpt-5.1-chat"
    model_fallbacks = list(provider_runtime.get("model_fallbacks") or model_fallbacks)
    resolved_default_model = str(provider_runtime.get("default_model") or provider_default_model).strip() or provider_default_model
    resolved_model_options = list(provider_runtime.get("model_options") or [resolved_default_model])

    return AppConfig(
        workspace_root=workspace_root,
        modules_dir=modules_dir,
        capability_modules=capability_modules,
        runtime_dir=runtime_dir,
        evolution_dir=evolution_dir,
        active_manifest_path=active_manifest_path,
        shadow_manifest_path=shadow_manifest_path,
        rollback_pointer_path=rollback_pointer_path,
        module_health_path=module_health_path,
        overlay_profile_path=overlay_profile_path,
        evolution_logs_dir=evolution_logs_dir,
        projects_registry_path=projects_registry_path,
        sessions_dir=sessions_dir,
        uploads_dir=uploads_dir,
        shadow_logs_dir=shadow_logs_dir,
        token_stats_path=token_stats_path,
        allowed_roots=allowed_roots,
        workspace_sibling_root=workspace_sibling_root,
        allow_workspace_sibling_access=allow_workspace_sibling_access,
        default_extra_allowed_roots=default_extra_root_paths,
        extra_allowed_roots_source=extra_allowed_roots_source,
        platform_name=platform_name,
        allow_any_path=allow_any_path,
        web_allowed_domains=web_allowed_domains,
        web_allow_all_domains=web_allow_all_domains,
        web_fetch_timeout_sec=max(3, min(30, web_fetch_timeout_sec)),
        web_fetch_max_chars=max(2000, min(500000, web_fetch_max_chars)),
        web_skip_tls_verify=web_skip_tls_verify,
        web_ca_cert_path=web_ca_cert_path,
        llm_provider=llm_provider,
        llm_primary_api_key_env=llm_primary_api_key_env,
        llm_api_key_env_keys=llm_api_key_env_keys,
        llm_auth_file_api_key_keys=llm_auth_file_api_key_keys,
        llm_supports_codex_auth=llm_supports_codex_auth,
        openai_base_url=openai_base_url,
        openai_ca_cert_path=openai_ca_cert_path,
        openai_temperature=openai_temperature,
        openai_use_responses_api=openai_use_responses_api,
        codex_home=codex_home,
        codex_auth_file=codex_auth_file,
        codex_chatgpt_base_url=codex_chatgpt_base_url or "https://chatgpt.com/backend-api/codex",
        codex_refresh_url=codex_refresh_url or "https://auth.openai.com/oauth/token",
        codex_client_id=codex_client_id or "app_EMoamEEZ73f0CkXaXp7hrann",
        codex_refresh_interval_days=max(1, min(30, codex_refresh_interval_days)),
        default_model=resolved_default_model,
        model_options=resolved_model_options,
        model_fallbacks=model_fallbacks,
        model_cooldown_base_sec=max(10, min(3600, model_cooldown_base_sec)),
        model_cooldown_max_sec=max(60, min(86400, model_cooldown_max_sec)),
        summary_model=(
            _env(
                "VP_SUMMARY_MODEL",
                "VP_SUMMARY_MODE",
                default=provider_default_model,
            )
            or provider_default_model
        ),
        system_prompt=_env("VP_SYSTEM_PROMPT", default=DEFAULT_SYSTEM_PROMPT)
        or DEFAULT_SYSTEM_PROMPT,
        summary_trigger_turns=max(
            6,
            min(
                10000,
                int(
                    _env("VP_SUMMARY_TRIGGER_TURNS", default="2000")
                    or "2000"
                ),
            ),
        ),
        max_context_turns=max(
            2,
            min(
                2000,
                int(_env("VP_MAX_CONTEXT_TURNS", default="2000") or "2000"),
            ),
        ),
        max_attachment_chars=max(
            2000,
            min(
                1000000,
                int(
                    _env("VP_MAX_ATTACHMENT_CHARS", default="1000000")
                    or "1000000"
                ),
            ),
        ),
        max_upload_mb=max(
            1,
            min(2048, int(_env("VP_MAX_UPLOAD_MB", default="200") or "200")),
        ),
        tool_result_soft_trim_chars=max(2000, min(1_000_000, tool_result_soft_trim_chars)),
        tool_result_hard_clear_chars=max(4000, min(2_000_000, tool_result_hard_clear_chars)),
        tool_result_head_chars=max(500, min(200_000, tool_result_head_chars)),
        tool_result_tail_chars=max(500, min(200_000, tool_result_tail_chars)),
        tool_context_prune_keep_last=max(0, min(20, tool_context_prune_keep_last)),
        max_concurrent_runs=max(1, min(32, max_concurrent_runs)),
        run_queue_wait_notice_ms=max(0, min(120_000, run_queue_wait_notice_ms)),
        execution_mode=execution_mode,
        docker_bin=docker_bin or "docker",
        docker_image=docker_image or "python:3.11-slim",
        docker_network=docker_network or "none",
        docker_memory=docker_memory or "2g",
        docker_cpus=docker_cpus or "1.0",
        docker_pids_limit=max(16, min(4096, docker_pids_limit)),
        docker_container_prefix=docker_container_prefix or "multi-agent-team-sbx",
        enable_session_tools=enable_session_tools,
        enable_shadow_logging=enable_shadow_logging,
        allowed_commands=_split_csv(allowed_commands_raw),
    )
