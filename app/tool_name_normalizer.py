from __future__ import annotations


_TOOL_NAME_ALIASES = {
    "analyze_image": "image_read",
    "download_web_file": "web_download",
    "extract_msg_attachments": "mail_extract_attachments",
    "extract_zip": "archive_extract",
    "fetch_web": "web_fetch",
    "image_analysis": "image_read",
    "image_analyze": "image_read",
    "image_ocr": "image_read",
    "image_reader": "image_read",
    "image_to_text": "image_read",
    "image_tool": "image_read",
    "list_sessions": "sessions_list",
    "ocr_image": "image_read",
    "read_image": "image_read",
    "read_section_by_heading": "read_section",
    "read_session_history": "sessions_history",
    "search_web": "web_search",
    "view_image": "image_inspect",
}

_IMAGE_READ_TOOL_HINTS = (
    "image",
    "screenshot",
    "picture",
    "photo",
    "vision",
)

_IMAGE_READ_ACTION_HINTS = (
    "read",
    "ocr",
    "analy",
    "describe",
    "caption",
    "tool",
)

_IMAGE_INSPECT_ACTION_HINTS = (
    "inspect",
    "meta",
    "info",
    "size",
    "dimension",
)


def normalize_tool_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    lowered = raw.lower()
    alias = _TOOL_NAME_ALIASES.get(lowered)
    if alias:
        return alias
    if any(hint in lowered for hint in _IMAGE_READ_TOOL_HINTS):
        if any(hint in lowered for hint in _IMAGE_INSPECT_ACTION_HINTS):
            return "image_inspect"
        if any(hint in lowered for hint in _IMAGE_READ_ACTION_HINTS):
            return "image_read"
    return raw
