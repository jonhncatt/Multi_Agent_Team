from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML_PATH = REPO_ROOT / "app" / "static" / "index.html"
LOCALES_JS_PATH = REPO_ROOT / "app" / "static" / "locales.js"
STYLES_CSS_PATH = REPO_ROOT / "app" / "static" / "styles.css"
INTERNAL_MANUAL_PATH = REPO_ROOT / "docs" / "internal_design_manual.md"
SUPPORTED_LOCALES = ("zh-CN", "ja-JP", "en")
REQUIRED_CORE_KEYS = (
    "labels.payload",
    "labels.copied",
    "buttons.copy_message",
    "settings.locale",
    "settings.theme_color",
    "settings.theme_color.slate",
    "settings.theme_color.blue",
    "settings.theme_color.emerald",
    "settings.theme_color.violet",
    "settings.theme_color.rose",
    "settings.theme_color.amber",
    "settings.context_turns.help",
    "tool.failure.error",
    "tool.failure.stderr",
    "tool.failure.returncode",
    "tool.failure.cwd",
    "tool.failure.command",
    "settings.locale.zh-CN",
    "settings.locale.ja-JP",
    "settings.locale.en",
    "settings.provider",
    "settings.model_preset",
    "settings.model_presets.refresh",
    "settings.model_presets.refreshing",
    "settings.model_presets.updated",
    "settings.model_presets.failed",
    "settings.model_presets.help",
    "settings.model_name",
    "settings.response_style",
    "settings.debug_raw",
    "buttons.save",
    "buttons.tasks",
    "buttons.load_task",
    "buttons.edit_task",
    "confirm.delete_task",
    "confirm.switch_project_for_task",
    "errors.update_task_failed",
    "errors.delete_task_failed",
    "errors.task_required_fields",
    "errors.pending_turn_resume_timeout",
    "buttons.bind_project_profile",
    "buttons.change_project_profile",
    "buttons.not_now",
    "project_profile.title",
    "project_profile.after_add_title",
    "project_profile.hint",
    "project_profile.select_label",
    "project_profile.none",
    "project_profile.none_hint",
    "project_profile.missing",
    "project_profile.loading",
    "tasks.title",
    "tasks.subtitle",
    "tasks.project",
    "tasks.edit_title",
    "tasks.field.title",
    "tasks.field.status",
    "tasks.field.goal",
    "tasks.field.summary",
    "tasks.field.progress",
    "tasks.field.decisions",
    "tasks.field.artifacts",
    "tasks.list_hint",
    "tasks.summarize_prompt",
    "tasks.load_prompt",
    "buttons.deleting",
    "buttons.select_all_threads",
    "buttons.clear_thread_selection",
    "buttons.delete_selected_threads",
    "tabs.run",
    "tabs.settings",
    "tabs.eval",
    "desktop.exit.button",
    "desktop.exit.confirm",
    "desktop.exit.confirm_idle",
    "desktop.exit.stopped",
    "eval.title",
    "eval.start",
    "eval.status.running",
    "activity.title",
    "activity.running",
    "activity.queued",
    "activity.failed",
    "activity.blocked",
    "activity.cancelled",
    "activity.status.queued",
    "run.live_agent.queued",
    "run.live_agent.queued_waiting",
    "run.progress.status.queued",
    "subagent.queued",
    "subagent.waiting_slot",
    "activity.raw_arguments",
    "activity.parameters",
    "activity.arguments_preview",
    "activity.preview_error",
    "activity.schema_validation",
    "activity.result_preview",
    "activity.stream_diagnostics",
    "activity.progress_title",
    "activity.execution_summary_counts",
    "activity.more_steps",
    "activity.debug_details",
    "activity.debug.tool_call_id",
    "activity.debug.model_output",
    "activity.debug.runtime",
    "activity.debug.advanced_raw",
    "activity.debug.raw_json",
    "activity.loading_execution",
    "activity.raw_events",
    "activity.debug.tools",
    "activity.debug.harness",
    "activity.debug.legacy_details",
    "activity.debug.runtime_controls",
    "activity.debug.runtime_phase",
    "activity.debug.blocked_reason",
    "activity.debug.pending_approval",
    "activity.debug.pending_user_input",
    "activity.debug.control_events",
    "activity.live.model_thinking",
    "activity.live.model_finished",
    "activity.live.model_failed",
    "activity.live.tool_running",
    "activity.live.tool_finished",
    "activity.live.waiting_next_model",
    "activity.live.answer_streaming",
    "activity.live.answer_done",
    "run.live_panel.title",
    "run.live_agent.preparing",
    "run.live_agent.understanding",
    "run.live_agent.context",
    "run.live_agent.tool",
    "run.live_agent.writing",
    "run.live_agent.background",
    "run.live_agent.default",
    "run.live_agent.blocked",
    "run.live_agent.failed",
    "run.live_agent.understanding_detail",
    "run.live_agent.model",
    "run.live_agent.model_detail",
    "run.live_agent.context_detail",
    "run.live_agent.tool_named",
    "run.live_agent.tool_detail",
    "run.live_agent.tool_preparing",
    "run.live_agent.tool_preparing_named",
    "run.live_agent.tool_preparing_detail",
    "run.live_agent.tool_running",
    "run.live_agent.tool_running_named",
    "run.live_agent.tool_running_detail",
    "run.live_agent.tool_result",
    "run.live_agent.tool_result_named",
    "run.live_agent.tool_result_detail",
    "run.live_agent.writing_detail",
    "run.live_agent.progress_detail",
    "runtime.error.title",
    "runtime.error.llm_request_failed",
    "runtime.error.llm_empty_response",
    "runtime.error.request_too_large",
    "runtime.error.phase",
    "runtime.error.kind",
    "runtime.error.debug_hint",
    "runtime.model_draft.title",
    "runtime.model_draft.empty",
    "runtime.execution_progress.title",
    "runtime.raw_model_io.title",
    "runtime.raw_model_io.round",
    "runtime.raw_model_io.sent_messages_exact",
    "runtime.raw_model_io.model_returned_exact",
    "runtime.raw_model_io.error",
    "runtime.raw_model_io.harness_interpretation",
    "runtime.raw_model_io.truncated",
    "runtime_panel.title",
    "runtime_panel.subtitle",
    "runtime_panel.attention_count",
    "runtime_panel.idle",
    "runtime_panel.action_required",
    "runtime_panel.approval_required",
    "runtime_panel.approval_submitting",
    "runtime_panel.approval_details",
    "runtime_panel.user_input_required",
    "runtime_panel.question",
    "runtime_panel.reply_in_composer",
    "runtime_panel.active_work",
    "runtime_panel.work_item",
    "runtime_panel.no_active_work",
    "runtime_panel.recent_events",
    "runtime_panel.no_recent_events",
    "runtime_panel.controls",
    "runtime_panel.open_developer_debug",
    "runtime_panel.last_run",
    "runtime_panel.failed_tools",
    "runtime_panel.last_run_loading",
    "runtime_panel.no_tool_failures",
    "runtime_panel.no_last_run",
    "task_approval.title",
    "task_approval.help",
    "task_approval.current",
    "task_approval.proposed",
    "task_approval.warning",
    "task_approval.cancel",
    "task_approval.approve",
    "activity.tool_title.read_file",
    "activity.tool_title.list_dir",
    "activity.tool_title.glob_file_search",
    "activity.tool_title.search_contents_in_file",
    "activity.tool_title.search_contents_in_file_multi",
    "activity.tool_title.search_codebase",
    "activity.tool_title.exec_command",
    "activity.tool_title.apply_patch",
    "activity.tool_title.web_search",
    "activity.tool_title.web_fetch",
    "activity.tool_title.web_download",
    "activity.tool_title.use_tool",
    "activity.tool_title.use_tool_named",
    "activity.detail.recorded_arguments",
    "activity.model_action",
    "activity.execution_trace",
    "activity.runtime_boundary",
    "activity.raw_tool_call",
    "activity.normalized_arguments",
    "activity.validation_result",
    "activity.revision_summary",
    "activity.observation_summary",
    "activity.original_excerpt",
    "activity.result_excerpt",
    "activity.reason",
    "activity.triggering_user_message",
    "activity.triggering_user_turn_id",
    "activity.progress.read",
    "activity.progress.list_dir",
    "activity.progress.glob_file_search",
    "activity.progress.search",
    "activity.progress.execute_command",
    "activity.progress.apply_patch",
    "activity.progress.use_tool",
    "activity.progress.preparing",
    "activity.progress.active",
    "activity.stage.model_action",
    "activity.stage.action_validation",
    "activity.stage.execution",
    "activity.stage.request_analysis",
    "activity.stage.loop.safeguard",
    "activity.stage.harness_validation",
    "activity.stage.tool_decision",
    "activity.stage.answer_generation",
    "activity.status.request_understood",
    "activity.status.request_understanding",
    "activity.status.waiting_model",
    "activity.status.waiting_model_slow",
    "activity.status.thinking",
    "activity.status.direct_answer_no_tool",
    "activity.status.tool_guard_pending",
    "activity.status.tool_guard_normalized",
    "activity.status.tool_guard_rejected",
    "activity.status.tool_running",
    "activity.status.tool_completed",
    "activity.status.answer_generating",
    "activity.status.answer_streaming",
    "activity.status.answer_ready",
    "confirm.delete_threads",
    "threads.selected_count",
    "log.threads_deleted",
    "errors.delete_threads_failed",
    "update.button",
    "update.running",
    "update.success",
    "update.failed",
    "update.restart_hint",
    "update.discards_local_changes",
    "update.details",
    "update.command",
    "update.exit_code",
    "update.stdout",
    "update.stderr",
    "update.branch",
    "activity.revision_summary_count",
    "validation.valid",
    "validation.invalid",
    "validation.missing",
    "validation.error",
    "context_meter.section.run",
    "context_meter.section.tools",
    "context_meter.section.context",
    "context_meter.section.safeguards",
    "context_meter.section.diagnostics",
    "context_meter.details_toggle",
    "context_meter.compact_usage",
    "context_meter.compact_usage_unknown",
    "context_meter.compact_tokens",
    "context_meter.compact_tokens_unknown",
    "context_meter.compact_elapsed_tools",
    "context_meter.compact_auto_compact",
    "context_meter.status.enough",
    "context_meter.status.tight",
    "context_meter.status.updating",
    "context_meter.compact.none",
    "context_meter.compact.completed",
    "context_meter.compact.completed_count",
    "context_meter.compact.suggested",
    "context_meter.compact.required",
    "context_meter.field.project",
    "context_meter.field.status",
    "context_meter.field.model",
    "context_meter.field.elapsed",
    "context_meter.field.runtime_mode",
    "context_meter.field.permission_profile",
    "context_meter.field.file_read_scope",
    "context_meter.field.file_write_scope",
    "context_meter.field.command_scope",
    "context_meter.field.network",
    "context_meter.network.enabled",
    "context_meter.network.disabled",
    "context_meter.network.global_disabled",
    "context_meter.network.profile_disabled",
    "context_meter.field.tool_total",
    "context_meter.field.tool_succeeded",
    "context_meter.field.tool_failed",
    "context_meter.field.tool_rejected",
    "context_meter.field.tool_latest",
    "context_meter.field.context_usage",
    "context_meter.field.remaining",
    "context_meter.field.estimate_mode",
    "context_meter.field.compact_recommendation",
    "context_meter.field.output_limit",
    "context_meter.field.context_window",
    "context_meter.field.model_max_context_window",
    "context_meter.field.auto_compact_limit",
    "context_meter.field.effective_context_limit",
    "context_meter.field.token_usage",
    "context_meter.field.continuation_policy",
    "context_meter.continuation.model_led",
    "context_meter.field.guard_tool_output",
    "context_meter.field.guard_user_stop",
    "context_meter.field.guard_compaction",
    "context_meter.field.runtime_status_total",
    "context_meter.field.runtime_status_runtime_meta",
    "context_meter.field.runtime_status_provider_options",
    "context_meter.field.runtime_status_auth_summary",
    "context_meter.value.enabled",
    "context_meter.value.disabled",
    "context_meter.mode.host",
    "context_meter.mode.docker",
    "context_meter.token_usage_value",
    "context_meter.unknown",
    "slash.menu.label",
    "slash.status.label",
    "slash.status.description",
    "slash.status.summary",
    "slash.status.failed",
    "slash.compact.label",
    "slash.compact.description",
    "slash.compact.started",
    "slash.compact.done",
    "slash.compact.skipped",
    "slash.compact.failed",
    "slash.compact.no_session",
    "run.execution_progress",
    "run.field.status",
    "run.field.current_step",
    "run.field.blocked_reason",
    "run.field.current_tool",
    "run.field.current_action",
    "run.field.current_state",
    "run.field.command",
    "run.field.recent_event",
    "run.progress.status.validating",
    "run.progress.status.waiting_model",
    "run.progress.status.waiting_tool",
    "run.progress.status.background_running",
    "run.progress.waiting_model",
    "run.progress.waiting_tool",
    "run.progress.background_running",
    "run.progress.recent_event_waiting_model",
    "run.progress.recent_event_waiting_tool",
    "run.progress.recent_event_background",
    "run.progress.recent_event_completed",
    "run.value.turn_status.failed",
)


def test_index_cache_busts_frontend_static_bundle_with_app_version() -> None:
    main_py = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    version_match = re.search(r'APP_VERSION = "([^"]+)"', main_py)
    assert version_match, "APP_VERSION not found"
    app_version = version_match.group(1)
    index = INDEX_HTML_PATH.read_text(encoding="utf-8")

    assert app_version == "3.1.6A"
    assert f'/static/app.js?v={app_version}' in index
    assert f'/static/locales.js?v={app_version}' in index
    assert f'/static/styles.css?v={app_version}' in index
    assert 'src="/static/app.js"' not in index


def test_index_renders_static_boot_loading_fallback() -> None:
    index = INDEX_HTML_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert '<div id="root" data-app="vintage-programmer">' in index
    assert 'class="app-boot-screen"' in index
    assert 'role="status"' in index
    assert "Loading workspace..." in index
    assert 'src="/static/assets/vintage_programmer.png"' in index
    assert 'href="/static/assets/vintage_programmer.ico?v=3"' in index
    for size in (16, 32, 48, 64):
        assert (
            f'sizes="{size}x{size}" '
            f'href="/static/assets/vintage_programmer_{size}.png?v=3"'
        ) in index
    assert 'window.__VP_DESKTOP_CONTROL_TOKEN__' in index
    for token in (
        ".app-boot-screen",
        ".app-boot-card",
        ".app-boot-ring",
        "conic-gradient(from -35deg",
    ):
        assert token in styles, token


def test_workspace_grid_children_can_shrink_inside_app_mode_viewport() -> None:
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    for selector in (".workspace-head", ".conversation-plane", ".composer-shell"):
        rule_match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", styles)
        assert rule_match, selector
        declarations = rule_match.group(1)
        assert "min-width: 0;" in declarations, selector
        assert "width: 100%;" in declarations, selector
        assert "max-width: 100%;" in declarations, selector

    head_stack_match = re.search(r"\.head-stack\s*\{([^}]+)\}", styles)
    assert head_stack_match
    assert "flex: 1 1 auto;" in head_stack_match.group(1)


def test_desktop_shell_uses_isolated_configurable_ui_density() -> None:
    index = INDEX_HTML_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'params.get("vp_desktop") !== "1"' in index
    assert 'params.get("vp_scale") || "0.8"' in index
    assert 'document.documentElement.dataset.vpDesktopShell = "true"' in index
    assert '--vp-desktop-viewport-height' in index
    assert 'html[data-vp-desktop-shell="true"] {' in styles
    assert 'zoom: var(--vp-desktop-ui-scale, 0.8);' in styles
    assert 'html[data-vp-desktop-shell="true"] .workspace-main' in styles


def test_chrome_desktop_exit_always_requires_confirmation() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "const confirmation = activeCount > 0" in script
    assert ': t("desktop.exit.confirm_idle");' in script
    assert "if (!window.confirm(confirmation)) return;" in script
    assert 'activeCount > 0 && !window.confirm' not in script
    assert '"desktop.exit.confirm_idle": "确定退出 Vintage Programmer 吗？本地后台也会同时关闭。"' in locales
    assert '"desktop.exit.confirm_idle": "Exit Vintage Programmer? The local backend will also stop."' in locales


