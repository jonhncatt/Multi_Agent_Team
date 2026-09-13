"""Execute the shipped state store rather than duplicating its implementation."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_thread_model_settings_are_independent_and_survive_reload():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for frontend behavior tests")
    source = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text()
    helper = source[source.index("const THREAD_MODEL_STORAGE_KEY"):source.index("function useThreadChatSettings")]
    script = helper + """
const assert = require('node:assert/strict');
const data = new Map();
const storage = {getItem: key => data.get(key), setItem: (key,value) => data.set(key,value)};
const defaults = {model:'default', provider:'company', reasoning_effort:'high', service_tier:'auto', locale:'zh'};
const store = createThreadSettingsStore(storage, defaults);
store.update('a', prev => ({...prev, model:'model-a', reasoning_effort:'max', service_tier:'priority'}));
store.update('b', prev => ({...prev, model:'model-b', provider:'other', reasoning_effort:'low'}));
assert.equal(store.get('a').model, 'model-a');
assert.equal(store.get('a').provider, 'company');
assert.equal(store.get('a').service_tier, 'priority');
assert.equal(store.get('b').service_tier, 'auto');
const requestA = {...store.get('a')};
store.update('b', prev => ({...prev, model:'model-b-new'}));
assert.equal(requestA.model, 'model-a');
store.copy('a', 'temporary');
store.update('temporary', prev => ({...prev, model:'new-thread-model'}));
store.move('temporary', 'real-id');
assert.equal(store.get('real-id').model, 'new-thread-model');
assert.equal(store.get('a').model, 'model-a');
const restored = createThreadSettingsStore(storage, defaults);
assert.equal(restored.get('a').reasoning_effort, 'max');
assert.equal(restored.get('b').model, 'model-b-new');
assert.equal(restored.get('real-id').model, 'new-thread-model');
restored.remove('a');
assert.equal(createThreadSettingsStore(storage, defaults).get('a').model, 'default');
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=10)
