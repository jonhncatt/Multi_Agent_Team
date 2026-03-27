from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parent.parent
BUSINESS_MODULES_DIR = REPO_ROOT / "app" / "business_modules"
MODULE_DOCS_DIR = REPO_ROOT / "docs" / "modules"
INTEGRATION_TESTS_DIR = REPO_ROOT / "tests" / "integration"
SWARM_ROADMAP = REPO_ROOT / "docs" / "swarm-roadmap.md"
SWARM_CONTRACT = REPO_ROOT / "docs" / "architecture" / "swarm_contract.md"
SWARM_CONTRACT_CODE = REPO_ROOT / "app" / "contracts" / "swarm.py"
STATIC_APP = REPO_ROOT / "app" / "static" / "app.js"
LEGACY_AGENT = REPO_ROOT / "app" / "agent.py"
SHIM_INVENTORY = REPO_ROOT / "docs" / "migration" / "compatibility_shim_inventory.md"
OUTPUT_PATH = REPO_ROOT / "artifacts" / "platform_metrics" / "latest.json"

PROTECTED_SHIMS = (
    "app/agent.py",
    "app/request_analysis_support.py",
    "app/router_intent_support.py",
    "app/router_rules.py",
    "app/execution_policy.py",
    "packages/runtime_core/kernel_host.py",
)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


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
    documented = sorted(
        set(match.group(1) for match in re.finditer(r"\| `([^`]+)` \|", inventory_text))
    )
    return {
        "compatibility_shim_count": len(PROTECTED_SHIMS),
        "compatibility_shim_paths": list(PROTECTED_SHIMS),
        "shim_inventory_documented_count": len(documented),
        "shim_inventory_paths": documented,
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