def test_react_boot_overlay_waits_for_workspace_and_thread_but_not_runtime_status() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'const [bootState, setBootState] = useState({ active: true, phase: "workspace" });' in script
    assert 'setBootState({ active: true, phase: "thread" });' in script
    assert "await selectProject(initialProjectId, { silentNotFound: true, fromBoot: true });" in script
    assert "refreshRuntimeStatus(targetProjectId, { background: true });" in script
    assert "runtimeStatusPromise" not in script
    assert "await runtimeStatus" not in script
    assert "setBootState((prev) => ({ ...prev, active: false }));" in script
    assert 'className="app-boot-screen app-boot-screen-overlay"' in script
    assert script.index('className="workspace-shell"') < script.index('className="app-boot-screen app-boot-screen-overlay"')
    assert 't("boot.loading_workspace")' in script
    assert 't("boot.loading_thread")' in script
    assert ".app-root-frame" in styles
    assert ".app-boot-screen-overlay" in styles
    assert "background: rgba(248, 250, 252, 0.38);" in styles
    assert "backdrop-filter: blur(2px) saturate(1.02);" in styles
    assert '"boot.loading_workspace": "Loading workspace..."' in locales
    assert '"boot.loading_thread": "Loading thread..."' in locales
REQUIRED_LIST_KEYS = ("starter.prompts",)


def _extract_object_body(content: str, marker: str) -> str:
    start = content.index(marker) + len(marker)
    depth = 1
    in_string = False
    escaped = False

    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return content[start:index]
    raise AssertionError(f"Could not extract object body for marker: {marker}")


def _locale_entry_types() -> dict[str, dict[str, str]]:
    content = LOCALES_JS_PATH.read_text(encoding="utf-8")
    entries: dict[str, dict[str, str]] = {}
    for locale in SUPPORTED_LOCALES:
        marker = f'"{locale}": {{'
        if marker not in content:
            marker = f"{locale}: {{"
        body = _extract_object_body(content, marker)
        entries[locale] = {
            match.group("key"): match.group("value_type")
            for match in re.finditer(r'"(?P<key>[^"]+)":\s*(?P<value_type>\[|")', body)
        }
    return entries


def test_settings_handlers_do_not_read_current_target_inside_state_updaters() -> None:
    lines = APP_JS_PATH.read_text(encoding="utf-8").splitlines()
    offenders = [
        f"{line_no}: {line.strip()}"
        for line_no, line in enumerate(lines, start=1)
        if "setChatSettings((prev)" in line and "event.currentTarget" in line
    ]
    assert offenders == []


def test_locale_catalog_contains_required_settings_keys() -> None:
    entries = _locale_entry_types()

    for locale in SUPPORTED_LOCALES:
        locale_entries = entries[locale]
        for key in REQUIRED_CORE_KEYS:
            assert locale_entries.get(key) == '"', f"{locale} is missing string key {key}"
        for key in REQUIRED_LIST_KEYS:
            assert locale_entries.get(key) == "[", f"{locale} is missing array key {key}"


def test_activity_flow_summary_is_wired_into_frontend() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        "function activityStageKeyFromTrace(",
        "function buildActivityFlowStages(",
        "function buildActivityProjection(",
        "function buildMainLiveCards(",
        "function buildMainCompletionSummary(",
        "function buildLiveAgentTimelineItems(",
        "function formatToolTitle(",
        "function buildRuntimeStatsSummary(",
        "function buildToolProgressGroups(",
        "function toolCallIdentityFromSource(",
        "function latestRevisionSummary(",
        "function nextRuntimeStatusPollIntervalMs(",
        "renderExecutionTraceDetails(",
        "plan_explanation",
        "tool_items",
        "loop_safeguards",
        "activity.status.request_understood",
        "activity.status.tool_guard_pending",
        "model_action",
        "execution_trace",
        "raw_tool_call",
        "validation_result",
        "normalized_arguments",
        'className="activity-progress"',
        'className="activity-progress-divider"',
        'className="activity-debug-drawer"',
        "MAIN_LIVE_CARD_LIMIT",
        "composer-profile-select",
        "composer-permission-profile",
        "selectedPermissionProfileClass",
        "selectedPermissionDescription",
        "selectedPermissionAriaLabel",
    )
    for token in required_script_tokens:
        assert token in script, token
    assert "const MAIN_LIVE_CARD_LIMIT = 3;" in script

    required_style_tokens = (
        ".activity-progress",
        ".activity-progress-item",
        ".activity-progress-divider",
        ".activity-debug-drawer",
        ".activity-debug-sections > .activity-payload",
        ".activity-debug-sections .activity-structured-details",
        "@keyframes activity-progress-pulse",
        ".activity-flow-summary",
        ".activity-flow-stages",
        ".activity-flow-stage",
        ".activity-flow-note",
        ".composer-toolbar select.composer-profile-select",
        ".composer-permission-profile",
        ".composer-toolbar select.composer-profile-select.profile-default",
        ".composer-toolbar select.composer-profile-select.profile-auto",
        ".composer-toolbar select.composer-profile-select.profile-full-access",
    )
    for token in required_style_tokens:
        assert token in styles, token


def test_plan_updates_and_tool_items_are_projected_into_message_activity() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        'tool_items: [item]',
        "live_items: [liveRunItemFromStreamItem(item, event)]",
        "plan_explanation: explanation",
        'summary>${t("activity.debug_details")}</summary>',
        'summary>${t("activity.debug.tool_execution")} · ${toolGroups.length}</summary>',
        't("activity.debug.thread_history")',
        't("activity.debug.view_trace")',
    )
    for token in required_tokens:
        assert token in script, token


def test_no_tool_progress_projection_uses_request_and_model_wait_states() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function buildFallbackProgressItems\(activity, locale, nowMs = Date\.now\(\)\) \{(?P<body>.*?)\n}\n\nfunction buildMainLiveCards",
        script,
        re.S,
    )
    assert match, "buildFallbackProgressItems function not found"
    body = match.group("body")

    assert 'label: translateUi(locale, "activity.status.request_understood")' in body
    assert 'id: "request-preparing"' in body
    assert 'label: translateUi(locale, "activity.status.preparing_request")' in body
    assert 'label: translateUi(locale, "activity.status.request_understanding")' not in body
    assert '"activity.status.waiting_model"' in body
    assert '"activity.status.waiting_model_slow"' in body
    assert "MODEL_WAIT_SLOW_HINT_MS" in script
    assert "const llmStartedAt = latestTraceTimestampByTypes(traces, \"llm.started\");" in body
    assert "const modelWaitStartedAt = llmStartedAt || (" in body
    assert "item.live_model_started" in body
    assert "const modelStarted = Boolean(item.live_model_started || llmStartedAt);" in body
    assert "!modelStarted && !hasAnswerStarted" in body
    assert "modelStarted && !hasAnswerStarted" in body
    assert 'const finalAnswerText = String(item.final_answer || "").trim();' in body
    assert "const hasAnswerReady = Boolean(finalAnswerText) || traces.some" in body
    assert '"answer.started"' in body
    assert "activity.status.direct_answer_no_tool" not in body


def test_live_agent_timeline_items_are_wired_into_activity_projection() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "function normalizeLiveRunItem(",
        "function liveRunItemFromStreamItem(",
        "function liveRunItemFromTrace(",
        "function mergeLiveRunItems(",
        "live_items: normalizeLiveRunItems(item.live_items)",
        "const liveItems = buildLiveAgentTimelineItems(item, locale);",
        "if (!hasLiveItems && !toolGroups.length",
        "activity.live.model_thinking",
        "activity.live.answer_streaming",
        'type === "tool.started" || type === "tool.finished" || type === "tool.failed"',
        "toolCallTargetFromSource(payload)",
    )
    for token in required_tokens:
        assert token in script, token


def test_subagent_cards_are_not_evicted_and_poll_only_while_background_work_is_pending() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const retainedNonSubagentIds = new Set(" in script
    assert 'String((item && item.type) || "") === "subagent"' in script
    assert "const backgroundSubagentPollingKey = messages" in script
    assert "const pollBackgroundSubagents = async () => {" in script
    assert '{ force: true, background: true }' in script
    assert "window.setInterval(pollBackgroundSubagents, 5000)" in script
    assert "if (options.background) return;" in script
    assert "if (item.visible === false) return null;" in script


def test_developer_debug_view_is_thread_first_and_trace_on_demand() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "const threadItems = Array.isArray(activity.thread_items)",
        "const traceSteps = Array.isArray(turnTrace.steps)",
        't("activity.debug.thread_history")',
        't("activity.debug.view_trace")',
        't("activity.debug.view_system_prompt")',
        "traceStepByItemId.get(itemId)",
        "requested_by_item_id",
        "tool_result_item_id",
    )
    for token in required_tokens:
        assert token in script, token

    debug_block = script.split("const renderActivityDebugDetails", 1)[1].split("const renderMessageActivity", 1)[0]
    assert "phaseTimingDetails" not in debug_block
    assert "sent_to_model" not in debug_block
    assert "model_rounds" not in debug_block


def test_tool_execution_ui_coalesces_one_call_into_one_indented_transaction() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert "function reconcileAuthoritativeActivityToolItems(" in script
    assert "replace_execution_details: true" in script
    assert "const visibleLiveItems = liveItems.filter" in script
    assert "!callId || !groupedCallIds.has(callId)" in script
    assert "const expandedProgressItems = toolGroups.length" in script
    assert "const toolStatus = normalizeProgressStatus(toolItem.status);" in script
    assert 'toolStatus === "completed"' in script
    assert 'className="activity-tool-transaction-list"' in script
    assert 'className=${`activity-tool-transaction status-${status}`}' in script
    assert 't("activity.debug.tool_call_id")' in script

    tool_details = script.split("const renderActivityToolDetails", 1)[1].split(
        "const renderActivityDebugDetails", 1
    )[0]
    assert 'renderDetailBlock(t("labels.payload"), toolItem)' not in tool_details
    assert "renderToolAuditDetails(" not in tool_details
    assert 'renderDetailBlock(t("activity.parameters"), effectiveArguments)' in tool_details
    assert 'className="activity-tool-trace-details"' in tool_details
    assert tool_details.index('className="activity-tool-trace-details"') < tool_details.index(
        't("activity.debug.tool_call_id")'
    )
    assert "argumentsChanged ? renderDetailBlock" in tool_details
    assert ".activity-tool-transaction-list" in styles
    assert ".activity-tool-transaction-body" in styles
    assert ".activity-tool-trace-body" in styles
    assert "padding-left: 16px" in styles


def test_tool_execution_audit_keeps_all_calls_and_authoritative_order() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    merge_block = script.split("function mergeActivityToolItems", 1)[1].split(
        "function reconcileAuthoritativeActivityToolItems", 1
    )[0]
    reconcile_block = script.split("function reconcileAuthoritativeActivityToolItems", 1)[1].split(
        "function normalizeLiveRunItem", 1
    )[0]
    grouping_block = script.split("function buildToolProgressGroups", 1)[1].split(
        "function latestTraceTimestampByTypes", 1
    )[0]
    identity_block = script.split("function toolCallIdentityFromSource", 1)[1].split(
        "function toolCallTargetFromSource", 1
    )[0]
    tool_details = script.split("const renderActivityToolDetails", 1)[1].split(
        "const renderActivityDebugDetails", 1
    )[0]

    assert ".slice(-24)" not in merge_block
    assert "return authoritative.map" in reconcile_block
    assert grouping_block.index("item.tool_items.forEach") < grouping_block.index("item.trace_events.forEach")
    assert "representedProtocolCallIds.has(protocolCallId)" in grouping_block
    assert identity_block.index("item.transaction_id") < identity_block.index("item.tool_call_id")
    assert "tool_call_id_collision" in grouping_block
    assert "toolItem.tool_call_id || toolItem.id" in tool_details
    assert 't("activity.debug.tool_batch"' in tool_details
    assert 't("activity.debug.tool_call_id_collision"' in tool_details
    # The low-cost Runtime recent list and the compact three-card preview remain bounded.
    assert ".slice(0, RECENT_TOOL_TIMELINE_LIMIT)" in script
    assert "const MAIN_LIVE_CARD_LIMIT = 3;" in script
    assert "const RECENT_TOOL_TIMELINE_LIMIT = 24;" in script


def test_early_activity_copy_and_visibility_are_updated() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert '"activity.status.request_understood": "开始处理请求"' in locales
    assert '"activity.status.request_understanding": "正在准备请求"' in locales
    assert '"activity.status.preparing_request": "正在准备请求"' in locales
    assert '"activity.status.waiting_model": "模型正在分析"' in locales
    assert '"activity.status.waiting_model_slow": "模型响应较慢，仍在等待返回"' in locales
    assert '"activity.status.thinking": "正在准备请求"' in locales
    assert "|| activity.started_at" in script
    assert "|| displayActivity.status" in script


def test_frontend_progress_projection_uses_canonical_tool_names_only() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert '"read_file"' in script
    assert '"list_dir"' in script
    assert '"glob_file_search"' in script
    assert '"search_contents_in_file"' in script
    assert '"search_contents_in_file_multi"' in script


def test_main_cards_project_tool_traces_with_non_blank_fallbacks() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'type === "tool.started" || type === "tool.finished" || type === "tool.failed"' in script
    assert "formatToolTitle(locale, tool)" in script
    assert 'translateUiOrFallback(locale, "activity.tool_title.use_tool", "调用工具")' in script
    assert 'translateUiOrFallback(locale, "activity.detail.recorded_arguments", "参数已记录")' in script
    assert "entry.label && collection.findIndex" not in script
    assert "entry.title && collection.findIndex" not in script
    assert 'const title = String(entry.label || entry.title || trace.title || (tool ? formatToolTitle(locale, tool) : "") || "").trim()' in script


def test_permission_profile_selector_lives_in_composer_not_settings() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'className="composer-permission-profile"' in script
    assert "composer-profile-select profile-${selectedPermissionProfileClass}" in script
    assert '<span>${t("settings.permission_profile")}</span>' not in script
    assert "selectedPermissionProfile.replaceAll(\"_\", \"-\")" in script
    assert "title=${selectedPermissionDescription}" in script
    assert 'aria-label=${selectedPermissionAriaLabel}' in script
    assert "permissionProfileTouched || permissionProfileInitializedRef.current" in script
    assert "setPermissionProfileTouched(true)" in script
    assert '<option value="default" title=${t("settings.permission_profile.default.help")}' in script
    assert '<option value="auto" title=${t("settings.permission_profile.auto.help")}' in script
    assert '<option value="full_access" title=${t("settings.permission_profile.full_access.help")}' in script
    assert ".composer-toolbar select.composer-profile-select.profile-default" in styles
    assert ".composer-toolbar select.composer-profile-select.profile-auto" in styles
    assert ".composer-toolbar select.composer-profile-select.profile-full-access" in styles
    assert '"settings.permission_profile": "权限"' in locales
    assert '"settings.permission_profile.default": "默认"' in locales
    assert '"settings.permission_profile.auto": "自动"' in locales
    assert '"settings.permission_profile.full_access": "完全访问"' in locales
    assert '"settings.permission_profile.full_access.help": "可读写完整本机文件系统、执行安全命令并访问网络；执行网络来源代码需要单次确认。请仅在信任任务时使用。"' in locales
    assert "settings: {\n            ...chatSettings," in script
    assert 'className="drawer-input"\n                      value=${chatSettings.permission_profile || "code"}' not in script
    assert '|| "code",' not in script
    selector_styles = re.search(
        r"\.composer-toolbar select\.composer-profile-select \{(?P<body>.*?)\n\}",
        styles,
        re.S,
    )
    assert selector_styles, "composer profile selector CSS block not found"
    body = selector_styles.group("body")
    assert "font-weight: 400;" in body
    assert "font-weight: 600" not in body
    assert "font-weight: 700" not in body


