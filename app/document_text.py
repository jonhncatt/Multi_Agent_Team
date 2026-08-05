from __future__ import annotations

import io
import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path


_DOC_CACHE_VERSION = "pdf-pages-v1"
_DOC_CACHE_DIR = (Path(__file__).resolve().parent / "data" / "document_cache").resolve()


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars - 64
    return f"{text[:keep]}\n\n[内容已截断，原始长度 {len(text)} 字符]"


def _score_extracted_text(text: str) -> int:
    compact = re.sub(r"\s+", "", text or "")
    return len(compact)


def normalize_lookup_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s./:-]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _cache_key_for_path(path: Path) -> str:
    stat = path.stat()
    payload = f"{_DOC_CACHE_VERSION}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return sha256(payload.encode("utf-8")).hexdigest()


def _cache_path_for_pdf(path: Path) -> Path:
    return _DOC_CACHE_DIR / f"{_cache_key_for_path(path)}.json"


def _read_cached_pdf_pages(path: Path) -> list[tuple[int, str]] | None:
    cache_path = _cache_path_for_pdf(path)
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("version") != _DOC_CACHE_VERSION:
        return None
    pages_raw = payload.get("pages")
    if not isinstance(pages_raw, list):
        return None
    pages: list[tuple[int, str]] = []
    for item in pages_raw:
        if not isinstance(item, dict):
            continue
        try:
            page_num = int(item.get("page") or 0)
        except Exception:
            page_num = 0
        body = str(item.get("text") or "")
        if page_num > 0 and body.strip():
            pages.append((page_num, body))
    return pages or None


def _write_cached_pdf_pages(path: Path, pages: list[tuple[int, str]]) -> None:
    try:
        _DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _cache_path_for_pdf(path)
        payload = {
            "version": _DOC_CACHE_VERSION,
            "source_path": str(path.resolve()),
            "pages": [{"page": page_num, "text": body} for page_num, body in pages],
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(_DOC_CACHE_DIR),
            delete=False,
            suffix=".tmp",
        ) as fp:
            json.dump(payload, fp, ensure_ascii=False)
            temp_name = fp.name
        os.replace(temp_name, cache_path)
    except Exception:
        try:
            if "temp_name" in locals() and temp_name:
                Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass


def _append_page_block(chunks: list[str], idx: int, body: str, total: int, limit: int) -> tuple[int, bool]:
    normalized = (body or "").strip()
    if not normalized:
        return total, False
    block = f"\n--- Page {idx} ---\n{normalized}\n"
    chunks.append(block)
    total += len(block)
    return total, total >= limit


def _table_to_lines(table: list[list[object]] | None) -> list[str]:
    if not table:
        return []
    lines: list[str] = []
    for row in table:
        if not row:
            continue
        cells = [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
        if not any(cells):
            continue
        lines.append(" | ".join(cells))
    return lines


def _looks_like_heading_line(line: str) -> bool:
    raw = re.sub(r"\s+", " ", (line or "").strip())
    if not raw or len(raw) < 4 or len(raw) > 160:
        return False
    if "...." in raw or raw.count(".") > 10:
        return False
    if re.match(r"^\d+$", raw):
        return False
    patterns = (
        r"^\d+(?:\.\d+){0,5}\s+[A-Za-z].+",
        r"^(?:Annex|Appendix)\s+[A-Z0-9][A-Za-z0-9.\- ]*",
        r"^[A-Z][A-Z0-9 /&(),.-]{6,}$",
    )
    return any(re.match(pattern, raw) for pattern in patterns)


def extract_heading_entries_from_pages(
    pages: list[tuple[int, str]],
    max_headings: int = 400,
) -> list[dict[str, object]]:
    headings: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    requested_limit = int(max_headings)
    limit = None if requested_limit <= 0 else max(1, min(100_000, requested_limit))
    for page_num, body in pages:
        for line_idx, line in enumerate(body.splitlines(), start=1):
            raw = re.sub(r"\s+", " ", (line or "").strip())
            if not _looks_like_heading_line(raw):
                continue
            normalized = normalize_lookup_text(raw)
            if not normalized:
                continue
            key = (page_num, normalized)
            if key in seen:
                continue
            seen.add(key)
            section_match = re.match(r"^(\d+(?:\.\d+){0,5})\s+(.+)$", raw)
            entry = {
                "page": page_num,
                "line_index": line_idx,
                "heading": raw,
                "normalized": normalized,
                "section": section_match.group(1) if section_match else "",
                "title": section_match.group(2).strip() if section_match else raw,
            }
            headings.append(entry)
            if limit is not None and len(headings) >= limit:
                return headings
    return headings


def _pdfplumber_page_texts(raw_pdf: bytes) -> list[tuple[int, str]]:
    import pdfplumber  # lazy import

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text(layout=True) or "").strip()
            table_lines: list[str] = []
            try:
                for table in page.extract_tables() or []:
                    table_lines.extend(_table_to_lines(table))
            except Exception:
                table_lines = []

            body_parts: list[str] = []
            if text:
                body_parts.append(text)
            if table_lines:
                body_parts.append("[Extracted tables]")
                body_parts.extend(table_lines)
            body = "\n".join(body_parts).strip()
            if body:
                pages.append((idx, body))
    return pages


