from __future__ import annotations

from pathlib import Path
from typing import Any

from app.i18n import translate


_IMAGE_TOOL_NAMES = {"image_read", "image_inspect"}
_DOCUMENT_READ_TOOL_NAMES = {
    "read_file",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "read_section",
    "table_extract",
    "fact_check_file",
}


def attachment_paths(attachments: list[dict[str, Any]], *, kind: str | None = None) -> list[str]:
    wanted_kind = str(kind or "").strip().lower()
    paths: list[str] = []
    for meta in attachments:
        if not isinstance(meta, dict):
            continue
        meta_kind = str(meta.get("kind") or "").strip().lower()
        if wanted_kind and meta_kind != wanted_kind:
            continue
        path = str(meta.get("path") or "").strip()
        if path:
            paths.append(path)
    return paths


def build_attachment_tool_guidance(attachments: list[dict[str, Any]], *, locale: str) -> str:
    if not attachments:
        return ""
    lines: list[str] = [
        translate(locale, "runtime.attachment_guidance.intro"),
        translate(locale, "runtime.attachment_guidance.no_guess"),
    ]
    image_paths = attachment_paths(attachments, kind="image")
    if image_paths:
        lines.append(translate(locale, "runtime.attachment_guidance.image"))
    document_paths = attachment_paths(attachments, kind="document")
    if document_paths:
        lines.append(translate(locale, "runtime.attachment_guidance.document"))
        lines.append(translate(locale, "runtime.attachment_guidance.msg"))
    return "\n".join(lines)


def _path_exists(raw_path: str) -> bool:
    value = str(raw_path or "").strip()
    if not value:
        return False
    try:
        return Path(value).expanduser().exists()
    except Exception:
        return False


def _first_attachment_path(
    attachments: list[dict[str, Any]],
    *,
    kind: str = "",
) -> str:
    paths = attachment_paths(attachments, kind=kind or None)
    return paths[0] if len(paths) == 1 else ""


def _resolve_attachment_argument_path(
    raw_value: Any,
    attachments: list[dict[str, Any]],
    *,
    preferred_kind: str = "",
) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return raw
    if _path_exists(raw):
        return raw

    wanted_kind = str(preferred_kind or "").strip().lower()
    candidate_paths: list[str] = []
    raw_basename = Path(raw).name.strip() if raw else ""
    for meta in attachments:
        if not isinstance(meta, dict):
            continue
        meta_kind = str(meta.get("kind") or "").strip().lower()
        if wanted_kind and meta_kind != wanted_kind:
            continue
        meta_path = str(meta.get("path") or "").strip()
        meta_id = str(meta.get("id") or "").strip()
        meta_name = str(meta.get("name") or meta.get("original_name") or "").strip()
        meta_basename = Path(meta_path).name.strip() if meta_path else ""
        candidate_keys = {meta_path, meta_id, meta_name, meta_basename}
        if raw in candidate_keys or (raw_basename and raw_basename in candidate_keys):
            return meta_path or raw
        if meta_path:
            candidate_paths.append(meta_path)

    if wanted_kind and len(candidate_paths) == 1:
        return candidate_paths[0]
    return raw


def rewrite_attachment_tool_arguments(
    *,
    name: str,
    arguments: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = dict(arguments or {})
    tool_name = str(name or "").strip()
    if tool_name in _IMAGE_TOOL_NAMES:
        for legacy_key in ("image_path", "file_path", "filepath", "file", "image", "attachment", "attachment_id"):
            if "path" not in normalized and legacy_key in normalized:
                normalized["path"] = normalized.pop(legacy_key)
    if tool_name in _IMAGE_TOOL_NAMES and "path" not in normalized and "image_path" in normalized:
        normalized["path"] = normalized.pop("image_path")

    if tool_name in _IMAGE_TOOL_NAMES and "path" in normalized:
        normalized["path"] = _resolve_attachment_argument_path(
            normalized.get("path"),
            attachments,
            preferred_kind="image",
        )
    elif tool_name in _IMAGE_TOOL_NAMES:
        fallback_path = _first_attachment_path(attachments, kind="image")
        if fallback_path:
            normalized["path"] = fallback_path
    elif tool_name in _DOCUMENT_READ_TOOL_NAMES and "path" in normalized:
        normalized["path"] = _resolve_attachment_argument_path(
            normalized.get("path"),
            attachments,
            preferred_kind="document",
        )
    elif tool_name in _DOCUMENT_READ_TOOL_NAMES:
        fallback_path = _first_attachment_path(attachments, kind="document")
        if fallback_path:
            normalized["path"] = fallback_path
    elif tool_name in {"list_dir", "glob_file_search", "search_codebase"} and "path" in normalized:
        normalized["path"] = _resolve_attachment_argument_path(normalized.get("path"), attachments)
    elif tool_name == "archive_extract" and "zip_path" in normalized:
        normalized["zip_path"] = _resolve_attachment_argument_path(normalized.get("zip_path"), attachments)
    elif tool_name == "mail_extract_attachments" and "msg_path" in normalized:
        normalized["msg_path"] = _resolve_attachment_argument_path(normalized.get("msg_path"), attachments)
    return normalized
