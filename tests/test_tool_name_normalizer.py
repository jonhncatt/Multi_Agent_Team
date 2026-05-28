from __future__ import annotations

from app.tool_name_normalizer import normalize_tool_name


def test_tool_name_normalizer_lowercases_canonical_names() -> None:
    assert normalize_tool_name("web_fetch") == "web_fetch"
    assert normalize_tool_name("Web_Search") == "web_search"
    assert normalize_tool_name("IMAGE_READ") == "image_read"
    assert normalize_tool_name("Browser_Screenshot") == "browser_screenshot"


def test_tool_name_normalizer_strips_whitespace() -> None:
    assert normalize_tool_name("  read_file  ") == "read_file"
    assert normalize_tool_name("") == ""
