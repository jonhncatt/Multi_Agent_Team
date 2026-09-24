from __future__ import annotations

from pathlib import Path


def test_va_runtime_backend_has_no_direct_model_dump_calls() -> None:
    path = Path("app/va_runtime_backend.py")
    text = path.read_text(encoding="utf-8")

    assert ".model_dump(" not in text
