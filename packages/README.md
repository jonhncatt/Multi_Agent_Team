# Packages Boundary Guide

## Canonical Python Packages

These are the formal import targets:

- `packages.agent_core`
- `packages.office_modules`
- `packages.runtime_core`

These should be treated as the stable Python package layer.

## Compatibility Placeholders

These directories exist only to document or bridge old distribution names:

- `packages/agent-core`
- `packages/office-modules`
- `packages/runtime-core`

Do not import from them in Python code.

## Removal Direction

- keep snake_case directories as the canonical implementation
- keep only placeholders that are still required by current product packaging
- remove compatibility placeholders once external references are updated
