from pathlib import Path

text = Path("PLAN.md").read_text(encoding="utf-8")
required = [
    "existing wire format",
    "Verification",
    "Compatibility check",
]
missing = [item for item in required if item.lower() not in text.lower()]
if missing:
    print("missing:", ", ".join(missing))
    raise SystemExit(1)
print("runtime steer fixture passed")
