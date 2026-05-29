from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field

from app.attachments import image_to_data_url_with_meta
from app.config import AppConfig, get_access_roots
from app.local_tools import LocalToolExecutor
from app.openai_auth import OpenAIAuthManager, normalize_model_for_auth_mode
from app.runtime_errors import classify_llm_exception as classify_runtime_llm_exception


class ExecCommandArgs(BaseModel):
    cmd: str = Field(description="Command string, e.g. `rg TODO .` or `pytest tests/test_app.py`")
    cwd: str = Field(default=".", description="Working directory relative to workspace")
    yield_time_ms: int = Field(default=1000, ge=0, le=10000)
    max_output_chars: int = Field(default=12000, ge=256, le=60000)
    tty: bool = False


class WriteStdinArgs(BaseModel):
    session_id: int
    chars: str = ""
    yield_time_ms: int = Field(default=1000, ge=0, le=10000)
    max_output_chars: int = Field(default=12000, ge=256, le=60000)


class ReadFileArgs(BaseModel):
    path: str
    start_char: int = Field(default=0, ge=0)
    max_chars: int = Field(default=200000, ge=128, le=1000000)
    start_line: int = Field(default=0, ge=0)
    max_lines: int = Field(default=0, ge=0, le=200000)


class ListDirArgs(BaseModel):
    path: str = Field(default=".")
    max_entries: int = Field(default=200, ge=1, le=500)


class SearchContentsInFileArgs(BaseModel):
    path: str
    query: str
    max_matches: int = Field(default=8, ge=1, le=20)
    context_chars: int = Field(default=280, ge=40, le=2000)


class SearchContentsInFileMultiArgs(BaseModel):
    path: str
    queries: list[str]
    per_query_max_matches: int = Field(default=3, ge=1, le=10)
    context_chars: int = Field(default=280, ge=40, le=2000)


class GlobFileSearchArgs(BaseModel):
    pattern: str
    path: str = Field(default=".")
    max_results: int = Field(default=200, ge=1, le=500)


class ReadSectionArgs(BaseModel):
    path: str
    heading: str
    max_chars: int = Field(default=12000, ge=512, le=50000)


class TableExtractArgs(BaseModel):
    path: str
    query: str = ""
    page_hint: int = Field(default=0, ge=0)
    max_tables: int = Field(default=5, ge=1, le=20)
    max_rows: int = Field(default=25, ge=1, le=200)


class FactCheckFileArgs(BaseModel):
    path: str
    claim: str
    queries: list[str] = Field(default_factory=list)
    max_evidence: int = Field(default=6, ge=1, le=12)


class SearchCodebaseArgs(BaseModel):
    query: str
    root: str = "."
    max_matches: int = Field(default=20, ge=1, le=100)
    file_glob: str = ""
    use_regex: bool = False
    case_sensitive: bool = False


class ArchiveExtractArgs(BaseModel):
    zip_path: str
    dst_dir: str = Field(default="", description="Destination directory. Empty means sibling folder next to zip file.")
    overwrite: bool = True
    create_dirs: bool = True
    max_entries: int = Field(default=20000, ge=1, le=100000)
    max_total_bytes: int = Field(default=524288000, ge=1024, le=2147483648)


class MailExtractAttachmentsArgs(BaseModel):
    msg_path: str
    dst_dir: str = Field(default="", description="Destination directory. Empty means <msg_stem>_attachments.")
    overwrite: bool = True
    create_dirs: bool = True
    max_attachments: int = Field(default=500, ge=1, le=5000)
    max_total_bytes: int = Field(default=524288000, ge=1024, le=2147483648)


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)
    timeout_sec: int = Field(default=12, ge=3, le=30)


class WebFetchArgs(BaseModel):
    url: str
    max_chars: int = Field(default=120000, ge=512, le=500000)
    timeout_sec: int = Field(default=12, ge=3, le=30)


class WebDownloadArgs(BaseModel):
    url: str
    dst_path: str = ""
    overwrite: bool = True
    create_dirs: bool = True
    timeout_sec: int = Field(default=20, ge=3, le=120)
    max_bytes: int = Field(default=52428800, ge=1024, le=209715200)


class ApplyPatchArgs(BaseModel):
    patch: str
    cwd: str = "."
    check: bool = False


class ImageInspectArgs(BaseModel):
    path: str


class ImageReadArgs(BaseModel):
    path: str
    prompt: str = ""
    max_output_chars: int = Field(default=12000, ge=256, le=24000)


class BrowserOpenArgs(BaseModel):
    url: str
    timeout_ms: int = Field(default=20000, ge=1000, le=60000)


class BrowserClickArgs(BaseModel):
    selector: str
    timeout_ms: int = Field(default=12000, ge=1000, le=60000)


class BrowserTypeArgs(BaseModel):
    selector: str
    text: str
    submit: bool = False
    clear: bool = True
    timeout_ms: int = Field(default=12000, ge=1000, le=60000)


class BrowserWaitArgs(BaseModel):
    selector: str = ""
    timeout_ms: int = Field(default=5000, ge=250, le=60000)
    state: str = "visible"


class BrowserSnapshotArgs(BaseModel):
    max_chars: int = Field(default=12000, ge=400, le=50000)


class BrowserScreenshotArgs(BaseModel):
    path: str = ""
    full_page: bool = True


