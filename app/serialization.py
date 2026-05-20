from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


def dump_model(value: Any) -> Any:
    """Convert common model-like values into JSON-friendly Python data."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): dump_model(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [dump_model(item) for item in value]
    if is_dataclass(value):
        return dump_model(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dump_model(model_dump())
    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        return dump_model(legacy_dict())
    return str(value)


def safe_model_dump(value: Any) -> Any:
    """Best-effort JSON-friendly dump for SDK/provider objects.

    This is intentionally more defensive than dump_model() around model_dump()
    because provider stream events may be None or partially constructed objects.
    """
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return dump_model(model_dump())
        except Exception:
            return str(value)
    return dump_model(value)
