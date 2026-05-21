from __future__ import annotations

from app.runtime_trace_labels import trace_label


def test_trace_label_localizes_known_keys() -> None:
    assert trace_label("zh-CN", "run.started") == "开始处理请求"
    assert trace_label("ja-JP", "blocked") == "停止"


def test_trace_label_formats_replacements_and_falls_back_to_key() -> None:
    assert trace_label("en", "tool.started", tool="read_file") == "Calling tool: read_file"
    assert trace_label("en", "unknown.key") == "unknown.key"
