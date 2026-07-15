import os
from pathlib import Path

configured = os.environ.get("VP_EVAL_TEAM_SKILLS_ROOT", "").strip()
root = Path(configured) if configured else Path(".eval_runtime/vp_install/skills/team")
skill = root / "protocol-review" / "SKILL.md"
if not skill.is_file():
    print("team skill missing")
    raise SystemExit(1)
text = skill.read_text(encoding="utf-8")
required = [
    "description: Use when reviewing protocol parser changes against repository specifications.",
    "incompatible wire-format changes",
    "python -m pytest tests/protocol -q",
]
missing = [item for item in required if item not in text]
if missing:
    print("missing:", ", ".join(missing))
    raise SystemExit(1)
print("team skill update fixture passed")