def test_command_execution_approval_runtime_control_and_payload_are_wired() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "if (!isRuntimeApproval(candidate)) continue;" in script
    assert 'id="commandApprovalModal"' not in script
    assert 'className="panel-card runtime-attention-card"' in script
    assert 'if (runtimeInteractionKey) setDrawerView("run");' in script
    assert 'handleCommandApproval("approve_once")' in script
    assert 'handleCommandApproval("approve_thread")' in script
    assert 'handleCommandApproval("cancel")' in script
    assert 'user_input_response: structuredUserInputResponse' in script
    assert 'type: "command_execution"' in script
    assert 'action: normalizedAction' in script
    assert 'approval_token: approvalToken' in script
    assert 'tool_call_id: toolCallId' in script
    assert 'const isTurnResume = ["command_execution", "task_update", "request_user_input"]' in script
    assert 'const displayStructuredUserInput = String(structuredUserInputResponse.type || "") === "request_user_input";' in script
    assert 'const userMessage = (!isTurnResume || displayStructuredUserInput)' in script
    assert 'event === "request_user_input"' in script
    assert 'pending_approval: nextApproval' in script
    assert 'markPendingAsRuntimeNotice' in script
    assert 'createMessage("runtime", noticeText' in script
    assert 'finalMessageRole' in script
    assert '["user", "assistant", "runtime", "system"].includes(storedRole)' in script
    assert "function clearCommandExecutionApprovalState" in script
    assert "function clearCommandExecutionApprovalResponse" in script
    assert "const [approvalSubmittingKeys, setApprovalSubmittingKeys] = useState({});" in script
    assert "const approvalSubmittingKeysRef = useRef({});" in script
    assert "function runtimeApprovalIdentity(value)" in script
    assert "function runtimeApprovalSubmissionIdentity(threadId, value)" in script
    assert "if (!hasCommandApproval) return;" in script
    assert "if (!hasCommandApproval || approvalSubmitting) return;" not in script
    assert "if (!hasTaskUpdateApproval || approvalSubmitting) return;" not in script
    assert "if (approvalSubmitting) return {};" not in script
    assert "runtimeApprovalSubmissionIdentity(sessionId, candidate)" in script
    assert "if (!claimApprovalSubmission(submissionKey)) return;" in script
    assert "approvalSubmittingKeysRef.current[key]" in script
    assert "const threadApprovalSubmitting = Object.keys(approvalSubmittingKeys).some(" in script
    assert "delete next[key];" in script
    assert 'const runExecutionProgress = threadApprovalSubmitting && !runtimeAttentionCount' in script
    assert "if (currentThreadBusy && !isTurnResume && !fromQueuedTurn)" in script
    assert "if (ownerBusy && !isTurnResume && !fromQueuedTurn) return;" in script
    assert "if (isTurnResume && activeSendThreadIdsRef.current.has(runOwnerThreadId))" in script
    assert "const unlockDeadline = Date.now() + 30000;" in script
    assert "while (activeSendThreadIdsRef.current.has(runOwnerThreadId) && Date.now() < unlockDeadline)" in script
    assert 'throw new Error(t("errors.pending_turn_resume_timeout"));' in script
    assert 'disabled=${activeApprovalSubmitting}' not in script
    assert 'disabled=${!String(activePendingApproval.approval_token || "").trim()}' in script
    approval_handler = script.split("const handleCommandApproval = async", 1)[1].split("const activeToolTimeline", 1)[0]
    assert "currentThreadBusy" not in approval_handler
    assert "pendingResumeState" in approval_handler
    assert 'activePendingApproval.purpose' in script
    assert "const commandThreadApprovalEligible = Boolean(" in script
    assert "activePendingApproval.thread_rule_eligible" in script
    assert 't("runtime_panel.approval_details"' in script
    assert 'className="runtime-control-actions"' in script
    assert "const safeApprovalDebug = Object.keys(debugPendingApproval).length" in script
    assert "runtimeRunState.pending_approval" in script
    assert 't("activity.debug.runtime_controls")' in script
    assert 't("activity.debug.control_events")' in script
    safe_debug = script.split("const safeApprovalDebug =", 1)[1].split("const safePendingInputDebug", 1)[0]
    assert "approval_token" not in safe_debug
    assert '"approval_modal.title": "确认命令执行"' in locales
    assert '"approval_modal.purpose": "执行目的"' in locales
    assert '"approval_modal.repository": "仓库"' in locales
    assert '"approval_modal.remote_url": "Remote 地址"' in locales
    assert '"approval_modal.approve_once": "本次运行允许"' in locales
    assert '"approval_modal.approve_thread": "本 Thread 内不再询问此命令"' in locales
    assert '"approval_modal.default_cancel": "默认操作是取消。批准后命令会在本机 host 环境实际执行，不是沙箱；只有明确显示 Thread 选项的低风险命令才能保存窄范围授权。"' in locales
    assert '"runtime_panel.approval_required": "等待用户审批"' in locales
    assert '"runtime_panel.approval_submitting": "正在提交审批"' in locales
    assert '"tabs.run": "Runtime"' in locales
    assert '"role.runtime": "运行时"' in locales
    assert ".role-runtime .message-card" in styles
    assert ".runtime-attention-card" in styles
    assert ".runtime-thread-approval-note" in styles
    assert ".runtime-control-actions .approval-thread-btn" in styles
    assert "border: 2px solid rgba(234, 88, 12, 0.58);" in styles


def test_runtime_input_options_can_resume_the_pending_turn_directly() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert "function runtimeInputSubmissionIdentity(threadId, value)" in script
    assert "const handleRuntimeInputOption = async (question, option)" in script
    assert 'type: "request_user_input"' in script
    assert "tool_call_id: String(activePendingInput.tool_call_id" in script
    assert "const allQuestionsAnswered = pendingRuntimeQuestions.every" in script
    assert 'const displayStructuredUserInput = String(structuredUserInputResponse.type || "") === "request_user_input";' in script
    assert 'onClick=${() => handleRuntimeInputOption(item, option)}' in script
    assert 'className=${`runtime-input-option ${selected ? "is-selected" : ""}`}' in script
    assert "option.description" in script
    assert ".runtime-input-options" in styles
    assert ".runtime-input-option.is-selected" in styles


def test_task_update_approval_shows_complete_snapshot_and_resumes_runtime() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "function isTaskUpdateApproval(value)" in script
    assert 'String(value.type || "") === "task_update"' in script
    assert "const hasTaskUpdateApproval = isTaskUpdateApproval(activePendingApproval);" in script
    assert "const handleTaskUpdateApproval = async" in script
    assert 'type: "task_update"' in script
    assert 'handleTaskUpdateApproval("approve_once")' in script
    assert 'handleTaskUpdateApproval("cancel")' in script
    assert "renderTaskApprovalSnapshot" in script
    assert "taskApprovalCurrent" in script
    assert "taskApprovalProposed" in script
    assert "taskApprovalChangedFields" in script
    assert 't("task_approval.current")' in script
    assert 't("task_approval.proposed")' in script
    assert 't("task_approval.warning")' in script
    assert ".task-approval-snapshots" in styles
    assert ".task-approval-snapshot" in styles
    assert '"task_approval.title": "等待确认 Task 更新"' in locales
    assert '"task_approval.approve": "确认更新"' in locales
    assert '"task_approval.cancel": "取消更新"' in locales


def test_consecutive_runtime_approvals_do_not_share_a_thread_wide_button_lock() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    active_approval_block = script.split("const activePendingApproval = (() => {", 1)[1].split(
        "const hasCommandApproval = Boolean(", 1
    )[0]
    command_handler = script.split("const handleCommandApproval = async", 1)[1].split(
        "const handleTaskUpdateApproval = async", 1
    )[0]
    task_handler = script.split("const handleTaskUpdateApproval = async", 1)[1].split(
        "const renderTaskApprovalSnapshot", 1
    )[0]

    assert "runtimeApprovalSubmissionIdentity(sessionId, candidate)" in active_approval_block
    assert "const threadApprovalSubmitting" in active_approval_block
    assert "threadApprovalSubmitting" not in command_handler
    assert "threadApprovalSubmitting" not in task_handler
    assert "claimApprovalSubmission(submissionKey)" in command_handler
    assert "claimApprovalSubmission(submissionKey)" in task_handler
    assert "releaseApprovalSubmission(submissionKey)" in command_handler
    assert "releaseApprovalSubmission(submissionKey)" in task_handler


def test_completed_thread_reconciliation_cannot_hold_an_approval_lock_forever() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const THREAD_RECONCILE_TIMEOUT_MS = 5_000;" in script
    reconcile_block = script.split("const reconcileCompletedThreadMessages = async", 1)[1].split(
        "const updateOwnerLiveHeartbeat", 1
    )[0]
    assert "const controller = new AbortController();" in reconcile_block
    assert "THREAD_RECONCILE_TIMEOUT_MS" in reconcile_block
    assert "{ signal: controller.signal }" in reconcile_block
    assert "window.clearTimeout(timeoutId);" in reconcile_block


def test_llm_and_tool_failure_traces_remain_nonterminal_until_run_failure() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    status_mapper = script.split("function activityStatusFromTraceType", 1)[1].split("function mergeActivityState", 1)[0]
    heartbeat_mapper = script.split("const syncHeartbeatFromTrace", 1)[1].split("const syncHeartbeatFromStreamItem", 1)[0]

    assert 'if (normalized === "tool.failed") return "tooling";' in status_mapper
    assert 'if (normalized === "llm.failed") return "background_running";' in status_mapper
    assert 'const finishedStatus = normalizeProgressStatus(eventStatus);' in status_mapper
    assert '["completed", "failed", "blocked", "cancelled"].includes(finishedStatus)' in status_mapper
    assert 'if (normalized === "run.failed") return "failed";' in status_mapper
    assert 'if (traceType === "tool.failed")' in heartbeat_mapper
    assert 'status: "tooling"' in heartbeat_mapper
    assert 'if (traceType === "llm.failed")' in heartbeat_mapper
    assert 'status: "background_running"' in heartbeat_mapper
    assert 'if (traceType === "run.failed")' in heartbeat_mapper
    assert 'status: "failed"' in heartbeat_mapper


def test_runtime_stats_panel_and_polling_cleanup_are_wired() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        "RUNTIME_STATUS_ACTIVE_INTERVAL_MS",
        "RUNTIME_STATUS_IDLE_INTERVAL_MS",
        "MODEL_WAIT_SLOW_HINT_MS",
        "PROJECTS_REFRESH_STALE_MS",
        "runtimeStatusAbortRef",
        "projectsInFlightRef",
        "refreshProjectsIfStale({ minAgeMs: PROJECTS_REFRESH_STALE_MS })",
        "currentRuntimeStatus.loop_safeguards",
        "currentRuntimeStatus.provider_diagnostics",
        'translateUi(locale, "context_meter.compact_usage"',
        'translateUi(locale, "context_meter.compact_tokens"',
        'translateUi(locale, "context_meter.compact_elapsed_tools"',
        'translateUi(locale, "context_meter.compact_auto_compact"',
        't("context_meter.section.run")',
        't("context_meter.section.tools")',
        't("context_meter.section.context")',
        't("context_meter.section.safeguards")',
        't("context_meter.section.diagnostics")',
        'className="context-meter-details"',
        'className="context-meter-details-toggle"',
    )
    for token in required_script_tokens:
        assert token in script, token

    assert "BRANCH_REFRESH_INTERVAL_MS" not in script
    assert "context_meter.field.guard_tool_calls" not in script
    assert 'Promise.all([refreshProjects(), refreshRuntimeStatus(projectId, { background: true })])' not in script

    required_style_tokens = (
        ".context-meter-compact",
        ".context-meter-details",
        ".context-meter-details-toggle",
        ".context-meter-details-body",
        ".context-meter-section",
        ".context-meter-section-title",
        ".context-meter-kv",
        ".context-meter-label",
        ".context-meter-value",
    )
    for token in required_style_tokens:
        assert token in styles, token


def test_context_meter_uses_compact_summary_with_collapsed_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "runtimeStats.compact.map(" in script
    assert '<details className="context-meter-details">' in script
    assert 'className="context-meter-details-toggle"' in script
    assert "<details className=\"context-meter-details\" open>" not in script


def test_empty_thread_title_uses_current_locale_after_refresh() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'hit.title || hit.display_title || translateUi(locale, "labels.new_thread")' in script
    assert '${item.title || t("labels.new_thread")}' in script
    assert '"labels.new_thread": "新しいスレッド"' in locales


def test_context_meter_hover_close_uses_delayed_timer() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "contextMeterCloseTimerRef",
        "function openContextMeter()",
        "function scheduleContextMeterClose()",
        "window.setTimeout(() => {",
        "onMouseEnter=${openContextMeter}",
        "onMouseLeave=${scheduleContextMeterClose}",
    )
    for token in required_tokens:
        assert token in script, token


def test_status_and_compact_slash_commands_are_local_only() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "function normalizeSlashCommandText(value)",
        "function updateCurrentSessionRuntimeState(value)",
        "const slashCommand = normalizeSlashCommandText(messageText);",
        "await handleStatusCommand();",
        "await handleCompactCommand();",
        "const slashCommandSuggestions = slashCommandQuery",
        'event.key === "ArrowDown"',
        'event.key === "ArrowUp"',
        'event.key === "Escape"',
        "slashCommandSelectedIndex",
        'className="slash-command-menu"',
        'className=${`slash-command-item ${slashCommandSuggestions[slashCommandSelectedIndex] === item ? "is-active" : ""}`}',
        'aria-selected=${slashCommandSuggestions[slashCommandSelectedIndex] === item ? "true" : "false"}',
        '/api/sessions/${encodeURIComponent(sid)}/context-status',
        '/api/sessions/${encodeURIComponent(sid)}/compact',
        'type: "contextCompaction"',
    )
    for token in required_tokens:
        assert token in script, token

    for token in (
        ".slash-command-menu",
        ".slash-command-item",
        ".slash-command-item.is-active",
        ".slash-command-name",
        ".slash-command-copy",
    ):
        assert token in styles, token

    status_guard_index = script.index("const slashCommand = normalizeSlashCommandText(messageText);")
    chat_request_index = script.index("/api/chat/stream")
    assert status_guard_index < chat_request_index


def test_home_live_panel_and_compaction_heartbeat_are_wired() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        'if (itemType === "contextCompaction") {',
        'status: isCompleted ? "background_running" : "running",',
        't(isCompleted ? "activity.live.context_compacted" : "activity.live.context_compacting")',
        "const currentThreadLive = isCurrentThreadLiveRun({",
        "const showEmptyLivePanel = Boolean(currentThreadLive && !messages.length && !showThreadDetailLoading);",
        'className="empty-panel empty-live-panel"',
        'const liveAgentMessage = Boolean(',
        'liveAgentMessage ? "live-agent-card" : ""',
        "const agentToolAction = (status) => formatLiveAgentToolActionText(uiLocale, {",
        'action: action || detail || command || t("run.progress.waiting_tool")',
        'className="live-run-eyebrow"',
        'className=${`live-run-dot status-${runExecutionProgress.status || "running"}`}',
        't("run.live_panel.title")',
        "function formatPendingAssistantAgentText(summary, activity, locale = \"zh-CN\")",
        "runExecutionProgress.currentAction || runExecutionProgress.recentEvent",
    )
    for token in required_script_tokens:
        assert token in script, token

    required_style_tokens = (
        ".empty-live-panel",
        ".live-run-eyebrow",
        ".live-run-dot",
        ".live-run-action",
        ".live-run-command",
        ".live-run-meta",
        ".message-article.live-agent-card .message-card",
        ".message-article.live-agent-card .message-card-body",
        ".message-article.live-agent-card .message-card-body::before",
        "@keyframes live-run-pulse",
    )
    for token in required_style_tokens:
        assert token in styles, token

    assert ".message-article.live-agent-card .message-card::before" not in styles
    assert 'if (item.source === "execution_progress") return text;' in script
    assert '"run.live_panel.title": "Agent 正在处理"' in locales
    assert '"run.live_agent.preparing": "Agent 正在准备请求。"' in locales
    assert '"run.live_agent.understanding": "Agent 正在准备请求。"' in locales
    assert '"run.live_agent.understanding_detail": "Agent 正在准备请求：{detail}"' in locales
    assert '"run.live_agent.model": "Agent 已发送请求，正在等待回应。"' in locales
    assert '"run.live_agent.model_detail": "Agent 已发送请求，正在等待回应: {detail}。"' in locales
    assert '"run.live_agent.tool_running_detail": "Agent 正在执行工具：{detail}"' in locales
    assert '"run.live_agent.tool_result": "Agent 已拿到工具结果，正在判断下一步。"' in locales
    assert '"run.live_panel.title": "Agent が処理中です"' in locales
    assert '"run.live_panel.title": "Agent is working"' in locales


