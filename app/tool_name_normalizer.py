from __future__ import annotations

def normalize_tool_name(name: str) -> str:
    return str(name or "").strip().lower()
