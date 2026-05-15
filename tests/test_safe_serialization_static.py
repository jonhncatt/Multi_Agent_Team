from __future__ import annotations

from pathlib import Path


def test_office_runtime_has_no_direct_model_dump_calls() -> None:
    path = Path("packages/office_modules/office_agent_runtime.py")
    text = path.read_text(encoding="utf-8")

    assert ".model_dump(" not in text
