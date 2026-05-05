from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
LOCALES_JS_PATH = REPO_ROOT / "app" / "static" / "locales.js"
STYLES_CSS_PATH = REPO_ROOT / "app" / "static" / "styles.css"
SUPPORTED_LOCALES = ("zh-CN", "ja-JP", "en")
REQUIRED_CORE_KEYS = (
    "labels.payload",
    "settings.locale",
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
    "context_meter.field.guard_tool_calls",
    "context_meter.field.guard_same_tool",
    "context_meter.field.guard_no_progress",
    "context_meter.field.guard_rejections",
    "context_meter.field.guard_wall_clock",
    "context_meter.field.guard_user_stop",
    "context_meter.field.guard_compaction",
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


def test_early_progress_placeholder_uses_neutral_thinking_state() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"function buildFallbackProgressItems\(activity, locale\) \{(?P<body>.*?)\n}\n\nfunction buildActivityProjection",
        script,
        re.S,
    )
    assert match, "buildFallbackProgressItems function not found"
    body = match.group("body")

    assert 'label: translateUi(locale, "activity.status.request_understood")' in body
    assert 'label: translateUi(locale, "activity.status.thinking")' in body
    assert 'id: "thinking"' in body
    assert '"answer.started"' in body
    assert "activity.status.direct_answer_no_tool" not in body


def test_early_activity_copy_and_visibility_are_updated() -> None:
    script = APP_JS_PATH.read_text(encoding="utf-8")
    locales = LOCALES_JS_PATH.read_text(encoding="utf-8")

    assert '"activity.status.request_understood": "开始处理请求"' in locales
    assert '"activity.status.thinking": "正在思考"' in locales
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
        "PROJECTS_REFRESH_STALE_MS",
        "runtimeStatusAbortRef",
        "projectsInFlightRef",
        "refreshProjectsIfStale({ minAgeMs: PROJECTS_REFRESH_STALE_MS })",
        "currentRuntimeStatus.loop_safeguards",
        'translateUi(locale, "context_meter.compact_usage"',
        'translateUi(locale, "context_meter.compact_tokens"',
        'translateUi(locale, "context_meter.compact_elapsed_tools"',
        'translateUi(locale, "context_meter.compact_auto_compact"',
        't("context_meter.section.run")',
        't("context_meter.section.tools")',
        't("context_meter.section.context")',
        't("context_meter.section.safeguards")',
        'className="context-meter-details"',
        'className="context-meter-details-toggle"',
    )
    for token in required_script_tokens:
        assert token in script, token

    assert "BRANCH_REFRESH_INTERVAL_MS" not in script
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

    assert 'onMouseLeave=${() => setContextMeterOpen(false)}' not in script
