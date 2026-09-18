from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


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
    assert "...mergeRuntimeToolState(prev, finalLogicalToolEvents" in body
    assert "tool_hits: latestToolEvents" in body
    assert "tool_count: Math.max(finalLogicalToolCount, latestToolEvents.length)" in body
