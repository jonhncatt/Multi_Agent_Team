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
