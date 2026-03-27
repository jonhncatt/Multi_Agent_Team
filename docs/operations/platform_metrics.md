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
- `retired_shim_count`
- `retired_shim_paths`
- `active_shim_dependency_counts`
- `active_shim_dependents`
- `office_legacy_helper_surface.run_chat_calls`
- `office_legacy_helper_surface.method_calls`
- `office_legacy_helper_surface.attribute_accesses`
- `shim_inventory_documented_count`
- `retired_inventory_documented_count`

Purpose:

- track how many shims are still active
- prove at least one shim has actually retired
- track whether the remaining active shims are spreading to new runtime dependents
- track which `OfficeLegacyHelperSurface` compatibility entrypoints are still being exercised
- track whether active and retired shim inventories stay aligned with docs
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
- `swarm.mvp_demo_present`
- `swarm.mvp_regression_present`

Purpose:

- separate “runtime primitives already exist” from “Swarm MVP contract is actually defined”
- show when the Swarm MVP stops being just architecture and becomes demoable + regression-protected

## Collection Policy

- Run locally when changing platform boundaries or roadmap gating.
- Run in CI to keep an artifact trail.
- Treat these as baseline readiness metrics in `M1-M2`, not as end-state success metrics.
