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
    "settings.model_name",
    "settings.response_style",
    "buttons.save",
    "buttons.deleting",
    "buttons.select_all_threads",
    "buttons.clear_thread_selection",
    "buttons.delete_selected_threads",
    "tabs.settings",
    "activity.title",
    "activity.running",
    "activity.failed",
    "activity.blocked",
    "activity.cancelled",
    "activity.raw_arguments",
    "activity.arguments_preview",
    "activity.preview_error",
    "activity.schema_validation",
    "activity.result_preview",
    "activity.stream_diagnostics",
    "activity.progress_title",
    "activity.execution_summary_counts",
    "activity.more_steps",
    "activity.debug_details",
    "activity.raw_events",
    "activity.debug.user_context",
    "activity.debug.model_rounds",
    "activity.debug.round_n",
    "activity.debug.tools",
    "activity.debug.harness",
    "activity.debug.final_status",
    "activity.debug.legacy_details",
    "activity.debug.raw_json",
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
    "context_meter.field.token_usage",
    "context_meter.field.guard_long_task",
    "context_meter.field.guard_progress_signal",
    "context_meter.field.guard_same_action",
    "context_meter.field.guard_replan",
    "context_meter.field.guard_tool_output",
    "context_meter.field.guard_emergency_tool_calls",
    "context_meter.field.guard_same_tool",
    "context_meter.field.guard_no_progress",
    "context_meter.field.guard_rejections",
    "context_meter.field.guard_wall_clock",
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

    assert f'/static/app.js?v={app_version}' in index
    assert f'/static/locales.js?v={app_version}' in index
    assert f'/static/styles.css?v={app_version}' in index
    assert 'src="/static/app.js"' not in index
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
        "function buildStructuredDebugView(",
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

    required_style_tokens = (
        ".activity-progress",
        ".activity-progress-item",
        ".activity-debug-drawer",
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
        'summary>${t("activity.debug.advanced_raw")}</summary>',
        'summary>${t("activity.debug.tool_execution")}</summary>',
        't("activity.debug.raw_json")',
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


def test_structured_debug_view_groups_runtime_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "function buildStructuredDebugView(activity, inspector = {}, locale = \"zh-CN\")",
        "user_context",
        "model_rounds",
        "tool_groups",
        "tool_boundary_clean",
        "retry_happened",
        "final_status",
        "raw: {",
        'summary>${t("activity.debug.model_rounds")}</summary>',
        'renderDetailBlock(t("activity.debug.runtime")',
        'summary>${t("activity.debug.model_output")}</summary>',
        'summary>${t("activity.debug.tool_execution")}</summary>',
        'summary>${t("activity.debug.advanced_raw")}</summary>',
    )
    for token in required_tokens:
        assert token in script, token

    debug_block = script.split("const renderActivityDebugDetails", 1)[1].split("const renderMessageActivity", 1)[0]
    assert "phaseTimingDetails" not in debug_block


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
    assert '"settings.permission_profile.full_access.help": "更大范围读写，可执行安全命令，网络开启；执行网络来源代码需要单次确认。请在信任任务时使用。"' in locales
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


