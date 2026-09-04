from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from app.attachments import image_to_data_url_with_meta
from app.config import AppConfig, get_access_roots, normalize_openai_base_url
from app.local_tools import (
    APPLY_PATCH_ARGUMENT_DESCRIPTION,
    APPLY_PATCH_TOOL_DESCRIPTION,
    EXEC_COMMAND_DEFAULT_YIELD_MS,
    EXEC_COMMAND_MAX_YIELD_MS,
    LocalToolExecutor,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
)
from app.openai_auth import OpenAIAuthManager, normalize_model_for_auth_mode
from app.runtime_errors import classify_llm_exception as classify_runtime_llm_exception
from app.serialization import safe_model_dump


class ExecCommandArgs(BaseModel):
    cmd: str = Field(description="Command string, e.g. `rg TODO .` or `pytest tests/test_app.py`")
    purpose: str = Field(
        min_length=1,
        max_length=240,
        description="One concise, user-facing sentence explaining why this command is needed. This is display-only and never grants permission.",
    )
    cwd: str = Field(default=".", description="Working directory under the active command roots.")
    yield_time_ms: int = Field(
        default=EXEC_COMMAND_DEFAULT_YIELD_MS,
        ge=0,
        le=EXEC_COMMAND_MAX_YIELD_MS,
        description="Maximum milliseconds to wait before returning output or a resumable session id; returns earlier on completion.",
    )
    max_output_chars: int = Field(
        default=12000,
        ge=256,
        le=60000,
        description="Maximum fresh output characters returned by this call.",
    )
    tty: bool = Field(
        default=False,
        description="Compatibility flag reported in the result; the current host runner uses pipes and does not allocate a PTY.",
    )


class WriteStdinArgs(BaseModel):
    session_id: int = Field(ge=1, description="Session id returned by a still-running exec_command call.")
    chars: str = Field(default="", description="Characters to write; leave empty to poll without writing.")
    yield_time_ms: int = Field(
        default=WRITE_STDIN_DEFAULT_YIELD_MS,
        ge=0,
        le=WRITE_STDIN_MAX_YIELD_MS,
        description="Maximum milliseconds to wait for fresh output after the optional write; returns earlier on completion.",
    )
    max_output_chars: int = Field(
        default=12000,
        ge=256,
        le=60000,
        description="Maximum fresh output characters returned by this call.",
    )


class ReadToolResultArgs(BaseModel):
    result_ref: str = Field(description="Opaque result_ref from a truncated tool response.")
    cursor: int = Field(default=0, ge=0, description="Character cursor returned by the previous chunk.")
    max_tokens: int = Field(default=4000, ge=512, le=8000, description="Maximum tokens to return in this chunk.")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Existing local file path under an allowed read root.")
    start_char: int = Field(default=0, ge=0, description="Zero-based character offset in character mode.")
    max_chars: int = Field(
        default=200000,
        ge=128,
        le=1000000,
        description="Maximum extracted characters returned in either character or line mode.",
    )
    start_line: int = Field(
        default=0,
        ge=0,
        description="One-based first line; 0 keeps character mode unless max_lines is set.",
    )
    max_lines: int = Field(
        default=0,
        ge=0,
        le=200000,
        description="Maximum lines to return; a value above 0 enables line mode.",
    )


class ListDirArgs(BaseModel):
    path: str = Field(default=".", description="Existing directory under an allowed read root.")
    max_entries: int = Field(default=200, ge=1, le=500, description="Maximum entries to return.")
    offset: int = Field(default=0, ge=0, description="Zero-based directory-entry offset.")


class SearchContentsInFileArgs(BaseModel):
    path: str = Field(description="Known local file or document path.")
    query: str = Field(description="Text to find in extracted file contents.")
    max_matches: int = Field(default=8, ge=1, le=20, description="Maximum matching snippets.")
    context_chars: int = Field(default=280, ge=40, le=2000, description="Context characters around each match.")


class SearchContentsInFileMultiArgs(BaseModel):
    path: str = Field(description="Known local file or document path.")
    queries: list[str] = Field(
        min_length=1,
        max_length=20,
        description="One to twenty distinct text queries to run against the same extracted contents.",
    )
    per_query_max_matches: int = Field(default=3, ge=1, le=10, description="Maximum snippets contributed by each query.")
    context_chars: int = Field(default=280, ge=40, le=2000, description="Context characters around each match.")


