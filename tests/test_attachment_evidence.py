from __future__ import annotations

from app.attachment_evidence import build_attachment_evidence_pack


def test_attachment_evidence_pack_uses_requested_preview_budget(tmp_path) -> None:
    attachment = tmp_path / "meeting.txt"
    attachment.write_text("A" * 20_000, encoding="utf-8")

    pack = build_attachment_evidence_pack(
        [
            {
                "id": "att-1",
                "name": "meeting.txt",
                "kind": "document",
                "path": str(attachment),
            }
        ],
        preview_chars=18_000,
    )

    assert len(pack[0]["preview"]) > 12_000
    assert pack[0]["has_more"] is True
