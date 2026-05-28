from __future__ import annotations

import ast
from pathlib import Path

import app.main as main_app
from scripts.check_platform_boundaries import forbidden_import_violations


REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_APP_PATH = REPO_ROOT / "app" / "main.py"


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


def test_main_app_no_longer_imports_runtime_assembly_directly() -> None:
    imported = _imported_modules(MAIN_APP_PATH)
    assert "app.bootstrap" not in imported
    assert "app.kernel" not in imported
    assert "app.core.bootstrap" not in imported
    assert "app.legacy_platform_runtime" not in imported


def test_main_app_uses_explicit_chat_runtime_boundary() -> None:
    content = MAIN_APP_PATH.read_text(encoding="utf-8")
    assert "from app.chat_product_runtime import ChatProductRuntime" in content
    assert "chat_product_runtime = ChatProductRuntime(config)" in content
    assert "get_chat_product_runtime().runtime_meta()" in content
    assert "get_chat_product_runtime().tool_executor" in content


def test_repo_has_no_removed_legacy_platform_imports() -> None:
    assert forbidden_import_violations() == []


def test_removed_redundant_layer_source_files_are_gone() -> None:
    removed_paths = {
        REPO_ROOT / "app" / "adapters" / "__init__.py",
        REPO_ROOT / "app" / "contracts" / "__init__.py",
        REPO_ROOT / "app" / "system_modules" / "__init__.py",
        REPO_ROOT / "app" / "tool_providers" / "__init__.py",
        REPO_ROOT / "app" / "agents" / "role_contracts.py",
        REPO_ROOT / "app" / "agents" / "role_debug_support.py",
        REPO_ROOT / "app" / "agents" / "role_smoke.py",
        REPO_ROOT / "packages" / "office_addons" / "__init__.py",
    }
    assert all(not path.exists() for path in removed_paths)


def test_removed_legacy_platform_routes_are_not_registered() -> None:
    route_paths = {getattr(route, "path", "") for route in main_app.app.routes}
    removed = {
        "/api/agents",
        "/api/agents/{agent_id}/reload",
        "/api/evolution/runtime",
        "/api/operations/overview",
        "/api/evals/run",
        "/api/kernel/runtime",
        "/api/kernel/shadow/stage",
        "/api/kernel/shadow/validate",
        "/api/kernel/shadow/promote-check",
        "/api/kernel/shadow/promote",
        "/api/kernel/shadow/smoke",
        "/api/kernel/shadow/replay",
        "/api/kernel/shadow/contracts",
        "/api/kernel/shadow/pipeline",
        "/api/kernel/shadow/auto-repair",
        "/api/kernel/shadow/patch-worker",
        "/api/kernel/shadow/package",
        "/api/kernel/shadow/self-upgrade",
    }
    assert removed.isdisjoint(route_paths)


def test_legacy_product_shell_entrypoints_are_removed() -> None:
    removed_paths = {
        REPO_ROOT / "app" / "product_profiles.py",
        REPO_ROOT / "app" / "multi_agent_robot_main.py",
        REPO_ROOT / "run-kernel-robot.sh",
        REPO_ROOT / "run-multi-agent-robot.sh",
        REPO_ROOT / "packages" / "kernel-robot" / "README.md",
        REPO_ROOT / "packages" / "role-agent-lab" / "README.md",
    }
    assert all(not path.exists() for path in removed_paths)
