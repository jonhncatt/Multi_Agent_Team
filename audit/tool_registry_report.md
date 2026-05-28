# Tool Registry Report
## Actual Registered Tool List
| Tool | Description | Implementation | Current Metadata | Validator Coverage | Notes |
|---|---|---|---|---|---|
| apply_patch | Apply a freeform patch inside the workspace. | app.local_tools:LocalToolExecutor.apply_patch | group=edit; source=native; risk=medium | cap:workspace_read,workspace_write | module=workspace_core_tools; runtime:write |
| archive_extract | Extract a local .zip archive into a target directory under allowed roots. | app.local_tools:LocalToolExecutor.archive_extract | group=archive; source=native; risk=medium | cap:workspace_read,workspace_write | module=content_unpack_tools; runtime:write |
| browser_click | Click one element in the current browser session by CSS selector. | app.local_tools:LocalToolExecutor.browser_click | group=browser; source=adapter; risk=medium | cap:network,browser | module=browser_tools; runtime:read_only |
| browser_open | Open a webpage in a headless browser session and capture the current page state. | app.local_tools:LocalToolExecutor.browser_open | group=browser; source=adapter; risk=medium | cap:network,browser | module=browser_tools; runtime:read_only |
| browser_screenshot | Save a screenshot from the current browser session to local storage. | app.local_tools:LocalToolExecutor.browser_screenshot | group=browser; source=adapter; risk=medium | cap:workspace_write,network,browser | module=browser_tools; runtime:read_only |
| browser_snapshot | Capture the current browser page title, URL, text excerpt, and top links. | app.local_tools:LocalToolExecutor.browser_snapshot | group=browser; source=adapter; risk=low | cap:network,browser | module=browser_tools; runtime:read_only |
| browser_type | Type or fill text into the current browser session by CSS selector. | app.local_tools:LocalToolExecutor.browser_type | group=browser; source=adapter; risk=medium | cap:network,browser | module=browser_tools; runtime:read_only |
| browser_wait | Wait for a selector or a timeout in the current browser session. | app.local_tools:LocalToolExecutor.browser_wait | group=browser; source=adapter; risk=low | cap:network,browser | module=browser_tools; runtime:read_only |
| exec_command | Run a workspace command and keep a resumable command session for follow-up polling or stdin. | app.local_tools:LocalToolExecutor.exec_command | group=shell; source=adapter; risk=high | cap:workspace_read,shell; shell_table | module=workspace_core_tools; runtime:write |
| fact_check_file | Check whether a file provides supporting evidence for a claim, using derived or provided search queries. | app.local_tools:LocalToolExecutor.fact_check_file | group=document; source=optional; risk=medium | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only; optional_deps=advisory |
| glob_file_search | Find files by glob pattern relative to the workspace or a given directory root. | app.local_tools:LocalToolExecutor.glob_file_search | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| image_inspect | Inspect a local image and return basic metadata such as size, mode, and format. | app.local_tools:LocalToolExecutor.image_inspect | group=media; source=optional; risk=low | cap:workspace_read; read_fields=path | module=media_context_tools; runtime:read_only; optional_deps=Pillow |
| image_read | Read a local image with zero-config OCR first, then optional multimodal analysis, and return visible text plus a concise analysis. | app.local_tools:LocalToolExecutor.image_read | group=media; source=optional; risk=medium | cap:workspace_read; read_fields=path | module=media_context_tools; runtime:read_only; optional_deps=Pillow |
| list_dir | List files and directories under one local directory path without reading file contents. | app.local_tools:LocalToolExecutor.list_dir | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| mail_extract_attachments | Extract attachments from a local Outlook .msg email into a target directory. | app.local_tools:LocalToolExecutor.mail_extract_attachments | group=archive; source=optional; risk=medium | cap:workspace_read,workspace_write | module=content_unpack_tools; runtime:write; optional_deps=extract-msg |
| read_file | Read one local file. Supports chunked reads plus Office/PDF text extraction for large document formats. | app.local_tools:LocalToolExecutor.read_file | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| read_section | Read a document section by matching a heading or section number and returning that section's content. | app.local_tools:LocalToolExecutor.read_section | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| request_user_input | Pause the turn and ask the user one to three structured follow-up questions. | app.local_tools:LocalToolExecutor.request_user_input | group=control; source=native; risk=low | metadata_only | module=workspace_core_tools; runtime:read_only |
| search_codebase | Search code or text files under a local root and return structured file, line, and text matches. | app.local_tools:LocalToolExecutor.search_codebase | group=file; source=native; risk=low | cap:workspace_read; read_fields=path,root | module=fs_content_tools; runtime:read_only |
| search_contents_in_file | Search text inside one known local file or extracted document text and return evidence snippets with read hints. | app.local_tools:LocalToolExecutor.search_contents_in_file | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| search_contents_in_file_multi | Run multiple text searches against one known local file or extracted document text and merge the evidence snippets. | app.local_tools:LocalToolExecutor.search_contents_in_file_multi | group=file; source=native; risk=low | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only |
| sessions_history | Read one local chat session summary and recent turns by session_id. | app.local_tools:LocalToolExecutor.sessions_history | group=session; source=native; risk=low | cap:workspace_read | module=session_context_tools; runtime:read_only |
| sessions_list | List recent local chat sessions so the agent can locate past context. | app.local_tools:LocalToolExecutor.sessions_list | group=session; source=native; risk=low | cap:workspace_read | module=session_context_tools; runtime:read_only |
| table_extract | Extract tables from a local PDF or XLSX file, optionally narrowed by query or page hint. | app.local_tools:LocalToolExecutor.table_extract | group=document; source=optional; risk=medium | cap:workspace_read; read_fields=path | module=fs_content_tools; runtime:read_only; optional_deps=pypdf,openpyxl |
| update_plan | Synchronize a lightweight checklist for the current turn. | app.local_tools:LocalToolExecutor.update_plan | group=control; source=native; risk=low | metadata_only | module=workspace_core_tools; runtime:read_only |
| web_download | Download a web file (binary-safe) to a local path under allowed roots for later reading or extraction. | app.local_tools:LocalToolExecutor.web_download | group=web; source=adapter; risk=medium | cap:workspace_write,network; network_table; write_fields=dst_path,path | module=web_context_tools; runtime:write |
| web_fetch | Fetch one web page or document URL through the local hosted web fetcher. | app.local_tools:LocalToolExecutor.web_fetch | group=web; source=adapter; risk=medium | cap:network; network_table | module=web_context_tools; runtime:read_only |
| web_search | Search the web using the local hosted provider and return candidate URLs and snippets. | app.local_tools:LocalToolExecutor.web_search | group=web; source=adapter; risk=medium | cap:network; network_table | module=web_context_tools; runtime:read_only |
| write_stdin | Write characters to a running exec_command session, or poll for fresh output. | app.local_tools:LocalToolExecutor.write_stdin | group=shell; source=adapter; risk=high | cap:shell; shell_table | module=workspace_core_tools; runtime:write |
## Metadata Coverage
- Registered tools: `29`
- Metadata-covered tools: `29`
- Missing metadata: `0`

## Validator Coverage
- Every registered tool now has metadata capability coverage.
- Legacy hardcoded validator tables still remain for network, shell, and path-field enforcement.
- Runtime read/write mode sets still remain in `app/vintage_programmer_runtime.py`.

## Tools Present in Metadata but Not Registered
None.
## Tools Registered but Missing Metadata
None.
## Unknown Tools
None.
## Tools With Unclear Implementation
None.
## Tools Requiring Owner Confirmation
None. Optional-dependency tools are documented separately but were not blocked in this phase.
## Optional Dependency Tools
fact_check_file, image_inspect, image_read, mail_extract_attachments, table_extract
## Extraction Limitations
- Descriptions and schemas are taken from the registered tool specs exposed by the scoped office executor.
- Implementation origin is inferred from the bound executor method on the current runtime path.
- Validator coverage combines metadata capability requirements with the current hardcoded boundary tables; it does not claim future metadata-only enforcement.
