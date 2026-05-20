from __future__ import annotations

from pathlib import Path

import pytest

from app.config import load_config
from app.local_tools import LocalToolExecutor


def _make_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LocalToolExecutor:
    monkeypatch.setenv("VP_SKIP_DOTENV", "1")
    monkeypatch.setenv("VP_WORKSPACE_ROOT", str(tmp_path))
    config = load_config()
    manager = LocalToolExecutor(config)
    manager.set_runtime_context(
        execution_mode="host",
        session_id="test-session",
        project_root=str(tmp_path),
        cwd=str(tmp_path),
    )
    return manager


def _runtime_boundary(tmp_path: Path, *, shell_allowed: bool = True, write_allowed: bool = True) -> dict[str, object]:
    return {
        "permission_profile": "code" if shell_allowed else "chat",
        "workspace_read_allowed": True,
        "workspace_write_allowed": write_allowed,
        "shell_allowed": shell_allowed,
        "network_allowed": False,
        "allowed_roots": [str(tmp_path.resolve())],
        "writable_roots": [str(tmp_path.resolve())] if write_allowed else [],
        "command_allowed_roots": [str(tmp_path.resolve())] if shell_allowed else [],
        "cwd": str(tmp_path.resolve()),
        "project_root": str(tmp_path.resolve()),
    }


def test_exec_command_allows_printf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _make_manager(monkeypatch, tmp_path)

    argv, error = manager._safe_split_command("printf '%s\\n' hello")

    assert error is None
    assert argv[0] == "printf"


def test_exec_command_allows_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _make_manager(monkeypatch, tmp_path)

    argv, error = manager._safe_split_command("dir")

    assert error is None
    assert argv[0] == "dir"


@pytest.mark.parametrize(
    "command",
    [
        "rm temp.txt",
        "chmod 644 sample.txt",
        "chown root sample.txt",
        "curl https://example.com",
        "wget https://example.com/file.txt",
        "sudo ls",
        "dd if=/dev/null of=x",
        "kill 123",
        "pkill node",
        "brew install jq",
        "pip install pytest",
        "pip3 install pytest",
    ],
)
def test_exec_command_blocks_high_risk_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)

    argv, error = manager._safe_split_command(command)

    assert argv == []
    assert error is not None
    assert "Command not allowed" in error


def test_python_commands_prefer_project_venv_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    manager = _make_manager(monkeypatch, tmp_path)

    argv, error = manager._safe_split_command("python -m pytest")

    assert error is None
    assert argv[0] == str(venv_python.resolve())


def test_project_venv_python_path_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    manager = _make_manager(monkeypatch, tmp_path)

    argv, error = manager._safe_split_command("./.venv/bin/python -m pytest")

    assert error is None
    assert argv[0] == "./.venv/bin/python"


def test_blocked_command_failure_includes_structured_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)

    result = manager.run_shell(command="rm temp.txt", cwd=str(tmp_path))

    assert result["ok"] is False
    assert result["error"].startswith("Command not allowed: rm")
    assert result["stderr"] == result["error"]
    assert result["returncode"] == 126
    assert result["cwd"] == str(tmp_path)
    assert result["command"] == "rm temp.txt"


def test_exec_command_denies_cwd_outside_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)
    manager.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path), runtime_boundary=_runtime_boundary(tmp_path))

    result = manager.run_shell(command="pwd", cwd="/etc")

    assert result["ok"] is False
    assert "allowed roots" in result["error"]


@pytest.mark.parametrize(
    "command",
    [
        "rg foo /etc",
        "git -C /tmp status",
        "python /tmp/outside.py",
    ],
)
def test_command_path_arguments_outside_project_are_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)
    manager.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path), runtime_boundary=_runtime_boundary(tmp_path))

    result = manager.run_shell(command=command, cwd=".")

    assert result["ok"] is False
    assert result["error_kind"] == "command_path_outside_allowed_roots"


def test_cp_outside_destination_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('x')", encoding="utf-8")
    manager = _make_manager(monkeypatch, tmp_path)
    manager.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path), runtime_boundary=_runtime_boundary(tmp_path))

    result = manager.run_shell(command="cp app/main.py /tmp/main.py", cwd=".")

    assert result["ok"] is False
    assert result["error_kind"] == "command_path_outside_allowed_roots"


def test_chat_profile_denies_shell_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)
    manager.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path), runtime_boundary=_runtime_boundary(tmp_path, shell_allowed=False))

    result = manager.run_shell(command="pytest -q", cwd=".")

    assert result["ok"] is False
    assert "Shell execution is not allowed" in result["error"]


def test_write_text_file_respects_writable_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _make_manager(monkeypatch, tmp_path)
    manager.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path), runtime_boundary=_runtime_boundary(tmp_path, write_allowed=True))

    allowed = manager.write_text_file("docs/test.md", "x")
    denied = manager.write_text_file("/tmp/outside.md", "x")

    assert allowed["ok"] is True
    assert denied["ok"] is False
    assert denied["error_kind"] == "write_outside_writable_roots"
