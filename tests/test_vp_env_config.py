from __future__ import annotations

import pytest

from app.config import list_provider_profiles, load_config, resolve_python_command
from app.models import ChatSettings
from app.openai_auth import OpenAIAuthManager


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
    assert config.llm_supports_codex_auth is False
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


def test_openai_uses_codex_auth_automatically_when_auth_file_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai")
    auth_file = tmp_path / ".codex" / "auth.json"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(
        '{"tokens":{"refresh_token":"refresh","account_id":"acct"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VP_CODEX_AUTH_FILE", str(auth_file))

    config = load_config()
    resolved = OpenAIAuthManager(config).resolve()

    assert resolved.mode == "codex_auth"
    assert resolved.available is True


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

    assert config.permission_profile == "code"
    assert config.default_extra_allowed_roots == []
    assert config.allow_workspace_sibling_access is False
    assert config.workspace_sibling_root is None
    assert config.allowed_roots == [tmp_path.resolve()]


def test_permission_profile_aliases(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VP_PERMISSION_PROFILE", "full")

    config = load_config()

    assert config.permission_profile == "full_dev"


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
