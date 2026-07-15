# Tool Rules

- Use file tools for exploration and `exec_command` only for read-oriented inspection or focused tests.
- Do not use inline interpreter forms such as `python -c` or `node -e`; they cannot preserve file provenance. Use file/search tools, an existing workspace script, or an existing test module instead.
- Never use shell commands to edit, delete, move, download, install, commit, or otherwise mutate workspace files.
- Read the minimum relevant evidence and include useful file paths or command outcomes in the final result.
