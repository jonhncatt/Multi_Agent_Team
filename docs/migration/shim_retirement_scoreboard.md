# Shim Retirement Scoreboard

## Completed

| Shim | Status | Replacement | Notes |
| --- | --- | --- | --- |
| `app/execution_policy.py` | Retired | `packages/office_modules/execution_policy.py` | Removed from runtime imports and guarded by the platform-boundary check |
| `app/router_rules.py` | Retired | `packages/office_modules/router_hints.py` | Removed from runtime imports and guarded by the platform-boundary check |
| `app/request_analysis_support.py` | Retired | `packages/office_modules/request_analysis.py` | Removed from runtime imports and guarded by the platform-boundary check |
| `app/router_intent_support.py` | Retired | `packages/office_modules/intent_support.py` | Removed from runtime imports and guarded by the platform-boundary check |

## Remaining Active Shims

| Shim | Current Role | Next Retirement Dependency |
| --- | --- | --- |
| `app/agent.py` | Legacy Office runtime shim | `office_module` must stop delegating to `OfficeAgent`; compatibility-only helpers should keep moving into `packages/office_modules/*` |
| `packages/runtime_core/kernel_host.py` | Legacy capability host shell | Agent OS assembly must stop instantiating the compatibility host, not just route through its helper shell |
