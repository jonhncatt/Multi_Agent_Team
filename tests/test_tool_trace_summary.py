from __future__ import annotations

from app.tool_trace_summary import (
    build_tool_argument_audit,
    mask_sensitive_text,
    safe_preview,
    summarize_tool_args,
    summarize_tool_result,
    validate_tool_arguments,
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


def test_validate_tool_arguments_reports_valid_and_invalid_payloads() -> None:
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    valid = validate_tool_arguments({"query": "needle", "limit": 2}, schema)
    invalid = validate_tool_arguments({"limit": 0, "extra": True}, schema)

    assert valid["status"] == "valid"
    assert valid["checked"] is True
    assert invalid["status"] == "invalid"
    assert any("$.query is required" in item for item in invalid["errors"])
    assert any("$.extra is not allowed" in item for item in invalid["errors"])


def test_build_tool_argument_audit_keeps_raw_arguments_and_validation() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    audit = build_tool_argument_audit("read", {"path": "README.md"}, schema)

    assert audit["arguments_preview"] == "path=README.md"
    assert audit["preview_error"] == ""
    assert audit["schema_validation"]["status"] == "valid"
    assert audit["raw_arguments"]["path"] == "README.md"
