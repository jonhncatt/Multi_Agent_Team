from __future__ import annotations

from scripts.check_provider_conformance import (
    _error_payload,
    build_stream_recommendation,
    redact_text,
    simulate_frontend_batching,
)
from app.config import normalize_openai_base_url


def test_redact_text_removes_configured_secrets() -> None:
    value = redact_text(
        "request to https://internal.example/v1 failed with key secret-key",
        ["https://internal.example/v1", "secret-key"],
    )
    assert "internal.example" not in value
    assert "secret-key" not in value
    assert value.count("<redacted>") == 2


def test_error_payload_does_not_persist_provider_metadata() -> None:
    class FakeRateLimitError(RuntimeError):
        status_code = 429

    payload = _error_payload(
        FakeRateLimitError("raw metadata user_id=user-123 api_key=secret-key"),
        ["secret-key"],
    )

    assert payload == {
        "type": "FakeRateLimitError",
        "status_code": 429,
        "message": "Provider or upstream model is rate-limited. Retry later or select another configured model.",
    }
    assert "user-123" not in str(payload)


def test_frontend_batching_reduces_frequent_delta_flushes() -> None:
    samples = [{"at_ms": index * 5, "chars": 2} for index in range(1, 101)]
    results = simulate_frontend_batching(
        samples,
        duration_ms=500,
        intervals_ms=(16, 50, 100),
        state_updates_per_flush=5,
    )

    assert [item["interval_ms"] for item in results] == [16, 50, 100]
    assert results[0]["flushes"] < 100
    assert results[1]["flushes"] < results[0]["flushes"]
    assert results[2]["estimated_state_updates"] == results[2]["flushes"] * 5
    assert results[2]["flush_reduction_percent"] > 80


def test_stream_recommendation_selects_first_interval_under_target() -> None:
    batching = [
        {"interval_ms": 16, "flushes_per_sec": 40},
        {"interval_ms": 33, "flushes_per_sec": 24},
        {"interval_ms": 50, "flushes_per_sec": 18},
        {"interval_ms": 100, "flushes_per_sec": 9},
    ]
    result = build_stream_recommendation(
        content_chunk_count=100,
        duration_ms=1000,
        batching=batching,
        state_updates_per_delta=5,
        target_ui_updates_per_sec=20,
    )

    assert result["naive_render_risk"] == "high"
    assert result["recommended_flush_interval_ms"] == 50
    assert result["recommended_flushes_per_sec"] == 18


def test_normalize_openai_base_url_matches_runtime_endpoint_handling() -> None:
    assert normalize_openai_base_url("https://gateway.example/v1/") == "https://gateway.example/v1"
    assert (
        normalize_openai_base_url("https://gateway.example/v1/chat/completions")
        == "https://gateway.example/v1"
    )
    assert normalize_openai_base_url("https://gateway.example/chat/completions") == "https://gateway.example"
    assert normalize_openai_base_url("https://gateway.example/v1/responses") == "https://gateway.example/v1"
