# Deprecation Plan

## Active Compatibility Layers

- `app/agent.py`

## Completed Retirements

- `packages/runtime_core/kernel_host.py`
  - Replaced by explicit `AgentOSRuntime` legacy facade/helper bindings plus `packages/runtime_core/legacy_host_support.py`
  - Removed from runtime assembly and deleted from the repository
  - Protected by the platform-boundary gate so legacy imports fail review
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
- `app/agent.py` no longer needs to retain compatibility-only session/debug helpers because they live in module-scoped support packages, including auth/capability/kernel/evolution snapshots, role-lab debug demos, and runtime-override demos
- office routing/policy helpers fully live behind module-scoped packages
- integration tests pass without instantiating compatibility host objects

Status:

- `packages/runtime_core/kernel_host.py`: retired
- runtime-path host instantiation: removed in favor of explicit facade/helper bindings
- `get_legacy_host()`: no longer part of runtime behavior; retained only as a compatibility accessor entrypoint
- blackboard orchestration: remains externalized in `packages/runtime_core/legacy_host_support.py`
- remaining active shim focus: `app/agent.py`
- `OfficeExecutionEngine`: canonical office runtime entry now exists, but still delegates into `OfficeAgent` for execution

## Sequence

1. move the main office execution path behind `OfficeExecutionEngine`
2. migrate module wrappers off `OfficeAgent` private methods
3. migrate shadow / smoke / replay / worker / eval helper consumers to explicit runtime/helper surfaces
4. sever `OfficeExecutionEngine -> OfficeAgent` delegation
5. retire `app/agent.py`
