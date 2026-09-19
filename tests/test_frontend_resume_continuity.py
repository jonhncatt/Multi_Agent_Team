from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


def _extract_js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    parameters_open = source.index("(", start)
    parameters_depth = 0
    parameters_close = -1
    for index in range(parameters_open, len(source)):
        character = source[index]
        if character == "(":
            parameters_depth += 1
        elif character == ")":
            parameters_depth -= 1
            if parameters_depth == 0:
                parameters_close = index
                break
    if parameters_close < 0:
        raise AssertionError(f"unterminated JavaScript parameters: {name}")
    opening = source.index("{", parameters_close)
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated JavaScript function: {name}")


def test_runtime_tool_state_counts_unique_calls_beyond_visible_timeline() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function runtimeToolIdentity(item)")
    end = source.index("function createLog(type, text)", start)
    helpers = source[start:end]
    script = f"""
const assert = require('node:assert/strict');
const RECENT_TOOL_TIMELINE_LIMIT = 24;
{helpers}
const event = (id, status = 'ok') => ({{ raw_tool_call: {{ id }}, status }});
let state = {{ toolTimeline: [], liveToolTimeline: [], toolCount: 0, toolEventIds: [] }};
for (let index = 0; index < 30; index += 1) state = {{ ...state, ...mergeRuntimeToolState(state, [event(`call-${{index}}`)]) }};
assert.equal(state.toolCount, 30);
assert.equal(state.liveToolTimeline.length, 24);
state = {{ ...state, ...mergeRuntimeToolState(state, [event('call-29', 'error')]) }};
assert.equal(state.toolCount, 30);
assert.equal(state.liveToolTimeline[0].status, 'error');
const rich = {{ id: 'transaction-1', tool_call_id: 'call-rich', type: 'commandExecution', status: 'completed' }};
const merged = mergeRuntimeToolTimeline([rich], [{{ raw_tool_call: {{ id: 'call-rich' }}, status: 'error' }}]);
assert.equal(merged[0].id, 'transaction-1');
assert.equal(merged[0].type, 'commandExecution');
assert.equal(merged[0].status, 'error');
const resumed = mergeRuntimeToolState(state, [event('call-30')], {{ minimumCount: 31, toolEventIds: state.toolEventIds }});
assert.equal(resumed.toolCount, 31);
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)


def test_handle_send_preserves_live_state_only_for_resume() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    body = source.split("async function handleSend(overrideText, userInputResponse)", 1)[1].split(
        "\n  async function loadSpecDetail", 1
    )[0]

    assert "if (!isTurnResume) {\n      setToolTimeline([]);" in body
    assert "const baseTurn = isTurnResume" in body
    assert 'if (!isTurnResume) setActiveRunId("");' in body
    assert "const initializedOwnerSnapshot = updateThreadSnapshot" in body
    assert "initializedOwnerSnapshot && initializedOwnerSnapshot.activeTurn" in body
    assert "...mergeRuntimeToolState(existingTurn, resumePendingTurn.logical_tool_events" in body
    assert "plan: isTurnResume ? pendingActivity.plan : []" in body
    assert "...mergeRuntimeToolState(prev, finalLogicalToolEvents" in body
    assert "tool_hits: latestToolEvents" in body
    assert "tool_count: Math.max(finalLogicalToolCount, latestToolEvents.length)" in body


def test_resume_message_activity_stays_continuous_through_live_projection() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    source = APP_JS.read_text(encoding="utf-8")
    function_names = [
        "normalizeActivityTimestamp",
        "normalizeTraceEvent",
        "normalizePlanChecklistItem",
        "normalizePlanChecklist",
        "hasPendingRuntimeInteraction",
        "formatRuntimeInputResponse",
        "runtimeToolIdentity",
        "toolCallIdentityFromSource",
        "normalizeActivityToolItem",
        "normalizeActivityToolItems",
        "mergeActivityToolItem",
        "mergeActivityToolItems",
        "normalizeRuntimeErrorPayload",
        "normalizeProgressStatus",
        "isActivityTerminalStatus",
        "normalizeMessageActivity",
        "mergeActivityState",
        "buildPendingAssistantActivity",
        "createEmptyLiveHeartbeat",
        "normalizeLiveHeartbeat",
        "isCurrentThreadLiveRun",
        "buildLiveDisplayActivity",
        "buildMainCompletionSummary",
        "buildActivityProjection",
    ]
    functions = "\n\n".join(_extract_js_function(source, name) for name in function_names)
    script = f"""