def test_frontend_live_timer_uses_local_interval_for_running_turns() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function normalizeMessageActivity\(raw\) \{(?P<body>.*?)\n}\n\nfunction defaultSkillTemplate",
        script,
        re.S,
    )
    assert match, "normalizeMessageActivity function not found"
    body = match.group("body")

    assert "isActivityTerminalStatus(status) && traceEvents.length" in body
    assert "const turnStartedAt = normalizeActivityTimestamp(item.turn_started_at || item.turnStartedAt || startedAt || 0);" in body
    assert "const finalElapsedMs = isActivityTerminalStatus(status)" in body
    assert "item.finished_at || 0" in body
    assert "llm_exchanges: Array.isArray(item.llm_exchanges) ? item.llm_exchanges : []" in body
    assert "traceEvents.length ? traceEvents[traceEvents.length - 1].timestamp : 0" not in body
    assert "const turnStartedAt = item.turn_started_at || item.started_at;" in script
    assert "const frozenElapsedMs = isActivityTerminalStatus(item.status)" in script
    assert "const activeRunBelongsToCurrentThread = Boolean(" in script
    assert "const shouldTickActivityClock = Boolean(" in script
    assert "Boolean(activeRunStartedAt)" in script
    assert "hasConnectionHeartbeat" in script
    clock_body = script.split("const activeRunBelongsToCurrentThread = Boolean(", 1)[1].split("if (!shouldTickActivityClock)", 1)[0]
    assert "hasLiveTurnState" not in clock_body
    assert "const ACTIVITY_CLOCK_INTERVAL_MS = 5_000;" in script
    assert "ACTIVITY_CLOCK_INTERVAL_MS," in script
    assert "formatElapsedFromStartedAt(activeRunStartedAt, activityClockMs || Date.now(), locale)" in script
    assert 'window.addEventListener("focus", syncActivityClock)' in script
    assert 'document.addEventListener("visibilitychange", syncVisibleActivityClock)' in script
    assert "hasConnectionHeartbeat]);" in script
    assert 'translateUi(locale, "duration.minutes_seconds"' in script
    assert 'translateUi(locale, "duration.hours_minutes_seconds"' in script
    polling_body = script.split("function nextRuntimeStatusPollIntervalMs", 1)[1].split("function mergeRunSnapshot", 1)[0]
    assert 'drawerView === "run"' not in polling_body
    assert "if (contextMeterOpen) return RUNTIME_STATUS_IDLE_INTERVAL_MS;" in polling_body
    assert "setActiveRunStartedAt(logicalTurnStartedAtMs);" in script
    assert "startedAt: logicalTurnStartedAtMs," in script
    assert "const liveAssistantMessageId = hasLiveRuntimeState" in script

    assert 'onMouseLeave=${() => setContextMeterOpen(false)}' not in script


def test_frontend_batches_live_rendering_and_avoids_persistent_shell_blurs() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert "const STREAM_UI_FLUSH_INTERVAL_MS = 250;" in script
    assert re.search(r"\.thread-rail\s*\{[^}]*backdrop-filter", styles, re.S) is None
    assert re.search(r"\.workspace-head\s*\{[^}]*backdrop-filter", styles, re.S) is None
    assert re.search(r"\.composer-shell\s*\{[^}]*backdrop-filter", styles, re.S) is None


def test_runtime_control_center_prioritizes_live_state_and_interactions() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        "function buildRunExecutionProgress({",
        "function latestAssistantMessage(messages, options = {})",
        "function currentChecklistStepLabel(plan, checkpoint = {})",
        "function executionProgressCommandFromSource(source)",
        "function formatRunProgressStatus(locale, status)",
        "const runtimeAttentionCount = Number(hasCommandApproval) + Number(hasTaskUpdateApproval) + Number(hasPendingRuntimeInput);",
        'className="workbench-scroll runtime-control-center"',
        "runtime-overview-card",
        'className="panel-card runtime-attention-card"',
        't("runtime_panel.active_work")',
        't("runtime_panel.recent_events")',
        't("runtime_panel.controls")',
        "activeRuntimeUnits",
        "runtimeDecisionEvents",
        "action\\.blocked",
        "openLatestRuntimeDebug",
        "handleStopRun",
        'formatRunFieldLabel(uiLocale, "current_tool")',
        "runExecutionProgress.statusLabel",
        "const baseRunExecutionProgress = buildRunExecutionProgress({",
        'status: "waiting_approval"',
        'status: "approval_submitting"',
        'statusLabel: t("runtime_panel.approval_required")',
        'statusLabel: t("runtime_panel.approval_submitting")',
        "function buildRuntimeOutcomeSummary(activity, locale)",
        "const runtimeOutcomeNeedsLoad = Boolean(",
        'if (drawerView !== "run" || hasLiveRuntimeState || !runtimeOutcomeNeedsLoad) return;',
        "if (messageId) ensureRunActivity(messageId);",
        't("runtime_panel.last_run")',
        't("runtime_panel.failed_tools")',
        "runtimeOutcome.failures",
    )
    for token in required_script_tokens:
        assert token in script, token

    required_style_tokens = (
        ".run-progress-grid",
        ".run-progress-row",
        ".run-progress-label",
        ".run-progress-value",
        ".run-progress-command",
        ".run-progress-state",
        ".run-progress-state.status-validating",
        ".run-progress-state.status-waiting_model",
        ".run-progress-state.status-waiting_approval",
        ".run-progress-state.status-approval_submitting",
        ".runtime-nav-btn",
        ".runtime-attention-badge",
        ".runtime-control-center",
        ".runtime-status-grid",
        ".runtime-attention-card",
        ".runtime-unit-row",
        ".runtime-event-row",
        ".runtime-control-actions",
        ".runtime-outcome-stats",
        ".runtime-failure-row",
        ".runtime-failure-summary",
    )
    for token in required_style_tokens:
        assert token in styles, token

    required_locale_tokens = (
        '"tabs.run": "Runtime"',
        '"runtime_panel.title": "Runtime"',
        '"runtime_panel.action_required": "需要处理"',
        '"runtime_panel.approval_required": "等待用户审批"',
        '"runtime_panel.approval_submitting": "正在提交审批"',
        '"runtime_panel.user_input_required": "等待你的输入"',
        '"runtime_panel.active_work": "当前执行单元"',
        '"runtime_panel.recent_events": "最近 Runtime 事件"',
        '"runtime_panel.open_developer_debug": "打开开发者调试"',
        '"runtime_panel.last_run": "最近运行结果"',
        '"runtime_panel.failed_tools": "失败工具"',
        '"run.field.current_tool": "当前工具"',
        '"run.progress.status.waiting_model": "等待模型下一步"',
        '"run.progress.status.waiting_tool": "等待工具结果"',
        '"run.progress.status.background_running": "后台仍在运行"',
    )
    for token in required_locale_tokens:
        assert token in locales, token

    runtime_drawer = script.split('${drawerView === "run"', 1)[1].split('${drawerView === "tools"', 1)[0]
    for removed_concern in (
        'formatRunFieldLabel(uiLocale, "goal")',
        'formatRunFieldLabel(uiLocale, "evidence")',
        'formatRunFieldLabel(uiLocale, "ocr")',
        'formatRunFieldLabel(uiLocale, "compaction")',
        'formatRunFieldLabel(uiLocale, "context")',
        't("run.checklist")',
        't("run.recent_tools")',
        't("run.logs")',
    ):
        assert removed_concern not in runtime_drawer, removed_concern


def test_guard_rejection_does_not_masquerade_as_missing_user_input() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    blocked_trace = script.split('if (traceType === "action.blocked") {', 1)[1].split(
        'if (traceType === "tool.failed") {',
        1,
    )[0]
    assert 'status: "validating"' in blocked_trace
    assert 'status: "blocked"' not in blocked_trace
    assert 't("activity.status.tool_guard_rejected")' in blocked_trace

    subagent_stream = script.split('if (itemType === "subagent") {', 1)[1].split(
        'if (!["toolCall"',
        1,
    )[0]
    assert 'status: isCompleted ? "background_running" : "running"' in subagent_stream
    assert 'source: "subagent"' in subagent_stream

    runtime_event_filter = script.split("const runtimeControlTraceEvents =", 1)[1].split(
        "const runtimeDecisionEvents",
        1,
    )[0]
    assert "action\\.blocked" in runtime_event_filter
    assert '"activity.blocked": "执行已停止"' in locales
    assert '"activity.blocked": "Stopped"' in locales


def test_live_run_snapshot_persists_owner_thread_and_started_at() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "activeRunThreadId: runOwnerThreadId,",
        "startedAt: logicalTurnStartedAtMs,",
        "startedAt: snapshotTurnStartedAt || prev.startedAt || logicalTurnStartedAtMs,",
        "startedAt: activeRunStartedAt,",
        "setActiveRunThreadId(next.activeRunThreadId);",
        "setActiveRunStartedAt(next.startedAt);",
        "setLastLiveProgressAt(next.lastLiveProgressAt);",
        "setLiveHeartbeat(next.liveHeartbeat);",
        'liveHeartbeat: createEmptyLiveHeartbeat(),',
    )
    for token in required_tokens:
        assert token in script, token


def test_live_trace_progress_covers_guard_and_waiting_states() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        'type === "action.detected" || type === "tool.call_detected"',
        'type === "action.validating"',
        'type === "action.allowed"',
        'type === "action.blocked"',
        'type === "observation.returned"',
        'status: "validating"',
        'status: "waiting_model"',
        'status: "waiting_tool"',
        "const progressIsStale = Boolean(",
        "(nowMs - lastProgressAtMs) >= LIVE_PROGRESS_STALE_AFTER_MS",
        'status = "background_running";',
        "const updateOwnerLiveHeartbeat = (value) => {",
        "const syncHeartbeatFromTrace = (trace) => {",
        "const syncHeartbeatFromStreamItem = (item, eventName = \"\") => {",
        "const agentMessageCompleted = isCompleted || normalizeProgressStatus(entry.status) === \"completed\";",
        "if (agentMessageCompleted) return;",
        'recentEvent: detail || t("run.progress.recent_event_waiting_model")',
        'recentEvent: detail || command || tool || t("run.progress.recent_event_background")',
        'source: "validator"',
        'source: "tool"',
        'source: "model"',
    )
    for token in required_tokens:
        assert token in script, token


def test_live_display_activity_overrides_latest_live_assistant_until_cleanup() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "function buildLiveDisplayActivity(activity, options = {}) {",
        'return !["run.finished", "answer.done", "answer.finished"].includes(traceType);',
        'const hasVisibleFinalAnswer = Boolean(String(item.final_answer || "").trim());',
        'const shouldSuppressTerminalDisplay = normalizeProgressStatus(item.status) === "completed" && !hasVisibleFinalAnswer;',
        'const heartbeatSource = String(heartbeat.source || "").trim();',
        'const heartbeatCanOwnLiveStatus = ["validating", "running", "waiting_tool", "waiting_model", "background_running", "blocked", "failed"].includes(heartbeatStatus);',
        'live_model_started: Boolean(item.live_model_started || (heartbeatStatus === "waiting_model" && heartbeatSource === "model")),',
        "const isDisplayLiveAssistant = Boolean(",
        "&& liveAssistantMessageId",
        "String(item.id || \"\") === liveAssistantMessageId",
        "buildLiveDisplayActivity(activity, {",
        "buildLiveDisplayActivity(item.activity || {}, {",
    )
    for token in required_tokens:
        assert token in script, token


def test_summary_reload_preserves_live_heartbeat_for_active_owner_thread() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "const existingActiveTurn = normalizeThreadActiveTurn((existingSnapshot && existingSnapshot.activeTurn) || {});",
        "const preserveLiveSnapshot = Boolean(",
        "activeRunStartedAt: existingActiveTurn.startedAt || activeRunStartedAt || 0,",
        "hasRunningActivity: Boolean(existingActiveTurn.startedAt || existingActiveTurn.lastLiveProgressAt || existingActiveTurn.liveHeartbeat.updatedAt),",
        "liveTurnState: existingActiveTurn.liveTurnState || liveTurnState || {},",
    )
    for token in required_tokens:
        assert token in script, token


def test_frontend_uses_large_context_default_max_output_tokens_and_server_bootstrap_override() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "max_output_tokens: 16384" in script
    assert "health.default_max_output_tokens" in script
    assert "setChatSettings((prev) =>" in script


def test_reasoning_effort_selector_is_wired_into_the_composer() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'const REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]' in script
    assert 'className="composer-reasoning-select"' in script
    assert "reasoning_effort: nextValue || null" in script
    assert 'const REASONING_EFFORT_STORAGE_KEY = "vintage_programmer.reasoning_effort";' in script
    assert "window.localStorage.setItem(REASONING_EFFORT_STORAGE_KEY, effort)" in script
    assert '"settings.reasoning_effort.xhigh": "极高"' in locales
    assert '"settings.reasoning_effort.max": "Max"' in locales


def test_context_turns_help_text_is_wired_into_frontend() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'className="field-hint"' in script
    assert 't("settings.context_turns.help")' in script
    assert '"settings.context_turns.help": "本次请求构建模型上下文时，最多纳入的历史对话轮数；不是当前 thread 的总轮数。"' in locales
    assert '"settings.context_turns.help": "今回のモデル文脈に含める履歴ターン数の上限です。スレッド全体の総ターン数ではありません。"' in locales
    assert '"settings.context_turns.help": "Maximum historical turns considered for the current model context, not the total thread turn count."' in locales


def test_model_presets_refresh_only_from_explicit_settings_action() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "async function refreshModelPresets()" in script
    assert "onClick=${refreshModelPresets}" in script
    assert "models/refresh`" in script
    assert '{ method: "POST" }' in script
    assert 't("settings.model_presets.help")' in script
    assert '"settings.model_presets.help": "只在点击时访问当前 Provider；结果会保存到本机，启动时不会联网更新。"' in locales
    assert "refreshModelPresets();" not in script


def test_settings_theme_color_selector_drives_accent_variables() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        'const THEME_COLOR_STORAGE_KEY = "vintage_programmer.theme_color";',
        "const THEME_COLOR_OPTIONS = [",
        '{ id: "amber", accent: "#f37021", accentInk: "#ffffff", accentSoft: "#ffede2", accentStrong: "#df5f10", accentDark: "#b94708" }',
        "function readStoredThemeColor() {",
        "function applyThemeColor(value) {",
        'root.style.setProperty("--accent", option.accent);',
        'root.style.setProperty("--accent-ink", option.accentInk);',
        'root.style.setProperty("--accent-soft", option.accentSoft);',
        "const [themeColor, setThemeColor] = useState(readStoredThemeColor);",
        "const selectedThemeColor = themeColorOptionById(themeColor).id;",
        'className="theme-color-options"',
        'className=${`theme-color-option ${selectedThemeColor === item.id ? "active" : ""}`}',
        'onClick=${() => setThemeColor(item.id)}',
        't("settings.theme_color")',
    )
    for token in required_script_tokens:
        assert token in script, token

    required_style_tokens = (
        ".theme-color-options",
        ".theme-color-option",
        ".theme-color-option.active",
        ".theme-color-swatch",
        ".theme-color-name",
    )
    for token in required_style_tokens:
        assert token in styles, token

    assert '"settings.theme_color": "主题色"' in locales
    assert '"settings.theme_color": "テーマ色"' in locales
    assert '"settings.theme_color": "Theme Color"' in locales
    assert '"settings.theme_color.amber": "橘黄色"' in locales
    assert '"settings.theme_color.amber": "オレンジ"' in locales
    assert '"settings.theme_color.amber": "Orange"' in locales


def test_internal_design_manual_describes_current_thread_runtime() -> None:
    manual = INTERNAL_MANUAL_PATH.read_text(encoding="utf-8")

    assert manual.startswith("# Vintage Programmer 内部设计手册")
    assert "`thread_transcript.items` 是可继续对话的唯一历史事实源" in manual
    assert "System Message 只有一个" in manual
    assert "Trace 不是第二份聊天历史" in manual
    assert "选择 Full Access 就是本轮完整文件系统授权" in manual
    assert "skills/builtin/<name>/SKILL.md" in manual
    assert "skills/team/<name>/SKILL.md" in manual
    assert "旧 Harness 六要素" in manual
    assert "workspace/skills/<name>/SKILL.md" not in manual
    assert "agents/vintage_programmer/skills/<skill>/SKILL.md" not in manual
    assert "VP_ALLOW_ANY_PATH" in manual


def test_failed_tool_summary_defaults_are_wired_into_frontend() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "function toolFailureSummary(item, locale)" in script
    assert 'translateUi(locale, "tool.failure.error")' in script
    assert 'translateUi(locale, "tool.failure.stderr")' in script
    assert 'translateUi(locale, "tool.failure.returncode")' in script
    assert 'translateUi(locale, "tool.failure.cwd")' in script
    assert 'translateUi(locale, "tool.failure.command")' in script
    assert 'status === "failed" || status === "error"' in script
    assert "lines.slice(0, 5).join(\"\\n\")" in script
    assert "white-space: pre-wrap;" in styles
    assert '"tool.failure.error": "error"' in locales
    assert '"tool.failure.stderr": "stderr"' in locales
    assert '"tool.failure.returncode": "returncode"' in locales
    assert '"tool.failure.cwd": "cwd"' in locales
    assert '"tool.failure.command": "command"' in locales


