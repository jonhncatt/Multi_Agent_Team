from __future__ import annotations

import os
from pathlib import Path
import re


team_root = Path(os.environ["VP_EVAL_TEAM_SKILLS_ROOT"])
skill_path = team_root / "translation-maintenance" / "SKILL.md"
text = skill_path.read_text(encoding="utf-8")

if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text):
    raise SystemExit("The maintained SKILL.md still contains Chinese text.")

required_literals = (
    "name: translation-maintenance",
    "python scripts/audit_labels.py --format json",
    "git status --short",
    "git push origin release",
    "deploy-tool production --confirm",
)
missing = [item for item in required_literals if item not in text]
if missing:
    raise SystemExit(f"The translated SKILL.md lost required reference content: {', '.join(missing)}")

print("skill maintenance translation checks passed")
