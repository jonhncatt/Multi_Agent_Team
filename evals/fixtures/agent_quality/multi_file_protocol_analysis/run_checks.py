from __future__ import annotations

from pathlib import Path
import sys


text = Path("REPORT.md").read_text(encoding="utf-8")
required = (
    "# Protocol Review",
    "0x7E",
    "little-endian",
    "64",
    "CRC-16/CCITT-FALSE",
    "0x1021",
    "0xFFFF",
    "FRAME_ERR_CHECKSUM",
    "-3",
    "legacy",
    "network order",
)
missing = [item for item in required if item.lower() not in text.lower()]
if "TODO" in text or missing:
    print("REPORT.md validation failed; missing:", ", ".join(missing))
    sys.exit(1)
print("REPORT.md validation passed")
