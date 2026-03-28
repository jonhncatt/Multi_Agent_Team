# Compatibility Shim Inventory

This file tracks every active compatibility shim as a managed migration object.

## Active Inventory

| Path | Current Role | Why It Still Exists | Known Dependents | Retirement Condition |
| --- | --- | --- | --- | --- |
| `app/agent.py` | Legacy Office runtime and compatibility orchestration shim | `office_module` main path now enters canonical `OfficeExecutionEngine`, but the engine still delegates into `OfficeAgent` for the core office execution path | `packages/office_modules/agent_module.py`, shadow/bootstrap repair flows, router-layer tests; session compaction plus auth/capability/kernel/evolution/role-lab/runtime-override debug helpers have been moved to `packages/office_modules/legacy_runtime_support.py` | `OfficeExecutionEngine` no longer delegates to `OfficeAgent`, and `packages/office_modules/agent_module.py` no longer imports `app.agent` |

## Retired Shims

| Path | Retirement Outcome | Replacement | Retirement Proof |
| --- | --- | --- | --- |
| `packages/runtime_core/kernel_host.py` | Removed from runtime assembly and deleted from the repository | `AgentOSRuntime` explicit legacy facade/helper bindings plus `packages/runtime_core/legacy_host_support.py` | runtime assembly no longer imports `packages.runtime_core.kernel_host`; `get_legacy_host()` now resolves to explicit compatibility accessors instead of a mixed host class; boundary gate rejects new `packages.runtime_core.kernel_host` imports |
| `app/router_rules.py` | Removed from the runtime path and deleted from the repository | `packages/office_modules/router_hints.py` | runtime imports now point at `packages/office_modules/router_hints.py`; boundary gate rejects new `app.router_rules` imports |
| `app/request_analysis_support.py` | Removed from the runtime path and deleted from the repository | `packages/office_modules/request_analysis.py` | runtime imports now point at `packages/office_modules/request_analysis.py`; boundary gate rejects new `app.request_analysis_support` imports |
| `app/router_intent_support.py` | Removed from the runtime path and deleted from the repository | `packages/office_modules/intent_support.py` | runtime imports now point at `packages/office_modules/intent_support.py`; boundary gate rejects new `app.router_intent_support` imports |
| `app/execution_policy.py` | Removed from the runtime path and deleted from the repository | `packages/office_modules/execution_policy.py` | runtime imports now point at `packages/office_modules/execution_policy.py`; boundary gate rejects new `app.execution_policy` imports |

## Operating Rules

- A shim may forward, normalize, or preserve compatibility.
- A shim may not become the long-term owner of new business capability.
- Any shim change must update this inventory and `docs/migration/deprecation_plan.md`.
- A retired shim must not be reintroduced through new runtime imports.
- A shim is not considered retired until tests and integration paths pass without importing it from the main execution path.
