from __future__ import annotations

import os
import platform as py_platform
from dataclasses import dataclass
from pathlib import Path


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _split_paths(raw: str) -> list[str]:
    if not raw:
        return []
    merged = raw.replace(",", os.pathsep)
    return [item.strip() for item in merged.split(os.pathsep) if item.strip()]


def _env(*keys: str, default: str | None = None) -> str | None:
    for key in keys:
        if key in os.environ:
            return os.environ.get(key)
    return default


def _env_is_set(*keys: str) -> bool:
    return any(key in os.environ for key in keys)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


def _should_dotenv_override(key: str) -> bool:
    normalized = key.strip().upper()
    if normalized.startswith("OFFICETOOL_") or normalized.startswith("OFFCIATOOL_"):
        return True
    return normalized in {
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    }


def _load_dotenv_if_present() -> None:
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
    openai_auth_mode: str
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

    workspace_root = Path(_env("OFFICETOOL_WORKSPACE_ROOT", "OFFCIATOOL_WORKSPACE_ROOT", default=os.getcwd()) or os.getcwd()).resolve()
    modules_dir = Path(
        _env(
            "OFFICETOOL_MODULES_DIR",
            "OFFCIATOOL_MODULES_DIR",
            default=str(workspace_root / "app" / "modules"),
        )
        or str(workspace_root / "app" / "modules")
    ).resolve()
    capability_modules = _split_csv(
        _env(
            "OFFICETOOL_CAPABILITY_MODULES",
            "OFFCIATOOL_CAPABILITY_MODULES",
            default="packages.office_modules",
        )
        or "packages.office_modules"
    )
    runtime_dir = Path(
        _env(
            "OFFICETOOL_RUNTIME_DIR",
            "OFFCIATOOL_RUNTIME_DIR",
            default=str(workspace_root / "app" / "data" / "runtime"),
        )
        or str(workspace_root / "app" / "data" / "runtime")
    ).resolve()
    evolution_dir = Path(
        _env(
            "OFFICETOOL_EVOLUTION_DIR",
            "OFFCIATOOL_EVOLUTION_DIR",
            default=str(workspace_root / "app" / "data" / "evolution"),
        )
        or str(workspace_root / "app" / "data" / "evolution")
    ).resolve()
    active_manifest_path = Path(
        _env(
            "OFFICETOOL_ACTIVE_MANIFEST_PATH",
            "OFFCIATOOL_ACTIVE_MANIFEST_PATH",
            default=str(runtime_dir / "active_manifest.json"),
        )
        or str(runtime_dir / "active_manifest.json")
    ).resolve()
    shadow_manifest_path = Path(
        _env(
            "OFFICETOOL_SHADOW_MANIFEST_PATH",
            "OFFCIATOOL_SHADOW_MANIFEST_PATH",
            default=str(runtime_dir / "shadow_manifest.json"),
        )
        or str(runtime_dir / "shadow_manifest.json")
    ).resolve()
    rollback_pointer_path = Path(
        _env(
            "OFFICETOOL_ROLLBACK_POINTER_PATH",
            "OFFCIATOOL_ROLLBACK_POINTER_PATH",
            default=str(runtime_dir / "rollback_pointer.json"),
        )
        or str(runtime_dir / "rollback_pointer.json")
    ).resolve()
    module_health_path = Path(
        _env(
            "OFFICETOOL_MODULE_HEALTH_PATH",
            "OFFCIATOOL_MODULE_HEALTH_PATH",
            default=str(runtime_dir / "module_health.json"),
        )
        or str(runtime_dir / "module_health.json")
    ).resolve()
    overlay_profile_path = Path(
        _env(
            "OFFICETOOL_OVERLAY_PROFILE_PATH",
            "OFFCIATOOL_OVERLAY_PROFILE_PATH",
            default=str(evolution_dir / "overlay_profile.json"),
        )
        or str(evolution_dir / "overlay_profile.json")
    ).resolve()
    evolution_logs_dir = Path(
        _env(
            "OFFICETOOL_EVOLUTION_LOGS_DIR",
            "OFFCIATOOL_EVOLUTION_LOGS_DIR",
            default=str(evolution_dir / "logs"),
        )
        or str(evolution_dir / "logs")
    ).resolve()
    sessions_dir = Path(
        _env(
            "OFFICETOOL_SESSIONS_DIR",
            "OFFCIATOOL_SESSIONS_DIR",
            default=str(workspace_root / "app" / "data" / "sessions"),
        )
        or str(workspace_root / "app" / "data" / "sessions")
    ).resolve()
    uploads_dir = Path(
        _env(
            "OFFICETOOL_UPLOADS_DIR",
            "OFFCIATOOL_UPLOADS_DIR",
            default=str(workspace_root / "app" / "data" / "uploads"),
        )
        or str(workspace_root / "app" / "data" / "uploads")
    ).resolve()
    token_stats_path = Path(
        _env(
            "OFFICETOOL_TOKEN_STATS_PATH",
            "OFFCIATOOL_TOKEN_STATS_PATH",
            default=str(workspace_root / "app" / "data" / "token_stats.json"),
        )
        or str(workspace_root / "app" / "data" / "token_stats.json")
    ).resolve()
    shadow_logs_dir = Path(
        _env(
            "OFFICETOOL_SHADOW_LOGS_DIR",
            "OFFCIATOOL_SHADOW_LOGS_DIR",
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
        "OFFICETOOL_ALLOWED_COMMANDS",
        "OFFCIATOOL_ALLOWED_COMMANDS",
        default="pwd,ls,cat,rg,head,tail,wc,find,echo,date,python3,git,npm,node,pytest,sed,awk,mkdir,touch,cp,mv",
    ) or "pwd,ls,cat,rg,head,tail,wc,find,echo,date,python3,git,npm,node,pytest,sed,awk,mkdir,touch,cp,mv"

    llm_provider = (
        _env("OFFICETOOL_LLM_PROVIDER", "OFFCIATOOL_LLM_PROVIDER", default="openai") or "openai"
    ).strip().lower()
    if not llm_provider:
        llm_provider = "openai"

    openai_base_url = (
        _env(
            "OFFICETOOL_LLM_BASE_URL",
            "OFFCIATOOL_LLM_BASE_URL",
            "OFFICETOOL_OPENAI_BASE_URL",
            "OFFCIATOOL_OPENAI_BASE_URL",
            "OPENAI_BASE_URL",
            default="",
        )
        or ""
    ).strip() or None
    openai_auth_mode = (
        _env(
            "OFFICETOOL_LLM_AUTH_MODE",
            "OFFCIATOOL_LLM_AUTH_MODE",
            "OFFICETOOL_OPENAI_AUTH_MODE",
            "OFFCIATOOL_OPENAI_AUTH_MODE",
            default="auto",
        )
        or "auto"
    ).strip().lower()
    if openai_auth_mode not in {"auto", "api_key", "codex_auth"}:
        openai_auth_mode = "auto"
    codex_home = Path(
        _env(
            "OFFICETOOL_CODEX_HOME",
            "OFFCIATOOL_CODEX_HOME",
            "CODEX_HOME",
            default=str(Path.home() / ".codex"),
        )
        or str(Path.home() / ".codex")
    ).expanduser().resolve()
    codex_auth_file = Path(
        _env(
            "OFFICETOOL_CODEX_AUTH_FILE",
            "OFFCIATOOL_CODEX_AUTH_FILE",
            default=str(codex_home / "auth.json"),
        )
        or str(codex_home / "auth.json")
    ).expanduser().resolve()
    codex_chatgpt_base_url = (
        _env(
            "OFFICETOOL_CODEX_CHATGPT_BASE_URL",
            "OFFCIATOOL_CODEX_CHATGPT_BASE_URL",
            "OFFICETOOL_CHATGPT_BASE_URL",
            "OFFCIATOOL_CHATGPT_BASE_URL",
            default="https://chatgpt.com/backend-api/codex",
        )
        or "https://chatgpt.com/backend-api/codex"
    ).strip().rstrip("/")
    codex_refresh_url = (
        _env(
            "OFFICETOOL_CODEX_REFRESH_URL",
            "OFFCIATOOL_CODEX_REFRESH_URL",
            default="https://auth.openai.com/oauth/token",
        )
        or "https://auth.openai.com/oauth/token"
    ).strip()
    codex_client_id = (
        _env(
            "OFFICETOOL_CODEX_CLIENT_ID",
            "OFFCIATOOL_CODEX_CLIENT_ID",
            default="app_EMoamEEZ73f0CkXaXp7hrann",
        )
        or "app_EMoamEEZ73f0CkXaXp7hrann"
    ).strip()
    codex_refresh_interval_days = int(
        (
            _env(
                "OFFICETOOL_CODEX_REFRESH_INTERVAL_DAYS",
                "OFFCIATOOL_CODEX_REFRESH_INTERVAL_DAYS",
                default="8",
            )
            or "8"
        ).strip()
    )
    openai_ca_cert_path = (
        _env("OFFICETOOL_CA_CERT_PATH", "OFFCIATOOL_CA_CERT_PATH", "SSL_CERT_FILE", default="") or ""
    ).strip() or None
    openai_temperature_raw = (
        _env(
            "OFFICETOOL_LLM_TEMPERATURE",
            "OFFCIATOOL_LLM_TEMPERATURE",
            "OFFICETOOL_TEMPERATURE",
            "OFFCIATOOL_TEMPERATURE",
            default="",
        )
        or ""
    ).strip()
    openai_temperature: float | None = None
    if openai_temperature_raw:
        try:
            openai_temperature = float(openai_temperature_raw)
        except Exception:
            openai_temperature = None

    use_responses_raw = (
        _env(
            "OFFICETOOL_LLM_USE_RESPONSES_API",
            "OFFCIATOOL_LLM_USE_RESPONSES_API",
            "OFFICETOOL_USE_RESPONSES_API",
            "OFFCIATOOL_USE_RESPONSES_API",
            default="false",
        )
        or "false"
    ).strip().lower()
    openai_use_responses_api = use_responses_raw in {"1", "true", "yes", "on"}

    model_fallbacks = _split_csv(
        _env("OFFICETOOL_MODEL_FALLBACKS", "OFFCIATOOL_MODEL_FALLBACKS", default="") or ""
    )
    model_cooldown_base_sec = int(
        (
            _env(
                "OFFICETOOL_MODEL_COOLDOWN_BASE_SEC",
                "OFFCIATOOL_MODEL_COOLDOWN_BASE_SEC",
                default="60",
            )
            or "60"
        ).strip()
    )
    model_cooldown_max_sec = int(
        (
            _env(
                "OFFICETOOL_MODEL_COOLDOWN_MAX_SEC",
                "OFFCIATOOL_MODEL_COOLDOWN_MAX_SEC",
                default="3600",
            )
            or "3600"
        ).strip()
    )

    allow_any_raw = (_env("OFFICETOOL_ALLOW_ANY_PATH", "OFFCIATOOL_ALLOW_ANY_PATH", default="false") or "false").strip().lower()
    allow_any_path = allow_any_raw in {"1", "true", "yes", "on"}
    sibling_access_raw = (
        _env(
            "OFFICETOOL_ALLOW_WORKSPACE_SIBLING_ACCESS",
            "OFFCIATOOL_ALLOW_WORKSPACE_SIBLING_ACCESS",
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
        if _env_is_set("OFFICETOOL_EXTRA_ALLOWED_ROOTS", "OFFCIATOOL_EXTRA_ALLOWED_ROOTS")
        else "platform_default"
    )
    extra_allowed_roots_raw = (
        _env(
            "OFFICETOOL_EXTRA_ALLOWED_ROOTS",
            "OFFCIATOOL_EXTRA_ALLOWED_ROOTS",
            default=os.pathsep.join(default_extra_roots),
        )
        or ""
    ).strip()
    extra_allowed_roots = [Path(item).resolve() for item in _split_paths(extra_allowed_roots_raw)]

    web_domains_raw = (_env("OFFICETOOL_WEB_ALLOWED_DOMAINS", "OFFCIATOOL_WEB_ALLOWED_DOMAINS", default="") or "").strip()
    web_allowed_domains = _split_csv(web_domains_raw)
    web_allow_all_domains = len(web_allowed_domains) == 0

    web_fetch_timeout_sec = int(
        (_env("OFFICETOOL_WEB_FETCH_TIMEOUT_SEC", "OFFCIATOOL_WEB_FETCH_TIMEOUT_SEC", default="12") or "12").strip()
    )
    web_fetch_max_chars = int(
        (_env("OFFICETOOL_WEB_FETCH_MAX_CHARS", "OFFCIATOOL_WEB_FETCH_MAX_CHARS", default="120000") or "120000").strip()
    )
    web_skip_tls_verify_raw = (
        _env("OFFICETOOL_WEB_SKIP_TLS_VERIFY", "OFFCIATOOL_WEB_SKIP_TLS_VERIFY", default="false") or "false"
    ).strip().lower()
    web_skip_tls_verify = web_skip_tls_verify_raw in {"1", "true", "yes", "on"}
    web_ca_cert_path = (
        _env(
            "OFFICETOOL_WEB_CA_CERT_PATH",
            "OFFCIATOOL_WEB_CA_CERT_PATH",
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
                "OFFICETOOL_TOOL_RESULT_SOFT_TRIM_CHARS",
                "OFFCIATOOL_TOOL_RESULT_SOFT_TRIM_CHARS",
                default="40000",
            )
            or "40000"
        ).strip()
    )
    tool_result_hard_clear_chars = int(
        (
            _env(
                "OFFICETOOL_TOOL_RESULT_HARD_CLEAR_CHARS",
                "OFFCIATOOL_TOOL_RESULT_HARD_CLEAR_CHARS",
                default="180000",
            )
            or "180000"
        ).strip()
    )
    tool_result_head_chars = int(
        (
            _env(
                "OFFICETOOL_TOOL_RESULT_HEAD_CHARS",
                "OFFCIATOOL_TOOL_RESULT_HEAD_CHARS",
                default="8000",
            )
            or "8000"
        ).strip()
    )
    tool_result_tail_chars = int(
        (
            _env(
                "OFFICETOOL_TOOL_RESULT_TAIL_CHARS",
                "OFFCIATOOL_TOOL_RESULT_TAIL_CHARS",
                default="4000",
            )
            or "4000"
        ).strip()
    )
    tool_context_prune_keep_last = int(
        (
            _env(
                "OFFICETOOL_TOOL_CONTEXT_PRUNE_KEEP_LAST",
                "OFFCIATOOL_TOOL_CONTEXT_PRUNE_KEEP_LAST",
                default="3",
            )
            or "3"
        ).strip()
    )
    max_concurrent_runs = int(
        (
            _env("OFFICETOOL_MAX_CONCURRENT_RUNS", "OFFCIATOOL_MAX_CONCURRENT_RUNS", default="2")
            or "2"
        ).strip()
    )
    run_queue_wait_notice_ms = int(
        (
            _env(
                "OFFICETOOL_RUN_QUEUE_WAIT_NOTICE_MS",
                "OFFCIATOOL_RUN_QUEUE_WAIT_NOTICE_MS",
                default="1500",
            )
            or "1500"
        ).strip()
    )
    execution_mode = (
        _env("OFFICETOOL_EXECUTION_MODE", "OFFCIATOOL_EXECUTION_MODE", default="host") or "host"
    ).strip().lower()
    if execution_mode not in {"host", "docker"}:
        execution_mode = "host"
    docker_bin = (
        _env("OFFICETOOL_DOCKER_BIN", "OFFCIATOOL_DOCKER_BIN", default="docker") or "docker"
    ).strip()
    docker_image = (
        _env("OFFICETOOL_DOCKER_IMAGE", "OFFCIATOOL_DOCKER_IMAGE", default="python:3.11-slim")
        or "python:3.11-slim"
    ).strip()
    docker_network = (
        _env("OFFICETOOL_DOCKER_NETWORK", "OFFCIATOOL_DOCKER_NETWORK", default="none") or "none"
    ).strip()
    docker_memory = (
        _env("OFFICETOOL_DOCKER_MEMORY", "OFFCIATOOL_DOCKER_MEMORY", default="2g") or "2g"
    ).strip()
    docker_cpus = (
        _env("OFFICETOOL_DOCKER_CPUS", "OFFCIATOOL_DOCKER_CPUS", default="1.0") or "1.0"
    ).strip()
    docker_pids_limit = int(
        (_env("OFFICETOOL_DOCKER_PIDS_LIMIT", "OFFCIATOOL_DOCKER_PIDS_LIMIT", default="256") or "256").strip()
    )
    docker_container_prefix = (
        _env("OFFICETOOL_DOCKER_CONTAINER_PREFIX", "OFFCIATOOL_DOCKER_CONTAINER_PREFIX", default="officetool-sbx")
        or "officetool-sbx"
    ).strip()
    enable_session_tools_raw = (
        _env("OFFICETOOL_ENABLE_SESSION_TOOLS", "OFFCIATOOL_ENABLE_SESSION_TOOLS", default="true") or "true"
    ).strip().lower()
    enable_session_tools = enable_session_tools_raw in {"1", "true", "yes", "on"}
    enable_shadow_logging_raw = (
        _env("OFFICETOOL_ENABLE_SHADOW_LOGGING", "OFFCIATOOL_ENABLE_SHADOW_LOGGING", default="true") or "true"
    ).strip().lower()
    enable_shadow_logging = enable_shadow_logging_raw in {"1", "true", "yes", "on"}

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
        openai_auth_mode=openai_auth_mode,
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
        default_model=(
            _env(
                "OFFICETOOL_LLM_MODEL",
                "OFFCIATOOL_LLM_MODEL",
                "OFFICETOOL_DEFAULT_MODEL",
                "OFFCIATOOL_DEFAULT_MODEL",
                default="gpt-5.1-chat",
            )
            or "gpt-5.1-chat"
        ),
        model_fallbacks=model_fallbacks,
        model_cooldown_base_sec=max(10, min(3600, model_cooldown_base_sec)),
        model_cooldown_max_sec=max(60, min(86400, model_cooldown_max_sec)),
        summary_model=(
            _env(
                "OFFICETOOL_LLM_SUMMARY_MODEL",
                "OFFCIATOOL_LLM_SUMMARY_MODEL",
                "OFFICETOOL_SUMMARY_MODEL",
                "OFFICETOOL_SUMMARY_MODE",
                "OFFCIATOOL_SUMMARY_MODEL",
                "OFFCIATOOL_SUMMARY_MODE",
                default="gpt-5.1-chat",
            )
            or "gpt-5.1-chat"
        ),
        system_prompt=_env("OFFICETOOL_SYSTEM_PROMPT", "OFFCIATOOL_SYSTEM_PROMPT", default=DEFAULT_SYSTEM_PROMPT)
        or DEFAULT_SYSTEM_PROMPT,
        summary_trigger_turns=max(
            6,
            min(
                10000,
                int(
                    _env("OFFICETOOL_SUMMARY_TRIGGER_TURNS", "OFFCIATOOL_SUMMARY_TRIGGER_TURNS", default="2000")
                    or "2000"
                ),
            ),
        ),
        max_context_turns=max(
            2,
            min(
                2000,
                int(_env("OFFICETOOL_MAX_CONTEXT_TURNS", "OFFCIATOOL_MAX_CONTEXT_TURNS", default="2000") or "2000"),
            ),
        ),
        max_attachment_chars=max(
            2000,
            min(
                1000000,
                int(
                    _env("OFFICETOOL_MAX_ATTACHMENT_CHARS", "OFFCIATOOL_MAX_ATTACHMENT_CHARS", default="1000000")
                    or "1000000"
                ),
            ),
        ),
        max_upload_mb=max(
            1,
            min(2048, int(_env("OFFICETOOL_MAX_UPLOAD_MB", "OFFCIATOOL_MAX_UPLOAD_MB", default="200") or "200")),
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
        docker_container_prefix=docker_container_prefix or "officetool-sbx",
        enable_session_tools=enable_session_tools,
        enable_shadow_logging=enable_shadow_logging,
        allowed_commands=_split_csv(allowed_commands_raw),
    )
