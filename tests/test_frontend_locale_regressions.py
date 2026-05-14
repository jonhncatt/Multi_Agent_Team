from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
LOCALES_JS_PATH = REPO_ROOT / "app" / "static" / "locales.js"
STYLES_CSS_PATH = REPO_ROOT / "app" / "static" / "styles.css"
INTERNAL_MANUAL_PATH = REPO_ROOT / "docs" / "internal_design_manual.md"
SUPPORTED_LOCALES = ("zh-CN", "ja-JP", "en")
REQUIRED_CORE_KEYS = (
    "labels.payload",
    "settings.locale",
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
    "settings.collaboration_mode",
    "settings.response_style",
    "buttons.save",
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
    "activity.debug_details",
    "activity.raw_events",
    "activity.high_level_proposal",
    "activity.validated_next_step",
    "activity.execution_trace",
    "activity.runtime_hint",
    "activity.model_proposal",
    "activity.validated_plan",
    "activity.runtime_guess",
    "activity.raw_tool_call",
    "activity.normalized_arguments",
    "activity.guard_result",
    "activity.revision_summary",
    "activity.observation_summary",
    "activity.original_excerpt",
    "activity.result_excerpt",
    "activity.reason",
    "activity.triggering_user_message",
    "activity.triggering_user_turn_id",
    "activity.current_turn_goal",
    "activity.current_turn_followup_type",
    "activity.current_turn_goal_source",
    "activity.active_task_focus",
    "activity.recent_user_messages",
    "activity.phase_timings",
    "activity.progress.read",
    "activity.progress.list_dir",
    "activity.progress.glob_file_search",
    "activity.progress.search",
    "activity.progress.execute_command",
    "activity.progress.apply_patch",
    "activity.progress.use_tool",
    "activity.stage.high_level_proposal",
    "activity.stage.step_validation",
    "activity.stage.execution",
    "activity.stage.request_analysis",
    "activity.stage.model_proposal",
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
    "context_meter.field.project",
    "context_meter.field.status",
    "context_meter.field.model",
    "context_meter.field.elapsed",
    "context_meter.field.runtime_mode",
    "context_meter.field.tool_total",
    "context_meter.field.tool_succeeded",
    "context_meter.field.tool_failed",
    "context_meter.field.tool_rejected",
    "context_meter.field.tool_latest",
    "context_meter.field.context_usage",
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
)
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
        "high_level_proposal",
        "validated_next_step",
        "execution_trace",
        "raw_tool_call",
        "guard_result",
        "normalized_arguments",
        "runtime_hint",
        'className="activity-progress"',
        'className="activity-debug-drawer"',
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
    )
    for token in required_style_tokens:
        assert token in styles, token


def test_plan_updates_and_tool_items_are_projected_into_message_activity() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    required_tokens = (
        'tool_items: [item]',
        "plan_explanation: explanation",
        'summary>${t("activity.debug_details")}</summary>',
        'summary>${t("activity.raw_events")}</summary>',
        'summary>${t("run.recent_tools")}</summary>',
    )
    for token in required_tokens:
        assert token in script, token


def test_no_tool_progress_projection_uses_request_and_model_wait_states() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function buildFallbackProgressItems\(activity, locale, nowMs = Date\.now\(\)\) \{(?P<body>.*?)\n}\n\nfunction buildActivityProjection",
        script,
        re.S,
    )
    assert match, "buildFallbackProgressItems function not found"
    body = match.group("body")

    assert 'label: translateUi(locale, "activity.status.request_understood")' in body
    assert 'label: translateUi(locale, "activity.status.request_understanding")' in body
    assert '"activity.status.waiting_model"' in body
    assert '"activity.status.waiting_model_slow"' in body
    assert "MODEL_WAIT_SLOW_HINT_MS" in script
    assert "const llmStartedAt = latestTraceTimestampByTypes(traces, \"llm.started\");" in body
    assert '"answer.started"' in body
    assert "activity.status.direct_answer_no_tool" not in body


