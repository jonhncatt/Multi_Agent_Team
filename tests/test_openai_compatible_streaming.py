from __future__ import annotations

import logging

from app.openai_compatible_streaming import (
    apply_local_provider_defaults,
    is_local_base_url,
    message_stats,
    provider_payload_summary,
)


def test_is_local_base_url_detects_loopback_and_lan_ranges() -> None:
    assert is_local_base_url("http://localhost:8080/v1") is True
    assert is_local_base_url("http://127.0.0.1:8080/v1") is True
    assert is_local_base_url("http://192.168.11.7:8080/v1") is True
    assert is_local_base_url("http://10.0.0.8:8080/v1") is True
    assert is_local_base_url("http://172.16.0.2:8080/v1") is True
    assert is_local_base_url("http://172.31.255.2:8080/v1") is True
    assert is_local_base_url("http://172.32.0.2:8080/v1") is False
    assert is_local_base_url("https://api.openai.com/v1") is False


def test_openai_compatible_local_defaults_enable_stream_and_cap_tokens(monkeypatch) -> None:
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("VP_OPENAI_COMPAT_BASE_URL", "http://192.168.11.7:8080/v1")
    monkeypatch.delenv("VP_OPENAI_COMPAT_STREAM", raising=False)
    monkeypatch.delenv("VP_OPENAI_COMPAT_MAX_OUTPUT_TOKENS", raising=False)

    adjusted, diagnostics = apply_local_provider_defaults(
        {
            "model": "mlx-community/Qwen3.5-9B-4bit",
            "base_url": "http://192.168.11.7:8080/v1",
            "max_tokens": 128000,
        }
    )

    assert adjusted["streaming"] is True
    assert adjusted["disable_streaming"] is False
    assert adjusted["max_tokens"] == 2048
    assert diagnostics["local_base_url"] is True
    assert diagnostics["max_tokens_cap"] == 2048


def test_openai_compatible_env_can_disable_stream_and_override_cap(monkeypatch) -> None:
    monkeypatch.setenv("VP_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("VP_OPENAI_COMPAT_STREAM", "false")
    monkeypatch.setenv("VP_OPENAI_COMPAT_MAX_OUTPUT_TOKENS", "1024")

    adjusted, diagnostics = apply_local_provider_defaults(
        {
            "model": "local-model",
            "base_url": "http://localhost:8080/v1",
            "max_tokens": 4096,
        }
    )

    assert adjusted["streaming"] is False
    assert adjusted["max_tokens"] == 1024
    assert diagnostics["stream_configured"] is False


def test_message_stats_counts_messages_and_chars_without_prompt_logging() -> None:
    messages = [
        {"role": "system", "content": "SECRET_SYSTEM_PROMPT"},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    ]

    count, chars = message_stats(messages)
    summary = provider_payload_summary(
        provider="openai_compatible",
        base_url="http://localhost:8080/v1",
        model="local-model",
        stream=True,
        max_tokens=1024,
        messages=messages,
    )

    assert count == 2
    assert chars == len("SECRET_SYSTEM_PROMPT") + len("hello")
    assert summary["messages_count"] == 2
    assert summary["total_chars"] == chars
    assert "SECRET_SYSTEM_PROMPT" not in str(summary)
    assert "hello" not in str(summary)


def test_payload_summary_log_shape_does_not_include_prompt_text(caplog) -> None:
    caplog.set_level(logging.INFO, logger="multi_agent_team.provider")
    summary = provider_payload_summary(
        provider="openai_compatible",
        base_url="http://localhost:8080/v1",
        model="local-model",
        stream=True,
        max_tokens=1024,
        messages=[{"role": "user", "content": "VERY_PRIVATE_PROMPT_TEXT"}],
    )

    logger = logging.getLogger("multi_agent_team.provider")
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

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "VERY_PRIVATE_PROMPT_TEXT" not in rendered
    assert "messages_count=1" in rendered
    assert "total_chars=24" in rendered
