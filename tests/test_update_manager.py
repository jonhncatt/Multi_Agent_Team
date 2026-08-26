from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.update_manager import AppUpdateManager, UpdateCommandResult


class FakeGitRunner:
    def __init__(
        self,
        *,
        fail_command: str = "",
        timeout_command: str = "",
        branch: str = "main",
        remote: str = "origin",
        remote_branch: str = "main",
    ) -> None:
        self.fail_command = fail_command
        self.timeout_command = timeout_command
        self.branch = branch
        self.remote = remote
        self.remote_branch = remote_branch
        self.calls: list[tuple[list[str], Path, int]] = []
        self.head = "abc1234"
        self.remote_head = "def5678"

    @property
    def upstream_ref(self) -> str:
        return f"refs/remotes/{self.remote}/{self.remote_branch}"

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
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.branch}\n")
        if args == ["git", "rev-parse", "--abbrev-ref", "@{upstream}"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.remote}/{self.remote_branch}\n")
        if args == ["git", "rev-parse", "--symbolic-full-name", "@{upstream}"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.upstream_ref}\n")
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.head}\n")
        if args == ["git", "rev-parse", "HEAD"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.head}\n")
        if args == ["git", "rev-parse", self.upstream_ref]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.remote_head}\n")
        if args == ["git", "config", "--get", f"branch.{self.branch}.remote"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{self.remote}\n")
        if args == ["git", "config", "--get", f"branch.{self.branch}.merge"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"refs/heads/{self.remote_branch}\n")
        if args == ["git", "remote", "get-url", self.remote]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"ssh://git.example.test/team/vp.git\n")
        if args[:2] == ["git", "describe"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="v2.9.19-test\n")
        if args[:3] == ["git", "status", "--porcelain"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=" M app/main.py\n")
        if args[:3] == ["git", "fetch", "--no-tags"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="fetched\n")
        if args[:3] == ["git", "reset", "--hard"]:
            self.head = self.remote_head
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"HEAD is now {self.remote_head}\n")
        if args[:3] == ["git", "pull", "--ff-only"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="Already up to date.\n")
        if args == ["git", "rev-list", "--count", f"HEAD..{self.upstream_ref}"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout=f"{0 if self.head == self.remote_head else 2}\n")
        if args == ["git", "rev-list", "--count", f"{self.upstream_ref}..HEAD"]:
            return UpdateCommandResult(command=command, exit_code=0, stdout="0\n")
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
    assert payload["upstream"] == "origin/main"
    assert payload["remote_url"] == "ssh://git.example.test/team/vp.git"


def test_update_manager_updates_active_branch_from_configured_upstream_without_tags(tmp_path: Path) -> None:
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
        "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main",
        "git reset --hard refs/remotes/origin/main",
        "git pull --ff-only",
    ]
    assert payload["upstream"] == "origin/main"
    assert all("--tags" not in " ".join(call[0]) for call in runner.calls)
    assert all("user" not in " ".join(call[0]) for call in runner.calls)


def test_update_manager_detects_new_commits_on_active_upstream(tmp_path: Path) -> None:
    runner = FakeGitRunner(remote="gitlab", remote_branch="release/company")
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.check_for_updates()

    assert payload["ok"] is True
    assert payload["update_available"] is True
    assert payload["behind_count"] == 2
    assert payload["ahead_count"] == 0
    assert payload["remote"] == "gitlab"
    assert payload["upstream"] == "gitlab/release/company"
    assert payload["remote_commit"] == "def5678"
    assert any(
        call[0] == [
            "git",
            "fetch",
            "--no-tags",
            "gitlab",
            "+refs/heads/release/company:refs/remotes/gitlab/release/company",
        ]
        for call in runner.calls
    )


def test_update_manager_returns_failure_payload(tmp_path: Path) -> None:
    runner = FakeGitRunner(fail_command="reset --hard")
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is False
    assert payload["failed_command"] == "git reset --hard refs/remotes/origin/main"
    assert payload["exit_code"] == 128
    assert payload["stderr"] == "boom"
    assert payload["message"] == "Update failed."


def test_update_manager_handles_timeout(tmp_path: Path) -> None:
    runner = FakeGitRunner(timeout_command="fetch --no-tags")
    manager = AppUpdateManager(app_dir=tmp_path, runner=runner)

    payload = manager.update()

    assert payload["ok"] is False
    assert payload["failed_command"].startswith("git fetch --no-tags origin")
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
