from __future__ import annotations

__doc__ = """Canonical VP router hint tables.

These constants back request interpretation without requiring the
retired `app.router_rules` shim.
"""


VERIFICATION_HINTS = (
    "证据",
    "出处",
    "引用",
    "定位",
    "命中",
    "查证",
    "核对",
    "根据原文",
    "according to",
    "citation",
    "在哪看到",
    "哪里看到",
    "哪儿看到",
    "哪一页",
    "哪页",
    "原文位置",
    "原文在哪",
    "show me where",
    "which page",
    "where did you see",
)

SOURCE_TRACE_HINTS = (
    "在哪看到",
    "哪里看到",
    "哪儿看到",
    "哪一页",
    "哪页",
    "原文位置",
    "原文在哪",
    "出处",
    "来源",
    "source",
    "where did you see",
    "where is it in",
    "which page",
    "show me where",
)

SPEC_SCOPE_HINTS = (
    "spec",
    "specification",
    "protocol",
    "opcode",
    "register",
    "section",
    "chapter",
    "heading",
    "pdf",
    "docx",
    "xlsx",
    "codebase",
    "repo",
    "source code",
    "line ",
    "规范",
    "协议",
    "规格",
    "章节",
    "源码",
    "代码库",
    "行号",
    "路径",
    "页码",
)

SPEC_LOOKUP_HINTS = (
    "spec",
    "specification",
    "protocol",
    "opcode",
    "command",
    "register",
    "section",
    "chapter",
    "status code",
    "feature id",
    "feature identifier",
    "nvme",
    "规范",
    "协议",
    "规格",
    "规格书",
    "命令",
    "寄存器",
    "章节",
    "条目",
    "状态码",
)

HOLISTIC_OVERVIEW_MARKERS = (
    "整体思路",
    "整体框架",
    "整体结构",
    "整体逻辑",
    "整体设计",
    "总体思路",
    "总体框架",
    "总体结构",
    "总体逻辑",
    "整体上",
    "从整体上",
    "先整体",
    "总览",
    "全貌",
    "全局",
    "主线",
    "big picture",
    "high level",
    "high-level",
    "overall idea",
    "overall structure",
    "overall flow",
    "overview",
)

HOLISTIC_EXPLAIN_MARKERS = (
    "解释",
    "解读",
    "说明",
    "分析",
    "梳理",
    "讲讲",
    "讲一下",
    "讲下",
    "介绍",
    "看懂",
    "explain",
    "interpret",
    "analyze",
    "analyse",
)

HOLISTIC_DIRECT_PHRASES = (
    "整体思路",
    "整体框架",
    "整体结构",
    "总体思路",
    "总体框架",
    "总体结构",
)

TABLE_REFERENCE_HINTS = (
    "表格",
    "这张表",
    "这个表",
    "该表",
    "table",
    "tsv",
    "csv",
)

TABLE_REFORMAT_HINTS = (
    "整理",
    "重整",
    "重排",
    "排版",
    "表格化",
    "格式",
    "格式化",
    "优化",
    "美化",
    "规范",
    "改成",
    "改为",
    "再整理",
    "再排",
    "再调整",
    "重新整理",
    "format",
    "reformat",
    "rearrange",
    "clean up",
    "tidy",
    "markdown",
)


def text_has_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(hint in lowered for hint in hints)
