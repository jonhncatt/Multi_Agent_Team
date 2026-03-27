# Deprecation Plan

## Active Compatibility Layers

- `app/agent.py`
- `packages/runtime_core/kernel_host.py`

## Completed Retirements

- `app/execution_policy.py`
  - Replaced by `packages/office_modules/execution_policy.py`
  - Removed from the runtime import path
  - Protected by the platform-boundary gate so legacy imports fail review
- `app/router_rules.py`
  - Replaced by `packages/office_modules/router_hints.py`
  - Removed from the runtime import path
  - Protected by the platform-boundary gate so legacy imports fail review
- `app/request_analysis_support.py`
  - Replaced by `packages/office_modules/request_analysis.py`
  - Removed from the runtime import path
  - Protected by the platform-boundary gate so legacy imports fail review
- `app/router_intent_support.py`
  - Replaced by `packages/office_modules/intent_support.py`
  - Removed from the runtime import path
  - Protected by the platform-boundary gate so legacy imports fail review

## Deletion Conditions

- `office_module` no longer delegates to `OfficeAgent`
- Agent OS assembly no longer needs capability-runtime host objects for health/debug
- `packages/runtime_core/kernel_host.py` is no longer needed even as a thin shell over `packages/runtime_core/legacy_host_support.py`
- `app/agent.py` no longer needs to retain compatibility-only session/debug helpers because they live in module-scoped support packages
- office routing/policy helpers fully live behind module-scoped packages
- integration tests pass without instantiating compatibility host objects

## Sequence

1. migrate office runtime internals into `app/business_modules/office_module/*`
2. sever `office_module -> OfficeAgent` delegation
3. retire legacy capability host coupling
