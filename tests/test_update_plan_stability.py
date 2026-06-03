from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.local_tools import LocalToolExecutor
from app.tool_trace_summary import validate_tool_arguments


def _config(tmp_path: Path):
    config = load_config()
    config.workspace_root = tmp_path
    config.allowed_roots = [tmp_path]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
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


def test_update_plan_accepts_step_id_and_alias_fields(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.update_plan(
        plan=[
            {
                "step_id": "step_1",
                "title": "Inspect schema",
                "status": "completed",
                "progress_basis": "Read current validator",
                "evidence_refs": [{"tool": "read_file", "ref": "app/local_tools.py"}],
            }
        ],
        explanation="Multi-step fix",
    )

    assert result["ok"] is True
    assert result["plan"][0]["step_id"] == "step_1"
    assert result["plan"][0]["step"] == "Inspect schema"
    assert result["plan"][0]["progress_basis"] == ["Read current validator"]
    assert result["plan"][0]["evidence_refs"][0]["tool"] == "read_file"


def test_update_plan_accepts_list_of_strings_and_normalizes_to_pending_steps(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.update_plan(plan=["Inspect code", "Patch code"])

    assert result["ok"] is True
    assert result["plan"] == [
        {"step": "Inspect code", "status": "pending"},
        {"step": "Patch code", "status": "pending"},
    ]


def test_update_plan_schema_allows_step_id_in_public_tool_spec(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    spec = next(item for item in executor.tool_specs if str(item.get("name") or "") == "update_plan")

    validation = validate_tool_arguments(
        {
            "plan": [
                {
                    "step_id": "step_1",
                    "step": "Inspect code",
                    "status": "in_progress",
                }
            ]
        },
        spec.get("parameters"),
    )

    assert validation["status"] == "valid"