def test_command_execution_approval_modal_and_payload_are_wired() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'String(candidate.type || "") !== "command_execution"' in script
    assert 'id="commandApprovalModal"' in script
    assert 'handleCommandApproval("approve_once")' in script
    assert 'handleCommandApproval("cancel")' in script
    assert 'user_input_response: structuredUserInputResponse' in script
    assert 'type: "command_execution"' in script
    assert 'action: normalizedAction' in script
    assert 'approval_token: approvalToken' in script
    assert 'event === "request_user_input"' in script
    assert 'pending_approval: nextApproval' in script
    assert "function clearCommandExecutionApprovalState" in script
    assert "function clearCommandExecutionApprovalResponse" in script
    assert "clearVisibleCommandApprovalState();" in script
    assert '"approval_modal.title": "确认命令执行"' in locales
    assert '"approval_modal.approve_once": "批准一次"' in locales
    assert '"approval_modal.default_cancel": "默认操作是取消。批准后命令会在本机 host 环境实际执行，不是沙箱；批准只对这一个精确命令生效一次。"' in locales


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
    assert "const shouldTickActivityClock = (" in script
    assert "|| Boolean(activeRunStartedAt)" in script
    assert "|| Boolean(Object.keys(liveTurnState || {}).length)" in script
    assert "window.setInterval(() => setActivityClockMs(Date.now()), 1000)" in script
    assert "formatElapsedFromStartedAt(activeRunStartedAt, activityClockMs || Date.now())" in script
    assert "setActiveRunStartedAt(clientSubmittedAtMs);" in script
    assert "startedAt: clientSubmittedAtMs," in script
    assert "const liveAssistantMessageId = hasLiveRuntimeState" in script

    assert 'onMouseLeave=${() => setContextMeterOpen(false)}' not in script


def test_run_execution_progress_panel_is_split_from_plan_checklist() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        "function buildRunExecutionProgress({",
        "function latestAssistantMessage(messages, options = {})",
        "function currentChecklistStepLabel(plan, checkpoint = {})",
        "function executionProgressCommandFromSource(source)",
        "function formatRunProgressStatus(locale, status)",
        "const hasPlanMode = Boolean(activePlan.length || hasTaskCheckpoint);",
        'className="panel-card run-progress-card"',
        'formatRunFieldLabel(uiLocale, "current_tool")',
        'formatRunFieldLabel(uiLocale, "current_action")',
        'formatRunFieldLabel(uiLocale, "current_state")',
        'formatRunFieldLabel(uiLocale, "recent_event")',
        'formatRunFieldLabel(uiLocale, "command")',
        "runExecutionProgress.statusLabel",
        "${hasPlanMode",
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
    )
    for token in required_style_tokens:
        assert token in styles, token

    required_locale_tokens = (
        '"run.execution_progress": "执行进展"',
        '"run.field.current_tool": "当前工具"',
        '"run.field.current_action": "当前动作"',
        '"run.field.current_state": "当前状态"',
        '"run.field.command": "命令"',
        '"run.field.recent_event": "最近事件"',
        '"run.progress.status.waiting_model": "等待模型下一步"',
        '"run.progress.status.waiting_tool": "等待工具结果"',
        '"run.progress.status.background_running": "后台仍在运行"',
    )
    for token in required_locale_tokens:
        assert token in locales, token


def test_live_run_snapshot_persists_owner_thread_and_started_at() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "activeRunThreadId: runOwnerThreadId,",
        "startedAt: clientSubmittedAtMs,",
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


def test_context_turns_help_text_is_wired_into_frontend() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert 'className="field-hint"' in script
    assert 't("settings.context_turns.help")' in script
    assert '"settings.context_turns.help": "本次请求构建模型上下文时，最多纳入的历史对话轮数；不是当前 thread 的总轮数。"' in locales
    assert '"settings.context_turns.help": "今回のモデル文脈に含める履歴ターン数の上限です。スレッド全体の総ターン数ではありません。"' in locales
    assert '"settings.context_turns.help": "Maximum historical turns considered for the current model context, not the total thread turn count."' in locales


