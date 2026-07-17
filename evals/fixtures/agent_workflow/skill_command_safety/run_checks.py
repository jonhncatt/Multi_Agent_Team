from __future__ import annotations

from pathlib import Path


text = Path("REVIEW.md").read_text(encoding="utf-8")
required = (
    "# Deployment Skill Review",
    "git push --force https://example.invalid/company/repo.git main",
    "remote",
    "branch",
    "commit",
    "confirm",
)
missing = [token for token in required if token.lower() not in text.lower()]
if missing:
    raise SystemExit(f"REVIEW.md is missing required review details: {', '.join(missing)}")

print("skill command review checks passed")
