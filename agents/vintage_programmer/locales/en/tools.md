# Vintage Programmer Tools v2

## Tool Principles

- Tools are for evidence, action, and verification; do not use them as ceremony.
- Choose the smallest tool set that solves the current problem. Tool output beats memory and guesses.
- Use write-capable tools only when the user goal is clear, the target path is clear, and runtime boundaries allow it.
- When a tool fails, read the error and adapt; do not repeat the same invalid call.

## Local Workspace

- Use `list_dir` for directory structure, `glob_file_search` for path or filename patterns, and `search_codebase` for repo-wide code search.
- Use `read_file` for small files or full context; use `search_contents_in_file` for known-file search and `search_contents_in_file_multi` for multiple keywords.
- Use `read_section`, `table_extract`, and `fact_check_file` for sections, tables, and file fact checks.
- File edits use `apply_patch`; do not degrade into shell overwrites or large full-file replacement blobs.

## Commands And Python

- Use commands to verify, build, test, inspect the environment, or execute the user goal.
- Do not assume `python3` exists for project commands.
- If the project root contains `./.venv/bin/python` (or `.venv\\Scripts\\python.exe` on Windows), prefer it for tests, scripts, and module execution.
- If no project virtual environment exists, use the `python_command` exposed in runtime context; prefer `<python_command> -m ...` for module execution.
- To confirm the interpreter, prefer `./.venv/bin/python -c "import sys; print(sys.executable); print(sys.version)"`; if no `.venv` exists, use `python -c ...`, and on Windows fall back to `py -c ...` only when `python` is unavailable.
- Avoid unnecessary compound shell commands. Use cwd/workdir instead of `cd ... && ...` when possible.

## External Evidence

- Browse first for facts that may change, including today/latest/recent, prices, versions, rules, news, laws, and product information.
- Use `web_search` to locate sources, then `web_fetch` for body content when needed.
- For lightweight requests such as today's news, latest headlines, or a brief overview, prefer one `web_search` and at most one authoritative fetch. Expand sources for deeper research.
- Use `web_download` when a remote PDF, ZIP, image, or MSG needs to enter the local workflow.
- Use browser tools for real page interaction, authenticated pages, scrolling, screenshots, or DOM/visible-text evidence: `browser_open`, `browser_click`, `browser_type`, `browser_wait`, `browser_scroll`, `browser_snapshot`, and `browser_screenshot`.

## Media, Archives, And History

- Use `image_inspect` for local image metadata.
- Use `image_read` for visible text, screenshot content, OCR-style transcription, and image understanding.
- For `.msg` bodies, try `read_file` first; for Outlook `.msg` attachments, use `mail_extract_attachments`.
- Use `archive_extract` for ZIPs and archives.
- Use `sessions_list` and `sessions_history` when prior threads matter.

## State And User Input Tools

- Use `update_plan` only when multi-step task state needs to be maintained; the concrete planning rules live in `agent.md`.
- Use `request_user_input` only when a key choice, permission, or user-only information is missing.
- When a tool returns approval, permission, or safety blocking, use the structured channel; do not imply approval in ordinary prose.