def test_settings_theme_color_selector_drives_accent_variables() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    required_script_tokens = (
        'const THEME_COLOR_STORAGE_KEY = "vintage_programmer.theme_color";',
        "const THEME_COLOR_OPTIONS = [",
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


def test_internal_design_manual_title_and_polish_notes_are_current() -> None:
    manual = INTERNAL_MANUAL_PATH.read_text(encoding="utf-8")

    assert manual.startswith("# 内部设计手册（v3.0.0）")
    assert "## 16. v2.9.2 Tool UX Polish Notes" in manual
    assert "## 17. v2.9.3 Allowlist and Serialization Compatibility Notes" in manual
    assert "## 18. v2.9.4 Runtime Status Performance Cleanup Notes" in manual
    assert "## 19. v2.9.5 Safe Serialization Fix Notes" in manual
    assert "## 20. v2.9.6 Model-led Action Runtime Notes" in manual
    assert "## 20.1 v2.9.7 Model-led Runtime Cleanup Notes" in manual
    assert "## 20.2 v2.9.8 ContextPack and Compaction Cleanup Notes" in manual
    assert "## 20.3 v2.9.9 Minimal ContextPack and TurnMemory Notes" in manual
    assert "## 20.4 v2.9.10 All-Tool Drain Fix Notes" in manual
    assert "## 20.5 v2.9.11 Path Portability and Search Safety Notes" in manual
    assert "## 20.6 v2.9.12 Live Timeline and LLM Diagnostics Notes" in manual
    assert "## 20.7 v2.9.13 Workspace and Permission Profiles Notes" in manual
    assert "## 20.8 v2.9.14 ModelContext-first Context System Notes" in manual
    assert "## 20.9 v2.9.15 Main Card and Debug Cleanup Notes" in manual
    assert "## 20.10 v2.9.16 UI Card Hotfix and Permission Profile Relocation Notes" in manual
    assert "## 20.11 v2.9.17 Permission Selector UI Polish Notes" in manual
    assert "## 20.12 v2.9.19 Hard Cleanup and Manual Update Notes" in manual
    assert "## 20.13 v2.9.20 Permission Mode Notes" in manual
    assert "## 20.14 v3.0.0 ModelContext Minimal Core Refactor Notes" in manual
    assert "## 25. Context Turns" in manual
    assert "## 26. Python Command Handling" in manual
    assert "## 27. Python Version Recommendation" in manual
    assert "## 28. Shell Command Allowlist" in manual
    assert "## 29. Workspace and Permission Profiles" in manual


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
    assert "turn_started_at: clientSubmittedAtMs," in script

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
        r'else if \(event === "turn/completed"\) \{(?P<body>.*?)\n            \} else if \(event === "item/started"\)',
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
        r'else if \(event === "turn/completed"\) \{(?P<body>.*?)\n            \} else if \(event === "item/started"\)',
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
    assert "activeRunThreadId: \"\",\n        startedAt: 0,\n        lastLiveProgressAt: 0," in body
    assert "liveHeartbeat: createEmptyLiveHeartbeat(),\n        stoppingRun: false," in body
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


def test_agent_message_completion_clears_streaming_model_draft() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "status: \"completed\",\n                  final_answer: assistantText,\n                  model_draft: \"\"," in script
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
    assert 'status: "completed"' in item_completed_body
    assert 'updateOwnerLiveHeartbeat({' not in item_completed_body
    assert "if (assistantText) collapseLiveRunUi();" in item_completed_body
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


def test_activity_debug_full_turn_loading_is_explicitly_lazy() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"async function ensureFullTurnActivity\(messageId\) \{(?P<body>.*?)\n  \}",
        script,
        re.S,
    )
    assert match, "ensureFullTurnActivity function not found"
    body = match.group("body")

    assert "currentActivity.full_loaded" in body
    assert "currentActivity.tool_items.length" not in body
    assert "currentActivity.live_items.length" not in body
    assert "currentActivity.llm_exchanges.length" not in body
    assert "currentActivity.trace_events.length" not in body
    assert "?view=full" in body
    assert "full_loaded: true" in body
    assert "?view=summary&max_turns=" in script
    assert 'const fullActivity = normalizeMessageActivity({ ...((payload && payload.activity) || {}), full_loaded: true });' in body