def test_turn_timer_anchor_is_preserved_across_activity_updates() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "prev.started_at || nextStartedAtCandidate || 0" in script
    assert "prev.turn_started_at || nextTurnStartedAtCandidate || nextStartedAt || 0" in script
    assert "Number(prev.final_elapsed_ms || 0) || 0" in script
    assert "function resumableTurnStartedAt(messages, runtimeState = {})" in script
    assert "pendingTurn.turn_started_at" in script
    assert "const logicalTurnStartedAtMs = isTurnResume" in script
    assert "resumableTurnStartedAt(messages, sessionRuntimeState) || clientSubmittedAtMs" in script
    assert "turn_started_at: logicalTurnStartedAtMs," in script
    assert "setActiveRunStartedAt(logicalTurnStartedAtMs);" in script
    assert "snapshot.turn_started_at || snapshot.turnStartedAt || 0" in script

    run_started_match = re.search(
        r'if \(event === "run_started"\) \{(?P<body>.*?)\n            \} else if \(event === "run_finished"\)',
        script,
        re.S,
    )
    assert run_started_match, "run_started handler not found"
    run_started_body = run_started_match.group("body")
    assert "modelRequestStarted = true;" in run_started_body
    assert 'status: "waiting_model"' in run_started_body
    assert "live_model_started: true" in run_started_body
    assert "live_model: runModelName" in run_started_body
    assert "model: runModelName" in run_started_body
    assert 't("run.live_agent.model_detail", { detail: runModelName })' in run_started_body
    assert 'replacePendingText(t("activity.status.waiting_model"), { onlyWhileWaiting: true });' in run_started_body
    assert 'source: "model"' in run_started_body
    assert "started_at" not in run_started_body


def test_prefinal_run_events_do_not_terminalize_pending_activity() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const previewPendingAssistant = (options = {}) => {" in script
    assert "const completeWhenStable = Boolean(options.completeWhenStable);" in script
    assert 'completeWhenStable && stableText\n              ? "completed"' in script
    assert "const nextFinalAnswer = completeWhenStable && stableText" in script

    run_finished_match = re.search(
        r'else if \(event === "run_finished"\) \{(?P<body>.*?)\n            \} else if \(event === "run_failed"\)',
        script,
        re.S,
    )
    assert run_finished_match, "run_finished handler not found"
    run_finished_body = run_finished_match.group("body")
    assert "previewPendingAssistant({" in run_finished_body
    assert "stabilizePendingAssistant({" not in run_finished_body
    assert "completeWhenStable: true" in run_finished_body
    assert "collapseLiveRunUi();" in run_finished_body
    assert "if (hasVisibleAnswer || displayedAnswer) {" in run_finished_body
    assert "} else {" in run_finished_body
    assert 'status: hasVisibleAnswer ? "completed"' not in run_finished_body.split("} else {", 1)[1]

    turn_completed_match = re.search(
        r'else if \(event === "turn/completed"\) \{(?P<body>.*?)\n            \} else if \(event === "item/started" \|\| event === "item/updated"\)',
        script,
        re.S,
    )
    assert turn_completed_match, "turn/completed handler not found"
    turn_completed_body = turn_completed_match.group("body")
    assert "previewPendingAssistant({" in turn_completed_body
    assert "stabilizePendingAssistant({" not in turn_completed_body
    assert "completeWhenStable: true" in turn_completed_body
    assert "collapseLiveRunUi();" in turn_completed_body
    assert "if (hasVisibleAnswer || displayedAnswer) {" in turn_completed_body
    assert "} else {" in turn_completed_body
    assert 'status: hasVisibleAnswer ? "completed"' not in turn_completed_body.split("} else {", 1)[1]


def test_stream_runtime_finished_does_not_cleanup_ui_before_final_payload() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    handle_send_match = re.search(
        r"async function handleSend\(overrideText, userInputResponse\) \{(?P<body>.*?)\n  }\n\n  async function loadSpecDetail",
        script,
        re.S,
    )
    assert handle_send_match, "handleSend function not found"
    body = handle_send_match.group("body")

    assert "const stabilizePendingAssistant = (options = {}) => {" in body
    assert "const cleanupRunUi = async () => {" in body
    assert "const collapseLiveRunUi = () => {" in body

    run_finished_match = re.search(
        r'else if \(event === "run_finished"\) \{(?P<body>.*?)\n            \} else if \(event === "run_failed"\)',
        body,
        re.S,
    )
    assert run_finished_match, "run_finished branch not found"
    run_finished_body = run_finished_match.group("body")
    assert "const hasVisibleAnswer = hasVisibleFinalAnswer();" in run_finished_body
    assert "previewPendingAssistant({" in run_finished_body
    assert 'status: hasVisibleAnswer ? "completed" : (latestActivity.status || "thinking")' in run_finished_body
    assert "allowDraft: !hasVisibleAnswer" in run_finished_body
    assert "completeWhenStable: true" in run_finished_body
    assert "collapseLiveRunUi();" in run_finished_body
    assert "if (hasVisibleAnswer || displayedAnswer) {" in run_finished_body
    assert "} else {" in run_finished_body
    assert "setSending(false)" not in run_finished_body
    assert "setActiveRunThreadId(\"\")" not in run_finished_body
    assert "activeRunId: \"\"" not in run_finished_body

    turn_completed_match = re.search(
        r'else if \(event === "turn/completed"\) \{(?P<body>.*?)\n            \} else if \(event === "item/started" \|\| event === "item/updated"\)',
        body,
        re.S,
    )
    assert turn_completed_match, "turn/completed branch not found"
    turn_completed_body = turn_completed_match.group("body")
    assert "const hasVisibleAnswer = hasVisibleFinalAnswer();" in turn_completed_body
    assert "previewPendingAssistant({" in turn_completed_body
    assert 'status: hasVisibleAnswer ? "completed" : (latestActivity.status || "thinking")' in turn_completed_body
    assert "completeWhenStable: true" in turn_completed_body
    assert "collapseLiveRunUi();" in turn_completed_body
    assert "if (hasVisibleAnswer || displayedAnswer) {" in turn_completed_body
    assert "} else {" in turn_completed_body
    assert "setSending(false)" not in turn_completed_body
    assert "setActiveRunThreadId(\"\")" not in turn_completed_body

    assert "await cleanupRunUi();" in body
    cleanup_body = body.split("const cleanupRunUi = async () => {", 1)[1].split("const collapseLiveRunUi = () => {", 1)[0]
    assert "activeRunThreadId: \"\"" in cleanup_body
    assert "startedAt: 0" in cleanup_body
    assert "lastLiveProgressAt: 0" in cleanup_body
    assert "liveHeartbeat: createEmptyLiveHeartbeat()" in cleanup_body
    assert "stoppingRun: false" in cleanup_body
    assert "if (!uiFinalized) {" in body


def test_chat_auto_scroll_switches_to_stick_to_bottom_mode() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "const CHAT_AUTO_SCROLL_THRESHOLD_PX = 100;" in script
    assert "const [showJumpToLatest, setShowJumpToLatest] = useState(false);" in script
    assert "const autoScrollEnabledRef = useRef(true);" in script
    assert "function isNearChatBottom(element, threshold = CHAT_AUTO_SCROLL_THRESHOLD_PX)" in script
    assert "function syncChatScrollState(element)" in script
    assert "function scrollChatToBottom(options = {})" in script
    assert "function jumpToLatest()" in script
    assert 'el.addEventListener("scroll", handleScroll, { passive: true });' in script
    assert "if (!autoScrollEnabledRef.current) {" in script
    assert "scrollChatToBottom();" in script
    assert 'onClick=${jumpToLatest}' in script
    assert 't("buttons.jump_to_latest")' in script
    assert "scrollTop = chatListRef.current.scrollHeight" not in script
    assert ".jump-latest-row" in styles
    assert '"buttons.jump_to_latest": "回到底部"' in locales
    assert '"buttons.jump_to_latest": "Jump to latest"' in locales


def test_model_draft_live_cards_cover_non_terminal_activity_states() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function buildMainLiveCards\(activity, liveItems = \[], runtimeTrace = \[], locale = \"zh-CN\", nowMs = Date\.now\(\)\) \{(?P<body>.*?)\n}\n\nfunction buildMainCompletionSummary",
        script,
        re.S,
    )
    assert match, "buildMainLiveCards function not found"
    body = match.group("body")

    assert "const modelDraftText = String(item.model_draft || \"\").trim();" in body
    assert "const finalAnswerText = String(item.final_answer || \"\").trim();" in body
    assert "!finalAnswerText" in body
    assert "!isActivityTerminalStatus(item.status)" in body
    assert 'normalizeProgressStatus(item.status) === "failed"' in body
    assert 'cards.unshift({' in body


def test_activity_merge_can_clear_model_draft_after_final_answer() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function mergeActivityState\(previous, patch = \{\}\) \{(?P<body>.*?)\n}\n\nfunction buildLiveDisplayActivity",
        script,
        re.S,
    )
    assert match, "mergeActivityState function not found"
    body = match.group("body")

    assert 'Object.prototype.hasOwnProperty.call(nextPatch, "model_draft")' in body
    assert "model_draft: nextModelDraft," in body
    assert 'Object.prototype.hasOwnProperty.call(nextPatch, "final_answer")' in body
    assert "final_answer: nextFinalAnswer," in body


def test_resumed_live_activity_clears_terminal_timer_anchor() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    merge_match = re.search(
        r"function mergeActivityState\(previous, patch = \{\}\) \{(?P<body>.*?)\n}\n\nfunction buildLiveDisplayActivity",
        script,
        re.S,
    )
    assert merge_match, "mergeActivityState function not found"
    merge_body = merge_match.group("body")
    assert "const nextStatusIsTerminal = isActivityTerminalStatus(nextStatus);" in merge_body
    assert re.search(
        r"const nextFinishedAt = nextStatusIsTerminal\s*\?.*?\n\s*: 0;",
        merge_body,
        re.S,
    )
    assert "finished_at: nextFinishedAt," in merge_body
    assert "final_elapsed_ms: nextFinalElapsedMs," in merge_body

    display_match = re.search(
        r"function buildLiveDisplayActivity\(activity, options = \{\}\) \{(?P<body>.*?)\n}\n\nfunction appendActivityTrace",
        script,
        re.S,
    )
    assert display_match, "buildLiveDisplayActivity function not found"
    display_body = display_match.group("body")
    assert "const displayStatusIsTerminal = isActivityTerminalStatus(displayStatus);" in display_body
    assert "options.activeRunStartedAt || item.turn_started_at || item.started_at || 0" in display_body
    assert "turn_started_at: liveTurnStartedAt," in display_body
    assert "finished_at: displayStatusIsTerminal ? item.finished_at : 0," in display_body
    assert "final_elapsed_ms: displayStatusIsTerminal ? item.final_elapsed_ms : 0," in display_body

    trace_match = re.search(
        r"function appendActivityTrace\(activity, trace, options = \{\}\) \{(?P<body>.*?)\n}\n\nfunction formatActivityDuration",
        script,
        re.S,
    )
    assert trace_match, "appendActivityTrace function not found"
    trace_body = trace_match.group("body")
    assert "const nextStatusIsTerminal = isActivityTerminalStatus(nextStatus);" in trace_body
    assert re.search(
        r"const finishedAt = nextStatusIsTerminal\s*\?.*?\n\s*: 0;",
        trace_body,
        re.S,
    )


def test_context_summary_distinguishes_compaction_history_from_recommendation() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function summarizeContextStatus\(meterLike, compactionLike\) \{(?P<body>.*?)\n  }\n\n  function appendLocalAssistantMessage",
        script,
        re.S,
    )
    assert match, "summarizeContextStatus function not found"
    body = match.group("body")

    assert "const generation = Math.max(0, Number(compaction.generation || 0) || 0);" in body
    assert "const hasCompactedHistory = Boolean(" in body
    assert "compaction.compacted_history_present" in body
    assert "compaction.last_compacted_at" in body
    assert "meter.last_compacted_at" in body
    assert 't("context_meter.compact.completed_count", { count: generation })' in body
    assert 't("context_meter.compact.completed")' in body
    assert '"context_meter.compact.none": "无需整理"' in locales
    assert '"context_meter.compact.completed_count": "已整理 {count} 次"' in locales
    assert '"context_meter.compact.suggested": "下轮自动整理"' in locales
    assert '"context_meter.compact.required": "等待自动整理"' in locales


def test_agent_message_completion_waits_for_turn_or_steer_boundary() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    event_completed_match = re.search(
        r'else if \(event === "item/completed"\) \{(?P<body>.*?)\n            \} else if \(event === "request_user_input"\)',
        script,
        re.S,
    )
    assert event_completed_match, "item/completed event branch not found"
    item_completed_match = re.search(
        r'if \(itemType === "agentMessage"\) \{(?P<body>.*?)\n              \} else if \(itemType === "userInputRequest"\)',
        event_completed_match.group("body"),
        re.S,
    )
    assert item_completed_match, "agentMessage item/completed branch not found"
    item_completed_body = item_completed_match.group("body")
    assert 'status: "waiting_model"' in item_completed_body
    assert 'final_answer: ""' in item_completed_body
    assert "model_draft: assistantText" in item_completed_body
    assert 'updateOwnerLiveHeartbeat({' not in item_completed_body
    assert "collapseLiveRunUi" not in item_completed_body
    assert "if (assistantText) replacePendingText(assistantText);" in item_completed_body
    assert 'model_draft: String(nextFinalAnswer).trim()\n              ? ""\n              : String(latestRunSnapshot.model_draft || activity.model_draft || stableText || ""),' in script


def test_live_summary_prefers_latest_meaningful_card_and_uses_progress_label() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function resolveLiveSummary\(activity, projection, locale = \"zh-CN\"\) \{(?P<body>.*?)\n}\n\nfunction formatLiveSummaryText",
        script,
        re.S,
    )
    assert match, "resolveLiveSummary function not found"
    body = match.group("body")

    assert 'const modelDraftText = String(item.model_draft || "").trim();' in body
    assert 'const finalAnswerText = String(item.final_answer || "").trim();' in body
    assert "if (modelDraftText && !finalAnswerText)" in body
    assert 'String(card && card.id || "") !== "model-draft"' in body
    assert body.index("if (selectedExecutionText)") < body.index("if (modelDraftText && !finalAnswerText)")
    assert "latestMeaningfulToolResultCard" in body
    assert 'type.startsWith("tool.")' in body
    assert 'const reversedCards = cards.slice().reverse();' in body
    assert "latestMeaningfulCurrentCard" in body
    assert "latestMeaningfulNonCompletedCard" in body
    assert 'title: translateUi(locale, "runtime.execution_progress.title")' in body
    assert "main_live_cards[0]" not in body


def test_pending_assistant_fallback_state_prefers_live_summary_without_mutating_message_text() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function pendingAssistantFallbackState\(item, locale = \"zh-CN\", nowMs = Date\.now\(\)\) \{(?P<body>.*?)\n}\n\nfunction buildMainCompletionSummary",
        script,
        re.S,
    )
    assert match, "pendingAssistantFallbackState function not found"
    body = match.group("body")

    assert 'const activity = normalizeMessageActivity(item.activity || {});' in body
    assert 'const currentText = String(item.text || "");' in body
    assert 'const modelDraftText = String(activity.model_draft || "").trim();' in body
    assert 'if (item.pending && modelDraftText && currentText.trim()) {' in body
    assert 'if (!item.pending || String(activity.final_answer || "").trim()) {' in body
    assert 'const projection = buildActivityProjection(activity, locale, nowMs);' in body
    assert 'const liveSummary = resolveLiveSummary(activity, projection, locale);' in body
    assert 'const liveSummaryText = formatLiveSummaryText(liveSummary);' in body
    assert 'const agentText = formatPendingAssistantAgentText(liveSummary, activity, locale);' in body
    assert 'fromSummaryFallback: true,' in body
    assert 'suppressNoteText: liveSummaryText,' in body


def test_pending_agent_copy_uses_actual_tool_metadata_not_keywords() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function formatPendingAssistantAgentText\(summary, activity, locale = \"zh-CN\"\) \{(?P<body>.*?)\n}\n\nfunction pendingAssistantFallbackState",
        script,
        re.S,
    )
    assert match, "formatPendingAssistantAgentText function not found"
    body = match.group("body")

    assert "const hasActualTool = Boolean(" in body
    assert "const toolPhase = toolProgressPhaseFromStatus(cardStatus, type);" in body
    assert 'if (hasActualTool && toolPhase === "preparing") {' in body
    assert 'if (hasActualTool && toolPhase === "active") {' in body
    assert "const isContextCompactionActivity = Boolean(" in body
    assert 'if (isContextCompactionActivity) {' in body
    assert "/context|compaction|compact|上下文|压缩|コンテキスト/" not in body
    assert 'translateUi(locale, "run.live_agent.tool_running_detail", { detail: toolAction })' in body
    assert 'translateUi(locale, "run.live_agent.tool_result_detail", { detail: toolAction })' in body
    assert 'if (status === "waiting_model") {' in body
    assert "const modelName = liveModelNameFromActivity(activityItem);" in body
    assert 'translateUi(locale, "run.live_agent.model_detail", { detail: modelName })' in body
    assert ': translateUi(locale, "run.live_agent.model"))' in body
    assert ': translateUi(locale, "run.live_agent.preparing")' in body
    assert 'if (status === "background_running") return translateUi(locale, "run.live_agent.preparing");' in body
    assert 'translateUi(locale, "run.live_agent.understanding_detail", { detail })' not in body
    assert 'translateUi(locale, "run.live_agent.understanding")' not in body
    assert "/model|thinking|理解|问题|request|モデル|問題/" not in body
    assert 'if (status === "waiting_model" || /model|thinking|理解|问题|request|モデル|問題/.test(haystack))' not in body
    assert 'translateUi(locale, "run.live_agent.model_detail", { detail })' not in body
    assert "activityItem.activity_summary" not in body


