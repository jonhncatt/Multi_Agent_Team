# Swarm Contract

This document freezes the `M4` Swarm contract without rewriting the kernel.

## Scope

The first Swarm contract exists to support one class of flow:

- multiple independent inputs can be processed in parallel
- one join point aggregates the results
- failure handling remains bounded and explicit

This contract does not authorize a new kernel scheduler or open-ended dynamic agent generation.

## Branch Contract

Each Swarm branch must declare:

- `branch_id`
- `task_kind`
- `objective`
- `input_ref`
- `runtime_profile`
- `required_tools`
- `failure_policy`

Formal code contract:

- [`app/contracts/swarm.py`](/Users/dalizhou/Desktop/new_validation_agent/app/contracts/swarm.py)

Current default branch failure policy:

- `serial_replay`

Meaning:

- if a branch fails during the MVP path, it may be replayed serially instead of expanding recovery logic inside the kernel

## Join Contract

Each join point must declare:

- `join_id`
- `branch_ids`
- `aggregation_mode`
- `conflict_policy`

Current default values:

- `aggregation_mode = merge_deduplicate_mark_conflicts`
- `conflict_policy = mark_only`

Meaning:

- the join step merges compatible outputs
- removes obvious duplicates
- marks conflicts without forcing arbitration

## Aggregator Minimum Responsibilities

The first Aggregator must do only three things:

1. merge
2. deduplicate
3. mark conflicts

The first Aggregator must not:

- invent a new global plan
- silently discard meaningful disagreement
- force a single answer when evidence conflicts
- bypass backend tool/provider guardrails

## Required Degradation Strategies

At least one degradation strategy is required for the first MVP. The current contract freezes two explicit behaviors:

1. branch failure -> `serial_replay`
2. aggregator conflict -> `mark_only`

These are intentionally conservative.

## Trace Requirements

Any Swarm MVP implementation must emit enough trace to answer:

- what got split into branches
- which branch failed
- whether serial replay was triggered
- what the join step merged
- how many conflicts were marked

Minimum fields:

- `swarm_run_id`
- `branch_id`
- `join_id`
- `aggregation_mode`
- `conflict_policy`
- `degradation_policy`
- `degradation_trigger`
- `failed_branch_count`
- `conflict_count`

## Kernel Boundary

Swarm remains outside a kernel rewrite path.

`KernelHost` may continue to:

- load
- dispatch
- isolate
- observe
- recover

But it must not become the owner of business-specific branch planning or aggregator reasoning.
