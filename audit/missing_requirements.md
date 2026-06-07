# Missing direct requirements audit

## Runtime imports missing from requirements.txt
| Imported module | Recommended package | Evidence |
| --- | --- | --- |
| langchain_core | langchain-core | app/vp_runtime_backend.py |
| tiktoken | tiktoken | app/context_meter.py |
| yaml | PyYAML | app/workbench.py |

These modules are currently satisfied only through transitive dependencies. They should be promoted to direct declarations.

## Test/dev imports
No additional dev/test package is missing. `pytest` is already declared in `requirements-dev.txt`.
