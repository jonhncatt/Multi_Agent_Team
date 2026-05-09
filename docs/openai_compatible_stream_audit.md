# OpenAI-compatible streaming audit

This note records the expected streaming chain for local MLX and OpenAI-compatible providers.

## Current chain

The browser calls the application endpoint `POST /api/chat/stream`. That endpoint is an application-level event stream, not a direct proxy of provider SSE from `/v1/chat/completions`.

The runtime chain is browser to FastAPI stream endpoint, then `VintageProgrammerRuntime.run(..., progress_cb=...)`, then the OfficeAgent backend or provider adapter, then the OpenAI-compatible chat completions endpoint.

The browser receives app events such as `stage`, `trace_event`, `plan_update`, `item/started`, `item/agentMessage/delta`, and `item/completed`. Answer text is progressive only when provider deltas are translated into `item/agentMessage/delta` events.

## Provider payload summary

Before the provider request is sent, log a compact summary only: provider, base URL, model, stream flag, max token value, message count, and total character count. Do not log the full prompt.

## Expected behavior

For local MLX via `openai_compatible`, the recommended default is streaming enabled with 1024 or 2048 max output tokens. If provider streaming is enabled and supported, upstream deltas should become `item/agentMessage/delta`. If provider streaming is disabled or unsupported, the UI can still receive stage and trace events, but the final answer should mark upstream progressive output as false.

## Local MLX recommendation

Local models should not default to 128000 output tokens. Recommended defaults are 1024 for 9B-class models, 2048 for 30B 3-bit models, and 4096 only for explicitly long document or code generation tasks.

## Proposed environment variables

`VP_OPENAI_COMPAT_STREAM=true`

`VP_OPENAI_COMPAT_MAX_OUTPUT_TOKENS=2048`

`VP_OPENAI_COMPAT_DEBUG_PAYLOAD=false`

`VP_OLLAMA_STREAM=true`

`VP_OLLAMA_MAX_OUTPUT_TOKENS=2048`

These variables are documented in `.env.example`. The next implementation step is to wire them into the actual provider call site and add provider-payload summary logging.
