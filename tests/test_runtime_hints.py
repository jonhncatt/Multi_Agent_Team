from __future__ import annotations

from app.runtime_hints import (
    extract_activity_excerpt,
    has_explicit_network_hint,
    has_explicit_workspace_hint,
    looks_like_inline_document_payload,
    looks_like_japanese_review_request,
    looks_like_revision_request,
)


def test_runtime_hints_detect_network_and_workspace_requests() -> None:
    assert has_explicit_network_hint("search today's web news") is True
    assert has_explicit_workspace_hint("请查看这个仓库里的文件") is True


def test_runtime_hints_detect_inline_document_and_revision_requests() -> None:
    inline_xml = """```xml\n<root>\n  <item>1</item>\n  <item>2</item>\n  <item>3</item>\n</root>\n```"""

    assert looks_like_inline_document_payload(inline_xml) is True
    assert looks_like_revision_request("请润色这段文本") is True
    assert looks_like_japanese_review_request("请把这句日语润色得更自然", route_state={}) is True


def test_runtime_hints_extract_activity_excerpt() -> None:
    text = "原句：これは古い文です。\n结果：これはより自然な文です。"

    assert "これは古い文です" in extract_activity_excerpt(text, prefer_japanese=True)
