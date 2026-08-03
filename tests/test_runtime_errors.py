from __future__ import annotations

from app.runtime_errors import (
    classify_llm_exception,
    is_request_too_large_exception,
    runtime_error_user_text,
)


class _Response:
    status_code = 413


class _StructuredGatewayError(RuntimeError):
    response = _Response()


def test_request_too_large_classifier_uses_status_and_sanitizes_html() -> None:
    error = _StructuredGatewayError(
        "<html><h1>413 Request Entity Too Large</h1><p>nginx/1.30.1</p></html>"
    )

    assert is_request_too_large_exception(error) is True
    payload = classify_llm_exception(
        error,
        phase="initial_model_response",
        model="gpt-test",
    )

    assert payload["kind"] == "request_too_large"
    assert payload["layer"] == "gateway"
    assert payload["status_code"] == 413
    assert payload["retryable_after_compaction"] is True
    assert "nginx/1.30.1" in payload["raw_message"]
    assert "nginx/1.30.1" not in payload["message"]
    user_text = runtime_error_user_text(payload, locale="zh-CN")
    assert "移除或缩小" in user_text
    assert "nginx/1.30.1" not in user_text


def test_request_too_large_classifier_accepts_nginx_text_without_structured_status() -> None:
    error = RuntimeError("413 Request Entity Too Large")

    assert is_request_too_large_exception(error) is True
    assert classify_llm_exception(error, phase="initial", model="gpt-test")["kind"] == (
        "request_too_large"
    )
