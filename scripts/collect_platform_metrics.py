from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.office_modules.execution_runtime import read_legacy_helper_surface_metrics

BUSINESS_MODULES_DIR = REPO_ROOT / "app" / "business_modules"
MODULE_DOCS_DIR = REPO_ROOT / "docs" / "modules"
INTEGRATION_TESTS_DIR = REPO_ROOT / "tests" / "integration"
SWARM_ROADMAP = REPO_ROOT / "docs" / "swarm-roadmap.md"
SWARM_CONTRACT = REPO_ROOT / "docs" / "architecture" / "swarm_contract.md"
SWARM_CONTRACT_CODE = REPO_ROOT / "app" / "contracts" / "swarm.py"
SWARM_DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo_research_swarm.py"
SWARM_DEMO_DOC = REPO_ROOT / "docs" / "demo" / "research_swarm_demo.md"
SWARM_INTEGRATION_TEST = REPO_ROOT / "tests" / "integration" / "test_kernel_research_swarm_flow.py"
SWARM_UNIT_TEST = REPO_ROOT / "tests" / "swarm" / "test_research_swarm_pipeline.py"
STATIC_APP = REPO_ROOT / "app" / "static" / "app.js"
LEGACY_AGENT = REPO_ROOT / "app" / "agent.py"
SHIM_INVENTORY = REPO_ROOT / "docs" / "migration" / "compatibility_shim_inventory.md"
OUTPUT_PATH = REPO_ROOT / "artifacts" / "platform_metrics" / "latest.json"

PROTECTED_SHIMS = (
    "app/agent.py",
    "packages/runtime_core/kernel_host.py",
)

RETIRED_SHIMS = (
    "app/execution_policy.py",
    "app/router_rules.py",
    "app/request_analysis_support.py",
    "app/router_intent_support.py",
)

ACTIVE_SHIM_IMPORT_TARGETS = (
    "app.agent",
    "packages.runtime_core.kernel_host",
)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


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


def _imports_module(text: str, module_path: str) -> bool:
    escaped = re.escape(module_path)
    patterns = (
        rf"(?m)^\s*from\s+{escaped}\s+import\s+",
        rf"(?m)^\s*import\s+{escaped}(?:\s|$)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_section_table_paths(text: str, heading: str) -> list[str]:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return []
    rest = text[start + len(marker):]
    next_heading = rest.find("\n## ")
    section = rest if next_heading < 0 else rest[:next_heading]
    return sorted(set(match.group(1) for match in re.finditer(r"(?m)^\| `([^`]+)` \|", section)))


def _module_id_from_manifest(path: Path) -> str:
    text = _read(path)
    match = re.search(r'module_id="([^"]+)"', text)
    return str(match.group(1) if match else path.parent.name)


def _mentioned_in_integration_tests(module_id: str, module_name: str) -> bool:
    needles = (module_id, module_name)
    for path in sorted(INTEGRATION_TESTS_DIR.glob("test_*.py")):
        text = _read(path)
        if any(needle in text for needle in needles):
            return True
    return False


def _business_module_metrics() -> dict[str, object]:
    modules: list[dict[str, object]] = []
    for path in sorted(BUSINESS_MODULES_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("__"):
            continue
        manifest = path / "manifest.py"
        module_entry = path / "module.py"
        module_doc = MODULE_DOCS_DIR / f"{path.name}.md"
        module_id = _module_id_from_manifest(manifest) if manifest.exists() else path.name
        modules.append(
            {
                "module_id": module_id,
                "directory": path.name,
                "has_manifest": manifest.exists(),
                "has_module_entry": module_entry.exists(),
                "has_module_doc": module_doc.exists(),
                "mentioned_in_integration_tests": _mentioned_in_integration_tests(module_id, path.name),
            }
        )
    non_office = [item for item in modules if str(item["module_id"]) != "office_module"]
    return {
        "business_module_count": len(modules),
        "non_office_business_module_count": len(non_office),
        "business_modules": modules,
    }


def _shim_metrics() -> dict[str, object]:
    inventory_text = _read(SHIM_INVENTORY)
    active_documented = _extract_section_table_paths(inventory_text, "Active Inventory")
    retired_documented = _extract_section_table_paths(inventory_text, "Retired Shims")
    office_legacy_helper_surface = read_legacy_helper_surface_metrics()
    active_shim_dependents: dict[str, list[str]] = {}
    for module_path in ACTIVE_SHIM_IMPORT_TARGETS:
        importers: list[str] = []
        for path in _python_sources():
            text = _read(path)
            if _imports_module(text, module_path):
                importers.append(path.relative_to(REPO_ROOT).as_posix())
        active_shim_dependents[module_path] = sorted(importers)
    return {
        "compatibility_shim_count": len(PROTECTED_SHIMS),
        "compatibility_shim_paths": list(PROTECTED_SHIMS),
        "retired_shim_count": len(RETIRED_SHIMS),
        "retired_shim_paths": list(RETIRED_SHIMS),
        "active_shim_dependency_counts": {
            module_path: len(importers) for module_path, importers in active_shim_dependents.items()
        },
        "active_shim_dependents": active_shim_dependents,
        "office_legacy_helper_surface": office_legacy_helper_surface,
        "shim_inventory_documented_count": len(active_documented),
        "shim_inventory_paths": active_documented,
        "retired_inventory_documented_count": len(retired_documented),
        "retired_inventory_paths": retired_documented,
    }


def _swarm_metrics() -> dict[str, object]:
    roadmap = _read(SWARM_ROADMAP)
    contract_doc = _read(SWARM_CONTRACT)
    contract_code = _read(SWARM_CONTRACT_CODE)
    static_app = _read(STATIC_APP)
    legacy_agent = _read(LEGACY_AGENT)
    return {
        "branch_join_runtime_present": 'node_type="branch"' in legacy_agent and 'node_type="join"' in legacy_agent,
        "branch_join_ui_present": 'if (nodeType === "join")' in static_app and 'if (nodeType === "branch")' in static_app,
        "aggregator_contract_defined": ("Aggregator Minimum Responsibilities" in contract_doc) or ("merge / deduplicate / mark conflicts" in roadmap),
        "degradation_strategy_defined": ("serial_replay" in contract_doc and "mark_only" in contract_doc),
        "contract_code_present": "class SwarmJoinSpec" in contract_code and "class SwarmBranchSpec" in contract_code,
        "mvp_demo_present": SWARM_DEMO_SCRIPT.exists() and SWARM_DEMO_DOC.exists(),
        "mvp_regression_present": SWARM_INTEGRATION_TEST.exists() and SWARM_UNIT_TEST.exists(),
    }


def main() -> int:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shim": _shim_metrics(),
        "second_module": _business_module_metrics(),
        "swarm": _swarm_metrics(),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