def test_early_activity_copy_and_visibility_are_updated() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert '"activity.status.request_understood": "开始处理请求"' in locales
    assert '"activity.status.request_understanding": "正在理解问题"' in locales
    assert '"activity.status.waiting_model": "等待模型返回"' in locales
    assert '"activity.status.waiting_model_slow": "模型响应较慢，仍在等待返回"' in locales
    assert "|| activity.started_at" in script
    assert "|| activity.status" in script


def test_frontend_progress_projection_uses_canonical_tool_names_only() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert '"read_file"' in script
    assert '"list_dir"' in script
    assert '"glob_file_search"' in script
    assert '"search_contents_in_file"' in script
    assert '"search_contents_in_file_multi"' in script
    assert '"search_file"' not in script
    assert '"search_file_multi"' not in script


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
        "emergency_max_tool_calls_per_turn",
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
    assert "traceEvents.length ? traceEvents[traceEvents.length - 1].timestamp : 0" not in body
    assert "const turnStartedAt = item.turn_started_at || item.started_at;" in script
    assert "const frozenElapsedMs = Math.max(0, Number(item.final_elapsed_ms || 0) || 0);" in script
    assert "const shouldTickActivityClock = hasRunningActivity || sending || Boolean(activeRunId);" in script
    assert "window.setInterval(() => setActivityClockMs(Date.now()), 1000)" in script

    assert 'onMouseLeave=${() => setContextMeterOpen(false)}' not in script


def test_frontend_uses_stable_default_max_output_tokens_and_server_bootstrap_override() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "max_output_tokens: 4096" in script
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


def test_internal_design_manual_title_and_polish_notes_are_current() -> None:
    manual = INTERNAL_MANUAL_PATH.read_text(encoding="utf-8")

    assert manual.startswith("# 内部设计手册（v2.9.3）")
    assert "## 16. v2.9.2 Tool UX Polish Notes" in manual
    assert "## 17. v2.9.3 Allowlist and Serialization Compatibility Notes" in manual
    assert "## 22. Context Turns" in manual
    assert "## 23. Python Command Handling" in manual
    assert "## 24. Python Version Recommendation" in manual
    assert "## 25. Shell Command Allowlist" in manual


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
    assert "turn_started_at: Date.now()," in script

    run_started_match = re.search(
        r'if \(event === "run_started"\) \{(?P<body>.*?)\n            \} else if \(event === "run_finished"\)',
        script,
        re.S,
    )
    assert run_started_match, "run_started handler not found"
    run_started_body = run_started_match.group("body")
    assert 'status: "thinking"' in run_started_body
    assert "started_at" not in run_started_body


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
    assert "handleSend();" in body


def test_activity_debug_drawer_surfaces_triggering_user_message() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "triggering_user_message" in script
    assert 'renderDetailBlock(t("activity.triggering_user_message"), item.triggering_user_message)' in script
    assert 'renderDetailBlock(t("activity.triggering_user_turn_id"), item.triggering_user_turn_id)' in script
    assert 'renderDetailBlock(t("activity.current_turn_goal"), item.current_turn_goal)' in script
    assert 'renderDetailBlock(t("activity.active_task_focus"), item.active_task_focus)' in script
    assert 'renderDetailBlock(t("activity.recent_user_messages"), item.recent_user_messages)' in script


def test_activity_debug_drawer_surfaces_phase_timings() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const renderPhaseTimingDetails = (source) => {" in script
    assert 'summary>${t("activity.phase_timings")}</summary>' in script
    assert 'formatPhaseTimingLabel(uiLocale, key)' in script
    assert 'formatPhaseTimingMs(value)' in script
    assert "item.phase_timings" in script


def test_handle_send_includes_client_submission_timestamp() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const clientSubmittedAtMs = Date.now();" in script
    assert "client_submitted_at_ms: clientSubmittedAtMs," in script