class GlobFileSearchArgs(BaseModel):
    pattern: str = Field(description="Glob pattern such as `**/*.cpp`; use a narrower pattern on large trees.")
    path: str = Field(default=".", description="Directory root under an allowed read root.")
    max_results: int = Field(default=200, ge=1, le=500, description="Maximum matching file paths.")
    offset: int = Field(default=0, ge=0, description="Zero-based matching-path offset.")


class ReadSectionArgs(BaseModel):
    path: str = Field(description="Local document path.")
    heading: str = Field(description="Heading text or section number to match.")
    max_chars: int = Field(default=12000, ge=512, le=50000, description="Maximum section characters returned.")
    start_char: int = Field(default=0, ge=0, description="Character offset within the matched section for continuation reads.")


class TableExtractArgs(BaseModel):
    path: str = Field(description="Local PDF or OpenXML Excel workbook path (.xlsx/.xlsm/.xltx/.xltm).")
    query: str = Field(default="", description="Optional text used to narrow matching tables or rows.")
    page_hint: int = Field(default=0, ge=0, description="One-based PDF page hint; 0 searches without a fixed page.")
    max_tables: int = Field(default=5, ge=1, le=20, description="Maximum tables or worksheets returned.")
    max_rows: int = Field(default=25, ge=1, le=200, description="Maximum rows returned per table or worksheet.")


class FactCheckFileArgs(BaseModel):
    path: str = Field(description="Local document whose extracted text will be searched for related evidence.")
    claim: str = Field(description="Claim to investigate; the heuristic verdict still requires model judgment.")
    queries: list[str] = Field(default_factory=list, description="Optional explicit evidence-search phrases.")
    max_evidence: int = Field(default=6, ge=1, le=12, description="Maximum evidence snippets returned.")


class SearchCodebaseArgs(BaseModel):
    query: str = Field(description="Literal text by default, or a regular expression when use_regex is true.")
    root: str = Field(default=".", description="Directory root under an allowed read root.")
    max_matches: int = Field(default=20, ge=1, le=100, description="Maximum line matches returned.")
    file_glob: str = Field(default="", description="Optional file filter such as `*.py` or `**/*.cpp`.")
    use_regex: bool = Field(default=False, description="Interpret query as a regular expression when true.")
    case_sensitive: bool = Field(default=False, description="Use case-sensitive matching when true.")


class ArchiveExtractArgs(BaseModel):
    zip_path: str = Field(description="Existing local .zip archive.")
    dst_dir: str = Field(default="", description="Destination directory. Empty means sibling folder next to zip file.")
    overwrite: bool = Field(default=True, description="Replace existing destination files when true.")
    create_dirs: bool = Field(default=True, description="Create the destination directory when missing.")
    max_entries: int = Field(default=20000, ge=1, le=100000, description="Maximum archive entries allowed.")
    max_total_bytes: int = Field(default=524288000, ge=1024, le=2147483648, description="Maximum total uncompressed bytes allowed.")


class MailExtractAttachmentsArgs(BaseModel):
    msg_path: str = Field(description="Existing local Outlook .msg file.")
    dst_dir: str = Field(default="", description="Destination directory. Empty means <msg_stem>_attachments.")
    overwrite: bool = Field(default=True, description="Replace existing attachment files when true.")
    create_dirs: bool = Field(default=True, description="Create the destination directory when missing.")
    max_attachments: int = Field(default=500, ge=1, le=5000, description="Maximum attachments allowed.")
    max_total_bytes: int = Field(default=524288000, ge=1024, le=2147483648, description="Maximum total extracted bytes allowed.")


class WebSearchArgs(BaseModel):
    query: str = Field(description="Web search query.")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum candidate results.")
    timeout_sec: int = Field(default=12, ge=3, le=30, description="Provider timeout in seconds.")


class WebFetchArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS page/document URL to fetch as readable content.")
    max_chars: int = Field(default=120000, ge=512, le=500000, description="Maximum extracted text characters.")
    timeout_sec: int = Field(default=12, ge=3, le=30, description="Fetch timeout in seconds.")


class WebDownloadArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS URL of the remote file.")
    dst_path: str = Field(default="", description="Destination under an allowed writable root; empty derives a filename.")
    overwrite: bool = Field(default=True, description="Replace an existing destination file when true.")
    create_dirs: bool = Field(default=True, description="Create missing parent directories when true.")
    timeout_sec: int = Field(default=20, ge=3, le=120, description="Download timeout in seconds.")
    max_bytes: int = Field(default=52428800, ge=1024, le=209715200, description="Maximum downloaded bytes.")


class ApplyPatchArgs(BaseModel):
    patch: str = Field(description=APPLY_PATCH_ARGUMENT_DESCRIPTION)
    cwd: str = Field(default=".", description="Base directory used to resolve relative patch paths.")
    check: bool = Field(default=False, description="Validate the complete patch without changing files when true.")


class ImageInspectArgs(BaseModel):
    path: str = Field(description="Existing local image path.")


class ImageReadArgs(BaseModel):
    path: str = Field(description="Existing local image path.")
    prompt: str = Field(default="", description="Optional focus for OCR or visual analysis.")
    max_output_chars: int = Field(default=12000, ge=256, le=24000, description="Maximum visible-text and analysis characters.")


class BrowserOpenArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS URL to open in the current browser session.")
    timeout_ms: int = Field(default=20000, ge=1000, le=60000, description="Navigation timeout in milliseconds.")


class BrowserClickArgs(BaseModel):
    selector: str = Field(description="CSS selector; the first matching element is clicked.")
    timeout_ms: int = Field(default=12000, ge=1000, le=60000, description="Element-action timeout in milliseconds.")


class BrowserTypeArgs(BaseModel):
    selector: str = Field(description="CSS selector; the first matching input is used.")
    text: str = Field(description="Text to enter.")
    submit: bool = Field(default=False, description="Press Enter after typing when true.")
    clear: bool = Field(default=True, description="Replace existing content when true; append/type when false.")
    timeout_ms: int = Field(default=12000, ge=1000, le=60000, description="Element-action timeout in milliseconds.")


class BrowserWaitArgs(BaseModel):
    selector: str = Field(default="", description="CSS selector to wait for; empty means wait only for timeout_ms.")
    timeout_ms: int = Field(default=5000, ge=250, le=60000, description="Maximum wait in milliseconds.")
    state: Literal["attached", "detached", "visible", "hidden"] = Field(
        default="visible",
        description="Required selector state; ignored when selector is empty.",
    )


class BrowserScrollArgs(BaseModel):
    direction: Literal["down", "up", "left", "right"] = Field(
        default="down",
        description="Page scroll direction when selector is empty.",
    )
    amount: int = Field(default=900, ge=1, le=5000, description="Pixels to scroll when selector is empty.")
    selector: str = Field(default="", description="CSS selector to bring into view instead of scrolling by direction.")
    timeout_ms: int = Field(default=5000, ge=250, le=60000, description="Selector scroll timeout in milliseconds.")


class BrowserSnapshotArgs(BaseModel):
    max_chars: int = Field(default=12000, ge=400, le=50000, description="Maximum visible page-text characters.")
    start_char: int = Field(default=0, ge=0, description="Character offset for continuing page text.")
    link_offset: int = Field(default=0, ge=0, description="Link offset for continuing the link list.")
    max_links: int = Field(default=12, ge=1, le=100, description="Maximum links returned in this snapshot.")


class BrowserScreenshotArgs(BaseModel):
    path: str = Field(default="", description="Destination under an allowed writable root; empty uses an automatic path.")
    full_page: bool = Field(default=True, description="Capture the full page when true, otherwise the viewport.")


class PlanItemArgs(BaseModel):
    step: str = Field(description="Human-readable checklist step.")
    status: Literal["pending", "in_progress", "completed"] = Field(description="Current step status.")
    description: str = Field(
        default="",
        description="Compatibility detail for placeholder step names; normally leave empty and put the real text in step.",
    )


class UpdatePlanArgs(BaseModel):
    explanation: str = Field(default="", description="Optional concise reason for this plan update.")
    plan: list[PlanItemArgs] = Field(
        min_length=1,
        description="Full current checklist. Use exactly one in_progress item until all items are completed.",
    )


