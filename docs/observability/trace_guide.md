# Trace Guide

## Environment Flags

- `AGENT_OS_TRACE=1`
  - writes JSON traces to `artifacts/agent_os_traces/`
- `AGENT_OS_TRACE_VERBOSE=1`
  - includes event payload details

## What A Trace Answers

A trace should explain:

- which module ran
- which roles were selected
- which tools/providers were selected
- whether fallback or degradation happened
- the final outcome and elapsed time

## Current Outputs

- structured logger: `agent_os.kernel`
- debug JSON files under `artifacts/agent_os_traces/`
- in-memory `recent_traces` exposed by kernel health snapshot

Related docs:

- [Troubleshooting Guide](troubleshooting.md)

## Common Debug Steps

1. Check `final_outcome`
2. Inspect `selected_tools` and `selected_providers`
3. Inspect `degraded_events` and `fallback_events`
4. Inspect `events[]` for `tool_dispatch`, `tool_result`, `provider_failed`, `tool_fallback`
