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