def test_frontend_normalizes_runtime_tooling_statuses() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function normalizeProgressStatus\(value\) \{(?P<body>.*?)\n}\n\nfunction latestActivityPayloadValue",
        script,
        re.S,
    )
    assert match, "normalizeProgressStatus function not found"
    body = match.group("body")

    assert '"tooling"' in body
    assert '"answering"' in body
    assert 'normalized === "tool.finished"' in script
    assert 'normalized === "tool.failed"' in script


def test_pending_assistant_body_uses_live_summary_fallback() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"const messageBodyText = \(item\) => \{(?P<body>.*?)\n  \};\n\n  return html`",
        script,
        re.S,
    )
    assert match, "messageBodyText helper not found"
    body = match.group("body")

    assert 'return pendingAssistantFallbackState(item, uiLocale, activityClockMs || Date.now()).text;' in body
    assert 'dangerouslySetInnerHTML=${{ __html: renderMessageHtml(messageBodyText(item), item.id) }}' in script


def test_message_copy_button_is_rendered_below_message_and_revealed_on_hover() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert "async function copyTextToClipboard(text)" in script
    assert "function fallbackCopyText(text)" in script
    assert "const [copiedMessageId, setCopiedMessageId] = useState(\"\");" in script
    assert "const handleCopyMessage = async (item) => {" in script
    assert 'const copyLabel = copied ? t("labels.copied") : t("buttons.copy_message");' in script
    assert '<div className="message-copy-row">' in script
    assert 'className=${`message-copy-btn ${copied ? "copied" : ""}`}' in script
    assert 'onClick=${() => handleCopyMessage(item)}' in script
    assert 'aria-label=${copyLabel}' in script
    assert 'className="message-copy-icon"' in script
    assert ".message-meta-actions" not in styles
    assert ".message-copy-row" in styles
    assert ".message-article:hover .message-copy-row" in styles
    assert ".message-article:focus-within .message-copy-row" in styles
    assert "pointer-events: none;" in styles
    assert ".message-copy-btn" in styles
    assert "--message-copy-bg" in styles
    assert "width: 28px;" in styles
    assert "border-radius: 9px;" in styles
    assert "background: var(--message-copy-bg);" in styles
    assert "width: 15px;" in styles
    assert "border: 1.7px solid currentColor;" in styles
    assert ".message-copy-icon::before" in styles
    assert ".message-copy-icon::after" in styles


def test_run_activity_and_debug_loading_are_separate_and_lazy() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"async function ensureRunDetail\(messageId, view, options = \{\}\) \{(?P<body>.*?)\n  \}",
        script,
        re.S,
    )
    assert match, "ensureRunDetail function not found"
    body = match.group("body")

    assert 'detailView === "debug"' in body
    assert "currentActivity.activity_loaded" in body
    assert "currentActivity.debug_loaded" in body
    assert "currentActivity.tool_items.length" not in body
    assert "currentActivity.live_items.length" not in body
    assert "currentActivity.llm_exchanges.length" not in body
    assert "currentActivity.trace_events.length" not in body
    assert "?view=${detailView}" in body
    assert "activity_loaded: true" in body
    assert 'debug_loaded: detailView === "debug"' in body
    assert 'const ensureRunActivity = (messageId) => ensureRunDetail(messageId, "activity");' in script
    assert 'const ensureRunDebug = (messageId) => ensureRunDetail(messageId, "debug");' in script
    assert "if (isOpen) ensureRunDebug(messageId);" in script
    assert "?view=summary&max_turns=" in script


def test_debug_loading_merges_only_slim_activity_debug_payload() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    ensure_body = re.search(
        r"async function ensureRunDetail\(messageId, view, options = \{\}\) \{(?P<body>.*?)\n  \}",
        script,
        re.S,
    )
    assert ensure_body, "ensureRunDetail function not found"
    body = ensure_body.group("body")

    assert "answerBundle:" not in body
    assert "runArtifact:" not in body
    assert "runtime_inspector" in script
    assert "runActivityLoading: true" in body
    assert "runActivityLoading: false" in body
    assert "runDebugLoading: true" in body
    assert "runDebugLoading: false" in body
    assert "runActivityError" in body
    assert "runDebugError" in body
    assert "if (currentMessage.pending) return;" in body
    assert "updateThreadSnapshot(sid" in body

    debug_body = re.search(
        r"const renderActivityDebugDetails = \(message\) => \{(?P<body>.*?)\n  \};\n\n  const renderMessageActivity",
        script,
        re.S,
    )
    assert debug_body, "renderActivityDebugDetails helper not found"
    debug = debug_body.group("body")
    assert "const runArtifact = message && message.runArtifact" not in debug
    assert "const threadItems = Array.isArray(activity.thread_items)" in debug
    assert "const turnTrace = activity.turn_trace" in debug
    assert "traceStepByItemId" in debug
    assert "chatSettings.debug_raw" not in debug
    assert "lastInspector || {}" not in debug


def test_finalized_assistant_message_replaces_temp_id_with_canonical_turn_id() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'turn_id: String(latestRunSnapshot.turn_id || "")' in script
    assert 'const previousPendingMessageId = pendingMessage.id;' in script
    assert 'const finalizedTurnId = String(finalPayload.turn_id || latestRunSnapshot.turn_id || previousPendingMessageId || "").trim() || previousPendingMessageId;' in script
    assert 'item.id === previousPendingMessageId' in script
    assert 'id: finalizedTurnId,' in script
    assert 'pendingMessage = { ...pendingMessage, id: finalizedTurnId };' in script


def test_running_thread_browse_state_is_thread_scoped_in_cache() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "activeRunThreadId" in script
    assert "createEmptyThreadActiveTurn()" in script
    assert "normalizeThreadActiveTurn(raw)" in script
    assert "rememberVisibleThreadSnapshot(sessionId);" in script
    assert "const preserveLiveSnapshot = Boolean(" in script
    assert "updateOwnerMessages" in script
    assert "ownerThreadVisible()" in script
    assert 'String(activeRunThreadId || "").trim() === String(sessionId || "").trim()' in script

    thread_block = script.split('className=${`thread-row', 1)[1].split("</button>", 1)[0]
    assert 'disabled=${sending}' not in thread_block
    assert "window.prompt" not in script


def test_thread_sidebar_supports_bulk_select_and_delete() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        "const [selectedThreadIds, setSelectedThreadIds] = useState(() => new Set());",
        'const [threadSelectionAnchorId, setThreadSelectionAnchorId] = useState("");',
        "const [bulkDeletingThreads, setBulkDeletingThreads] = useState(false);",
        "function selectThreadRange(targetThreadId)",
        "if (event && event.shiftKey) {",
        "selectThreadRange(sid);",
        "function toggleAllVisibleThreadsSelected()",
        "async function handleBulkDeleteThreads()",
        'window.confirm(t("confirm.delete_threads", { count: selectedIds.length }))',
        'await fetchJson(`/api/thread/${encodeURIComponent(sid)}`, { method: "DELETE" });',
        'className="thread-select-box"',
        'aria-checked=${itemSelected}',
        't("buttons.delete_selected_threads", { count: selectedThreadCount })',
    )
    for token in required_script_tokens:
        assert token in script, token

    for token in (
        ".thread-bulk-actions",
        ".thread-selection-summary",
        ".thread-row.selected",
        ".thread-select-box",
    ):
        assert token in styles, token

    for token in (
        '"buttons.select_all_threads": "全选"',
        '"buttons.delete_selected_threads": "删除 {count} 个"',
        '"confirm.delete_threads": "删除选中的 {count} 个线程？此操作不可恢复。"',
        '"threads.selected_count": "已选择 {count} 个线程"',
    ):
        assert token in locales, token

    assert 't("buttons.select_threads")' not in script
    assert "toggleThreadSelectionMode" not in script


def test_thread_rename_uses_modal_and_patch_endpoint() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'fetchJson(`/api/session/${encodeURIComponent(sid)}/title`' in script
    assert 'setRenameDialog({' in script
    assert 'id="renameThreadModal"' in script
    assert 't("buttons.rename_thread")' in script
    assert 't("thread_modal.rename_title")' in script
    assert '"buttons.rename_thread": "重命名线程"' in locales
    assert '"thread_modal.rename_title": "重命名线程"' in locales


def test_thread_context_menu_can_pin_and_unpin_persistently() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert "async function handleToggleThreadPinned()" in script
    assert 'method: "PATCH"' in script
    assert 'body: JSON.stringify({ pinned: nextPinned })' in script
    assert "sessionsRequestSeqRef.current += 1;" in script
    assert 't(threadMenu.pinned ? "buttons.unpin_thread" : "buttons.pin_thread")' in script
    assert 'item.pinned ? "pinned"' in script
    assert 'className="thread-pin-icon"' in script
    assert "const pinDelta = Number(Boolean(right && right.pinned))" in script
    assert '"buttons.pin_thread": "置顶线程"' in locales
    assert '"buttons.unpin_thread": "取消置顶"' in locales
    assert ".thread-pin-icon" in styles


def test_tasks_entry_queries_globally_and_confirms_before_loading_across_projects() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")
    load_handler = script.split("async function handleLoadTask(task)", 1)[1].split(
        "function openTaskEditor(task)",
        1,
    )[0]

    assert 'drawerView === "tasks"' in script
    assert 'showArchivedTasks ? "/api/tasks?include_archived=true" : "/api/tasks"' in script
    assert 't("tasks.show_archived")' in script
    assert '${["active", "blocked", "completed", "archived"].map' in script
    assert 'const taskProjectId = String(normalized.project_id || "").trim();' in load_handler
    assert 'const switchesProject = Boolean(taskProjectId && taskProjectId !== activeProjectId);' in load_handler
    assert 'window.confirm(t("confirm.switch_project_for_task", { title: taskTitle, project: projectTitle }))' in load_handler
    assert 'await selectProject(taskProjectId, { silentNotFound: false })' in load_handler
    assert "createSession(" not in load_handler
    assert "projectIdOverride: targetProjectId" in load_handler
    assert "sessionIdOverride: targetSessionId" in load_handler
    assert 'targetSessionId = String(activeSessionIdRef.current || "").trim();' in load_handler
    assert "const targetProjectId = String(options.projectIdOverride || projectId || \"\").trim();" in script
    assert "const targetSessionId = String(options.sessionIdOverride || sessionId || \"\").trim();" in script
    assert 'task_id: String(options.taskId || "").trim() || null' in script
    assert 'project_id: targetProjectId' in script
    assert 'handleSend(t("tasks.summarize_prompt"))' in script
    assert 't("tasks.project")' in script
    assert 'id="taskEditorModal"' in script
    assert 'fetchJson(`/api/tasks/${encodeURIComponent(taskId)}`' in script
    assert 'method: "PUT"' in script
    assert 'fetchJson(`/api/tasks/${encodeURIComponent(normalized.task_id)}`, { method: "DELETE" })' in script
    assert 'window.confirm(t("confirm.delete_task", { title }))' in script
    assert 't("buttons.edit_task")' in script
    assert '>Workbench</button>' not in script
    for token in (
        ".tasks-drawer",
        ".task-card",
        ".task-card-project",
        ".task-status",
        ".task-card-actions",
        ".tasks-archive-toggle",
        ".task-editor-modal",
        ".task-editor-grid",
    ):
        assert token in styles, token
    assert '"tasks.show_archived": "显示已归档"' in locales
    assert '"tasks.show_archived": "アーカイブ済みを表示"' in locales
    assert '"tasks.show_archived": "Show archived"' in locales
    assert '"confirm.switch_project_for_task": "Task“{title}”属于项目“{project}”。是否切换到该项目并加载？"' in locales


def test_runtime_control_center_uses_live_progress_without_task_state_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "renderRunStateDetail" not in script
    assert "const currentPlanStep = activePlan.find" in script
    assert "checkpoint: activeTaskCheckpoint" in script
    assert "runState.task_state" not in script
    assert "sessionRuntimeState.task_state" not in script
    runtime_drawer = script.split('${drawerView === "run"', 1)[1].split('${drawerView === "tools"', 1)[0]
    assert "completed_steps_count" not in runtime_drawer
    assert "progress_basis" not in runtime_drawer
    assert "evidence_refs" not in runtime_drawer


def test_debug_panel_does_not_render_removed_task_state_layers() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    debug_body = re.search(
        r"const renderActivityDebugDetails = \(message\) => \{(?P<body>.*?)\n  \};\n\n  const renderMessageActivity",
        script,
        re.S,
    )
    assert debug_body, "renderActivityDebugDetails helper not found"
    body = debug_body.group("body")
    assert "runArtifact.task_state" not in body
    assert 'renderDetailBlock("task_state"' not in body
    assert 'renderDetailBlock("task_state_delta"' not in body
    assert 'renderDetailBlock("task_state_validation"' not in body


def test_runtime_projection_does_not_restore_thread_replay_diagnostics() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "inspectorRuntimeState.thread_context" not in script
    assert "sent_to_model" not in script
    assert "runState.goal" in script
    assert "const currentPlanStep = activePlan.find" in script
    assert "activeTaskState.goal" not in script
    assert "activeWorkCursor.active_files" not in script
    assert "modelContextTask" not in script


def test_preview_progress_note_can_suppress_duplicate_live_summary() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"const renderActivityProgressList = \(projection, activity, options = \{\}\) => \{(?P<body>.*?)\n  \};\n\n  const renderActivityToolDetails",
        script,
        re.S,
    )
    assert match, "renderActivityProgressList function not found"
    body = match.group("body")

    assert 'const suppressNoteText = String(options.suppressNoteText || "").trim();' in body
    assert 'const suppressPreview = Boolean(options.suppressPreview) && preview;' in body
    assert 'const suppressCompletedPreview = Boolean(options.suppressCompletedPreview) && preview && normalizedStatus === "completed";' in body
    assert 'const liveSummaryText = suppressPreview || suppressCompletedPreview ? "" : formatLiveSummaryText(liveSummary);' in body
    assert 'const recentExecutionItems = (preview ? mainLiveCards : expandedProgressItems).slice(-MAIN_LIVE_CARD_LIMIT);' in body
    assert 'suppressPreview || isTerminal ? [] : recentExecutionItems' in body
    assert "const showLiveStatusPanel = Boolean(" in body
    assert "showPlanSummary && (visibleItems.length || showLiveStatusPanel)" in body
    assert 'className="activity-progress-divider" role="separator"' in body
    assert 'className="activity-live-status" role="status"' in body
    assert "runExecutionProgress.currentStep" in body
    assert "runExecutionProgress.currentTool" in body
    assert "runExecutionProgress.elapsed" in body
    assert '!suppressPreview && normalizedStatus === "completed" && !suppressCompletedPreview ? completionSummary.label : ""' in body
    assert '|| (suppressPreview ? "" : item.activity_summary)' in body
    assert 'const showNote = Boolean(note) && !(preview && suppressNoteText && note === suppressNoteText);' in body
    assert 'if (!visibleItems.length && !visiblePlanItems.length && !showNote && !showPlanSummary) return null;' in body
    assert '${showNote ? html`<div className="activity-flow-note">${note}</div>` : null}' in body


def test_collapsed_activity_preview_passes_summary_suppression_text() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"const renderMessageActivity = \(item\) => \{(?P<body>.*?)\n  \};\n\n  const messageBodyText",
        script,
        re.S,
    )
    assert match, "renderMessageActivity function not found"
    body = match.group("body")

    assert 'const pendingFallback = pendingAssistantFallbackState({ ...item, activity: displayActivity }, uiLocale, activityClockMs || Date.now());' in body
    assert "const hasVisibleAnswerContent = Boolean(String(" in body
    assert "displayActivity.model_draft" in body
    assert "(!item.pending ? item.text : \"\")" in body
    assert "suppressPreview: hasVisibleAnswerContent," in body
    assert 'suppressNoteText: pendingFallback.fromSummaryFallback ? (pendingFallback.suppressNoteText || pendingFallback.text) : "",' in body
    assert 'suppressCompletedPreview: Boolean(!item.pending && String(displayActivity.final_answer || item.text || "").trim()),' in body
    assert "entries.map((entry) => {" in script