def test_full_turn_loading_merges_message_scoped_debug_payloads() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    ensure_body = re.search(
        r"async function ensureFullTurnActivity\(messageId\) \{(?P<body>.*?)\n  \}",
        script,
        re.S,
    )
    assert ensure_body, "ensureFullTurnActivity function not found"
    body = ensure_body.group("body")

    assert "answerBundle:" in body
    assert "runArtifact:" in body
    assert "fullTurnLoading: true" in body
    assert "fullTurnLoading: false" in body
    assert "fullTurnError" in body
    assert "if (currentMessage.pending) return;" in body
    assert "updateThreadSnapshot(sid" in body

    debug_body = re.search(
        r"const renderActivityDebugDetails = \(message, projection\) => \{(?P<body>.*?)\n  \};\n\n  const renderMessageActivity",
        script,
        re.S,
    )
    assert debug_body, "renderActivityDebugDetails helper not found"
    debug = debug_body.group("body")
    assert "const runArtifact = message && message.runArtifact" in debug
    assert "const answerBundle = message && message.answerBundle" in debug
    assert "const inspector = runArtifact.inspector" in debug
    assert "buildStructuredDebugView(item, inspector, uiLocale)" in debug
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


def test_run_panel_surfaces_task_state_validation_and_evidence_details() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert "renderRunStateDetail" in script
    assert "completed_steps: Array.isArray(activeTaskState.completed_steps)" in script
    assert "failed_attempts: Array.isArray(activeTaskState.failed_attempts)" in script
    assert "completed_steps_count" in script
    assert "failed_attempts_count" in script
    assert "validation_warnings" in script
    assert "progress_basis" in script
    assert "evidence_refs" in script
    assert 'renderRunStateDetail(formatRunFieldLabel(uiLocale, "completed_steps"), activeTaskCheckpoint.completed_steps)' in script
    assert 'renderRunStateDetail(formatRunFieldLabel(uiLocale, "failed_attempts"), activeTaskCheckpoint.failed_attempts)' in script
    assert 'renderRunStateDetail(formatRunFieldLabel(uiLocale, "validation_warnings"), activeTaskCheckpoint.validation_warnings)' in script
    assert 'renderRunStateDetail(formatRunFieldLabel(uiLocale, "progress_basis"), activeTaskCheckpoint.progress_basis)' in script
    assert 'renderRunStateDetail(formatRunFieldLabel(uiLocale, "evidence_refs"), activeTaskCheckpoint.evidence_refs)' in script
    assert 'formatRunFieldLabel(uiLocale, "progress_basis")' in script
    assert 'formatRunFieldLabel(uiLocale, "evidence_refs")' in script
    assert '"run.field.progress_basis": "进展依据"' in locales
    assert '"run.field.evidence_refs": "证据引用"' in locales


def test_debug_panel_reads_task_state_from_run_artifact_or_inspector_fallback() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    debug_body = re.search(
        r"const renderActivityDebugDetails = \(message, projection\) => \{(?P<body>.*?)\n  \};\n\n  const renderMessageActivity",
        script,
        re.S,
    )
    assert debug_body, "renderActivityDebugDetails helper not found"
    body = debug_body.group("body")
    assert "const debugRunState = inspector.run_state" in body
    assert "const debugSessionState = inspector.session" in body
    assert "const debugTaskState = runArtifact.task_state" in body
    assert "const debugTaskStateDelta = runArtifact.task_state_delta" in body
    assert "const debugTaskStateValidation = runArtifact.task_state_validation" in body
    assert 'renderDetailBlock("task_state", debugTaskState)' in body
    assert 'renderDetailBlock("task_state_delta", debugTaskStateDelta)' in body
    assert 'renderDetailBlock("task_state_validation", debugTaskStateValidation)' in body