const assert = require('node:assert/strict');
const RECENT_TOOL_TIMELINE_LIMIT = 24;
const MAIN_CARD_TRACE_EVENT_LIMIT = 64;
const NORMALIZED_ACTIVITY_MARKER = Symbol('normalizedActivity');
function normalizeTurnChanges(raw) {{ return raw && typeof raw === 'object' ? raw : {{}}; }}
function normalizeLiveRunItems(raw) {{ return Array.isArray(raw) ? raw : []; }}
function mergeLiveRunItems(previous, next) {{ return [...(Array.isArray(previous) ? previous : []), ...(Array.isArray(next) ? next : [])]; }}
function latestRevisionSummary() {{ return {{ items: [] }}; }}
function buildPlanChecklistItems(plan) {{ return normalizePlanChecklist(plan); }}
function buildFallbackProgressItems() {{ return []; }}
function latestExecutionTrace() {{ return []; }}
function buildToolProgressGroups() {{ return []; }}
function buildMainLiveCards() {{ return []; }}
function formatRevisionSummaryBadge() {{ return ''; }}
function latestActivityPayloadValue() {{ return {{}}; }}
function translateUiOrFallback(locale, key, fallback) {{ return fallback; }}
{functions}

const plan = [
  {{ step: 'Inspect', status: 'completed' }},
  {{ step: 'Choose', status: 'completed' }},
  {{ step: 'Continue', status: 'in_progress' }},
];
assert.equal(
  formatRuntimeInputResponse(
    [{{ id: 'direction', header: '测试方向', question: '请选择测试方向' }}],
    {{ direction: 'A' }},
  ),
  '测试方向: A',
);
assert.equal(
  formatRuntimeInputResponse(
    [
      {{ id: 'direction', header: '测试方向' }},
      {{ id: 'scope', header: '测试范围' }},
    ],
    {{ direction: 'A', scope: 'B' }},
  ),
  '测试方向: A\\n测试范围: B',
);
const streamTool = (index) => ({{
  id: `transaction-${{index}}`,
  transaction_id: `transaction-${{index}}`,
  tool_call_id: `call-${{index}}`,
  name: index === 7 ? 'exec_command' : 'read_file',
  tool: index === 7 ? 'exec_command' : 'read_file',
  type: index === 7 ? 'commandExecution' : 'toolCall',
  status: 'completed',
  summary: `tool ${{index}}`,
}});
const rawTool = (index) => ({{
  raw_tool_call: {{ id: `call-${{index}}`, name: index === 7 ? 'exec_command' : 'read_file' }},
  name: index === 7 ? 'exec_command' : 'read_file',
  status: 'ok',
  summary: `tool ${{index}}`,
}});
const tools = Array.from({{ length: 6 }}, (_, index) => streamTool(index + 1));
const rawTools = Array.from({{ length: 6 }}, (_, index) => rawTool(index + 1));
const collisionItems = [
  {{ ...streamTool(1), id: 'transaction-a', transaction_id: 'transaction-a', tool_call_id: 'shared-call', tool_round: 1, tool_index: 1 }},
  {{ ...streamTool(2), id: 'transaction-b', transaction_id: 'transaction-b', tool_call_id: 'shared-call', tool_round: 2, tool_index: 1 }},
];
const collisionEvents = [
  {{ ...rawTool(1), raw_tool_call: {{ id: 'shared-call', name: 'read_file' }}, tool_round: 1, tool_index: 1 }},
  {{ ...rawTool(2), raw_tool_call: {{ id: 'shared-call', name: 'read_file' }}, tool_round: 2, tool_index: 1 }},
];
const mergedCollisions = mergeActivityToolItems(collisionItems, collisionEvents);
assert.equal(mergedCollisions.length, 2);
assert.deepEqual(mergedCollisions.map((item) => item.id), ['transaction-a', 'transaction-b']);
const initialActivity = normalizeMessageActivity({{
  status: 'needs_user_input',
  started_at: 1700000000000,
  turn_started_at: 1700000000000,
  plan,
  tool_items: tools,
  tool_count: 6,
}});

