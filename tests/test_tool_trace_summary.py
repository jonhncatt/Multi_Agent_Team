from __future__ import annotations

from app.tool_trace_summary import (
    build_tool_argument_audit,
    mask_sensitive_text,
    normalize_tool_arguments,
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


def test_mask_sensitive_text_preserves_long_skill_names_and_masks_only_named_secrets() -> None:
    skill_path = "/repo/skills/team/read-redmine-discussion-and-summarize-progress/SKILL.md"
    long_identifier = "abcdefghijklmnopqrstuvwxyz123456"

    assert mask_sensitive_text(skill_path) == skill_path
    assert mask_sensitive_text(long_identifier) == long_identifier
    assert mask_sensitive_text(f"REDMINE_API_KEY={long_identifier}") == "REDMINE_API_KEY=***"
    assert mask_sensitive_text(f"https://example.test/?token={long_identifier}") == "https://example.test/?token=***"


def test_safe_preview_truncates_nested_payloads() -> None:
    preview = safe_preview({"output": "x" * 5000, "nested": ["y" * 5000]}, limit=120)

    assert isinstance(preview, dict)
    assert len(str(preview["output"])) <= 120
    assert isinstance(preview["nested"], list)


def test_safe_preview_preserves_number_and_boolean_types() -> None:
    preview = safe_preview({"count": 5, "checked": True, "ratio": 0.5})

    assert preview == {"count": 5, "checked": True, "ratio": 0.5}


def test_safe_preview_preserves_long_skill_path_and_masks_sensitive_dict_values() -> None:
    skill_path = "/repo/skills/team/read-redmine-discussion-and-summarize-progress/SKILL.md"

    preview = safe_preview(
        {
            "path": skill_path,
            "REDMINE_API_KEY": "company-secret",
            "nested": {
                "client_secret": "oauth-secret",
                "token_limit": 4096,
            },
        },
        limit=4000,
    )

    assert preview == {
        "path": skill_path,
        "REDMINE_API_KEY": "***",
        "nested": {
            "client_secret": "***",
            "token_limit": 4096,
        },
    }


def test_summarize_tool_args_and_result_for_common_tools() -> None:
    assert summarize_tool_args("search_codebase", {"query": "update_plan"}) == "query=update_plan"
    assert summarize_tool_args("update_plan", {"steps": [{"step": "Inspect", "status": "completed"}]}) == "items=1"
    assert summarize_tool_result("read_file", {"ok": True, "content": "hello"}) == "read 5 chars"
    assert summarize_tool_result("list_dir", {"ok": True, "entries": [{"name": "a"}, {"name": "b"}]}) == "listed 2 entries"
    assert summarize_tool_result("glob_file_search", {"ok": True, "matches": ["a.py", "b.py"]}) == "matched 2 files"
    assert summarize_tool_result("search_codebase", {"ok": True, "matches": [1, 2, 3]}) == "found 3 results"
    assert summarize_tool_result("update_plan", {"ok": True, "plan": [{"step": "Inspect", "status": "completed"}]}) == "plan updated: 1 items"
    assert summarize_tool_result("read_file", {"ok": True, "content": "hello"}, locale="zh-CN") == "已读取 5 个字符"
    assert summarize_tool_result("read_file", {"ok": True, "content": "hello"}, locale="ja-JP") == "5 文字を読み取りました"


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
    assert valid["summary"] == "schema matched"
    assert invalid["status"] == "invalid"
    assert any("$.query is required" in item for item in invalid["errors"])
    assert any("$.extra is not allowed" in item for item in invalid["errors"])

    zh_valid = validate_tool_arguments({"query": "needle"}, schema, locale="zh-CN")
    ja_missing = validate_tool_arguments({"query": "needle"}, None, locale="ja-JP")

    assert zh_valid["summary"] == "schema 匹配"
    assert ja_missing["summary"] == "schema は利用できません"


def test_build_tool_argument_audit_keeps_raw_arguments_and_validation() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    audit = build_tool_argument_audit("read_file", {"path": "README.md"}, schema)

    assert audit["arguments_preview"] == "path=README.md"
    assert audit["preview_error"] == ""
    assert audit["schema_validation"]["status"] == "valid"
    assert audit["raw_arguments"]["path"] == "README.md"

    zh_audit = build_tool_argument_audit("read_file", {"path": "README.md"}, schema, locale="zh-CN")
    assert zh_audit["schema_validation"]["summary"] == "schema 匹配"


def test_normalize_tool_arguments_applies_known_aliases_when_schema_is_clear() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    normalized = normalize_tool_arguments("web_search", {"q": "PLAN.md"}, schema)

    assert normalized["status"] == "normalized"
    assert normalized["arguments"] == {"query": "PLAN.md"}
    assert normalized["notes"] == ["q->query"]


def test_normalize_tool_arguments_keeps_payload_when_target_schema_is_unknown() -> None:
    normalized = normalize_tool_arguments("custom_tool", {"q": "PLAN.md"}, None)

    assert normalized["status"] == "unchanged"
    assert normalized["arguments"] == {"q": "PLAN.md"}
    assert normalized["notes"] == []


def test_normalize_tool_arguments_clamps_numeric_values_to_schema_minimums() -> None:
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 128, "maximum": 1000000},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    normalized = normalize_tool_arguments("read_file", {"path": "README.md", "max_chars": 100}, schema)

    assert normalized["status"] == "normalized"
    assert normalized["arguments"]["max_chars"] == 128
    assert "max_chars:100->128" in normalized["notes"]
