from __future__ import annotations

from pathlib import Path

import pytest

from app.config import list_provider_profiles, load_config, resolve_python_command
from app.models import ChatSettings
from app.openai_auth import OpenAIAuthManager

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vp_openai_compatible_env_is_first_class(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("VP_OPENAI_COMPAT_API_KEY", "test-key")
    monkeypatch.setenv("VP_OPENAI_COMPAT_BASE_URL", "https://gateway.example.com/v1")

    config = load_config()
    resolved = OpenAIAuthManager(config).resolve()

    assert config.llm_provider == "openai_compatible"
    assert config.llm_primary_api_key_env == "VP_OPENAI_COMPAT_API_KEY"
    assert config.openai_base_url == "https://gateway.example.com/v1"
    assert config.default_model in config.model_options
    assert "gpt-5.1-chat" in config.model_options
    assert resolved.mode == "api_key"


def test_vp_openrouter_env_uses_dedicated_keys(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("VP_OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("VP_OPENROUTER_DEFAULT_MODEL", "google/gemma-4-31b-it:free")
    monkeypatch.setenv("VP_OPENROUTER_MODEL_FALLBACKS", "nvidia/nemotron-3-super-120b-a12b:free")

    config = load_config()

    assert config.llm_provider == "openrouter"
    assert config.llm_primary_api_key_env == "VP_OPENROUTER_API_KEY"
    assert config.openai_base_url == "https://openrouter.ai/api/v1"
    assert config.llm_api_key_env_keys[0] == "VP_OPENROUTER_API_KEY"
    assert config.default_model == "google/gemma-4-31b-it:free"
    assert "google/gemma-4-31b-it:free" in config.model_options
    assert "nvidia/nemotron-3-super-120b-a12b:free" in config.model_options


def test_openai_requires_explicit_api_key_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai")

    config = load_config()
    resolved = OpenAIAuthManager(config).resolve()

    assert resolved.mode == "unconfigured"
    assert resolved.available is False


def test_provider_profiles_only_list_env_configured_providers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("VP_OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("VP_DEEPSEEK_API_KEY", "deepseek-key")

    config = load_config()
    profiles = list_provider_profiles(config)
    providers = [item["provider"] for item in profiles]

    assert "openrouter" in providers
    assert "deepseek" in providers
    assert "openai_compatible" not in providers
    openrouter = next(item for item in profiles if item["provider"] == "openrouter")
    assert openrouter["default_model"]
    assert "google/gemma-4-31b-it:free" in openrouter["model_options"]


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_vp_default_locale_can_be_configured(monkeypatch, tmp_path, locale: str) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_DEFAULT_LOCALE", locale)

    config = load_config()

    assert config.default_locale == locale


def test_vp_max_output_tokens_defaults_to_stable_4096(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))

    config = load_config()

    assert config.max_output_tokens == 4096


def test_vp_max_output_tokens_env_is_loaded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_MAX_OUTPUT_TOKENS", "2048")

    config = load_config()

    assert config.max_output_tokens == 2048


def test_web_fetch_budget_matches_main_branch_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))

    config = load_config()

    assert config.web_fetch_max_chars == 120000


def test_web_fetch_budget_allows_large_configured_fetches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_WEB_FETCH_MAX_CHARS", "800000")

    config = load_config()

    assert config.web_fetch_max_chars == 500000


def test_browser_chrome_profile_env_is_loaded(monkeypatch, tmp_path) -> None:
    profile_dir = tmp_path / "app" / "data" / "browser_profile"
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_BROWSER_MODE", "chrome_profile")
    monkeypatch.setenv("VP_BROWSER_CHANNEL", "chrome")
    monkeypatch.setenv("VP_BROWSER_HEADLESS", "false")
    monkeypatch.setenv("VP_BROWSER_USER_DATA_DIR", "app/data/browser_profile")
    monkeypatch.setenv("VP_BROWSER_PROXY_SERVER", "http://proxy.example:8080")
    monkeypatch.setenv("VP_BROWSER_IGNORE_HTTPS_ERRORS", "true")
    monkeypatch.setenv("VP_BROWSER_DISABLE_PASSWORD_MANAGER", "true")

    config = load_config()

    assert config.browser_mode == "chrome_profile"
    assert config.browser_channel == "chrome"
    assert config.browser_headless is False
    assert config.browser_user_data_dir == profile_dir.resolve()
    assert config.browser_proxy_server == "http://proxy.example:8080"
    assert config.browser_ignore_https_errors is True
    assert config.browser_chromium_sandbox is True
    assert config.browser_disable_password_manager is True


def test_env_example_matches_web_fetch_budget_default() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    lines = {line.strip() for line in env_example.splitlines()}

    assert "# VP_WEB_FETCH_MAX_CHARS=120000" in lines
    assert "# VP_WEB_FETCH_MAX_CHARS=12000" not in lines


def test_vp_allowed_commands_env_is_full_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_ALLOWED_COMMANDS", "printf,dir")

    config = load_config()

    assert config.allowed_commands == ["printf", "dir"]


def test_permission_safe_defaults_do_not_add_user_folders(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))

    config = load_config()

    assert config.permission_profile == "auto"
    assert config.default_extra_allowed_roots == []
    assert config.allow_workspace_sibling_access is False
    assert config.workspace_sibling_root is None
    assert config.allowed_roots == [tmp_path.resolve()]


def test_permission_profile_aliases(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_PERMISSION_PROFILE", "full")

    config = load_config()

    assert config.permission_profile == "full_access"


def test_permission_profile_alias_normalization(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))

    cases = {
        "chat": "default",
        "readonly": "default",
        "read_only": "default",
        "read only": "default",
        "default": "default",
        "safe": "default",
        "safe_default": "default",
        "code": "auto",
        "coding": "auto",
        "auto": "auto",
        "automatic": "auto",
        "full_dev": "full_access",
        "full dev": "full_access",
        "fulldev": "full_access",
        "full": "full_access",
        "dev": "full_access",
        "full_access": "full_access",
        "full-access": "full_access",
        "danger_full_access": "full_access",
        "danger-full-access": "full_access",
        "unknown": "auto",
    }

    for raw, expected in cases.items():
        monkeypatch.setenv("VP_PERMISSION_PROFILE", raw)
        assert load_config().permission_profile == expected


def test_chat_settings_max_context_turns_default_remains_2000() -> None:
    assert ChatSettings().max_context_turns == 2000


def test_resolve_python_command_prefers_python_on_windows() -> None:
    which = lambda name: f"/fake/{name}" if name in {"python", "py", "python3"} else None

    assert resolve_python_command("Windows", which=which) == "python"


def test_resolve_python_command_prefers_python_then_python3_on_non_windows() -> None:
    which = lambda name: f"/fake/{name}" if name in {"python", "python3"} else None

    assert resolve_python_command("Linux", which=which) == "python"


def test_resolve_python_command_uses_python3_when_python_missing() -> None:
    which = lambda name: f"/fake/{name}" if name == "python3" else None

    assert resolve_python_command("Linux", which=which) == "python3"


def test_resolve_python_command_falls_back_to_py_when_needed() -> None:
    which = lambda name: f"/fake/{name}" if name == "py" else None

    assert resolve_python_command("Windows", which=which) == "py"
