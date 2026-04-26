from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.local_tools import LocalToolExecutor


def _config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_update_plan_accepts_primary_plan_argument(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.update_plan(plan=[{"step": "Inspect", "status": "completed"}])

    assert result["ok"] is True
    assert result["plan"][0]["step"] == "Inspect"


def test_update_plan_accepts_steps_alias(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.update_plan(steps=[{"step": "Patch", "status": "in_progress"}])

    assert result["ok"] is True
    assert result["plan"][0]["step"] == "Patch"


def test_update_plan_missing_plan_returns_structured_error(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.execute("update_plan", {})

    assert result["ok"] is False
    assert result["error"]["kind"] == "bad_tool_arguments"
    assert result["error"]["tool"] == "update_plan"
    assert "plan" in result["error"]["message"]
