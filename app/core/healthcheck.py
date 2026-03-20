from __future__ import annotations

from typing import Any

from app.core.bootstrap import KernelRuntime


def build_kernel_health_payload(runtime: KernelRuntime) -> dict[str, Any]:
    snapshot = runtime.health_snapshot()
    shadow_manifest = runtime.load_shadow_manifest().to_dict()
    shadow_validation = runtime.validate_shadow_manifest()
    rollback_pointer = runtime.supervisor.read_rollback_pointer()
    last_shadow_run = runtime.read_last_shadow_run()
    last_upgrade_run = runtime.read_last_upgrade_run()
    last_repair_run = runtime.read_last_repair_run()
    return {
        "active_manifest": dict(snapshot.active_manifest),
        "shadow_manifest": shadow_manifest,
        "shadow_validation": shadow_validation,
        "rollback_pointer": rollback_pointer,
        "last_shadow_run": last_shadow_run,
        "last_upgrade_run": last_upgrade_run,
        "last_repair_run": last_repair_run,
        "selected_modules": dict(snapshot.selected_modules),
        "module_health": dict(snapshot.module_health),
        "runtime_files": dict(snapshot.runtime_files),
    }
