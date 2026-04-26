from __future__ import annotations

from app.tool_trace_summary import (
    mask_sensitive_text,
    safe_preview,
    summarize_tool_args,
    summarize_tool_result,
)


def test_mask_sensitive_text_hides_common_secret_patterns() -> None:
    raw = (
        "Authorization: Bearer abc123\n"
        "OPENAI_API_KEY=super-secret\n"
        "token=visible\n"
        "cookie=session123"
    )

    masked = mask_sensitive_text(raw)

    assert "abc123" not in masked
    assert "super-secret" not in masked
    assert "visible" not in masked
    assert "session123" not in masked
    assert "***" in masked


def test_safe_preview_truncates_nested_payloads() -> None:
    preview = safe_preview({"output": "x" * 5000, "nested": ["y" * 5000]}, limit=120)

    assert isinstance(preview, dict)
    assert len(str(preview["output"])) <= 120
    assert isinstance(preview["nested"], list)


def test_summarize_tool_args_and_result_for_common_tools() -> None:
    assert summarize_tool_args("search_codebase", {"query": "update_plan"}) == "query=update_plan"
    assert summarize_tool_args("update_plan", {"steps": [{"step": "Inspect", "status": "completed"}]}) == "items=1"
    assert summarize_tool_result("read", {"ok": True, "content": "hello"}) == "read 5 chars"
    assert summarize_tool_result("search_codebase", {"ok": True, "matches": [1, 2, 3]}) == "found 3 results"
    assert summarize_tool_result("update_plan", {"ok": True, "plan": [{"step": "Inspect", "status": "completed"}]}) == "plan updated: 1 items"
