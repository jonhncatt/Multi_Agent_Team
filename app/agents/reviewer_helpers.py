from __future__ import annotations

from typing import Any


def reviewer_readonly_tool_names() -> list[str]:
    return [
        "list_directory",
        "read_text_file",
        "search_text_in_file",
        "multi_query_search",
        "doc_index_build",
        "read_section_by_heading",
        "table_extract",
        "fact_check_file",
        "search_codebase",
        "search_web",
        "fetch_web",
    ]


def normalize_reviewer_verdict(
    agent: Any,
    raw_verdict: Any,
    *,
    risks: Any,
    followups: Any,
    spec_lookup_request: bool,
    evidence_required_mode: bool,
    readonly_checks: list[str],
    conflict_has_conflict: bool,
    conflict_realtime_only: bool,
    web_tools_success: bool,
    attachment_context_available: bool = False,
) -> str:
    verdict = str(raw_verdict or "pass").strip().lower()
    if verdict == "needs_attention":
        if (conflict_has_conflict and not (conflict_realtime_only and web_tools_success)) or (
            spec_lookup_request and "search_text_in_file" not in set(readonly_checks)
        ):
            return "block"
        if attachment_context_available and not readonly_checks:
            return "warn"
        return "warn"
    if verdict in {"pass", "warn", "block"}:
        if verdict == "block" and conflict_realtime_only and web_tools_success:
            return "warn"
        if verdict == "block" and attachment_context_available and not readonly_checks and not conflict_has_conflict:
            return "warn"
        return verdict

    has_risks = bool(agent._normalize_string_list(risks or [], limit=4, item_limit=180))
    has_followups = bool(agent._normalize_string_list(followups or [], limit=4, item_limit=180))
    readonly_set = set(readonly_checks)
    if conflict_has_conflict and not (conflict_realtime_only and web_tools_success):
        return "block"
    if spec_lookup_request and "search_text_in_file" not in readonly_set:
        return "block"
    if evidence_required_mode and not readonly_set:
        return "block"
    if has_risks or has_followups:
        return "warn"
    return "pass"


def summarize_reviewer_tool_result(agent: Any, *, name: str, result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return f"{name} 返回了非结构化结果。"

    if not bool(result.get("ok")):
        return f"{name} 失败: {agent._shorten(result.get('error') or 'unknown error', 120)}"

    if name == "fact_check_file":
        verdict = str(result.get("verdict") or "unknown").strip() or "unknown"
        evidence_count = int(result.get("evidence_count") or 0)
        queries = agent._normalize_string_list(result.get("queries_used") or [], limit=3, item_limit=40)
        query_text = ", ".join(queries) if queries else "(none)"
        return f"fact_check_file verdict={verdict}, evidence={evidence_count}, queries={query_text}"

    if name == "search_text_in_file":
        query = str(result.get("query") or "").strip() or "(empty)"
        matches = list(result.get("matches") or [])
        match_count = int(result.get("match_count") or len(matches))
        first = matches[0] if matches else {}
        page_hint = int(first.get("page_hint") or 0)
        matched_text = agent._shorten(first.get("matched_text") or "", 60) if first else ""
        if page_hint > 0:
            return f"search_text_in_file query={query}, matches={match_count}, first_page={page_hint}, first_hit={matched_text or '(none)'}"
        return f"search_text_in_file query={query}, matches={match_count}, first_hit={matched_text or '(none)'}"

    if name == "multi_query_search":
        queries = agent._normalize_string_list(result.get("queries") or [], limit=4, item_limit=40)
        matches = list(result.get("matches") or [])
        match_count = int(result.get("match_count") or len(matches))
        first = matches[0] if matches else {}
        page_hint = int(first.get("page_hint") or 0)
        return f"multi_query_search queries={', '.join(queries) or '(none)'}, matches={match_count}, first_page={page_hint or 'n/a'}"

    if name == "doc_index_build":
        page_count = int(result.get("page_count") or 0)
        heading_count = int(result.get("heading_count") or 0)
        cached = bool(result.get("cached"))
        return f"doc_index_build cached={str(cached).lower()}, pages={page_count}, headings={heading_count}"

    if name == "read_section_by_heading":
        heading = str(result.get("matched_heading") or result.get("matched_section") or "").strip() or "(not found)"
        page_start = int(result.get("page_start") or 0)
        page_end = int(result.get("page_end") or 0)
        if page_start > 0:
            return f"read_section_by_heading matched={heading}, pages={page_start}-{page_end or page_start}"
        return f"read_section_by_heading matched={heading}"

    if name == "table_extract":
        tables = list(result.get("tables") or [])
        table_count = int(result.get("table_count") or len(tables))
        first = tables[0] if tables else {}
        page = int(first.get("page") or 0)
        rows = len(first.get("rows") or []) if isinstance(first, dict) else 0
        if page > 0:
            return f"table_extract tables={table_count}, first_page={page}, first_rows={rows}"
        return f"table_extract tables={table_count}, first_rows={rows}"

    if name == "search_codebase":
        matches = list(result.get("matches") or [])
        match_count = int(result.get("match_count") or len(matches))
        first = matches[0] if matches else {}
        path = str(first.get("path") or "").strip()
        line = int(first.get("line") or 0)
        if path:
            return f"search_codebase matches={match_count}, first={path}:{line or '?'}"
        return f"search_codebase matches={match_count}"

    if name == "search_web":
        query = str(result.get("query") or "").strip() or "(empty)"
        count = int(result.get("count") or 0)
        engine = str(result.get("engine") or "unknown").strip() or "unknown"
        rows = list(result.get("results") or [])
        first = rows[0] if rows else {}
        first_title = agent._shorten(first.get("title") or "", 60) if isinstance(first, dict) else ""
        return f"search_web query={query}, count={count}, engine={engine}, first={first_title or '(none)'}"

    if name == "fetch_web":
        url = str(result.get("url") or "").strip() or "(empty)"
        source_format = str(result.get("source_format") or result.get("content_type") or "unknown").strip()
        length = int(result.get("length") or 0)
        warning = agent._shorten(result.get("warning") or "", 80)
        if warning:
            return (
                f"fetch_web url={agent._shorten(url, 80)}, format={source_format or 'unknown'}, "
                f"length={length}, warning={warning}"
            )
        return f"fetch_web url={agent._shorten(url, 80)}, format={source_format or 'unknown'}, length={length}"

    if name == "read_text_file":
        path = str(result.get("path") or "").strip()
        length = int(result.get("length") or 0)
        start_char = int(result.get("start_char") or 0)
        end_char = int(result.get("end_char") or 0)
        truncated = bool(result.get("truncated"))
        if bool(result.get("line_mode")):
            start_line = int(result.get("start_line") or 0)
            end_line = int(result.get("end_line") or 0)
            total_lines = int(result.get("total_lines") or 0)
            return (
                f"read_text_file path={agent._shorten(path, 60)}, chars={length}, "
                f"lines={start_line}-{end_line}/{total_lines}, truncated={str(truncated).lower()}"
            )
        return (
            f"read_text_file path={agent._shorten(path, 60)}, chars={length}, "
            f"range={start_char}-{end_char}, truncated={str(truncated).lower()}"
        )

    if name == "list_directory":
        path = str(result.get("path") or "").strip() or "."
        entries = result.get("entries") or []
        count = len(entries) if isinstance(entries, list) else 0
        return f"list_directory path={agent._shorten(path, 60)}, entries={count}"

    return f"{name} 已完成复核。"