def test_plan_and_live_execution_are_projected_as_separate_layers() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const planItems = buildPlanChecklistItems(projectionItem.plan);" in script
    assert "const executionItems = buildFallbackProgressItems(projectionItem, locale, nowMs);" in script
    assert "main_live_cards: mainLiveCards" in script
    assert "plan_items: planItems" in script
    assert "execution_items: executionItems" in script
    assert '${t("run.checklist")}' in script
    assert '${t("run.execution_progress")}' in script
    assert "const visiblePlanItems = preview" in script
    assert "planItems.slice(0, COMPACT_PLAN_ITEM_LIMIT)" in script
    assert 'translateUi(uiLocale, "run.plan_progress"' in script
    assert "const showPlanSummary = Boolean(planItems.length);" in script


def test_transport_heartbeat_does_not_replace_last_semantic_progress() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "connectionAt: 0" in script
    assert 'if (event === "heartbeat") {' in script
    assert "markOwnerConnectionHeartbeat(payload.ts || Date.now());" in script
    heartbeat_helper = re.search(
        r"const markOwnerConnectionHeartbeat = \(value\) => \{(?P<body>.*?)\n      \};",
        script,
        re.S,
    )
    assert heartbeat_helper, "transport heartbeat helper not found"
    assert "connectionAt" in heartbeat_helper.group("body")
    assert "lastLiveProgressAt" not in heartbeat_helper.group("body")


def test_execution_progress_shows_elapsed_last_progress_and_connection() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "lastProgressAgo:" in script
    assert "connectionState," in script
    assert "connectionLabel:" in script
    assert 'formatRunFieldLabel(uiLocale, "elapsed")' in script
    assert 'formatRunFieldLabel(uiLocale, "last_progress")' in script
    assert 'formatRunFieldLabel(uiLocale, "connection")' in script


def test_append_activity_trace_promotes_model_draft_and_runtime_error_from_trace_payload() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"function appendActivityTrace\(activity, trace, options = \{\}\) \{(?P<body>.*?)\n}\n\nfunction formatActivityDuration",
        script,
        re.S,
    )
    assert match, "appendActivityTrace function not found"
    body = match.group("body")

    assert "const payload = normalizedTrace.payload" in body
    assert 'model_draft: String(payload.model_draft || current.model_draft || ""),' in body
    assert 'final_answer: String(payload.final_answer || current.final_answer || ""),' in body
    assert 'normalizeRuntimeErrorPayload(payload.runtime_error)' in body
    assert 'normalizedTrace.type === "llm.failed"' in body
    assert "llm_exchanges: current.llm_exchanges," in body


def test_main_activity_projection_bounds_main_card_trace_work() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const MAIN_CARD_TRACE_EVENT_LIMIT = 50;" in script
    assert "item.trace_events.length > MAIN_CARD_TRACE_EVENT_LIMIT" in script
    assert "item.trace_events.slice(-MAIN_CARD_TRACE_EVENT_LIMIT)" in script
    assert "item.tool_items.slice(-RECENT_TOOL_TIMELINE_LIMIT)" in script
    assert "const expanded = Boolean(options.expanded);" in script
    assert "trace_events: item.trace_events," in script


def test_timer_visibility_checks_use_turn_level_start_timestamp() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "Boolean(activity.turn_started_at || activity.started_at) && !isActivityTerminalStatus(activity.status)" in script
    assert "activity.turn_started_at || activity.started_at || activity.run_duration_ms || activity.trace_events.length" in script
    assert "const hasStarted = Boolean(item.turn_started_at || item.started_at || traces.length);" in script


def test_composer_submit_ignores_enter_during_ime_composition() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function handleComposerKeyDown\(event\) \{(?P<body>.*?)\n  \}",
        script,
        re.S,
    )
    assert match, "handleComposerKeyDown not found"
    body = match.group("body")

    assert "event.isComposing" in body
    assert "event.nativeEvent" in body
    assert "keyCode === 229" in body
    assert "if (currentThreadBusy && !canQueueGuidance) return;" in body
    assert "handleSend();" in body


def test_composer_textarea_remains_editable_while_run_is_active() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    frame_match = re.search(
        r"<div className=\"composer-frame\">(?P<body>.*?)</div>\n          <div className=\"status-bar status-inline\"",
        script,
        re.S,
    )
    assert frame_match, "composer frame not found"
    body = frame_match.group("body")
    textarea_body = body.split("</textarea>", 1)[0]

    assert 'value=${draft}' in textarea_body
    assert "disabled=${sending}" not in textarea_body
    assert "disabled=${(currentThreadBusy && !canQueueGuidance) || !draft.trim() || pendingUploads.some((item) => item && item.uploading)}" in body
    assert '${canQueueGuidance ? t("buttons.queue_next")' in body


def test_running_composer_queues_enter_and_steers_shift_enter() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    keydown = script.split("function handleComposerKeyDown(event) {", 1)[1].split(
        "\n  const runtimeStatus",
        1,
    )[0]

    assert 'if (currentThreadBusy && event.key === "Enter") {' in keydown
    assert 'delivery: event.shiftKey ? "steer" : "queue"' in keydown
    assert keydown.index('if (currentThreadBusy && event.key === "Enter") {') < keydown.index(
        "if (slashCommandSuggestions.length) {"
    )
    assert 't("composer.followup_hint")' in script


def test_subagent_stream_items_render_as_collapsible_main_thread_cards() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'itemType === "subagent"' in script
    assert 'String(liveItem.type || "") === "subagent"' in script
    assert 'className=${`subagent-card ${queued ? "queued" : (running ? "running" : "completed")}`}' in script
    assert '<span>${queued ? t("subagent.queued") : (running ? t("subagent.running") : t("subagent.completed"))}</span>' in script
    assert 'open=${running}' in script
    assert 't(queued ? "subagent.waiting_slot" : "subagent.waiting_result")' in script
    assert ".subagent-card-list" in styles
    assert ".subagent-card > summary" in styles


def test_reloaded_subagent_cards_keep_persisted_work_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    normalize_block = script.split("function normalizeLiveRunItem(raw) {", 1)[1].split(
        "\n}\n\nfunction normalizeLiveRunItems",
        1,
    )[0]
    render_block = script.split("const subagentCards = displayActivity.live_items", 1)[1].split(
        "return html`",
        1,
    )[0]

    assert 'role: String(item.role || rawItem.role || "").trim()' in normalize_block
    assert 'task: String(item.task || rawItem.task || "").trim()' in normalize_block
    assert "summary: String(item.summary || rawItem.summary" in normalize_block
    assert "item.tool_count ?? item.toolCount ?? rawItem.tool_count" in normalize_block
    assert "raw: Object.keys(rawItem).length ? rawItem : item" in normalize_block
    assert 'String(liveItem.role || raw.role || "explorer")' in render_block
    assert "String(liveItem.label || liveItem.task || raw.label || raw.task" in render_block
    assert 'String(liveItem.summary || liveItem.detail || raw.summary || "")' in render_block


def test_frontend_eval_center_runs_background_jobs_from_header_modal() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'onClick=${openEvalDialog}' in script
    assert 'fetchJson("/api/evals/catalog")' in script
    assert 'fetchJson("/api/evals/runs", {' in script
    assert 'id="evalModal"' in script
    assert "evalButtonLabel" in script
    assert "completed_attempts" in script
    assert "selectedEvalSuite.requires_live !== false" in script
    assert "selectedEvalSuite.supports_repeat !== false" in script
    assert "selectedEvalRequiresLive && !evalForm.live" in script
    assert 't("eval.deterministic_hint")' in script


def test_frontend_steer_stays_near_composer_until_runtime_accepts_it() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    busy_branch = script.split(
        "if (currentThreadBusy && !isTurnResume && !fromQueuedTurn) {",
        1,
    )[1].split("const slashCommand", 1)[0]
    assert 'if (followupDelivery === "queue") {' in busy_branch
    assert "enqueueNextTurn(targetSessionId, targetProjectId, messageText);" in busy_branch
    assert "const queuedGuidance = {" in busy_branch
    assert "updateThreadPendingGuidance(steerOwnerThreadId, (prev) => [...prev, queuedGuidance]);" in busy_branch
    assert "setMessages(" not in busy_branch
    assert 'className="pending-guidance-strip"' in script
    assert 't("steer.pending_waiting")' in script
    assert 'event === "turn/segment/completed"' in script
    assert "completeCurrentAssistantSegment(segment)" in script
    assert 'event === "turn/steer/accepted"' in script
    assert 'const acceptedMessage = createMessage("user", String(steer.message || ""), {' in script
    assert 'if (steerBoundary === "after_tool") {' in script
    assert "return [...previous, acceptedMessage];" in script
    assert "pendingGuidance: (Array.isArray(prev.pendingGuidance) ? prev.pendingGuidance : [])" in script
    assert "setPendingGuidance(nextTurn.pendingGuidance);" in script
    assert 'beginNextAssistantSegment(String(payload.next_segment_id || ""))' in script
    assert "const nextQueuedIndex = next.findIndex" in script
    assert "next.splice(nextQueuedIndex, 0, nextPending)" in script
    assert "return previous.filter((message) => String(message.id || \"\") !== currentId)" in script
    assert "const carriedActivity = normalizeMessageActivity(latestActivity || {})" in script
    assert "runArtifact: {}" in script
    assert 'status: "waiting_model"' in script


def test_frontend_next_turn_queue_runs_in_order_after_active_turn_completes() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    handle_send = script.split(
        "async function handleSend(overrideText, userInputResponse) {",
        1,
    )[1].split("\n  async function loadSpecDetail", 1)[0]

    assert "const queuedNextTurnsRef = useRef(new Map());" in script
    assert "function enqueueNextTurn(threadId, targetProjectId, message)" in script
    assert "function takeNextQueuedTurn(threadId)" in script
    assert 'delivery: "next_turn"' in script
    assert "shouldStartNextQueuedTurn = Boolean(" in handle_send
    assert "const queuedTurn = takeNextQueuedTurn(runOwnerThreadId);" in handle_send
    assert "fromQueuedTurn: true" in handle_send
    assert "window.setTimeout(() => {" in handle_send
    assert 'filter((item) => String(item.delivery || "") === "next_turn")' in handle_send
    assert 't("queue.pending_waiting")' in script
    assert "removeQueuedTurn(sessionId, item.id)" in script


def test_frontend_renders_runtime_and_subagent_queue_lifecycle() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'event === "run_queued"' in script
    assert 'event === "run_dequeued"' in script
    assert 'status: "queued"' in script
    assert 'event === "item/started" || event === "item/updated"' in script
    assert 'id: "run-queued"' in script
    assert 'const runQueued = activityStatus === "queued"' in script
    assert '&& status !== "queued"' in script
    assert 'recentEvent = recentEvent || translateUi(locale, "run.live_agent.queued_waiting")' in script
    assert 'status === "queued" ? "subagent.queued"' in script
    assert 't(queued ? "subagent.waiting_slot" : "subagent.waiting_result")' in script
    assert ".subagent-card.queued" in styles
    assert ".activity-pill.tone-queued" in styles


def test_live_execution_card_renders_after_queued_guidance_before_acceptance() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "function messagesForLiveGuidanceDisplay(messages, liveAssistantMessageId)" in script
    assert '["steer_queued", "steer_accepted", "steer_rejected"].includes(steerStatus)' in script
    assert "const [liveAssistant] = list.splice(liveIndex, 1);" in script
    assert "list.splice(displayAfterIndex, 0, liveAssistant);" in script
    assert "const conversationMessages = messagesForLiveGuidanceDisplay(" in script
    assert "appendMessagesOnceById([], messages)," in script
    assert "? conversationMessages.map(" in script


def test_completed_steered_turn_reconciles_authoritative_thread_order_before_cleanup() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    handle_send_match = re.search(
        r"async function handleSend\(overrideText, userInputResponse\) \{(?P<body>.*?)\n  \}\n\n  async function loadSpecDetail",
        script,
        re.S,
    )
    assert handle_send_match, "handleSend function not found"
    body = handle_send_match.group("body")

    assert "function mergeAuthoritativeThreadMessages(authoritativeMessages, currentMessages, options = {})" in script
    assert "const optimisticMessageIds = new Set(" in script
    assert "const optimisticBoundaryIndex = rawCurrent.findIndex" in script
    assert "!optimisticMessageIds.has(String(item.id || \"\").trim())" in script
    assert "if (optimisticBoundaryIndex >= 0) {" in script
    assert ".slice(0, optimisticBoundaryIndex)" in script
    assert "return [...preservedPrefix, ...mergedTail];" in script
    assert "const reconcileCompletedThreadMessages = async (threadId) => {" in body
    assert "mergeAuthoritativeThreadMessages(authoritativeMessages, prev, {" in body
    assert "optimisticMessageIds: userMessage ? [String(userMessage.id || \"\")] : []" in body
    assert "client_message_id: String((userMessage && userMessage.id) || \"\")," in body
    reconcile_call = "await reconcileCompletedThreadMessages(latestThreadId || runOwnerThreadId)"
    assert reconcile_call in body
    assert body.index(reconcile_call) < body.index("await cleanupRunUi();")
    assert "messagesForLiveGuidanceDisplay(prev, String((pendingMessage && pendingMessage.id) || \"\"))" in body


def test_thread_runs_use_thread_scoped_busy_state() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    handle_send_match = re.search(
        r"async function handleSend\(overrideText, userInputResponse\) \{(?P<body>.*?)\n  \}\n\n  async function loadSpecDetail",
        script,
        re.S,
    )
    assert handle_send_match, "handleSend function not found"
    body = handle_send_match.group("body")

    assert 'const sendingSource = has("sending")' in script
    assert 'const activeRunIdSource = has("activeRunId") ? item.activeRunId : item.active_run_id;' in script
    assert 'const activeRunThreadIdSource = has("activeRunThreadId") ? item.activeRunThreadId : item.active_run_thread_id;' in script
    assert "sending: Boolean(sendingSource)" in script
    assert "activeRunId: String(activeRunIdSource || \"\")" in script
    assert "function isThreadSnapshotBusy(threadId, snapshot)" in script
    assert "const activeSendThreadIdsRef = useRef(new Set());" in script
    assert "const currentThreadBusy = isThreadSnapshotBusy(sessionId" in script
    assert "const anyThreadBusy = (() => {" in script
    assert "if (!messageText) return;" in body
    assert "if (currentThreadBusy && !isTurnResume && !fromQueuedTurn) {" in body
    assert 'fetchJson(`/api/chat/runs/${encodeURIComponent(String(activeRunId || ""))}/steer`' in body
    assert "if (ownerBusy && !isTurnResume && !fromQueuedTurn) return;" in body
    assert "if (activeSendThreadIdsRef.current.has(runOwnerThreadId)) {" in body
    assert 'throw new Error(t("errors.pending_turn_resume_timeout"));' in body
    lock_check = body.split("if (ownerBusy && !isTurnResume && !fromQueuedTurn) return;", 1)[1].split("activeSendThreadIdsRef.current.add(runOwnerThreadId);", 1)[0]
    assert "activeSendThreadIdsRef.current.delete" not in lock_check
    assert "appendMessagesOnceById(" in body
    assert body.index("let uiFinalized = false;") < body.index("try {\n      if (isTempThreadId(sid)")
    assert body.count("let uiFinalized = false;") == 1
    assert "setSending(false);" not in body.split("const cleanupRunUi = async () => {", 1)[0]
    assert "disabled=${creatingThread || sending}" not in script


def test_optimistic_thread_messages_are_idempotent_by_message_id() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "function appendMessagesOnceById(previousMessages, incomingMessages)" in script
    helper_body = script.split(
        "function appendMessagesOnceById(previousMessages, incomingMessages)",
        1,
    )[1].split("\n}\n", 1)[0]
    assert "if (messageId && knownIds.has(messageId)) return;" in helper_body
    assert "knownIds.add(messageId);" in helper_body
    assert "messages: appendMessagesOnceById(" in script
    assert "? appendMessagesOnceById(prev, [userMessage, pendingMessage].filter(Boolean))" in script
    assert "appendMessagesOnceById([], messages)," in script


def test_assistant_stream_deltas_are_batched_before_react_updates() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const STREAM_UI_FLUSH_INTERVAL_MS = 250;" in script
    assert 'let assistantDeltaBuffer = "";' in script
    assert "const flushAssistantDelta = () => {" in script
    assert 'const queueAssistantDelta = (delta, itemId = "") => {' in script
    assert "STREAM_UI_FLUSH_INTERVAL_MS," in script
    delta_branch = script.split('event === "item/agentMessage/delta"', 1)[1].split(
        'event === "item/completed"',
        1,
    )[0]
    assert "queueAssistantDelta(delta" in delta_branch
    assert "updateOwnerActiveTurn" not in delta_branch
    assert "replacePendingText" not in delta_branch
    assert "patchPendingActivity" not in delta_branch
    assert "recentEvent: assistantText" not in script
    assert 'event === "run_failed"' in script
    run_failed_branch = script.split('event === "run_failed"', 1)[1].split(
        'event === "trace_event"',
        1,
    )[0]
    assert "flushAssistantDelta();" in run_failed_branch


