from __future__ import annotations

import re
from typing import Any


_REASONING_MODEL_PATTERN = re.compile(
    r"(?:^|[/:])(?:gpt-5\.6|gpt-6-astra)(?:[-.:]|$)",
    flags=re.IGNORECASE,
)


def supports_reasoning_effort(model: Any) -> bool:
    """Return whether the selected model accepts an explicit reasoning effort."""

    return bool(_REASONING_MODEL_PATTERN.search(str(model or "").strip()))
