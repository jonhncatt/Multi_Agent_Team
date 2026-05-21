from __future__ import annotations

from app.tool_name_normalizer import normalize_tool_name


def test_tool_name_normalizer_handles_aliases() -> None:
    assert normalize_tool_name("fetch_web") == "web_fetch"
    assert normalize_tool_name("search_web") == "web_search"
    assert normalize_tool_name("read_image") == "image_read"
    assert normalize_tool_name("view_image") == "image_inspect"


def test_tool_name_normalizer_infers_image_read_and_inspect_modes() -> None:
    assert normalize_tool_name("image_meta_probe") == "image_inspect"
    assert normalize_tool_name("picture_describe") == "image_read"
    assert normalize_tool_name("read_file") == "read_file"
