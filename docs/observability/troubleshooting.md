# Troubleshooting Guide

## Start With The Product Path

Use the chat product entrypoint first:

```bash
./run.sh
```

On Windows:

```powershell
.\run.ps1
```

If the app starts but behavior looks wrong, reproduce the issue in the current chat UI before checking lower-level diagnostics.

## Where To Look

- request/stream behavior: chat UI + browser devtools network tab
- trace fields: [`docs/observability/trace_guide.md`](trace_guide.md)
- runtime snapshot: `GET /api/runtime-status`
- workbench diagnostics: `Run`, `Logs`, `Recent Tools`, `Context Meter`

## Common Failure Modes

### Provider auth missing or model unavailable

Symptoms:

- assistant replies that no model auth is available
- requests fail before any tool call happens
- provider/model switches appear to recover the issue

Check:

- provider API key in `Settings`
- `.env` provider defaults
- `GET /api/runtime-status` provider/auth snapshot

### Tool dispatch works but the answer stalls

Symptoms:

- final text appears
- send button keeps spinning too long
- thread or runtime metadata updates lag behind the message

Check:

- SSE stream completion in browser devtools
- `Run` panel live state
- background refresh logs

### Attachments are present but not used

Symptoms:

- uploaded image, mail, or document is ignored
- assistant asks for missing context even though an attachment exists

Check:

- upload succeeded in the network tab
- `active_attachments` and current focus in the workbench
- attachment/tool events in the current turn log

### Trace exists but is not detailed enough

Set:

- `VP_TRACE=1`

Then inspect the current thread log and shadow log output under `app/data/`.

## Escalation Order

1. reproduce in the current chat UI
2. inspect `Run` / `Logs` / `Recent Tools`
3. inspect `/api/runtime-status`
4. inspect provider/auth configuration
5. full HTTP/UI reproduction with attachment/tool evidence