class UpdatePlanArgs(BaseModel):
    explanation: str = ""
    plan: list[dict[str, str]]


class RequestUserInputArgs(BaseModel):
    questions: list[dict[str, Any]]


class SessionsListArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class SessionsHistoryArgs(BaseModel):
    session_id: str
    max_turns: int = Field(default=80, ge=1, le=800)


class VPRuntimeBackend:
    """Minimal app-owned backend for the active Vintage Programmer runtime."""

    def __init__(
        self,
        config: AppConfig,
        *,
        kernel_runtime: Any | None = None,
        tool_executor: Any | None = None,
        host: Any | None = None,
    ) -> None:
        self.config = config
        self._host = host
        self.tools = tool_executor or LocalToolExecutor(config)
        if hasattr(self.tools, "set_image_read_handler"):
            try:
                self.tools.set_image_read_handler(self._image_read_tool_payload)
            except Exception:
                pass
        self._auth_manager = OpenAIAuthManager(config)

        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
            from langchain_core.tools import StructuredTool
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(
                "Missing dependency: langchain_openai. Install with `pip install langchain-openai`."
            ) from exc

        self._AIMessage = AIMessage
        self._HumanMessage = HumanMessage
        self._SystemMessage = SystemMessage
        self._ToolMessage = ToolMessage
        self._StructuredTool = StructuredTool
        self._ChatOpenAI = ChatOpenAI
        _ = kernel_runtime
        self._lc_tools = self._build_langchain_tools()
        self._lc_tool_map = {
            str(getattr(tool, "name", "") or "").strip(): tool
            for tool in self._lc_tools
            if str(getattr(tool, "name", "") or "").strip()
        }
        self._lc_tool_map_casefold = {name.lower(): tool for name, tool in self._lc_tool_map.items()}
        self._model_failover_lock = threading.Lock()
        self._model_failover_state: dict[str, dict[str, int | float]] = {}

    def resolve_auth(self, mode: str) -> Any:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "api_key":
            return self._auth_manager._resolve_api_key_auth()
        return self._auth_manager.resolve()

    def default_model(self) -> str:
        return str(self.config.default_model or "")

    def _ensure_openai_ca_env(self, ca_cert_path: str) -> None:
        os.environ.setdefault("SSL_CERT_FILE", ca_cert_path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_cert_path)

    def _build_llm(self, model: str, max_output_tokens: int, use_responses_api: bool | None = None):
        auth = self._auth_manager.require()
        return self._build_llm_direct_fallback(
            auth=auth,
            model=model,
            max_output_tokens=max_output_tokens,
            use_responses_api=use_responses_api,
        )

    def build_llm(
        self,
        *,
        model: str,
        max_output_tokens: int,
        use_responses_api: bool | None = None,
    ):
        return self._build_llm(
            model=model,
            max_output_tokens=max_output_tokens,
            use_responses_api=use_responses_api,
        )

    def _build_llm_direct_fallback(
        self,
        *,
        auth: Any,
        model: str,
        max_output_tokens: int,
        use_responses_api: bool | None = None,
    ):
        selected_use_responses = self.config.openai_use_responses_api if use_responses_api is None else use_responses_api
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": auth.api_key,
            "max_tokens": max_output_tokens,
            "use_responses_api": selected_use_responses,
        }
        if self.config.openai_temperature is not None:
            kwargs["temperature"] = self.config.openai_temperature
        if self.config.openai_base_url:
            kwargs["base_url"] = self._normalize_base_url(self.config.openai_base_url)
        if self.config.openai_ca_cert_path:
            self._ensure_openai_ca_env(self.config.openai_ca_cert_path)
        return self._ChatOpenAI(**kwargs)

    def _invoke_chat_with_runner(
        self,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        candidates = self._build_model_candidates(model)
        notes: list[str] = []
        last_exc: Exception | None = None
        attempted_any = False

        for candidate in candidates:
            cooldown_left = self._model_cooldown_left(candidate)
            if cooldown_left > 0:
                notes.append(f"模型 {candidate} 仍在冷却中（剩余约 {cooldown_left}s），跳过。")
                continue

            attempted_any = True
            try:
                response, runner, invoke_notes = self._invoke_single_model(
                    messages=messages,
                    model=candidate,
                    max_output_tokens=max_output_tokens,
                    enable_tools=enable_tools,
                    tool_names=tool_names,
                    event_cb=event_cb,
                )
                self._mark_model_success(candidate)
                if candidate != model:
                    notes.append(f"模型故障转移: {model} -> {candidate}")
                notes.extend(invoke_notes)
                return response, runner, candidate, notes
            except Exception as exc:
                last_exc = exc
                if not self._is_failover_error(exc):
                    raise
                cooldown_sec = self._mark_model_failure(candidate)
                notes.append(
                    f"模型 {candidate} 调用失败（{self._shorten(exc, 220)}），进入冷却 {cooldown_sec}s，尝试下一个候选模型。"
                )

        if not attempted_any and candidates:
            primary = candidates[0]
            notes.append("所有候选模型均处于冷却状态，强制重试主模型一次。")
            response, runner, invoke_notes = self._invoke_single_model(
                messages=messages,
                model=primary,
                max_output_tokens=max_output_tokens,
                enable_tools=enable_tools,
                tool_names=tool_names,
                event_cb=event_cb,
            )
            notes.extend(invoke_notes)
            return response, runner, primary, notes

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No model candidates available")

    def _invoke_with_runner_recovery(
        self,
        runner: Any,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Any, Any, str, list[str]]:
        try:
            return self._invoke_runner(runner, messages, event_cb=event_cb), runner, model, []
        except Exception as exc:
            if not (self._is_failover_error(exc) or self._is_405_error(exc)):
                raise
            recovered_msg, recovered_runner, recovered_model, notes = self._invoke_chat_with_runner(
                messages=messages,
                model=model,
                max_output_tokens=max_output_tokens,
                enable_tools=enable_tools,
                tool_names=tool_names,
                event_cb=event_cb,
            )
            prefix = f"模型 {model} 在持续推理阶段失败（{self._shorten(exc, 200)}），已自动恢复重试。"
            return recovered_msg, recovered_runner, recovered_model, [prefix, *notes]

    def _invoke_single_model(
        self,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Any, Any, list[str]]:
        notes: list[str] = []
        llm = self._build_llm(model=model, max_output_tokens=max_output_tokens)
        runner = llm.bind_tools(self._select_langchain_tools(tool_names)) if enable_tools else llm
        try:
            return self._invoke_runner(runner, messages, event_cb=event_cb), runner, notes
        except Exception as exc:
            if not self._is_405_error(exc):
                raise

        fallback_use_responses = not self.config.openai_use_responses_api
        notes.append(
            f"模型 {model} 返回 405，自动切换 use_responses_api={str(fallback_use_responses).lower()} 重试。"
        )
        llm_fb = self._build_llm(
            model=model,
            max_output_tokens=max_output_tokens,
            use_responses_api=fallback_use_responses,
        )
        runner_fb = llm_fb.bind_tools(self._select_langchain_tools(tool_names)) if enable_tools else llm_fb
        return self._invoke_runner(runner_fb, messages, event_cb=event_cb), runner_fb, notes

    @staticmethod
    def _invoke_runner(
        runner: Any,
        messages: list[Any],
        *,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        if event_cb is not None and hasattr(runner, "invoke_with_events"):
            return runner.invoke_with_events(messages, event_cb=event_cb)
        return runner.invoke(messages)

    def _build_model_candidates(self, primary_model: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for raw in [primary_model, *self.config.model_fallbacks]:
            model = self._normalize_model_for_current_auth(str(raw or "").strip())
            if not model:
                continue
            key = model.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(model)
        return candidates

    def _normalize_model_for_current_auth(self, model: str) -> str:
        resolved = self._auth_manager.resolve()
        return normalize_model_for_auth_mode(model, resolved.mode)

    def _mark_model_success(self, model: str) -> None:
        key = model.strip().lower()
        if not key:
            return
        now = time.time()
        with self._model_failover_lock:
            state = self._model_failover_state.setdefault(key, {})
            state["failures"] = 0
            state["cooldown_until"] = 0.0
            state["last_used_at"] = now

    def _mark_model_failure(self, model: str) -> int:
        key = model.strip().lower()
        if not key:
            return self.config.model_cooldown_base_sec
        now = time.time()
        with self._model_failover_lock:
            state = self._model_failover_state.setdefault(key, {})
            failures = int(state.get("failures") or 0) + 1
            state["failures"] = failures
            cooldown = min(
                self.config.model_cooldown_max_sec,
                self.config.model_cooldown_base_sec * (5 ** max(0, failures - 1)),
            )
            state["cooldown_until"] = now + cooldown
            state["last_failed_at"] = now
            return int(cooldown)

    def _model_cooldown_left(self, model: str) -> int:
        key = model.strip().lower()
        if not key:
            return 0
        now = time.time()
        with self._model_failover_lock:
            state = self._model_failover_state.get(key) or {}
            until = float(state.get("cooldown_until") or 0.0)
        if until <= now:
            return 0
        return int(until - now)

    def _build_langchain_tools(self) -> list[Any]:
        return [
            self._StructuredTool.from_function(
                name="exec_command",
                description="Run a workspace command in host mode and keep a resumable session for follow-up stdin or polling.",
                args_schema=ExecCommandArgs,
                func=self._exec_command_tool,
            ),
            self._StructuredTool.from_function(
                name="write_stdin",
                description="Write bytes to a running exec_command session, or poll for more output.",
                args_schema=WriteStdinArgs,
                func=self._write_stdin_tool,
            ),
            self._StructuredTool.from_function(
                name="apply_patch",
                description="Apply a freeform patch inside the workspace.",
                args_schema=ApplyPatchArgs,
                func=self._apply_patch_tool,
            ),
            self._StructuredTool.from_function(
                name="read_file",
                description="Read one local file. Supports chunked reads and document/PDF text extraction for large formats.",
                args_schema=ReadFileArgs,
                func=self._read_file_tool,
            ),
            self._StructuredTool.from_function(
                name="list_dir",
                description="List files and directories under one local directory path without reading file contents.",
                args_schema=ListDirArgs,
                func=self._list_dir_tool,
            ),
            self._StructuredTool.from_function(
                name="glob_file_search",
                description="Find files by glob pattern relative to the workspace or a given directory root.",
                args_schema=GlobFileSearchArgs,
                func=self._glob_file_search_tool,
            ),
            self._StructuredTool.from_function(
                name="search_contents_in_file",
                description="Search text inside one known local file or extracted document text and return evidence snippets with read hints.",
                args_schema=SearchContentsInFileArgs,
                func=self._search_contents_in_file_tool,
            ),
            self._StructuredTool.from_function(
                name="search_contents_in_file_multi",
                description="Run multiple search queries against one known local file or extracted document text and merge the evidence snippets.",
                args_schema=SearchContentsInFileMultiArgs,
                func=self._search_contents_in_file_multi_tool,
            ),
            self._StructuredTool.from_function(
                name="read_section",
                description="Read one matched section from a local document by heading or section title.",
                args_schema=ReadSectionArgs,
                func=self._read_section_tool,
            ),
            self._StructuredTool.from_function(
                name="table_extract",
                description="Extract table-like rows from a local PDF, spreadsheet, or document.",
                args_schema=TableExtractArgs,
                func=self._table_extract_tool,
            ),
            self._StructuredTool.from_function(
                name="fact_check_file",
                description="Check whether one local document supports or contradicts a claim and return evidence snippets.",
                args_schema=FactCheckFileArgs,
                func=self._fact_check_file_tool,
            ),
            self._StructuredTool.from_function(
                name="search_codebase",
                description="Search code or text files under a local root and return structured file, line, and text matches.",
                args_schema=SearchCodebaseArgs,
                func=self._search_codebase_tool,
            ),
            self._StructuredTool.from_function(
                name="web_search",
                description="Search the web by query and return candidate URLs/snippets.",
                args_schema=WebSearchArgs,
                func=self._web_search_tool,
            ),
            self._StructuredTool.from_function(
                name="web_fetch",
                description="Fetch one web page or document URL through the local hosted web fetcher.",
                args_schema=WebFetchArgs,
                func=self._web_fetch_tool,
            ),
            self._StructuredTool.from_function(
                name="web_download",
                description="Download one remote file to local storage so follow-up tools can read it from the workspace.",
                args_schema=WebDownloadArgs,
                func=self._web_download_tool,
            ),
            self._StructuredTool.from_function(
                name="sessions_list",
                description="List recent local chat sessions so the agent can locate past context.",
                args_schema=SessionsListArgs,
                func=self._sessions_list_tool,
            ),
            self._StructuredTool.from_function(
                name="sessions_history",
                description="Read one local chat session summary and recent turns by session_id.",
                args_schema=SessionsHistoryArgs,
                func=self._sessions_history_tool,
            ),
            self._StructuredTool.from_function(
                name="image_inspect",
                description="Inspect a local image and return basic metadata such as size, mode, and format.",
                args_schema=ImageInspectArgs,
                func=self._image_inspect_tool,
            ),
            self._StructuredTool.from_function(
                name="image_read",
                description="Read the visible contents of one local image, including OCR-style text extraction and a concise visual analysis.",
                args_schema=ImageReadArgs,
                func=self._image_read_tool,
            ),
            self._StructuredTool.from_function(
                name="archive_extract",
                description="Extract a local .zip archive into a target directory under allowed roots.",
                args_schema=ArchiveExtractArgs,
                func=self._archive_extract_tool,
            ),
            self._StructuredTool.from_function(
                name="mail_extract_attachments",
                description="Extract attachments from a local Outlook .msg email into a target directory.",
                args_schema=MailExtractAttachmentsArgs,
                func=self._mail_extract_attachments_tool,
            ),
            self._StructuredTool.from_function(
                name="update_plan",
                description="Synchronize a lightweight checklist for the current turn.",
                args_schema=UpdatePlanArgs,
                func=self._update_plan_tool,
            ),
            self._StructuredTool.from_function(
                name="request_user_input",
                description="Pause the turn and ask the user one to three structured follow-up questions.",
                args_schema=RequestUserInputArgs,
                func=self._request_user_input_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_open",
                description="Open a webpage in a headless browser session and capture the current page state.",
                args_schema=BrowserOpenArgs,
                func=self._browser_open_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_click",
                description="Click one element in the current browser session by CSS selector.",
                args_schema=BrowserClickArgs,
                func=self._browser_click_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_type",
                description="Type or fill text into the current browser session by CSS selector.",
                args_schema=BrowserTypeArgs,
                func=self._browser_type_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_wait",
                description="Wait for a selector or a timeout in the current browser session.",
                args_schema=BrowserWaitArgs,
                func=self._browser_wait_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_snapshot",
                description="Capture the current browser page title, URL, text excerpt, and top links.",
                args_schema=BrowserSnapshotArgs,
                func=self._browser_snapshot_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_screenshot",
                description="Save a screenshot from the current browser session to local storage.",
                args_schema=BrowserScreenshotArgs,
                func=self._browser_screenshot_tool,
            ),
        ]

    def build_langchain_tools(self) -> list[Any]:
        return list(getattr(self, "_lc_tools", None) or self._build_langchain_tools())

    def _resolve_tool_name(self, name: str) -> str:
        key = str(name or "").strip()
        if not key:
            return key
        if key in self._lc_tool_map:
            return key
        tool = self._lc_tool_map_casefold.get(key.lower())
        if tool is None:
            return key
        resolved = str(getattr(tool, "name", "") or "").strip()
        return resolved or key

    def _invoke_langchain_tool_fallback(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resolved_name = self._resolve_tool_name(name)
        tool = self._lc_tool_map.get(resolved_name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            payload = tool.invoke(arguments if isinstance(arguments, dict) else {})
        except Exception as exc:
            return {"ok": False, "error": f"Tool execution failed ({resolved_name}): {exc}"}
        if isinstance(payload, dict):
            return payload if "ok" in payload else {"ok": True, "result": payload}
        if isinstance(payload, str):
            stripped = payload.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    decoded = json.loads(stripped)
                except Exception:
                    decoded = None
                if isinstance(decoded, dict):
                    return decoded
            return {"ok": True, "output": payload}
        if isinstance(payload, (int, float, bool)) or payload is None:
            return {"ok": True, "output": payload}
        return {"ok": True, "output": str(payload)}

    def _execute_tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resolved_name = self._resolve_tool_name(name)
        args = arguments if isinstance(arguments, dict) else {}
        try:
            result = self.tools.execute(resolved_name, args)
        except Exception as exc:
            message = str(exc or "").strip()
            lowered = message.lower()
            if "not registered in module" in lowered or "unknown tool" in lowered:
                return self._invoke_langchain_tool_fallback(resolved_name, args)
            return {"ok": False, "error": message or f"Tool execution failed: {resolved_name}"}
        if isinstance(result, dict):
            error_text = str(result.get("error") or "").strip().lower()
            if not bool(result.get("ok", True)) and error_text.startswith("unknown tool:"):
                fallback = self._invoke_langchain_tool_fallback(resolved_name, args)
                if bool(fallback.get("ok", False)):
                    return fallback
            return result
        return {"ok": True, "output": result}

    def _select_langchain_tools(self, tool_names: list[str] | None = None) -> list[Any]:
        if not tool_names:
            return self._lc_tools
        selected: list[Any] = []
        seen: set[str] = set()
        for name in tool_names:
            key = self._resolve_tool_name(str(name or "").strip())
            if not key or key in seen:
                continue
            tool = self._lc_tool_map.get(key)
            if tool is None:
                continue
            seen.add(key)
            selected.append(tool)
        return selected

    def _exec_command_tool(
        self,
        cmd: str,
        cwd: str = ".",
        yield_time_ms: int = 1000,
        max_output_chars: int = 12000,
        tty: bool = False,
    ) -> str:
        return json.dumps(
            self.tools.exec_command(
                cmd=cmd,
                cwd=cwd,
                yield_time_ms=yield_time_ms,
                max_output_chars=max_output_chars,
                tty=tty,
            ),
            ensure_ascii=False,
        )

    def _write_stdin_tool(
        self,
        session_id: int,
        chars: str = "",
        yield_time_ms: int = 1000,
        max_output_chars: int = 12000,
    ) -> str:
        return json.dumps(
            self.tools.write_stdin(
                session_id=session_id,
                chars=chars,
                yield_time_ms=yield_time_ms,
                max_output_chars=max_output_chars,
            ),
            ensure_ascii=False,
        )

    def _apply_patch_tool(self, patch: str, cwd: str = ".", check: bool = False) -> str:
        return json.dumps(self.tools.apply_patch(patch=patch, cwd=cwd, check=check), ensure_ascii=False)

    def _read_section_tool(self, path: str, heading: str, max_chars: int = 12000) -> str:
        return json.dumps(self.tools.read_section(path=path, heading=heading, max_chars=max_chars), ensure_ascii=False)

    def _table_extract_tool(
        self, path: str, query: str = "", page_hint: int = 0, max_tables: int = 5, max_rows: int = 25
    ) -> str:
        return json.dumps(
            self.tools.table_extract(
                path=path,
                query=query,
                page_hint=page_hint,
                max_tables=max_tables,
                max_rows=max_rows,
            ),
            ensure_ascii=False,
        )

    def _fact_check_file_tool(
        self, path: str, claim: str, queries: list[str] | None = None, max_evidence: int = 6
    ) -> str:
        return json.dumps(
            self.tools.fact_check_file(path=path, claim=claim, queries=queries or [], max_evidence=max_evidence),
            ensure_ascii=False,
        )

    def _web_search_tool(self, query: str, max_results: int = 5, timeout_sec: int = 12) -> str:
        return json.dumps(self.tools.web_search(query=query, max_results=max_results, timeout_sec=timeout_sec), ensure_ascii=False)

    def _web_fetch_tool(self, url: str, max_chars: int = 120000, timeout_sec: int = 12) -> str:
        return json.dumps(self.tools.web_fetch(url=url, max_chars=max_chars, timeout_sec=timeout_sec), ensure_ascii=False)

    def _web_download_tool(
        self,
        url: str,
        dst_path: str = "",
        overwrite: bool = True,
        create_dirs: bool = True,
        timeout_sec: int = 20,
        max_bytes: int = 52428800,
    ) -> str:
        return json.dumps(
            self.tools.web_download(
                url=url,
                dst_path=dst_path,
                overwrite=overwrite,
                create_dirs=create_dirs,
                timeout_sec=timeout_sec,
                max_bytes=max_bytes,
            ),
            ensure_ascii=False,
        )

    def _sessions_list_tool(self, limit: int = 20) -> str:
        return json.dumps(self.tools.sessions_list(limit=limit), ensure_ascii=False)

    def _sessions_history_tool(self, session_id: str, max_turns: int = 80) -> str:
        return json.dumps(self.tools.sessions_history(session_id=session_id, max_turns=max_turns), ensure_ascii=False)

    def _image_inspect_tool(self, path: str) -> str:
        return json.dumps(self.tools.image_inspect(path=path), ensure_ascii=False)

    def _image_read_tool_payload(
        self,
        *,
        path: str,
        prompt: str = "",
        max_output_chars: int = 12000,
        model: str = "",
    ) -> dict[str, Any]:
        inspect_result = self.tools.image_inspect(path=path)
        if not isinstance(inspect_result, dict):
            return {"ok": False, "path": str(path or ""), "error": "image_inspect returned an invalid payload"}
        if not bool(inspect_result.get("ok")):
            return {
                "ok": False,
                "path": str(inspect_result.get("path") or path or "").strip(),
                "error": str(inspect_result.get("error") or "image inspection failed").strip(),
                "model_capability_status": "read_error",
            }

        inspected_path = str(inspect_result.get("path") or path or "").strip()
        mime = str(inspect_result.get("mime") or "").strip()
        width = int(inspect_result.get("width") or 0)
        height = int(inspect_result.get("height") or 0)
        base_warning = str(inspect_result.get("warning") or "").strip()
        requested_model = self._normalize_model_for_current_auth(
            str(model or self.default_model() or self.config.default_model or "").strip()
        )

        try:
            data_url, data_warning = image_to_data_url_with_meta(inspected_path, mime)
        except Exception as exc:
            return {
                "ok": False,
                "path": inspected_path,
                "mime": mime or None,
                "width": width,
                "height": height,
                "warning": base_warning or None,
                "visible_text": "",
                "analysis": "",
                "model_capability_status": "read_error",
                "error": f"failed to prepare image input: {exc}",
            }

        warnings = [item for item in (base_warning, data_warning) if str(item or "").strip()]
        system_text = (
            "You are a local image reading helper. "
            "Return JSON only with keys visible_text and analysis. "
            "visible_text must contain the readable text in the image as faithfully as possible, preserving line breaks when useful. "
            "If no readable text is present, use an empty string. "
            "analysis must briefly describe the relevant visual content without repeating visible_text verbatim."
        )
        prompt_text = str(prompt or "").strip() or "Read the image. Extract visible text and provide a concise analysis of the content."
        max_tokens = max(300, min(4096, int(max_output_chars / 3) + 256))
        messages = [
            self._SystemMessage(content=system_text),
            self._HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
            ),
        ]

        try:
            response, _, effective_model, invoke_notes = self._invoke_chat_with_runner(
                messages=messages,
                model=requested_model or self.default_model(),
                max_output_tokens=max_tokens,
                enable_tools=False,
            )
        except Exception as exc:
            error_text = str(exc or "").strip()
            lowered = error_text.lower()
            capability_status = (
                "unsupported_by_model"
                if any(
                    token in lowered
                    for token in (
                        "does not support image",
                        "doesn't support image",
                        "unsupported image",
                        "unsupported content type",
                        "image_url",
                        "vision",
                        "multimodal",
                        "input_image",
                        "only text",
                    )
                )
                else "read_error"
            )
            return {
                "ok": False,
                "path": inspected_path,
                "mime": mime or None,
                "width": width,
                "height": height,
                "warning": "; ".join(warnings) or None,
                "visible_text": "",
                "analysis": "",
                "model_capability_status": capability_status,
                "error": error_text or "image_read failed",
            }

        raw_text = self._content_to_text(getattr(response, "content", response)).strip()
        warning_text = "; ".join([*warnings, *[str(note).strip() for note in invoke_notes if str(note).strip()]]) or None
        if self._looks_like_image_capability_denial(raw_text):
            return {
                "ok": False,
                "path": inspected_path,
                "mime": mime or None,
                "width": width,
                "height": height,
                "warning": warning_text,
                "visible_text": "",
                "analysis": "",
                "model_capability_status": "unsupported_by_model",
                "error": raw_text or "model reported that image input is unsupported",
                "effective_model": effective_model,
            }

        parsed = self._parse_json_object(raw_text) or self._parse_loose_object_literal(raw_text)
        if isinstance(parsed, dict):
            visible_text = str(parsed.get("visible_text") or "").strip()
            analysis = str(parsed.get("analysis") or "").strip()
        else:
            visible_text = ""
            analysis = raw_text

        return {
            "ok": True,
            "path": inspected_path,
            "mime": mime or None,
            "width": width,
            "height": height,
            "warning": warning_text,
            "visible_text": visible_text[:max_output_chars],
            "analysis": analysis[:max_output_chars],
            "model_capability_status": "ok",
            "effective_model": effective_model,
        }

    def _image_read_tool(self, path: str, prompt: str = "", max_output_chars: int = 12000) -> str:
        return json.dumps(self.tools.image_read(path=path, prompt=prompt, max_output_chars=max_output_chars), ensure_ascii=False)

    def _archive_extract_tool(
        self,
        zip_path: str,
        dst_dir: str = "",
        overwrite: bool = True,
        create_dirs: bool = True,
        max_entries: int = 20000,
        max_total_bytes: int = 524288000,
    ) -> str:
        return json.dumps(
            self.tools.archive_extract(
                zip_path=zip_path,
                dst_dir=dst_dir,
                overwrite=overwrite,
                create_dirs=create_dirs,
                max_entries=max_entries,
                max_total_bytes=max_total_bytes,
            ),
            ensure_ascii=False,
        )

    def _mail_extract_attachments_tool(
        self,
        msg_path: str,
        dst_dir: str = "",
        overwrite: bool = True,
        create_dirs: bool = True,
        max_attachments: int = 500,
        max_total_bytes: int = 524288000,
    ) -> str:
        return json.dumps(
            self.tools.mail_extract_attachments(
                msg_path=msg_path,
                dst_dir=dst_dir,
                overwrite=overwrite,
                create_dirs=create_dirs,
                max_attachments=max_attachments,
                max_total_bytes=max_total_bytes,
            ),
            ensure_ascii=False,
        )

    def _update_plan_tool(self, plan: list[dict[str, str]], explanation: str = "") -> str:
        return json.dumps(self.tools.update_plan(plan=plan, explanation=explanation), ensure_ascii=False)

    def _request_user_input_tool(self, questions: list[dict[str, Any]]) -> str:
        return json.dumps(self.tools.request_user_input(questions=questions), ensure_ascii=False)

    def _browser_open_tool(self, url: str, timeout_ms: int = 20000) -> str:
        return json.dumps(self.tools.browser_open(url=url, timeout_ms=timeout_ms), ensure_ascii=False)

    def _browser_click_tool(self, selector: str, timeout_ms: int = 12000) -> str:
        return json.dumps(self.tools.browser_click(selector=selector, timeout_ms=timeout_ms), ensure_ascii=False)

    def _browser_type_tool(
        self,
        selector: str,
        text: str,
        submit: bool = False,
        clear: bool = True,
        timeout_ms: int = 12000,
    ) -> str:
        return json.dumps(
            self.tools.browser_type(
                selector=selector,
                text=text,
                submit=submit,
                clear=clear,
                timeout_ms=timeout_ms,
            ),
            ensure_ascii=False,
        )

    def _browser_wait_tool(self, selector: str = "", timeout_ms: int = 5000, state: str = "visible") -> str:
        return json.dumps(self.tools.browser_wait(selector=selector, timeout_ms=timeout_ms, state=state), ensure_ascii=False)

    def _browser_snapshot_tool(self, max_chars: int = 12000) -> str:
        return json.dumps(self.tools.browser_snapshot(max_chars=max_chars), ensure_ascii=False)

    def _browser_screenshot_tool(self, path: str = "", full_page: bool = True) -> str:
        return json.dumps(self.tools.browser_screenshot(path=path, full_page=full_page), ensure_ascii=False)

    def _list_dir_tool(self, path: str = ".", max_entries: int = 200) -> str:
        return json.dumps(self.tools.list_dir(path=path, max_entries=max_entries), ensure_ascii=False)

    def _glob_file_search_tool(self, pattern: str, path: str = ".", max_results: int = 200) -> str:
        return json.dumps(self.tools.glob_file_search(pattern=pattern, path=path, max_results=max_results), ensure_ascii=False)

    def _read_file_tool(
        self,
        path: str,
        start_char: int = 0,
        max_chars: int = 200000,
        start_line: int = 0,
        max_lines: int = 0,
    ) -> str:
        return json.dumps(
            self.tools.read_file(
                path=path,
                start_char=start_char,
                max_chars=max_chars,
                start_line=start_line,
                max_lines=max_lines,
            ),
            ensure_ascii=False,
        )

    def _search_contents_in_file_tool(
        self,
        path: str,
        query: str,
        max_matches: int = 8,
        context_chars: int = 280,
    ) -> str:
        return json.dumps(
            self.tools.search_contents_in_file(
                path=path,
                query=query,
                max_matches=max_matches,
                context_chars=context_chars,
            ),
            ensure_ascii=False,
        )

    def _search_contents_in_file_multi_tool(
        self,
        path: str,
        queries: list[str],
        per_query_max_matches: int = 3,
        context_chars: int = 280,
    ) -> str:
        return json.dumps(
            self.tools.search_contents_in_file_multi(
                path=path,
                queries=queries,
                per_query_max_matches=per_query_max_matches,
                context_chars=context_chars,
            ),
            ensure_ascii=False,
        )

    def _search_codebase_tool(
        self,
        query: str,
        root: str = ".",
        max_matches: int = 20,
        file_glob: str = "",
        use_regex: bool = False,
        case_sensitive: bool = False,
    ) -> str:
        result = self.tools.search_codebase(
            query=query,
            root=root,
            max_matches=max_matches,
            file_glob=file_glob,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
        )
        base_root = str(root or ".").strip() or "."
        try:
            base_match_count = int((result or {}).get("match_count") or len((result or {}).get("matches") or []))
        except Exception:
            base_match_count = 0
        if bool((result or {}).get("ok")) and base_match_count <= 0 and base_root in {"", "."} and not bool(file_glob.strip()) and bool(str(query or "").strip()):
            searched_roots: list[str] = [str((result or {}).get("root") or base_root)]
            for candidate in get_access_roots(self.config):
                candidate_root = str(candidate)
                if candidate_root in searched_roots:
                    continue
                extra = self.tools.search_codebase(
                    query=query,
                    root=candidate_root,
                    max_matches=max_matches,
                    file_glob=file_glob,
                    use_regex=use_regex,
                    case_sensitive=case_sensitive,
                )
                searched_roots.append(str((extra or {}).get("root") or candidate_root))
                try:
                    extra_match_count = int((extra or {}).get("match_count") or len((extra or {}).get("matches") or []))
                except Exception:
                    extra_match_count = 0
                if bool((extra or {}).get("ok")) and extra_match_count > 0:
                    merged = dict(extra)
                    merged["auto_root_fallback"] = True
                    merged["initial_root"] = "."
                    merged["searched_roots"] = searched_roots
                    return json.dumps(merged, ensure_ascii=False)
            if isinstance(result, dict):
                result = dict(result)
                result["auto_root_fallback"] = True
                result["initial_root"] = "."
                result["searched_roots"] = searched_roots
        return json.dumps(result, ensure_ascii=False)

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or "")
        out: list[str] = []
        for item in content:
            if isinstance(item, str):
                out.append(item)
                continue
            if not isinstance(item, dict):
                out.append(str(item))
                continue
            item_type = item.get("type")
            if item_type in {"text", "output_text", "input_text"}:
                text = item.get("text")
                if isinstance(text, str) and text:
                    out.append(text)
        return "\n".join(out).strip()

    def _shorten(self, text: Any, limit: int = 800) -> str:
        raw = str(text or "")
        if len(raw) <= limit:
            return raw
        return f"{raw[:limit]}\n...[truncated {len(raw) - limit} chars]"

    def _empty_usage(self) -> dict[str, int]:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}

    def _merge_usage(self, base: dict[str, int], extra: dict[str, int]) -> dict[str, int]:
        merged = dict(base)
        merged["input_tokens"] = int(merged.get("input_tokens", 0)) + int(extra.get("input_tokens", 0))
        merged["output_tokens"] = int(merged.get("output_tokens", 0)) + int(extra.get("output_tokens", 0))
        merged["total_tokens"] = int(merged.get("total_tokens", 0)) + int(extra.get("total_tokens", 0))
        merged["llm_calls"] = int(merged.get("llm_calls", 0)) + int(extra.get("llm_calls", 0))
        return merged

    def _extract_usage_from_message(self, message: Any) -> dict[str, int]:
        usage = self._empty_usage()
        usage_metadata = getattr(message, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            usage["input_tokens"] = int(usage_metadata.get("input_tokens") or usage_metadata.get("prompt_tokens") or 0)
            usage["output_tokens"] = int(usage_metadata.get("output_tokens") or usage_metadata.get("completion_tokens") or 0)
            usage["total_tokens"] = int(usage_metadata.get("total_tokens") or 0)
        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                if usage["input_tokens"] <= 0:
                    usage["input_tokens"] = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
                if usage["output_tokens"] <= 0:
                    usage["output_tokens"] = int(token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0)
                if usage["total_tokens"] <= 0:
                    usage["total_tokens"] = int(token_usage.get("total_tokens") or 0)
        if usage["total_tokens"] <= 0:
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        usage["llm_calls"] = 1 if (usage["input_tokens"] > 0 or usage["output_tokens"] > 0 or usage["total_tokens"] > 0) else 0
        return usage

    def _normalize_base_url(self, raw_url: str) -> str:
        url = raw_url.strip().strip("\"'").rstrip("/")
        parsed = urlparse(url)
        path = parsed.path or ""
        suffixes = ["/chat/completions", "/responses", "/v1/chat/completions", "/v1/responses"]
        lowered = path.lower()
        for suffix in suffixes:
            if lowered.endswith(suffix):
                path = path[: -len(suffix)] + ("/v1" if suffix.startswith("/v1/") else "")
                break
        return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), parsed.params, parsed.query, parsed.fragment))

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _parse_loose_object_literal(text: str) -> dict[str, Any] | None:
        raw = str(text or "")
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _looks_like_image_capability_denial(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        hints = (
            "cannot view the image",
            "can't view the image",
            "cannot access the image",
            "can't access the image",
            "unable to view the image",
            "unable to access the image",
            "i can't see the image",
            "i cannot see the image",
            "image input is not supported",
            "do not support image input",
        )
        return any(hint in lowered for hint in hints)

    def _is_failover_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        hints = (
            "429",
            "rate limit",
            "rate_limit",
            "timeout",
            "timed out",
            "temporarily unavailable",
            "service unavailable",
            "overloaded",
            "connection reset",
            "connection aborted",
            "connection error",
            "502",
            "503",
            "504",
            "quota",
            "insufficient",
            "authentication",
            "unauthorized",
            "forbidden",
            "401",
            "403",
        )
        return any(item in text for item in hints)

    def _is_405_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "405" in text or "method not allowed" in text


def create_vp_runtime_backend(
    config: Any,
    *,
    kernel_runtime: Any | None = None,
    tool_executor: Any | None = None,
    host: Any | None = None,
) -> VPRuntimeBackend:
    return VPRuntimeBackend(
        config,
        kernel_runtime=kernel_runtime,
        tool_executor=tool_executor,
        host=host,
    )


def classify_vp_llm_exception(exc: BaseException, *, phase: str, model: str) -> dict[str, Any]:
    return classify_runtime_llm_exception(exc, phase=phase, model=model)