def _pypdf_page_texts(raw_pdf: bytes) -> list[tuple[int, str]]:
    from pypdf import PdfReader  # lazy import

    reader = PdfReader(io.BytesIO(raw_pdf))
    pages: list[tuple[int, str]] = []
    for idx, page in enumerate(reader.pages, start=1):
        body = (page.extract_text() or "").strip()
        if body:
            pages.append((idx, body))
    return pages


def extract_pdf_page_texts_from_bytes(raw_pdf: bytes) -> list[tuple[int, str]]:
    errors: list[str] = []
    for extractor in (_pdfplumber_page_texts, _pypdf_page_texts):
        try:
            pages = extractor(raw_pdf)
        except Exception as exc:
            errors.append(f"{extractor.__name__}: {exc}")
            continue
        if pages:
            return pages

    if errors:
        raise RuntimeError("; ".join(errors))
    return []


def extract_pdf_page_texts_from_path(path: Path) -> list[tuple[int, str]]:
    cached = _read_cached_pdf_pages(path)
    if cached is not None:
        return cached
    pages = extract_pdf_page_texts_from_bytes(path.read_bytes())
    if pages:
        _write_cached_pdf_pages(path, pages)
    return pages


def _extract_pdf_with_pdfplumber(raw_pdf: bytes, max_chars: int) -> str:
    chunks: list[str] = []
    total = 0
    limit = max(512, int(max_chars))
    for idx, body in _pdfplumber_page_texts(raw_pdf):
        total, reached = _append_page_block(chunks, idx, body, total, limit)
        if reached:
            break
    return truncate_text("".join(chunks).strip(), limit)


def _extract_pdf_with_pypdf(raw_pdf: bytes, max_chars: int) -> str:
    chunks: list[str] = []
    total = 0
    limit = max(512, int(max_chars))
    for idx, body in _pypdf_page_texts(raw_pdf):
        total, reached = _append_page_block(chunks, idx, body, total, limit)
        if reached:
            break
    return truncate_text("".join(chunks).strip(), limit)


def extract_pdf_text_from_bytes(raw_pdf: bytes, max_chars: int) -> str:
    limit = max(512, int(max_chars))
    candidates: list[tuple[int, str]] = []
    errors: list[str] = []

    for extractor in (_extract_pdf_with_pdfplumber, _extract_pdf_with_pypdf):
        try:
            text = extractor(raw_pdf, limit)
        except Exception as exc:
            errors.append(f"{extractor.__name__}: {exc}")
            continue
        if text.strip():
            candidates.append((_score_extracted_text(text), text))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    if errors:
        raise RuntimeError("; ".join(errors))
    return ""


def extract_pdf_text_from_path(path: Path, max_chars: int) -> str:
    pages = extract_pdf_page_texts_from_path(path)
    if not pages:
        return extract_pdf_text_from_bytes(path.read_bytes(), max_chars=max_chars)
    chunks: list[str] = []
    total = 0
    limit = max(512, int(max_chars))
    for idx, body in pages:
        total, reached = _append_page_block(chunks, idx, body, total, limit)
        if reached:
            break
    return truncate_text("".join(chunks).strip(), limit)


def clear_pdf_cache_for_path(path: Path) -> Path:
    cache_path = _cache_path_for_pdf(path)
    cache_path.unlink(missing_ok=True)
    return cache_path


def build_pdf_document_index(path: Path, force_rebuild: bool = False, max_headings: int = 400) -> dict[str, object]:
    if force_rebuild:
        clear_pdf_cache_for_path(path)
    pages = extract_pdf_page_texts_from_path(path)
    headings = extract_heading_entries_from_pages(pages, max_headings=max_headings)
    table_pages = [page_num for page_num, body in pages if "[Extracted tables]" in body]
    return {
        "path": str(path.resolve()),
        "cache_path": str(_cache_path_for_pdf(path)),
        "cached": _cache_path_for_pdf(path).is_file(),
        "page_count": len(pages),
        "heading_count": len(headings),
        "headings": headings,
        "table_pages": table_pages,
    }


def extract_pdf_tables_from_path(
    path: Path,
    page_numbers: list[int] | None = None,
    max_tables: int = 10,
    max_rows: int = 40,
) -> list[dict[str, object]]:
    import pdfplumber  # lazy import

    page_filter = set(page_numbers or [])
    requested_table_limit = int(max_tables)
    table_limit = None if requested_table_limit <= 0 else max(1, min(100_000, requested_table_limit))
    requested_row_limit = int(max_rows)
    row_limit = None if requested_row_limit <= 0 else max(1, min(100_000, requested_row_limit))
    tables: list[dict[str, object]] = []
    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            if page_filter and idx not in page_filter:
                continue
            raw_tables = page.extract_tables() or []
            for table in raw_tables:
                rows = _table_to_lines(table)
                if not rows:
                    continue
                tables.append(
                    {
                        "page": idx,
                        "rows": rows if row_limit is None else rows[:row_limit],
                    }
                )
                if table_limit is not None and len(tables) >= table_limit:
                    return tables
    return tables
