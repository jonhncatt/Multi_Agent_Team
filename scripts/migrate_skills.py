from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.config import load_config  # noqa: E402
from app.workbench import WorkbenchStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy VP system/workspace Skills into the global Team catalog.")
    parser.add_argument("--json", action="store_true", help="Print the complete path-redacted migration report")
    args = parser.parse_args(argv)

    store = WorkbenchStore(
        config=load_config(),
        agent_dir=REPOSITORY_ROOT / "agents" / "vintage_programmer",
    )
    report = store.skill_migration_report
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"migration_status={report.get('status', 'unknown')} "
            f"migrated={len(report.get('migrated') or [])} "
            f"already_present={len(report.get('already_present') or [])} "
            f"conflicts={len(report.get('conflicts') or [])} "
            f"skipped={len(report.get('skipped') or [])}"
        )
        for item in list(report.get("conflicts") or []):
            print(f"CONFLICT {item.get('source_scope')}:{item.get('name')}: {item.get('reason')}")
    return 1 if report.get("conflicts") else 0


if __name__ == "__main__":
    raise SystemExit(main())
