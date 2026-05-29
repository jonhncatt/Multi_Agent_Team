from __future__ import annotations

from pathlib import Path


def test_app_runtime_sources_do_not_import_legacy_packages() -> None:
    for relative_path in (
        "app/vintage_programmer_runtime.py",
        "app/policy_router.py",
        "app/vp_runtime_backend.py",
    ):
        text = Path(relative_path).read_text(encoding="utf-8")
        assert "packages.office_modules" not in text
        assert "packages.agent_core" not in text
        assert "packages.runtime_core" not in text


def test_legacy_runtime_compat_layers_are_removed() -> None:
    backend_source = Path("app/vp_runtime_backend.py").read_text(encoding="utf-8")
    assert "capability_runtime" not in backend_source
    assert "selected_agent_module_id" not in backend_source
    assert "selected_tool_module_id" not in backend_source
    assert "VP_APP_PROFILE" not in backend_source
    assert "role_agent_lab" not in backend_source
    assert not Path("app/vp_support/blackboard.py").exists()


def test_old_role_runtime_symbols_removed_from_active_runtime() -> None:
    active_paths = (
        Path("app/vp_runtime_backend.py"),
        Path("app/vintage_programmer_runtime.py"),
        Path("app/main.py"),
        Path("app/policy_router.py"),
    )
    forbidden = (
        "RoleRuntimeController",
        "RoleExecution",
        "RoleSpec",
        "RoleContext",
        "RoleResult",
        "RunState",
        "RoleRegistry",
        "RegisteredRole",
        "build_vp_role_registry",
        "SPECIALIST_LABELS",
        "ROLE_KINDS",
        "run_planner_role",
        "run_specialist_with_context",
        "run_reviewer_role",
        "run_revision_role",
        "run_structurer_role",
        "run_conflict_detector_role",
    )

    for path in active_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} still present in {path}"


def test_old_role_runtime_files_removed() -> None:
    removed = (
        "app/vp_support/role_runtime.py",
        "app/vp_support/runtime_controller.py",
        "app/vp_support/role_registry.py",
        "app/vp_support/roles.py",
        "app/vp_support/role_catalog.py",
        "app/vp_support/specialist_role.py",
        "app/vp_support/planner_role.py",
        "app/vp_support/reviewer_role.py",
        "app/vp_support/revision_role.py",
        "app/vp_support/structurer_role.py",
        "app/vp_support/conflict_detector_role.py",
        "app/vp_support/role_helpers.py",
    )

    for item in removed:
        assert not Path(item).exists(), item
