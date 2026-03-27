# Platform Metrics

These metrics start in `M1` so later milestones can use real baselines instead of retroactive estimates.

## Output

The baseline collector writes JSON to:

- `artifacts/platform_metrics/latest.json`

CI also uploads the metrics artifact.

## Metrics

### Shim Metrics

- `compatibility_shim_count`
- `compatibility_shim_paths`
- `shim_inventory_documented_count`

Purpose:

- track how many shims are still active
- verify the shim inventory stays aligned with the protected list

### Second-Module Baseline Metrics

- `business_module_count`
- `non_office_business_module_count`
- `business_modules[*].has_manifest`
- `business_modules[*].has_module_entry`
- `business_modules[*].has_module_doc`
- `business_modules[*].mentioned_in_integration_tests`

Purpose:

- measure whether the repository really contains multiple usable module candidates
- expose the gap between skeleton modules and independently demoable modules

### Swarm Baseline Metrics

- `swarm.branch_join_runtime_present`
- `swarm.branch_join_ui_present`
- `swarm.aggregator_contract_defined`
- `swarm.degradation_strategy_defined`
- `swarm.contract_code_present`

Purpose:

- separate “runtime primitives already exist” from “Swarm MVP contract is actually defined”

## Collection Policy

- Run locally when changing platform boundaries or roadmap gating.
- Run in CI to keep an artifact trail.
- Treat these as baseline readiness metrics in `M1-M2`, not as end-state success metrics.