for (const resumeType of ['request_user_input', 'command_execution', 'task_update']) {{
  const pendingTurn = {{
    type: resumeType,
    plan,
    logical_tool_events: rawTools,
    logical_tool_count: 6,
  }};
  const pendingActivity = buildPendingAssistantActivity({{
    isTurnResume: true,
    messages: [{{ role: resumeType === 'request_user_input' ? 'assistant' : 'runtime', activity: initialActivity }}],
    sessionRuntimeState: {{ plan, pending_turn: pendingTurn }},
    resumePendingTurn: pendingTurn,
    resumeActiveTurn: {{
      liveTurnState: {{ plan }},
      liveToolTimeline: tools,
      toolTimeline: tools,
      toolCount: 6,
    }},
    clientSubmittedAtMs: 1700000005000,
    logicalTurnStartedAtMs: 1700000000000,
    runModelName: 'gpt-test',
  }});
  const displayActivity = buildLiveDisplayActivity(pendingActivity, {{
    sessionId: 'thread-1',
    activeRunThreadId: 'thread-1',
    sending: true,
    activeRunId: 'run-2',
    activeRunStartedAt: 1700000000000,
    liveTurnState: {{ plan }},
    liveToolTimeline: tools,
    liveToolCount: 6,
    liveHeartbeat: {{ status: 'background_running' }},
  }});
  const firstProjection = buildActivityProjection(displayActivity, 'en', 1700000005000, {{ expanded: true }});
  assert.equal(firstProjection.plan.length, 3, `${{resumeType}} plan at first resume frame`);
  assert.equal(firstProjection.tool_items.length, 6, `${{resumeType}} tools at first resume frame`);
  assert.equal(displayActivity.tool_count, 6, `${{resumeType}} count at first resume frame`);
  assert.deepEqual(
    pendingActivity.tool_items.map((item) => item.id),
    tools.map((item) => item.id),
    `${{resumeType}} preserves typed transaction identities`,
  );

  const nextTool = streamTool(7);
  const activityAfterTool = mergeActivityState(pendingActivity, {{ tool_items: [nextTool] }});
  const liveAfterTool = buildLiveDisplayActivity(activityAfterTool, {{
    sessionId: 'thread-1',
    activeRunThreadId: 'thread-1',
    sending: true,
    activeRunId: 'run-2',
    activeRunStartedAt: 1700000000000,
    liveTurnState: {{ plan }},
    liveToolTimeline: [nextTool, ...tools],
    liveToolCount: 7,
    liveHeartbeat: {{ status: 'running' }},
  }});
  const nextProjection = buildActivityProjection(liveAfterTool, 'en', 1700000006000, {{ expanded: true }});
  assert.equal(nextProjection.plan.length, 3, `${{resumeType}} plan after next tool`);
  assert.equal(nextProjection.tool_items.length, 7, `${{resumeType}} tools after next tool`);
  assert.equal(liveAfterTool.tool_count, 7, `${{resumeType}} count after next tool`);
  assert.equal(nextProjection.completion_summary.tool_count, 7, `${{resumeType}} projected tool count`);
}}

const freshActivity = buildPendingAssistantActivity({{
  isTurnResume: false,
  messages: [{{ role: 'assistant', activity: initialActivity }}],
  sessionRuntimeState: {{ plan }},
  resumePendingTurn: {{ plan, logical_tool_events: tools, logical_tool_count: 6 }},
  resumeActiveTurn: {{ liveToolTimeline: tools, toolCount: 6 }},
  clientSubmittedAtMs: 1700000010000,
  logicalTurnStartedAtMs: 1700000010000,
  runModelName: 'gpt-test',
}});
const freshProjection = buildActivityProjection(freshActivity, 'en', 1700000010000, {{ expanded: true }});
assert.equal(freshProjection.plan.length, 0);
assert.equal(freshProjection.tool_items.length, 0);
assert.equal(freshActivity.tool_count, 0);
for (const resumeType of ['request_user_input', 'command_execution', 'task_update']) {{
  assert.equal(hasPendingRuntimeInteraction({{ pending_turn: {{ type: resumeType }} }}), true);
}}
assert.equal(hasPendingRuntimeInteraction({{ turn_status: 'needs_user_input' }}), true);
assert.equal(hasPendingRuntimeInteraction({{ turn_status: 'idle' }}), false);
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)