def test_preview_progress_note_can_suppress_duplicate_live_summary() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    match = re.search(
        r"const renderActivityProgressList = \(projection, activity, options = \{\}\) => \{(?P<body>.*?)\n  \};\n\n  const renderActivityDebugDetails",
        script,
        re.S,
    )
    assert match, "renderActivityProgressList function not found"
    body = match.group("body")

    assert 'const suppressNoteText = String(options.suppressNoteText || "").trim();' in body
    assert 'const suppressCompletedPreview = Boolean(options.suppressCompletedPreview) && preview && normalizedStatus === "completed";' in body
    assert 'const liveSummaryText = suppressCompletedPreview ? "" : formatLiveSummaryText(liveSummary);' in body
    assert 'normalizedStatus === "completed" && !suppressCompletedPreview ? completionSummary.label : ""' in body
    assert 'const showNote = Boolean(note) && !(preview && suppressNoteText && note === suppressNoteText);' in body
    assert 'if (!visibleItems.length && !overflowCount && !showNote) return null;' in body
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
    assert 'suppressNoteText: pendingFallback.fromSummaryFallback ? (pendingFallback.suppressNoteText || pendingFallback.text) : "",' in body
    assert 'suppressCompletedPreview: Boolean(!item.pending && String(displayActivity.final_answer || item.text || "").trim()),' in body
    assert "visibleItems.map((entry) => {" in script


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
    assert "trace_events: item.trace_events.slice(-MAIN_CARD_TRACE_EVENT_LIMIT)" in script
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
    assert "if (sending) return;" in body
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
    assert "disabled=${sending || !draft.trim() || pendingUploads.some((item) => item && item.uploading)}" in body
    assert '${sending ? t("buttons.running")' in body


def test_activity_debug_drawer_surfaces_triggering_user_message() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "triggering_user_message" in script
    assert 'renderDetailBlock(t("activity.triggering_user_message"), item.triggering_user_message)' in script
    assert 'renderDetailBlock(t("activity.current_turn_goal"), item.current_turn_goal)' not in script
    assert 'renderDetailBlock(t("activity.debug.sent_to_model"), structured.sent_to_model, { open: true })' in script
    assert 'renderDetailBlock(t("activity.debug.runtime"), structured.harness, { open: true })' in script
    assert 'const exchanges = Array.isArray(item.llm_exchanges) ? item.llm_exchanges : [];' in script
    assert 'renderRawModelIo(exchanges)' in script
    assert 't("runtime.raw_model_io.title")' in script
    assert 't("runtime.raw_model_io.sent_messages_exact")' in script
    assert 't("runtime.raw_model_io.model_returned_exact")' in script
    assert 't("runtime.raw_model_io.error")' in script
    assert 't("runtime.raw_model_io.harness_interpretation")' in script
    assert "phase_timings: item.phase_timings || {}" not in script


def test_manual_update_button_is_click_only_and_reports_results() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    styles = STYLES_CSS_PATH.read_text(encoding="utf-8")

    assert 'fetchJson("/api/app/update", { method: "POST" })' in script
    assert 'onClick=${handleAppUpdate}' in script
    assert 'appUpdateRunning ? t("update.running") : t("update.button")' in script
    assert 'title=${t("update.discards_local_changes")}' in script
    assert 'className=${`rail-update-result status-${appUpdateState.status}`}' in script
    assert 'setInterval' in script
    assert "/api/app/update" not in script.split("function handleAppUpdate", 1)[0]
    assert "autoUpdate" not in script
    assert "update check" not in script.lower()
    assert ".rail-update-result" in styles
    assert ".rail-update-details" in styles


def test_activity_debug_drawer_does_not_surface_phase_timings_as_normal_section() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    debug_block = script.split("const renderActivityDebugDetails", 1)[1].split("const renderMessageActivity", 1)[0]
    assert "phase_timings" not in debug_block
    assert "renderPhaseTimingDetails(" not in debug_block


def test_handle_send_includes_client_submission_timestamp() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const clientSubmittedAtMs = Date.now();" in script
    assert "client_submitted_at_ms: clientSubmittedAtMs," in script


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
