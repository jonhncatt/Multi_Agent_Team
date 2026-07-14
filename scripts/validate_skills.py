from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.skill_registry import SKILL_SCOPE_TEAM, SkillRegistry  # noqa: E402


PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\s]+"),
    re.compile(r"/(?:Users|home)/[^/\s]+"),
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"),
)


def validate_repository_skills(repository_root: Path) -> dict[str, Any]:
    root = repository_root.expanduser().resolve()
    registry = SkillRegistry(repository_root=root, migrate_legacy=False)
    entries = registry.list_skills(include_content=True)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    names: dict[str, list[str]] = {}

    for item in entries:
        key = str(item.get("key") or "")
        name = str(item.get("name") or "")
        names.setdefault(name, []).append(key)
        if item.get("validation_status") != "valid":
            errors.append({"key": key, "kind": "schema", "message": str(item.get("description") or "invalid skill")[:300]})
            continue
        if item.get("scope") == SKILL_SCOPE_TEAM:
            documents = [("SKILL.md", str(item.get("content") or ""))]
            for resource in registry.list_resources(key):
                try:
                    resource_payload = registry.load_resource(key, resource)
                except ValueError as exc:
                    warnings.append({"key": f"{key}:{resource}", "kind": "resource_skipped", "message": str(exc)[:300]})
                    continue
                documents.append((resource, str(resource_payload.get("content") or "")))
            for relative_path, content in documents:
                location_key = key if relative_path == "SKILL.md" else f"{key}:{relative_path}"
                for pattern in PERSONAL_PATH_PATTERNS:
                    if pattern.search(content):
                        errors.append({"key": location_key, "kind": "personal_path", "message": "Team Skill contains a hard-coded personal absolute path."})
                        break
                for pattern in SECRET_PATTERNS:
                    if pattern.search(content):
                        errors.append({"key": location_key, "kind": "secret", "message": "Team Skill appears to contain a credential or private key."})
                        break
                if len(content) > 120_000:
                    warnings.append({"key": location_key, "kind": "large_body", "message": "Skill text exceeds 120,000 characters; split or shorten it."})

    for name, keys in sorted(names.items()):
        if name and len(keys) > 1:
            errors.append(
                {
                    "key": ",".join(keys),
                    "kind": "duplicate_name",
                    "message": f"Skill name '{name}' exists in multiple catalogs; rename one skill.",
                }
            )

    return {
        "ok": not errors,
        "repository_root": str(root),
        "skill_count": len(entries),
        "builtin_count": sum(1 for item in entries if item.get("scope") == "builtin"),
        "team_count": sum(1 for item in entries if item.get("scope") == "team"),
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Vintage Programmer Built-in and Team Skills.")
    parser.add_argument("--root", default=str(REPOSITORY_ROOT), help="Vintage Programmer repository root")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    args = parser.parse_args(argv)

    report = validate_repository_skills(Path(args.root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASSED" if report["ok"] else "FAILED"
        print(
            f"{status}: skills={report['skill_count']} "
            f"builtin={report['builtin_count']} team={report['team_count']} "
            f"errors={len(report['errors'])} warnings={len(report['warnings'])}"
        )
        for item in report["errors"]:
            print(f"ERROR [{item['kind']}] {item['key']}: {item['message']}")
        for item in report["warnings"]:
            print(f"WARNING [{item['kind']}] {item['key']}: {item['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
