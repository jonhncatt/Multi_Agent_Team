from __future__ import annotations

import argparse
import json
import sys

from app.config import load_config
from app.storage import ProjectStore, SessionStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair session metadata, sidecars, and lightweight activity summaries.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero when any session repair error occurs.")
    args = parser.parse_args()

    config = load_config()
    project_store = ProjectStore(config.projects_registry_path, default_root=config.workspace_root)
    session_store = SessionStore(
        config.sessions_dir,
        runs_dir=config.runs_dir,
        session_meta_dir=config.session_meta_dir,
    )
    default_project = project_store.ensure_default_project()
    stats = session_store.repair_sessions(default_project=default_project)
    json.dump(stats, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    if args.fail_on_error and list(stats.get("errors") or []):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
