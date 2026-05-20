from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.update_manager import AppUpdateManager, UpdateCommandResult


class FakeGitRunner:
    def __init__(self, *, fail_command: str = "", timeout_command: str = "") -> None:
        self.fail_command = fail_command
        self.timeout_command = timeout_command
        self.calls: list[tuple[list[str], Path, int]] = []
        self.head = "abc1234"

    def __call__(self, argv: Sequence[str], cwd: Path, timeout_sec: int) -> UpdateCommandResult:
        args = [str(item) for item in argv]
        self.calls.append((args, cwd, timeout_sec))
        command = " ".join(args)
        if self.timeout_command and self.timeout_command in command:
            return UpdateCommandResult(command=command, exit_code=124, stderr="timed out", timed_out=True)
        if self.fail_command and self.fail_command in command:
            return UpdateCommandResult(command=command, exit_code=128, stderr="boom")
        if args[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=str(cwd))
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="main\n")
        if args[:3] == ["git", "rev-parse", "--short"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.head}\n")
        if args[:2] == ["git", "describe"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="v2.9.19-test\n")
        if args[:3] == ["git", "status", "--porcelain"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=" M app/main.py\n")
        if args[:3] == ["git", "fetch", "--tags"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="fetched\n")
        if args[:3] == ["git", "reset", "--hard"]:
            self.head = "def5678"
            return UpdateCommandResult(command=command, exit_code=0, stdout="HEAD is now def5678\n")
        if args[:3] == ["git", "pull", "--ff-only"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="Already up to date.\n")
        return UpdateCommandResult(command=command, exit_code=0)


def test_update_manager_status_detects_repo_branch_and_version(tmp_path: Path) -> None:
    runner = FakeGitRunner()
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.status()

    assert payload["ok"] is True
    assert payload["is_git_repo"] is True
    assert payload["repo_root"] == str(tmp_path)
    assert payload["branch"] == "main"
    assert payload["commit"] == "abc1234"
    assert payload["version"] == "v2.9.19-test"


def test_update_manager_runs_fixed_manual_update_sequence(tmp_path: Path) -> None:
    runner = FakeGitRunner()
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is True
    assert payload["repo_root"] == str(tmp_path)
    assert payload["branch"] == "main"
    assert payload["before"] == "abc1234"
    assert payload["after"] == "def5678"
    assert payload["dirty_before_update"] is True
    assert [item["command"] for item in payload["commands"]] == [
        "git fetch --tags origin",
        "git reset --hard origin/main",
        "git pull --ff-only",
    ]
    assert all("user" not in " ".join(call[0]) for call in runner.calls)


def test_update_manager_returns_failure_payload(tmp_path: Path) -> None:
    runner = FakeGitRunner(fail_command="reset --hard")
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is False
    assert payload["failed_command"] == "git reset --hard origin/main"
    assert payload["exit_code"] == 128
    assert payload["stderr"] == "boom"
    assert payload["message"] == "Update failed."


def test_update_manager_handles_timeout(tmp_path: Path) -> None:
    runner = FakeGitRunner(timeout_command="pull --ff-only")
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is False
    assert payload["failed_command"] == "git pull --ff-only"
    assert payload["exit_code"] == 124
    assert payload["message"] == "Update command timed out."


def test_update_manager_rejects_non_git_directory(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], cwd: Path, timeout_sec: int) -> UpdateCommandResult:
        command = " ".join(str(item) for item in argv)
        return UpdateCommandResult(command=command, exit_code=128, stderr="not a git repository")

    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is False
    assert payload["message"] == "Current app directory is not a git repository."
    assert payload["failed_command"] == "git rev-parse --show-toplevel"
