from __future__ import annotations

from pathlib import Path


def test_va_support_package_removed() -> None:
    assert not Path("app/va_support").exists()


def test_evolution_runtime_artifact_config_removed() -> None:
    text = Path("app/config.py").read_text(encoding="utf-8")
    forbidden = (
        "runtime_dir",
        "evolution_dir",
        "active_manifest_path",
        "shadow_manifest_path",
        "rollback_pointer_path",
        "module_health_path",
        "overlay_profile_path",
        "evolution_logs_dir",
        "shadow_logs_dir",
        "enable_shadow_logging",
        "VA_RUNTIME_DIR",
        "VA_EVOLUTION_DIR",
        "VA_ACTIVE_MANIFEST_PATH",
        "VA_SHADOW_MANIFEST_PATH",
        "VA_ROLLBACK_POINTER_PATH",
        "VA_MODULE_HEALTH_PATH",
        "VA_OVERLAY_PROFILE_PATH",
        "VA_EVOLUTION_LOGS_DIR",
        "VA_SHADOW_LOGS_DIR",
        "VA_ENABLE_SHADOW_LOGGING",
    )
    for token in forbidden:
        assert token not in text


def test_main_does_not_create_removed_runtime_stores() -> None:
    text = Path("app/main.py").read_text(encoding="utf-8")
    forbidden = (
        "EvolutionStore",
        "evolution_store",
        "ShadowLogStore",
        "shadow_log_store",
        "ChatProductRuntime",
        "chat_product_runtime",
    )
    for token in forbidden:
        assert token not in text


def test_no_old_module_or_va_support_imports_in_active_runtime() -> None:
    active_paths = (
        Path("app/main.py"),
        Path("app/config.py"),
        Path("app/validation_assistant_runtime.py"),
        Path("app/va_runtime_backend.py"),
    )
    forbidden = (
        "app.va_support",
        "module_id",
        "module_title",
        "ToolDispatchMeta",
        "ScopedToolExecutor",
        "packages.",
    )
    for path in active_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} still present in {path}"


def test_old_runtime_scaffolding_files_removed() -> None:
    removed = (
        "app/policy_router.py",
        "app/chat_product_runtime.py",
        "app/evolution.py",
        "app/va_support",
    )
    for item in removed:
        assert not Path(item).exists(), item