class UserInputOptionArgs(BaseModel):
    label: str = Field(description="Short user-facing option label.")
    description: str = Field(description="One sentence explaining the option's impact or tradeoff.")


class UserInputQuestionArgs(BaseModel):
    header: str = Field(max_length=12, description="Short header label of at most 12 characters.")
    id: str = Field(description="Stable snake_case identifier for mapping the answer.")
    question: str = Field(description="Single-sentence question shown to the user.")
    options: list[UserInputOptionArgs] = Field(
        min_length=2,
        max_length=3,
        description="Two or three mutually exclusive choices; the client adds free-form Other automatically.",
    )


class RequestUserInputArgs(BaseModel):
    questions: list[UserInputQuestionArgs] = Field(
        min_length=1,
        max_length=3,
        description="One to three structured questions.",
    )


class SpawnSubagentArgs(BaseModel):
    task: str = Field(description="Self-contained assignment with scope, relevant paths, and expected result.")
    role: Literal["explorer", "tester", "analyst", "summarizer"] = Field(
        default="explorer",
        description="Builtin role: explorer, tester, analyst, or summarizer.",
    )
    label: str = Field(default="", description="Short user-facing label for the delegated work.")


class WaitSubagentsArgs(BaseModel):
    subagent_ids: list[str] = Field(
        default_factory=list,
        description="Subagent ids to collect from this parent Thread; omit to collect all relevant children.",
    )
    timeout_seconds: float = Field(
        default=30,
        ge=0,
        le=300,
        description="Maximum seconds to wait before returning any still-running ids.",
    )


class SaveSkillArgs(BaseModel):
    name: str = Field(description="Team Skill name using lowercase letters, digits, hyphens, or underscores.")
    description: str = Field(description="Trigger description that tells models when this Skill should be used.")
    body: str = Field(description="Markdown instruction body only; do not include YAML frontmatter.")
    enabled: bool = Field(default=True, description="Whether the Team Skill is enabled after saving.")
    overwrite: bool = Field(default=False, description="Set true only to replace an existing Team SKILL.md of the same name.")


class ListTasksArgs(BaseModel):
    query: str = Field(
        default="",
        description="Optional topic text matched against Task titles, goals, summaries, lists, and project names.",
    )
    status: str = Field(
        default="",
        description="Optional exact lifecycle status filter: active, blocked, completed, or archived. Leave empty to avoid filtering.",
    )
    project_scope: Literal["current_project", "all_projects"] = Field(
        default="all_projects",
        description="Search all locally registered Task snapshots by default, or only the active project when explicitly requested.",
    )
    include_archived: bool = Field(
        default=False,
        description="Include archived Tasks; automatically enabled when status is archived.",
    )
    detail_level: Literal["summary", "full"] = Field(
        default="summary",
        description="Use summary to identify candidates; use full after narrowing to retrieve a complete replacement baseline.",
    )
    limit: int = Field(default=20, ge=1, le=50, description="Maximum matching Tasks to return.")


class SaveTaskArgs(BaseModel):
    task_id: str = Field(default="", max_length=160, description="Existing Task id to update; leave empty only when creating a new Task.")
    title: str = Field(min_length=1, max_length=120, description="Short, recognizable title shown in the Tasks list.")
    goal: str = Field(min_length=1, max_length=4000, description="Concrete outcome that defines what the Task is trying to achieve.")
    summary: str = Field(min_length=1, max_length=12000, description="Self-contained continuation summary that does not require opening the source Thread.")
    progress: list[str] = Field(default_factory=list, max_length=32, description="Important work already completed or verified.")
    next_steps: list[str] = Field(default_factory=list, max_length=24, description="Ordered concrete actions that should happen next.")
    decisions: list[str] = Field(default_factory=list, max_length=24, description="Key decisions and constraints future work must preserve.")
    blockers: list[str] = Field(default_factory=list, max_length=16, description="Known blockers, missing inputs, or unresolved risks.")
    artifacts: list[str] = Field(default_factory=list, max_length=32, description="Relevant files, branches, commits, pull requests, or other durable artifacts.")
    status: Literal["active", "blocked", "completed", "archived"] = Field(
        default="active",
        description="Current lifecycle status of the Task.",
    )


class SessionsListArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=200, description="Maximum recent sessions from the current project.")
    offset: int = Field(default=0, ge=0, description="Zero-based offset into matching recent sessions.")


class SessionsHistoryArgs(BaseModel):
    session_id: str = Field(description="Session id returned by sessions_list.")
    max_turns: int = Field(default=80, ge=1, le=800, description="Maximum most-recent turns returned.")
    recent_offset: int = Field(
        default=0,
        ge=0,
        description="How many of the newest turns to skip when reading older history pages.",
    )


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
        except Exception as exc:
            raise RuntimeError(
                "Missing dependency: langchain_core. Install the project dependencies and retry."
            ) from exc

        self._AIMessage = AIMessage
        self._HumanMessage = HumanMessage
        self._SystemMessage = SystemMessage
        self._ToolMessage = ToolMessage
        self._StructuredTool = StructuredTool
        self._ChatOpenAI = None
        self._chat_openai_lock = threading.Lock()
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
        self._run_http_clients_lock = threading.Lock()
        self._run_http_clients: dict[str, list[Any]] = {}

    def _current_cancel_event(self) -> Any | None:
        getter = getattr(self.tools, "_current_cancel_event", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _current_run_id(self) -> str:
        getter = getattr(self.tools, "_current_run_id", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""

    def _new_owned_http_client(self) -> Any | None:
        run_id = self._current_run_id()
        if not run_id:
            return None
        from openai import DefaultHttpxClient

        client = DefaultHttpxClient()
        with self._run_http_clients_lock:
            self._run_http_clients.setdefault(run_id, []).append(client)
        return client

    def release_model_run(self, *, run_id: str) -> int:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return 0
        with self._run_http_clients_lock:
            clients = list(self._run_http_clients.pop(normalized_run_id, []))
        for client in clients:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return len(clients)

    def _cancelled_model_response(self) -> Any:
        return self._AIMessage(
            content="",
            additional_kwargs={"vp_model_invocation_cancelled": True},
        )

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

    def _chat_openai_cls(self):
        if self._ChatOpenAI is not None:
            return self._ChatOpenAI
        with self._chat_openai_lock:
            if self._ChatOpenAI is not None:
                return self._ChatOpenAI
            try:
                from langchain_openai import ChatOpenAI
            except Exception as exc:
                raise RuntimeError(
                    "Missing dependency: langchain_openai. Install with `pip install langchain-openai`."
                ) from exc
            self._ChatOpenAI = ChatOpenAI
            return self._ChatOpenAI

    def _build_llm(
        self,
        model: str,
        max_output_tokens: int,
        use_responses_api: bool | None = None,
        reasoning_effort: str | None = None,
    ):
        auth = self._auth_manager.require()
        return self._build_llm_direct_fallback(
            auth=auth,
            model=model,
            max_output_tokens=max_output_tokens,
            use_responses_api=use_responses_api,
            reasoning_effort=reasoning_effort,
        )

    def build_llm(
        self,
        *,
        model: str,
        max_output_tokens: int,
        use_responses_api: bool | None = None,
        reasoning_effort: str | None = None,
    ):
        return self._build_llm(
            model=model,
            max_output_tokens=max_output_tokens,
            use_responses_api=use_responses_api,
            reasoning_effort=reasoning_effort,
        )

    def _build_llm_direct_fallback(
        self,
        *,
        auth: Any,
        model: str,
        max_output_tokens: int,
        use_responses_api: bool | None = None,
        reasoning_effort: str | None = None,
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
        normalized_reasoning_effort = str(reasoning_effort or "").strip().lower()
        if normalized_reasoning_effort:
            kwargs["reasoning_effort"] = normalized_reasoning_effort
        if self.config.openai_base_url:
            kwargs["base_url"] = self._normalize_base_url(self.config.openai_base_url)
        if self.config.openai_ca_cert_path:
            self._ensure_openai_ca_env(self.config.openai_ca_cert_path)
        owned_http_client = self._new_owned_http_client()
        if owned_http_client is not None:
            # LangChain caches its default HTTP transport across ChatOpenAI
            # instances. Agent runs need an owned transport so cancelling one
            # request cannot close the connection pool used by later Threads.
            kwargs["http_client"] = owned_http_client
        return self._chat_openai_cls()(**kwargs)

    def _invoke_chat_with_runner(
        self,
        messages: list[Any],
        model: str,
        max_output_tokens: int,
        enable_tools: bool,
        tool_names: list[str] | None = None,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
        reasoning_effort: str | None = None,
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
                    reasoning_effort=reasoning_effort,
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
                reasoning_effort=reasoning_effort,
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
        reasoning_effort: str | None = None,
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
                reasoning_effort=reasoning_effort,
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
        reasoning_effort: str | None = None,
    ) -> tuple[Any, Any, list[str]]:
        notes: list[str] = []
        llm = self._build_llm(
            model=model,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
        )
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
            reasoning_effort=reasoning_effort,
        )
        runner_fb = llm_fb.bind_tools(self._select_langchain_tools(tool_names)) if enable_tools else llm_fb
        return self._invoke_runner(runner_fb, messages, event_cb=event_cb), runner_fb, notes

    def _invoke_runner(
        self,
        runner: Any,
        messages: list[Any],
        *,
        event_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        cancel_event = self._current_cancel_event()
        if cancel_event is None or not hasattr(cancel_event, "is_set"):
            if event_cb is not None and hasattr(runner, "invoke_with_events"):
                return runner.invoke_with_events(messages, event_cb=event_cb)
            return runner.invoke(messages)
        if cancel_event.is_set():
            return self._cancelled_model_response()

        completed = threading.Event()
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def guarded_event_cb(payload: dict[str, Any]) -> None:
            if not cancel_event.is_set() and event_cb is not None:
                event_cb(payload)

        def invoke() -> None:
            try:
                if event_cb is not None and hasattr(runner, "invoke_with_events"):
                    result = runner.invoke_with_events(messages, event_cb=guarded_event_cb)
                else:
                    result = runner.invoke(messages)
                result_queue.put_nowait(("result", result))
            except BaseException as exc:
                try:
                    result_queue.put_nowait(("error", exc))
                except queue.Full:
                    pass
            finally:
                completed.set()

        worker = threading.Thread(
            target=invoke,
            name="vp-model-invocation",
            daemon=True,
        )
        worker.start()
        while not completed.wait(timeout=0.05):
            if cancel_event.is_set():
                return self._cancelled_model_response()
        if cancel_event.is_set():
            return self._cancelled_model_response()
        kind, value = result_queue.get_nowait()
        if kind == "error":
            raise value
        return value

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
                description="Write characters to a running exec_command session, or poll for more output.",
                args_schema=WriteStdinArgs,
                func=self._write_stdin_tool,
            ),
            self._StructuredTool.from_function(
                name="read_tool_result",
                description="Continue reading an omitted tool result without rerunning the original execution.",
                args_schema=ReadToolResultArgs,
                func=self._read_tool_result_tool,
            ),
            self._StructuredTool.from_function(
                name="apply_patch",
                description=APPLY_PATCH_TOOL_DESCRIPTION,
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
                description="Extract table-like rows from a local PDF or OpenXML Excel workbook.",
                args_schema=TableExtractArgs,
                func=self._table_extract_tool,
            ),
            self._StructuredTool.from_function(
                name="fact_check_file",
                description="Retrieve document snippets related to a claim and return a heuristic evidence verdict that still requires model judgment.",
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
                description="Download one remote file under allowed writable roots. Downloaded content is marked untrusted; executing it may require approval.",
                args_schema=WebDownloadArgs,
                func=self._web_download_tool,
            ),
            self._StructuredTool.from_function(
                name="sessions_list",
                description="List recent local chat sessions for the current project so the agent can locate past context.",
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
                description="Extract a local .zip archive under allowed writable roots; files inherit untrusted provenance from a downloaded archive.",
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
                name="spawn_subagent",
                description="Start one bounded Subagent task in an isolated context and immediately return its id. The id remains waitable across later Agent runs in the same parent Thread. Independent tasks can run in parallel.",
                args_schema=SpawnSubagentArgs,
                func=self._spawn_subagent_tool,
            ),
            self._StructuredTool.from_function(
                name="wait_subagents",
                description="Wait for selected Subagents from the current or an earlier Agent run in this parent Thread, or all relevant Thread Subagents, and collect saved terminal results.",
                args_schema=WaitSubagentsArgs,
                func=self._wait_subagents_tool,
            ),
            self._StructuredTool.from_function(
                name="update_plan",
                description="Synchronize the full current checklist. Keep exactly one step in_progress until every step is completed.",
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
                name="save_skill",
                description="Create a repository-shared Team SKILL.md in the global VP Skill Registry, or replace it only when overwrite is true. Use apply_patch for Team Skill scripts, references, or partial edits; Built-in Skills are read-only.",
                args_schema=SaveSkillArgs,
                func=self._save_skill_tool,
            ),
            self._StructuredTool.from_function(
                name="list_tasks",
                description="Search durable Tasks across all registered projects by default and return real task_id values before updating an existing Task. Use current_project only when the user explicitly limits the request to the active project.",
                args_schema=ListTasksArgs,
                func=self._list_tasks_tool,
            ),
            self._StructuredTool.from_function(
                name="save_task",
                description="Create a durable Task snapshot for the current project, or replace the loaded Task when task_id is provided. Use it when the user asks to summarize/save current work as a Task and to checkpoint material progress on a loaded Task.",
                args_schema=SaveTaskArgs,
                func=self._save_task_tool,
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
                description="Wait for a selector state, or wait only for timeout_ms when selector is empty.",
                args_schema=BrowserWaitArgs,
                func=self._browser_wait_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_scroll",
                description="Scroll by direction/amount, or ignore those fields and bring selector into view when selector is set.",
                args_schema=BrowserScrollArgs,
                func=self._browser_scroll_tool,
            ),
            self._StructuredTool.from_function(
                name="browser_snapshot",
                description="Capture a pageable browser page text and link snapshot with explicit completeness metadata.",
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
        purpose: str,
        cwd: str = ".",
        yield_time_ms: int = EXEC_COMMAND_DEFAULT_YIELD_MS,
        max_output_chars: int = 12000,
        tty: bool = False,
    ) -> str:
        return json.dumps(
            self.tools.exec_command(
                cmd=cmd,
                purpose=purpose,
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
        yield_time_ms: int = WRITE_STDIN_DEFAULT_YIELD_MS,
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

    def _read_tool_result_tool(
        self,
        result_ref: str,
        cursor: int = 0,
        max_tokens: int = 4000,
    ) -> str:
        return json.dumps(
            self.tools.read_tool_result(
                result_ref=result_ref,
                cursor=cursor,
                max_tokens=max_tokens,
            ),
            ensure_ascii=False,
        )

    def _apply_patch_tool(self, patch: str, cwd: str = ".", check: bool = False) -> str:
        return json.dumps(self.tools.apply_patch(patch=patch, cwd=cwd, check=check), ensure_ascii=False)

    def _read_section_tool(
        self,
        path: str,
        heading: str,
        max_chars: int = 12000,
        start_char: int = 0,
    ) -> str:
        return json.dumps(
            self.tools.read_section(
                path=path,
                heading=heading,
                max_chars=max_chars,
                start_char=start_char,
            ),
            ensure_ascii=False,
        )

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

    def _sessions_list_tool(self, limit: int = 20, offset: int = 0) -> str:
        return json.dumps(self.tools.sessions_list(limit=limit, offset=offset), ensure_ascii=False)

    def _sessions_history_tool(self, session_id: str, max_turns: int = 80, recent_offset: int = 0) -> str:
        return json.dumps(
            self.tools.sessions_history(
                session_id=session_id,
                max_turns=max_turns,
                recent_offset=recent_offset,
            ),
            ensure_ascii=False,
        )

    def _save_skill_tool(
        self,
        name: str,
        description: str,
        body: str,
        enabled: bool = True,
        overwrite: bool = False,
    ) -> str:
        return json.dumps(
            self.tools.save_skill(
                name=name,
                description=description,
                body=body,
                enabled=enabled,
                overwrite=overwrite,
            ),
            ensure_ascii=False,
        )

    def _list_tasks_tool(
        self,
        query: str = "",
        status: str = "",
        project_scope: str = "all_projects",
        include_archived: bool = False,
        detail_level: str = "summary",
        limit: int = 20,
    ) -> str:
        return json.dumps(
            self.tools.list_tasks(
                query=query,
                status=status,
                project_scope=project_scope,
                include_archived=include_archived,
                detail_level=detail_level,
                limit=limit,
            ),
            ensure_ascii=False,
        )

    def _save_task_tool(
        self,
        title: str,
        goal: str,
        summary: str,
        task_id: str = "",
        progress: list[str] | None = None,
        next_steps: list[str] | None = None,
        decisions: list[str] | None = None,
        blockers: list[str] | None = None,
        artifacts: list[str] | None = None,
        status: str = "active",
    ) -> str:
        return json.dumps(
            self.tools.save_task(
                task_id=task_id,
                title=title,
                goal=goal,
                summary=summary,
                progress=progress,
                next_steps=next_steps,
                decisions=decisions,
                blockers=blockers,
                artifacts=artifacts,
                status=status,
            ),
            ensure_ascii=False,
        )

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
            # Preserve the complete model response. The shared tool-result store
            # handles model-context paging without rerunning image analysis.
            "visible_text": visible_text,
            "analysis": analysis,
            "visible_text_total_chars": len(visible_text),
            "analysis_total_chars": len(analysis),
            "truncated": False,
            "has_more": False,
            "source_complete": True,
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

    def _update_plan_tool(self, plan: list[PlanItemArgs], explanation: str = "") -> str:
        normalized_plan = [
            dict(safe_model_dump(item) or {})
            for item in list(plan or [])
        ]
        return json.dumps(
            self.tools.update_plan(plan=normalized_plan, explanation=explanation),
            ensure_ascii=False,
        )

    def _request_user_input_tool(self, questions: list[UserInputQuestionArgs]) -> str:
        normalized_questions = [
            dict(safe_model_dump(item) or {})
            for item in list(questions or [])
        ]
        return json.dumps(
            self.tools.request_user_input(questions=normalized_questions),
            ensure_ascii=False,
        )

    def _spawn_subagent_tool(self, task: str, role: str = "explorer", label: str = "") -> str:
        return json.dumps(
            self.tools.spawn_subagent(task=task, role=role, label=label),
            ensure_ascii=False,
        )

    def _wait_subagents_tool(
        self,
        subagent_ids: list[str] | None = None,
        timeout_seconds: float = 30,
    ) -> str:
        return json.dumps(
            self.tools.wait_subagents(
                subagent_ids=subagent_ids or [],
                timeout_seconds=timeout_seconds,
            ),
            ensure_ascii=False,
        )

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

    def _browser_scroll_tool(
        self,
        direction: str = "down",
        amount: int = 900,
        selector: str = "",
        timeout_ms: int = 5000,
    ) -> str:
        return json.dumps(
            self.tools.browser_scroll(
                direction=direction,
                amount=amount,
                selector=selector,
                timeout_ms=timeout_ms,
            ),
            ensure_ascii=False,
        )

    def _browser_snapshot_tool(
        self,
        max_chars: int = 12000,
        start_char: int = 0,
        link_offset: int = 0,
        max_links: int = 12,
    ) -> str:
        return json.dumps(
            self.tools.browser_snapshot(
                max_chars=max_chars,
                start_char=start_char,
                link_offset=link_offset,
                max_links=max_links,
            ),
            ensure_ascii=False,
        )

    def _browser_screenshot_tool(self, path: str = "", full_page: bool = True) -> str:
        return json.dumps(self.tools.browser_screenshot(path=path, full_page=full_page), ensure_ascii=False)

    def _list_dir_tool(self, path: str = ".", max_entries: int = 200, offset: int = 0) -> str:
        return json.dumps(self.tools.list_dir(path=path, max_entries=max_entries, offset=offset), ensure_ascii=False)

    def _glob_file_search_tool(self, pattern: str, path: str = ".", max_results: int = 200, offset: int = 0) -> str:
        return json.dumps(
            self.tools.glob_file_search(pattern=pattern, path=path, max_results=max_results, offset=offset),
            ensure_ascii=False,
        )

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
        return normalize_openai_base_url(raw_url)

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
