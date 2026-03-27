# Platform Boundaries

## Canonical Rule

All new business capability must enter the system through `business_modules`.

The kernel is responsible for runtime order and isolation only. Compatibility shims may forward requests, but they are not valid homes for new product logic.

## Allowed Logic Zones

Add or evolve logic in these areas when the intent is platform growth:

- `app/business_modules/`
- `app/system_modules/`
- `app/kernel/`
- `app/contracts/`
- `app/tool_providers/`
- `app/bootstrap/`
- `tests/`
- `evals/`
- `docs/`

## Protected Compatibility Zones

These files exist to preserve legacy behavior and migration continuity. They are not valid places for new business heuristics, module-local prompt logic, or Swarm orchestration.

- `app/agent.py`
- `packages/runtime_core/kernel_host.py`

The preferred pattern for these zones is to push reusable logic into adjacent canonical helpers, leaving the shim file as a thin shell.

For `app/agent.py`, prefer `packages/office_modules/*` helpers for session compaction, runtime debug views, and other compatibility-only support code.

## Retired Compatibility Zones

- `app/router_rules.py`
  - replaced by `packages/office_modules/router_hints.py`
  - must not be reintroduced through runtime imports
- `app/request_analysis_support.py`
  - replaced by `packages/office_modules/request_analysis.py`
  - must not be reintroduced through runtime imports
- `app/router_intent_support.py`
  - replaced by `packages/office_modules/intent_support.py`
  - must not be reintroduced through runtime imports
- `app/execution_policy.py`
  - replaced by `packages/office_modules/execution_policy.py`
  - must not be reintroduced through runtime imports

## Team Rules

1. New business capabilities go into `app/business_modules/*`.
2. `KernelHost` may load, dispatch, isolate, observe, and recover. It must not absorb module-specific product logic.
3. A compatibility shim may translate or forward legacy calls, but it must not become the policy owner for new behavior.
4. The second formal module must be independently demoable. It may not rely on `office_module` as a fallback explainer.
5. The first Swarm MVP must stay outside the kernel rewrite path. It should use existing runtime primitives and define at least one failure degradation strategy.

## Required Documentation When A Shim Changes

Any change to a protected compatibility shim must update:

- `docs/migration/compatibility_shim_inventory.md`
- `docs/migration/deprecation_plan.md`

The update must state:

- why the shim still exists
- who still depends on it
- what would allow it to retire

## Active-Shim Dependency Rule

- Existing active shim dependents are explicitly allowlisted in the boundary gate.
- New files must not start importing `app.agent` or `packages.runtime_core.kernel_host`.
- If a dependency truly must exist, update the allowlist and the shim inventory in the same change, with a retirement reason.

## Review Questions

Use these questions in PR review:

1. Did this change add business logic outside a module boundary
2. Did this change expand a compatibility shim instead of moving logic behind a module
3. If a shim changed, did the inventory and retirement condition change with it
4. Does the change keep `KernelHost` free of business heuristics
5. If the change touches Swarm, does it preserve a defined degradation path
