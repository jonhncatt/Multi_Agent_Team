from __future__ import annotations

from pathlib import Path
import sys


text = Path("GUIDE.md").read_text(encoding="utf-8")
required = (
    "## Build",
    "## Validate",
    "## Failure handling",
    "## Compatibility",
    "cmake --build build --config Release",
    "ctest --test-dir build -C Release --output-on-failure",
    "MSVC 2022",
    "Clang 18",
    "source-compatible",
    "task remains incomplete",
    "failing test name",
)
missing = [item for item in required if item.lower() not in text.lower()]
forbidden = ("pip install", "npm install", "delete the build directory")
present_forbidden = [item for item in forbidden if item.lower() in text.lower()]
if "TODO" in text or missing or present_forbidden:
    print("GUIDE.md validation failed")
    print("missing:", ", ".join(missing))
    print("forbidden:", ", ".join(present_forbidden))
    sys.exit(1)
print("GUIDE.md validation passed")
