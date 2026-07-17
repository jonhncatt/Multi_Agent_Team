from pathlib import Path

text = Path("src/calculator.cpp").read_text(encoding="utf-8")
required = [
    "values == 0",
    "out_sum == 0",
    "values[index] > 0",
    "*out_sum = sum",
    "return 0",
]
missing = [item for item in required if item not in text]
if missing:
    print("implementation is still incomplete:", ", ".join(missing))
    raise SystemExit(1)
print("test failure recovery fixture passed")
