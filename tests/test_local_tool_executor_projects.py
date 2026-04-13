from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.local_tools import LocalToolExecutor
from app.storage import ProjectStore


def _project_config(tmp_path: Path):
    app_root = tmp_path / "app-root"
    project_root = tmp_path / "external-project"
    app_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config.workspace_root = app_root
    config.allowed_roots = [app_root]
    config.projects_registry_path = tmp_path / "projects.json"
    config.sessions_dir = tmp_path / "sessions"
    config.uploads_dir = tmp_path / "uploads"
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
    store = ProjectStore(config.projects_registry_path, default_root=app_root)
    store.ensure_default_project()
    project = store.create(root_path=str(project_root), title="External Project")
    return config, project_root, project


def test_local_tools_resolve_relative_paths_inside_selected_project(tmp_path: Path) -> None:
    config, project_root, project = _project_config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(
        execution_mode="host",
        session_id="s-project",
        project_id=str(project["project_id"]),
        project_root=str(project_root),
        cwd=str(project_root),
    )

    write_result = executor.write_text_file("notes.txt", "hello from project")
    list_result = executor.list_directory(".")

    assert write_result["ok"] is True
    assert Path(write_result["path"]) == project_root / "notes.txt"
    assert list_result["ok"] is True
    assert Path(list_result["path"]) == project_root
    assert any(item["name"] == "notes.txt" for item in list_result["entries"])