def test_thread_run_indicators_show_running_and_completed_attention() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    handle_send_match = re.search(
        r"async function handleSend\(overrideText, userInputResponse\) \{(?P<body>.*?)\n  \}\n\n  async function loadSpecDetail",
        script,
        re.S,
    )
    assert handle_send_match, "handleSend function not found"
    body = handle_send_match.group("body")
    cleanup_body = body.split("const cleanupRunUi = async () => {", 1)[1].split("      const collapseLiveRunUi = () => {", 1)[0]
    thread_click_body = re.search(
        r"function handleThreadClick\(event, targetSessionId\) \{(?P<body>.*?)\n  \}\n\n  function openRenameThreadDialog",
        script,
        re.S,
    )
    assert thread_click_body, "handleThreadClick function not found"

    assert "const [threadRunIndicators, setThreadRunIndicators] = useState({});" in script
    assert "function markThreadRunIndicator(targetThreadId, status)" in script
    assert "function clearThreadRunIndicator(targetThreadId)" in script
    assert "function finishThreadRunIndicator(targetThreadId)" in script
    assert "function threadRunIndicatorStatus(targetThreadId)" in script
    assert 'markThreadRunIndicator(runOwnerThreadId, "running");' in body
    assert "finishThreadRunIndicator(runOwnerThreadId);" in cleanup_body
    assert "finishThreadRunIndicator(lockedRunOwnerThreadId);" in body
    assert 'markThreadRunIndicator(key, "");' in script
    assert 'markThreadRunIndicator(key, "completed_unread");' in script
    assert 'String(serverRow.status || "") === "active"' in script
    assert "document.hasFocus()" in script
    assert "clearThreadRunIndicator(sid);" in thread_click_body.group("body")
    assert "const indicatorStatus = threadRunIndicatorStatus(itemId);" in script
    assert "thread-run-indicator status-${indicatorStatus}" in script
    assert "indicator-${indicatorStatus}" in script
    assert 'indicatorStatus === "completed_unread" ? "1" : ""' in script
    assert "navigator.setAppBadge(unreadThreadCompletionCount)" in script
    assert "navigator.clearAppBadge()" in script
    assert "const activeThreadPollingKey = sessions" in script
    assert "const pollActiveThreads = async () => {" in script
    assert "refreshSessions(projectId, { background: true })" in script
    assert "activeSendThreadIdsRef.current.has(threadId)" in script
    assert "silentLog: true" in script

    for token in (
        ".thread-run-indicator",
        ".thread-run-indicator.status-running",
        ".thread-run-indicator.status-completed_unread",
        "conic-gradient(from -35deg",
        "-webkit-mask: radial-gradient",
    ):
        assert token in styles, token
    assert "@keyframes thread-run-indicator-spin" not in styles
    assert "animation: thread-run-indicator-spin" not in styles


def test_thread_rows_use_monotonic_activity_ordering_and_reject_stale_refreshes() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    upsert_match = re.search(
        r"function upsertThreadRow\(rawItem, options = \{\}\) \{(?P<body>.*?)\n  \}\n\n  function removeThreadRow",
        script,
        re.S,
    )
    assert upsert_match, "upsertThreadRow function not found"
    body = upsert_match.group("body")

    assert "const existingIndex = previousList.findIndex" in body
    assert "const merged = mergeThreadRow(existing, candidate);" in body
    assert "return sortThreadRows([merged, ...remainder]);" in body
    assert "function compareThreadFreshness(incoming, existing)" in script
    assert "if (nextRevision !== currentRevision)" in script
    assert "if (Object.keys(current).length && compareThreadFreshness(next, current) < 0)" in script
    assert "setSessions((prev) => mergeAuthoritativeThreadRows(list, prev));" in script
    assert 'if (payload.thread) upsertThreadRow(payload.thread);' in script
    assert 'if (event === "heartbeat") {' in script
    assert "Transport liveness is deliberately separate from semantic" in script


def test_completed_thread_runs_release_busy_state() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    handle_send_match = re.search(
        r"async function handleSend\(overrideText, userInputResponse\) \{(?P<body>.*?)\n  \}\n\n  async function loadSpecDetail",
        script,
        re.S,
    )
    assert handle_send_match, "handleSend function not found"
    body = handle_send_match.group("body")

    live_messages_match = re.search(
        r"function hasLiveThreadMessages\(messages\) \{(?P<body>.*?)\n}\n\nfunction isThreadActiveTurnLive",
        script,
        re.S,
    )
    assert live_messages_match, "hasLiveThreadMessages function not found"
    live_messages_body = live_messages_match.group("body")
    assert "if (message.pending) return !isActivityTerminalStatus(activity.status);" in live_messages_body
    assert "function hasBusyThreadMessages(messages)" in script
    assert "if (!message || typeof message !== \"object\" || !message.pending) return false;" in script
    assert "|| hasBusyThreadMessages(item.messages)" in script
    active_turn_busy_match = re.search(
        r"function isThreadActiveTurnBusy\(threadId, activeTurn\) \{(?P<body>.*?)\n}\n\nfunction isThreadSnapshotBusy",
        script,
        re.S,
    )
    assert active_turn_busy_match, "isThreadActiveTurnBusy function not found"
    active_turn_busy_body = active_turn_busy_match.group("body")
    assert "if (turn.sending) return true;" in active_turn_busy_body
    assert "return Boolean(String(turn.activeRunId || \"\").trim());" in active_turn_busy_body
    assert "isThreadActiveTurnLive" not in active_turn_busy_body

    terminal_status_match = re.search(
        r"function isActivityTerminalStatus\(status\) \{(?P<body>.*?)\n}\n\nfunction normalizeTurnChanges",
        script,
        re.S,
    )
    assert terminal_status_match, "isActivityTerminalStatus function not found"
    assert "const normalized = normalizeProgressStatus(status);" in terminal_status_match.group("body")

    assert "const finalActivitySourceStatus = normalizeProgressStatus(" in body
    assert "const finalActivityStatus = isActivityTerminalStatus(finalActivitySourceStatus)" in body
    assert "status: finalActivityStatus," in body
    assert "finished_at: Date.now()," in body
    cleanup_body = body.split("const cleanupRunUi = async () => {", 1)[1].split("      const collapseLiveRunUi = () => {", 1)[0]
    assert "window.requestAnimationFrame" not in cleanup_body
    assert "activeSendThreadIdsRef.current.delete(runOwnerThreadId);" in cleanup_body
    assert "sending: false," in cleanup_body
    assert "activeRunThreadId: \"\"," in cleanup_body


def test_activity_debug_drawer_contains_thread_history_trace_and_system_prompt() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "triggering_user_message" in script
    assert 'renderDetailBlock(t("activity.triggering_user_message"), item.triggering_user_message)' not in script
    assert 'renderDetailBlock(t("activity.current_turn_goal"), item.current_turn_goal)' not in script
    assert "structured.sent_to_model" not in script
    assert 't("activity.debug.thread_history")' in script
    assert 't("activity.debug.view_trace")' in script
    assert 't("activity.debug.view_system_prompt")' in script
    assert "const systemPromptGroupsByText = new Map();" in script
    assert "systemPromptGroupsByText.get(groupKey).contexts.push(normalizedContext);" in script
    assert 't("activity.debug.base_system_prompt")' in script
    assert 't("activity.debug.context_variants")' in script
    assert "context.supporting_messages.length" in script
    assert "context.tool_names.length" in script
    assert 'renderDetailBlock(t("activity.debug.supporting_messages"), context.supporting_messages)' in script
    assert 'renderDetailBlock(t("activity.debug.available_tools"), context.tool_names)' in script
    assert 'className="system-prompt-variants"' in script
    assert ".system-prompt-variants" in STYLES_CSS_PATH.read_text(encoding="utf-8")
    assert "${threadHistory}" in script
    assert "${systemPrompt}" in script
    debug_block = script.split("const renderActivityDebugDetails", 1)[1].split("const renderMessageActivity", 1)[0]
    assert "const rawTraceList = chatSettings.debug_raw" not in debug_block
    assert "phase_timings: item.phase_timings || {}" not in script


def test_activity_tool_target_surfaces_skill_name_instead_of_long_absolute_path() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "function skillTargetFromPath(value)" in script
    assert ".replace(/\\\\/g, \"/\")" in script
    assert r"skills\/(?:builtin|team)\/([^/]+)\/SKILL\.md" in script
    assert "if (skillTarget) return shortenActivityTarget(skillTarget, 96);" in script


def test_update_button_checks_hourly_but_only_updates_on_click() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'fetchJson("/api/app/update", { method: "POST" })' in script
    assert 'onClick=${handleAppUpdate}' in script
    assert 'appUpdateRunning ? t("update.running") : t("update.button")' in script
    assert 'fetchJson("/api/app/update-check")' in script
    assert "const APP_UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1_000;" in script
    assert "const APP_UPDATE_INITIAL_DELAY_MS = 30 * 1_000;" in script
    assert "window.setTimeout(() => {" in script
    assert "}, APP_UPDATE_INITIAL_DELAY_MS);" in script
    assert "if (bootState.active) return undefined;" in script
    assert "window.setInterval(() => runUpdateCheck(true), APP_UPDATE_CHECK_INTERVAL_MS)" in script
    assert 't("update.available_title", {' in script
    assert '})} ${t("update.discards_local_changes")}`' in script
    assert 'className="app-update-badge"' in script
    assert 'className=${`rail-update-result status-${appUpdateState.status}`}' in script
    assert 'setInterval' in script
    assert 'fetchJson("/api/app/update", { method: "POST" })' not in script.split("function handleAppUpdate", 1)[0]
    assert "autoUpdate" not in script
    assert '"update.available": "有更新"' in locales
    assert '"update.available_title": "{branch} 有 {count} 个新提交可更新。"' in locales
    assert ".app-update-btn.has-update" in styles
    assert ".app-update-badge" in styles
    assert ".rail-update-result" in styles
    assert ".rail-update-details" in styles
    assert "if (data && data.ok && IS_CHROME_DESKTOP_APP) {" in script
    assert 'id="appRestartPromptModal"' in script
    assert 'fetchJson("/api/desktop/restart"' in script
    assert '"X-VP-Desktop-Token": DESKTOP_CONTROL_TOKEN' in script
    assert "nextProcessId !== previousProcessId" in script
    assert "window.location.reload();" in script
    assert 'className="app-boot-screen app-boot-screen-overlay app-restart-screen"' in script
    assert 'aria-label=${t("update.restarting_message")}' in script
    assert "onClick=${closeAppRestartPrompt}" in script
    assert "onClick=${handleAppRestart}" in script
    assert '"update.restart_required_title": "需要重启 VP"' in locales
    assert '"update.restart_now": "立即重启 VP"' in locales
    assert '"update.restarting_message": "VP 正在重启。新后台准备好后，页面会自动刷新。"' in locales
    assert ".app-restart-modal" in styles
    assert ".app-restart-message" in styles


def test_add_project_dialog_can_open_the_system_folder_picker() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'fetchJson("/api/system/folder-picker", {' in script
    assert 'body: JSON.stringify({ initial_path: String(projectPathDraft || "").trim() })' in script
    assert "setProjectPathDraft(String(data.path || \"\"));" in script
    assert "if (data && data.cancelled) return;" in script
    assert 'onClick=${chooseProjectFolder}' in script
    assert 't("project_modal.browsing") : t("project_modal.browse")' in script
    assert '"project_modal.browse": "选择文件夹"' in locales
    assert '"project_modal.hint": "可以手动输入绝对路径，也可以使用系统文件夹选择器。"' in locales
    assert ".project-path-picker-row" in styles
    assert ".project-folder-picker-btn" in styles


def test_project_sidebar_height_is_resizable_and_persisted() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'const PROJECT_LIST_HEIGHT_STORAGE_KEY = "vintage_programmer.project_list_height";' in script
    assert "useState(readStoredProjectListHeight)" in script
    assert "onPointerDown=${startProjectListResize}" in script
    assert "onKeyDown=${handleProjectListResizeKeyDown}" in script
    assert "window.localStorage.setItem(PROJECT_LIST_HEIGHT_STORAGE_KEY" in script
    assert 'role="separator"' in script
    assert '"projects.resize_handle": "拖动以调整 Project 列表高度；双击恢复默认高度"' in locales
    assert ".project-thread-resizer" in styles
    assert "cursor: row-resize" in styles
    rail_brand = styles.split(".rail-brand {", 1)[1].split("}", 1)[0]
    workspace_head = styles.split(".workspace-head {", 1)[1].split("}", 1)[0]
    assert ".project-thread-resizer::before" not in styles
    assert "flex: 0 0 64px;" in rail_brand
    assert "height: 64px;" in rail_brand
    assert "height: 64px;" in workspace_head


def test_activity_debug_drawer_does_not_surface_phase_timings_as_normal_section() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    debug_block = script.split("const renderActivityDebugDetails", 1)[1].split("const renderMessageActivity", 1)[0]
    assert "phase_timings" not in debug_block
    assert "renderPhaseTimingDetails(" not in debug_block


def test_handle_send_includes_client_submission_timestamp() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const clientSubmittedAtMs = Date.now();" in script
    assert "client_submitted_at_ms: clientSubmittedAtMs," in script


def test_project_profile_binding_is_explicit_after_add_and_from_context_menu() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'fetchJson("/api/project-profiles")' in script
    assert "await openProjectProfileDialog(payload, { afterCreate: true });" in script
    assert 'method: "PUT"' in script
    assert 'body: JSON.stringify({ profile_key: String(projectProfileDraft || "") })' in script
    assert 't("buttons.bind_project_profile")' in script
    assert 't("buttons.change_project_profile")' in script
    assert '<option value="">${t("project_profile.none")}</option>' in script


def test_llm_started_promotes_pending_message_to_model_waiting() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'if (normalized === "llm.started") return "waiting_model";' in script
    assert "let modelRequestStarted = false;" in script
    assert "modelRequestStarted = true;" in script
    assert 'replacePendingText(t("activity.status.waiting_model"), { onlyWhileWaiting: true });' in script
    assert "skipAfterModelStarted" in script
    assert '"activity.status.waiting_model": "模型正在分析"' in locales


def test_run_progress_waits_for_llm_started_before_model_copy() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'const modelStarted = hasTraceType(traces, ["llm.started", "answer.started", "answer.delta"]) || String(heartbeat.source || "") === "model";' in script
    assert 'if (status === "waiting_model" && !modelStarted && !toolName && String(heartbeat.source || "") !== "tool") {' in script
    assert 'status = "background_running";' in script
    assert 'currentAction = translateUi(locale, "activity.status.preparing_request");' in script
    assert 'recentEvent = translateUi(locale, "run.live_agent.preparing");' in script
    assert 'currentAction = translateUi(locale, "activity.status.waiting_model");' in script
    assert 'const modelName = String(heartbeat.model || liveModelNameFromActivity(activity) || "").trim();' in script
    assert 'translateUi(locale, "run.live_agent.model_detail", { detail: modelName })' in script
    assert 'detail: item.detail || "",' in script


def test_retained_turn_changes_are_visible_without_opening_developer_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "function normalizeTurnChanges(raw)" in script
    assert "function renderTurnChangesSummary(activity, locale)" in script
    message_activity = script.split("const renderMessageActivity = (item) => {", 1)[1].split("const renderSteerStatus", 1)[0]
    before_open_panel = message_activity.split("${isOpen\n          ? html`", 1)[0]
    assert "${renderTurnChangesSummary(displayActivity, uiLocale)}" in before_open_panel
    assert ".turn-changes-summary.is-retained" in styles
    assert '"activity.changes.retained": "更改仍然保留"' in locales
    assert '"activity.changes.view": "View changes"' in locales


def test_loading_run_details_preserves_summary_turn_changes_when_detail_omits_them() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    detail_loader = script.split("async function ensureRunDetail", 1)[1].split(
        "const ensureRunActivity", 1
    )[0]

    assert "const rawLoadedActivity =" in detail_loader
    assert 'Object.prototype.hasOwnProperty.call(rawLoadedActivity, "turn_changes")' in detail_loader
    assert "delete loadedActivityPatch.turn_changes;" in detail_loader
    assert "...loadedActivityPatch," in detail_loader


def test_cancelled_stream_waits_for_authoritative_terminal_ack_before_releasing_turn() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert '"interrupted"].includes(normalized)' in script
    assert "async function waitForChatRunTerminal(runId, timeoutMs = 30000)" in script
    assert "terminalRecord = await waitForChatRunTerminal(runIdForAck);" in script
    assert 'const interrupted = String((terminalRecord && terminalRecord.status) || "") === "interrupted";' in script
    assert "shouldStartNextQueuedTurn = true;" in script
