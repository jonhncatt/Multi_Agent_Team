from __future__ import annotations

from pathlib import Path

from app.attachment_argument_rewriter import (
    attachment_paths,
    build_attachment_tool_guidance,
    rewrite_attachment_tool_arguments,
)


def test_attachment_paths_filters_by_kind(tmp_path: Path) -> None:
    attachments = [
        {"kind": "image", "path": str(tmp_path / "diagram.png")},
        {"kind": "document", "path": str(tmp_path / "report.docx")},
    ]

    assert attachment_paths(attachments, kind="image") == [str(tmp_path / "diagram.png")]
    assert attachment_paths(attachments, kind="document") == [str(tmp_path / "report.docx")]


def test_attachment_guidance_mentions_image_paths(tmp_path: Path) -> None:
    attachments = [{"kind": "image", "path": str(tmp_path / "diagram.png")}]
    guidance = build_attachment_tool_guidance(attachments, locale="zh-CN")

    assert str(tmp_path / "diagram.png") in guidance


def test_attachment_rewriter_maps_legacy_image_keys_and_attachment_ids(tmp_path: Path) -> None:
    image_path = tmp_path / "diagram.png"
    attachments = [{"id": "att-1", "kind": "image", "name": "diagram.png", "path": str(image_path)}]

    rewritten = rewrite_attachment_tool_arguments(
        name="image_read",
        arguments={"attachment_id": "att-1"},
        attachments=attachments,
    )

    assert rewritten == {"path": str(image_path)}


def test_attachment_rewriter_resolves_document_and_archive_paths(tmp_path: Path) -> None:
    doc_path = tmp_path / "notes.md"
    zip_path = tmp_path / "bundle.zip"
    attachments = [
        {"id": "doc-1", "kind": "document", "name": "notes.md", "path": str(doc_path)},
        {"id": "zip-1", "kind": "document", "name": "bundle.zip", "path": str(zip_path)},
    ]

    rewritten_doc = rewrite_attachment_tool_arguments(
        name="read_file",
        arguments={"path": "notes.md"},
        attachments=attachments,
    )
    rewritten_zip = rewrite_attachment_tool_arguments(
        name="archive_extract",
        arguments={"zip_path": "zip-1"},
        attachments=attachments,
    )

    assert rewritten_doc == {"path": str(doc_path)}
    assert rewritten_zip == {"zip_path": str(zip_path)}
