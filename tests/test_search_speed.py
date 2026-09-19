import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.local_tools import LocalToolExecutor
from app.vintage_programmer_runtime import VintageProgrammerRuntime
from tests.test_local_tools_public_surface import _config


@pytest.mark.parametrize("fallback", [False, True])
def test_glob_project_scope_and_explicit_all_files(tmp_path, monkeypatch, fallback):
    if not fallback and not shutil.which("rg"):
        pytest.skip("ripgrep unavailable")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("build/\n")
    for name in ("src/main.py", "build/generated.py", "node_modules/dep.py", ".hidden/private.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("hello")
    tools = LocalToolExecutor(_config(tmp_path))
    tools.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    if fallback:
        original = shutil.which
        monkeypatch.setattr(shutil, "which", lambda name: None if name == "rg" else original(name))
    result = tools.glob_file_search("**/*.py")
    assert result["ok"]
    assert result["matches"] == ["src/main.py"]
    assert tools.glob_file_search("*.py")["matches"] == []
    assert len(tools.glob_file_search("**/*.py", include_ignored=True)["matches"]) == 4


def make_runtime(monkeypatch, execute, allowed=True):
    runtime = object.__new__(VintageProgrammerRuntime)
    local = threading.local()
    local.project_root = "test-project"
    tools = SimpleNamespace(_runtime_ctx=local, execute=execute, _current_cancel_requested=lambda: False)
    runtime._backend = SimpleNamespace(tools=tools)
    monkeypatch.setattr(runtime, "_validate_model_tool_call", lambda **kw: SimpleNamespace(
        allowed=allowed, tool_name=kw["call"]["name"], normalized_arguments=kw["call"]["args"],
    ))
    return runtime, local


def test_parallel_reads_overlap_and_preserve_context_and_order(monkeypatch):
    barrier = threading.Barrier(2)
    observed = []

    def execute(name, args):
        observed.append(local.project_root)
        barrier.wait(timeout=3)
        return {"ok": True, "path": args["path"]}

    runtime, local = make_runtime(monkeypatch, execute)
    result = runtime._parallel_read_results(
        [{"name": "read_file", "args": {"path": path}} for path in ("a", "b")],
        runnable_tools=[], locale="en", runtime_boundary=None, attachments=[],
    )
    assert [result[i][0]["path"] for i in (1, 2)] == ["a", "b"]
    assert observed == ["test-project", "test-project"]
    assert local.project_root == "test-project"


@pytest.mark.parametrize("allowed,second", [(False, "read_file"), (True, "apply_patch")])
def test_parallel_batch_never_executes_rejected_or_mixed_calls(monkeypatch, allowed, second):
    def forbidden(*args):
        pytest.fail("batch must stay sequential")
    runtime, _ = make_runtime(monkeypatch, forbidden, allowed)
    assert runtime._parallel_read_results(
        [{"name": name, "args": {}} for name in ("read_file", second)],
        runnable_tools=[], locale="en", runtime_boundary=None, attachments=[],
    ) == {}


def test_cancelled_parallel_batch_does_not_start_io(monkeypatch):
    runtime, _ = make_runtime(monkeypatch, lambda *args: pytest.fail("cancelled I/O"))
    runtime._backend.tools._current_cancel_requested = lambda: True
    results = runtime._parallel_read_results(
        [{"name": "read_file", "args": {}}] * 2,
        runnable_tools=[], locale="en", runtime_boundary=None, attachments=[],
    )
    assert all(not result[0]["ok"] for result in results.values())


def test_runtime_parallel_batch_executes_each_read_once(tmp_path, monkeypatch):
    from tests.test_vintage_programmer_runtime import _write_specs, _FakeBackend, _FakeMessage, ChatSettings
    agent_dir = tmp_path / "agents" / "vintage_programmer"
    _write_specs(agent_dir)
    config = _config(tmp_path)
    backend = _FakeBackend([
        _FakeMessage(tool_calls=[{"id": path, "name": "read_file", "args": {"path": path}} for path in ("a.txt", "b.txt")]),
        _FakeMessage(content="done"),
    ])
    backend.tools = LocalToolExecutor(config)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    original = backend.tools.execute
    barrier = threading.Barrier(2)
    calls = []

    def execute(name, arguments):
        if name == "read_file":
            calls.append(arguments["path"])
            barrier.wait(timeout=3)
        return original(name, arguments)

    monkeypatch.setattr(backend.tools, "execute", execute)
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=agent_dir, backend=backend)
    result = runtime.run(
        message="Read a.txt and b.txt", settings=ChatSettings(model="gpt-test", enable_tools=True),
        context={"session_id": "parallel-test", "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
                 "history_turns": [], "attachments": []},
    )
    assert sorted(calls) == ["a.txt", "b.txt"]
    assert result["text"] == "done"
    assert len(result["tool_events"]) == 2
    assert all(event["status"] == "ok" for event in result["tool_events"])
