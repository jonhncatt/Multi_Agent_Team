from __future__ import annotations

from pathlib import Path
from typing import Any


_MAX_EVIDENCE_ITEMS = 8
_PREVIEW_CHARS = 12000
_SUMMARY_CHARS = 700
_INLINE_PREVIEW_MAX_BYTES = 5 * 1024 * 1024
_TEXT_SUFFIXES = {
    ".atom",
    ".csv",
    ".css",
    ".html",
    ".js",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rss",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_DOCUMENT_SUFFIXES = {
    ".docx",
    ".doc",
    ".msg",
    ".pdf",
    ".pptx",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".xltx",
    ".xltm",
}


def _safe_path(raw: str) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return Path(value).expanduser().resolve()
    except Exception:
        return None


def _source_format_for_suffix(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".pdf":
        return "pdf_text_extracted"
    if suffix in {".doc", ".docx"}:
        return "docx_text_extracted"
    if suffix == ".msg":
        return "msg_text_extracted"
    if suffix in {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return "xlsx_text_extracted"
    if suffix == ".pptx":
        return "pptx_text_extracted"
    if suffix in {".atom", ".rss", ".xml"}:
        return "xml_text_extracted"
    return "text_utf8"


def _compact_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _image_probe(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return {
                "width": int(image.width),
                "height": int(image.height),
                "format": str(image.format or ""),
                "mode": str(image.mode or ""),
            }
    except Exception as exc:
        return {"warning": f"image metadata unavailable: {exc}"}


def _extract_document_preview(path: Path, *, locale: str) -> tuple[str, dict[str, Any]]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".msg":
            from app.attachments import extract_outlook_msg_payload

            payload = extract_outlook_msg_payload(str(path), max_chars=_PREVIEW_CHARS, locale=locale) or {}
            return str(payload.get("content") or ""), {
                "email_meta": dict(payload.get("email_meta") or {}),
                "attachment_list": list(payload.get("attachment_list") or []),
            }
        from app.attachments import extract_document_text

        return str(extract_document_text(str(path), max_chars=_PREVIEW_CHARS, locale=locale) or ""), {}
    except Exception as exc:
        return "", {"warning": f"document preview failed: {exc}"}


def build_attachment_evidence_pack(
    attachments: list[dict[str, Any]],
    *,
    locale: str = "zh-CN",
    max_items: int = _MAX_EVIDENCE_ITEMS,
) -> list[dict[str, Any]]:
    pack: list[dict[str, Any]] = []
    for meta in list(attachments or [])[: max(1, int(max_items))]:
        if not isinstance(meta, dict):
            continue
        path = _safe_path(str(meta.get("path") or ""))
        name = str(meta.get("original_name") or meta.get("name") or "").strip()
        mime = str(meta.get("mime") or "").strip()
        kind = str(meta.get("kind") or "").strip().lower()
        item: dict[str, Any] = {
            "id": str(meta.get("id") or "").strip(),
            "name": name,
            "mime": mime,
            "kind": kind or "other",
            "path": str(path or meta.get("path") or ""),
            "exists": bool(path and path.exists()),
            "summary": "",
            "preview": "",
            "source_format": "",
            "read_hint": {},
        }
        if not path or not path.exists():
            item["summary"] = "attachment path is missing or no longer available"
            pack.append(item)
            continue

        suffix = path.suffix.lower()
        try:
            item["size"] = int(path.stat().st_size)
        except Exception:
            item["size"] = int(meta.get("size") or 0)

        if kind == "image" or mime.lower().startswith("image/"):
            image_meta = _image_probe(path)
            item.update(image_meta)
            item["source_format"] = "image_metadata"
            item["summary"] = f"{name or path.name} · image"
            if item.get("width") and item.get("height"):
                item["summary"] += f" · {item['width']}x{item['height']}"
            item["read_hint"] = {"tool": "image_read", "path": str(path)}
            pack.append(item)
            continue

        can_preview = suffix in _TEXT_SUFFIXES or suffix in _DOCUMENT_SUFFIXES or kind == "document"
        if can_preview:
            if int(item.get("size") or 0) > _INLINE_PREVIEW_MAX_BYTES:
                item["source_format"] = _source_format_for_suffix(suffix)
                item["summary"] = _compact_text(
                    f"{name or path.name} · {item['source_format']} · large file, use targeted read/search tools",
                    _SUMMARY_CHARS,
                )
                item["has_more"] = True
                item["read_hint"] = {
                    "tool": "read",
                    "path": str(path),
                    "max_chars": 24000,
                    "followups": ["search_file", "search_file_multi", "read_section", "table_extract"],
                }
                pack.append(item)
                continue
            preview, extra = _extract_document_preview(path, locale=locale)
            item.update(extra)
            item["source_format"] = _source_format_for_suffix(suffix)
            item["preview"] = _compact_text(preview, _PREVIEW_CHARS)
            total_len = len(preview or "")
            if suffix == ".msg" and item.get("email_meta"):
                subject = str((item.get("email_meta") or {}).get("subject") or "").strip()
                item["summary"] = _compact_text(f"{name or path.name} · email · {subject or 'no subject'}", _SUMMARY_CHARS)
            else:
                first_line = next((line.strip() for line in str(preview or "").splitlines() if line.strip()), "")
                item["summary"] = _compact_text(f"{name or path.name} · {item['source_format']} · {first_line}", _SUMMARY_CHARS)
            item["has_more"] = bool(total_len >= _PREVIEW_CHARS or int(item.get("size") or 0) > _PREVIEW_CHARS)
            item["read_hint"] = {
                "tool": "read",
                "path": str(path),
                "max_chars": 24000,
                "followups": ["search_file", "search_file_multi", "read_section", "table_extract"],
            }
            pack.append(item)
            continue

        item["source_format"] = "binary_or_unknown"
        item["summary"] = f"{name or path.name} · {mime or suffix or 'unknown'} · use read/search tools if needed"
        item["read_hint"] = {"tool": "read", "path": str(path), "max_chars": 12000}
        pack.append(item)
    return pack
