from pathlib import Path

text = Path("HANDOFF.md").read_text(encoding="utf-8").lower()
required = ["orion-742", "clang-cl", "c abi"]
missing = [item for item in required if item not in text]
if missing:
    print("missing:", ", ".join(missing))
    raise SystemExit(1)
print("long thread compaction fixture passed")
