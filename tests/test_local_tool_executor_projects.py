from __future__ import annotations

import json
from pathlib import Path

import app.storage as storage_mod
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
    assert list_result["path"] == "."
    assert Path(list_result["resolved_path"]) == project_root
    assert any(item["name"] == "notes.txt" for item in list_result["entries"])


def test_project_store_list_projects_prefers_live_git_metadata_and_persists_registry(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app-root"
    repo_root = tmp_path / "repo-root"
    app_root.mkdir(parents=True, exist_ok=True)
    repo_root.mkdir(parents=True, exist_ok=True)
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(
        json.dumps(
            {
                "projects": {
                    "project_repo": {
                        "project_id": "project_repo",
                        "title": "Repo Root",
                        "root_path": str(repo_root),
                        "created_at": "2026-04-22T00:00:00Z",
                        "updated_at": "2026-04-22T00:00:00Z",
                        "last_opened_at": "2026-04-22T00:00:00Z",
                        "pinned": False,
                        "is_default": False,
                        "git_root": "/stale/root",
                        "git_branch": "stale-branch",
                        "is_worktree": False,
                    }
                },
                "default_project_id": "",
                "updated_at": "2026-04-22T00:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    store = ProjectStore(registry_path, default_root=app_root)
    monkeypatch.setattr(
        storage_mod,
        "_git_metadata",
        lambda root: {
            "git_root": str(root),
            "git_branch": "feature/live-refresh",
            "is_worktree": True,
        },
    )

    projects = store.list_projects()

    repo_project = next(item for item in projects if item["project_id"] == "project_repo")
    assert repo_project["git_root"] == str(repo_root)
    assert repo_project["git_branch"] == "feature/live-refresh"
    assert repo_project["is_worktree"] is True

    saved_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_payload["projects"]["project_repo"]["git_branch"] == "feature/live-refresh"
    assert saved_payload["projects"]["project_repo"]["git_root"] == str(repo_root)
    assert saved_payload["projects"]["project_repo"]["is_worktree"] is True
