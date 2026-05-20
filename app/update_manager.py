from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class UpdateCommandResult:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


CommandRunner = Callable[[Sequence[str], Path, int], UpdateCommandResult]


def _shorten_output(text: str, limit: int = 12000) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return f"{value[: limit // 2]}\n...[truncated]...\n{value[-limit // 2 :]}"


def default_command_runner(argv: Sequence[str], cwd: Path, timeout_sec: int) -> UpdateCommandResult:
    command = " ".join(str(item) for item in argv)
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
        return UpdateCommandResult(
            command=command,
            exit_code=int(completed.returncode),
            stdout=_shorten_output(completed.stdout),
            stderr=_shorten_output(completed.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return UpdateCommandResult(
            command=command,
            exit_code=124,
            stdout=_shorten_output(exc.stdout or ""),
            stderr=_shorten_output(exc.stderr or "Update command timed out."),
            timed_out=True,
        )


class AppUpdateManager:
    """Manual-only updater for the Vintage Programmer application repository."""

    def __init__(
        self,
        *,
        app_dir: Path,
        runner: CommandRunner = default_command_runner,
        timeout_sec: int = 60,
        remote: str = "origin",
    ) -> None:
        self.app_dir = Path(app_dir).resolve()
        self.runner = runner
        self.timeout_sec = int(timeout_sec)
        self.remote = str(remote or "origin").strip() or "origin"

    def _git(self, args: Sequence[str], cwd: Path | None = None) -> UpdateCommandResult:
        return self.runner(["git", *args], Path(cwd or self.app_dir), self.timeout_sec)

    def _repo_root_result(self) -> tuple[Path | None, UpdateCommandResult]:
        result = self._git(["rev-parse", "--show-toplevel"], self.app_dir)
        if result.exit_code != 0:
            return None, result
        root = Path(str(result.stdout or "").strip()).resolve()
        return root, result

    def _git_text(self, args: Sequence[str], repo_root: Path) -> str:
        result = self._git(args, repo_root)
        if result.exit_code != 0:
            return ""
        return str(result.stdout or "").strip()

    def status(self) -> dict[str, object]:
        repo_root, root_result = self._repo_root_result()
        if repo_root is None:
            return {
                "ok": False,
                "is_git_repo": False,
                "repo_root": "",
                "branch": "",
                "commit": "",
                "version": "",
                "message": "Current app directory is not a git repository.",
                "diagnostic": root_result.as_dict(),
            }
        branch = self._git_text(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
        commit = self._git_text(["rev-parse", "--short", "HEAD"], repo_root)
        version = self._git_text(["describe", "--tags", "--always", "--dirty"], repo_root)
        return {
            "ok": True,
            "is_git_repo": True,
            "repo_root": str(repo_root),
            "branch": branch,
            "commit": commit,
            "version": version,
        }

    def update(self) -> dict[str, object]:
        repo_root, root_result = self._repo_root_result()
        if repo_root is None:
            return {
                "ok": False,
                "repo_root": "",
                "branch": "",
                "before": "",
                "after": "",
                "dirty_before_update": False,
                "commands": [root_result.as_dict()],
                "failed_command": root_result.command,
                "exit_code": root_result.exit_code,
                "stdout": root_result.stdout,
                "stderr": root_result.stderr,
                "message": "Current app directory is not a git repository.",
            }

        branch = self._git_text(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
        before = self._git_text(["rev-parse", "--short", "HEAD"], repo_root)
        dirty_result = self._git(["status", "--porcelain"], repo_root)
        dirty_before_update = bool(str(dirty_result.stdout or "").strip())
        commands: list[UpdateCommandResult] = []

        if not branch or branch == "HEAD":
            return {
                "ok": False,
                "repo_root": str(repo_root),
                "branch": branch,
                "before": before,
                "after": before,
                "dirty_before_update": dirty_before_update,
                "commands": [],
                "failed_command": "git rev-parse --abbrev-ref HEAD",
                "exit_code": 1,
                "stdout": "",
                "stderr": "Cannot update from detached HEAD.",
                "message": "Update failed.",
            }

        fixed_sequence = [
            ["fetch", "--tags", self.remote],
            ["reset", "--hard", f"{self.remote}/{branch}"],
            ["pull", "--ff-only"],
        ]
        for args in fixed_sequence:
            result = self._git(args, repo_root)
            commands.append(result)
            if result.exit_code != 0:
                after_failure = self._git_text(["rev-parse", "--short", "HEAD"], repo_root) or before
                return {
                    "ok": False,
                    "repo_root": str(repo_root),
                    "branch": branch,
                    "before": before,
                    "after": after_failure,
                    "dirty_before_update": dirty_before_update,
                    "commands": [item.as_dict() for item in commands],
                    "failed_command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "message": "Update command timed out." if result.timed_out else "Update failed.",
                }

        after = self._git_text(["rev-parse", "--short", "HEAD"], repo_root)
        return {
            "ok": True,
            "repo_root": str(repo_root),
            "branch": branch,
            "before": before,
            "after": after,
            "dirty_before_update": dirty_before_update,
            "commands": [item.as_dict() for item in commands],
            "message": "Update completed. Restart the app to use the latest code.",
        }
