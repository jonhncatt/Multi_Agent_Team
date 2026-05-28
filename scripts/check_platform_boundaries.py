from __future__ import annotations

import argparse
import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_IMPORT_PREFIXES = (
    "app.bootstrap",
    "app.kernel",
    "app.core.bootstrap",
    "app.core.kernel_debug_support",
    "app.legacy_platform_runtime",
    "app.evals",
    "app.operations_overview",
    "app.adapters",
    "app.contracts",
    "app.system_modules",
    "app.tool_providers",
    "app.agents",
    "packages.office_addons",
)


def _python_sources() -> list[Path]:
    roots = ("app", "packages", "tests", "scripts")
    paths: list[Path] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts or "app/data" in str(path):
                continue
            paths.append(path)
    return paths


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name or ""))
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(str(node.module))
    return modules


def forbidden_import_violations() -> list[str]:
    violations: list[str] = []
    for path in _python_sources():
        relative = path.relative_to(REPO_ROOT).as_posix()
        try:
            imported = _imported_modules(path)
        except Exception:
            continue
        for imported_module in imported:
            if any(
                imported_module == prefix or imported_module.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(
                    f"{relative} imports removed legacy platform module {imported_module}"
                )
    return sorted(set(violations))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check chat-product-only boundary guardrails.")
    parser.add_argument("--base", default="", help="Ignored compatibility flag.")
    parser.add_argument("--head", default="HEAD", help="Ignored compatibility flag.")
    args = parser.parse_args()
    _ = args

    violations = forbidden_import_violations()
    if violations:
        print("[platform-boundaries] removed legacy platform imports detected:")
        for item in violations:
            print(f"  - {item}")
        print(
            "[platform-boundaries] failing because chat product code must not import removed legacy platform layers."
        )
        return 1

    print("[platform-boundaries] checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
