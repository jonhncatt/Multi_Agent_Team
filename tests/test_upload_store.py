from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from app.storage import UploadStore


class _FakeUpload:
    def __init__(self, name: str, data: bytes, *, content_type: str = "text/plain") -> None:
        self.filename = name
        self.content_type = content_type
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_upload_store_streams_with_size_limit_and_cleans_partial_file(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)

    with pytest.raises(ValueError, match="File too large"):
        asyncio.run(store.save_upload(_FakeUpload("large.txt", b"abcdef"), max_bytes=3))

    stored_files = [path for path in tmp_path.iterdir() if path.is_file() and path.name != "index.json"]
    assert stored_files == []


def test_upload_store_reads_per_upload_metadata_when_index_is_not_rewritten(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)
    store._INDEX_REWRITE_LIMIT_BYTES = 0

    meta = asyncio.run(store.save_upload(_FakeUpload("note.txt", b"hello"), max_bytes=100))

    assert meta["metadata_index_mode"] == "per_upload_metadata"
    loaded = store.get_many([meta["id"]])
    assert loaded and loaded[0]["original_name"] == "note.txt"
    assert loaded[0]["bytes_written"] == 5
