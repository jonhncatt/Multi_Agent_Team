from __future__ import annotations

from datetime import datetime, timezone
import os
import subprocess
import threading
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
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=env,
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
    """Updater for the Vintage Programmer repository's active branch/upstream."""

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
        self._operation_lock = threading.Lock()

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

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _tracking_context(self, repo_root: Path, branch: str) -> dict[str, str]:
        remote = self._git_text(["config", "--get", f"branch.{branch}.remote"], repo_root) or self.remote
        merge_ref = self._git_text(["config", "--get", f"branch.{branch}.merge"], repo_root)
        if not merge_ref:
            merge_ref = f"refs/heads/{branch}"
        remote_branch = merge_ref.removeprefix("refs/heads/")
        upstream_ref = self._git_text(
            ["rev-parse", "--symbolic-full-name", "@{upstream}"],
            repo_root,
        )
        if not upstream_ref:
            upstream_ref = (
                merge_ref
                if remote == "."
                else f"refs/remotes/{remote}/{remote_branch}"
            )
        upstream = self._git_text(
            ["rev-parse", "--abbrev-ref", "@{upstream}"],
            repo_root,
        ) or (remote_branch if remote == "." else f"{remote}/{remote_branch}")
        remote_url = self._git_text(["remote", "get-url", remote], repo_root) if remote != "." else str(repo_root)
        return {
            "remote": remote,
            "remote_branch": remote_branch,
            "merge_ref": merge_ref,
            "upstream": upstream,
            "upstream_ref": upstream_ref,
            "remote_url": remote_url,
        }

    def _fetch_branch(
        self,
        *,
        repo_root: Path,
        tracking: dict[str, str],
    ) -> UpdateCommandResult | None:
        remote = str(tracking.get("remote") or "")
        if remote == ".":
            return None
        merge_ref = str(tracking.get("merge_ref") or "")
        upstream_ref = str(tracking.get("upstream_ref") or "")
        return self._git(
            ["fetch", "--no-tags", remote, f"+{merge_ref}:{upstream_ref}"],
            repo_root,
        )

    def _base_status(self) -> tuple[Path | None, dict[str, object]]:
        repo_root, root_result = self._repo_root_result()
        if repo_root is None:
            return None, {
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
        local_commit = self._git_text(["rev-parse", "HEAD"], repo_root)
        version = self._git_text(["describe", "--tags", "--always", "--dirty"], repo_root)
        tracking = self._tracking_context(repo_root, branch) if branch and branch != "HEAD" else {}
        return repo_root, {
            "ok": bool(branch and branch != "HEAD"),
            "is_git_repo": True,
            "repo_root": str(repo_root),
            "branch": branch,
            "commit": commit,
            "local_commit": local_commit,
            "version": version,
            **tracking,
            **(
                {}
                if branch and branch != "HEAD"
                else {"message": "Cannot check or update from detached HEAD."}
            ),
        }

    def status(self) -> dict[str, object]:
        _repo_root, payload = self._base_status()
        return payload

    def check_for_updates(self) -> dict[str, object]:
        with self._operation_lock:
            repo_root, payload = self._base_status()
            if repo_root is None or not bool(payload.get("ok")):
                return {
                    **payload,
                    "checked_at": self._utc_now(),
                    "update_available": False,
                }
            tracking = {key: str(payload.get(key) or "") for key in (
                "remote",
                "remote_branch",
                "merge_ref",
                "upstream",
                "upstream_ref",
                "remote_url",
            )}
            fetch_result = self._fetch_branch(repo_root=repo_root, tracking=tracking)
            if fetch_result is not None and fetch_result.exit_code != 0:
                return {
                    **payload,
                    "ok": False,
                    "checked_at": self._utc_now(),
                    "update_available": False,
                    "message": "Could not check the active branch upstream.",
                    "diagnostic": fetch_result.as_dict(),
                }
            upstream_ref = str(tracking.get("upstream_ref") or "")
            remote_commit = self._git_text(["rev-parse", upstream_ref], repo_root)
            if not remote_commit:
                return {
                    **payload,
                    "ok": False,
                    "checked_at": self._utc_now(),
                    "update_available": False,
                    "message": "The active branch upstream could not be resolved.",
                }
            behind_text = self._git_text(["rev-list", "--count", f"HEAD..{upstream_ref}"], repo_root)
            ahead_text = self._git_text(["rev-list", "--count", f"{upstream_ref}..HEAD"], repo_root)
            try:
                behind_count = max(0, int(behind_text or "0"))
                ahead_count = max(0, int(ahead_text or "0"))
            except ValueError:
                return {
                    **payload,
                    "ok": False,
                    "checked_at": self._utc_now(),
                    "update_available": False,
                    "message": "Could not compare the local and upstream commits.",
                }
            return {
                **payload,
                "ok": True,
                "checked_at": self._utc_now(),
                "remote_commit": remote_commit,
                "behind_count": behind_count,
                "ahead_count": ahead_count,
                "update_available": behind_count > 0,
                "message": (
                    f"{behind_count} upstream commit(s) available."
                    if behind_count > 0
                    else "The active branch is up to date."
                ),
            }

    def update(self) -> dict[str, object]:
        with self._operation_lock:
            return self._update_locked()

    def _update_locked(self) -> dict[str, object]:
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

        tracking = self._tracking_context(repo_root, branch)
        fetch_result = self._fetch_branch(repo_root=repo_root, tracking=tracking)
        fixed_sequence: list[tuple[Sequence[str], UpdateCommandResult | None]] = [
            ([], fetch_result),
            (["reset", "--hard", str(tracking.get("upstream_ref") or "")], None),
            (["pull", "--ff-only"], None),
        ]
        for args, prepared_result in fixed_sequence:
            if prepared_result is None and not args:
                continue
            result = prepared_result or self._git(args, repo_root)
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
            "remote": str(tracking.get("remote") or ""),
            "remote_branch": str(tracking.get("remote_branch") or ""),
            "upstream": str(tracking.get("upstream") or ""),
            "before": before,
            "after": after,
            "dirty_before_update": dirty_before_update,
            "commands": [item.as_dict() for item in commands],
            "message": "Update completed. Restart the app to use the latest code.",
        }
