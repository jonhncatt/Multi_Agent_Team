from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.task_store import TaskStore, task_context_snapshot


def _create_task(store: TaskStore, *, project_id: str = "project-1", title: str = "Auth refactor") -> dict:
    return store.save(
        project_id=project_id,
        project_title="Demo",
        project_root="/workspace/demo",
        title=title,
        goal="Finish the authentication refactor",
        summary="Backend migration is complete; frontend error handling remains.",
        progress=["Migrated the token endpoint", "Added backend tests"],
        next_steps=["Update the login form", "Run the full test suite"],
        decisions=["Keep refresh tokens server-side"],
        blockers=[],
        artifacts=["app/auth.py", "codex/auth-refactor"],
    )


def test_task_store_creates_lists_and_updates_cross_thread_snapshot(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    created = _create_task(store)

    assert created["task_id"]
    assert store.list(project_id="project-1") == [created]
    assert store.list(project_id="other-project") == []

    updated = store.save(
        task_id=created["task_id"],
        project_id="project-1",
        project_title="Demo",
        project_root="/workspace/demo",
        title="Auth refactor",
        goal="Finish the authentication refactor",
        summary="Implementation is complete and the full suite passes.",
        progress=["Migrated backend", "Updated login form", "Ran full suite"],
        next_steps=[],
        decisions=["Keep refresh tokens server-side"],
        blockers=[],
        artifacts=["app/auth.py", "app/login.js"],
        status="completed",
        source_thread_id="thread-new",
    )

    assert updated["task_id"] == created["task_id"]
    assert updated["status"] == "completed"
    assert updated["source_thread_id"] == "thread-new"
    persisted = json.loads((tmp_path / "tasks" / f"{created['task_id']}.json").read_text(encoding="utf-8"))
    assert persisted["summary"] == "Implementation is complete and the full suite passes."


def test_task_store_marks_load_without_binding_task_to_thread(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    task = _create_task(store)

    first = store.mark_loaded(task["task_id"], thread_id="thread-a")
    second = store.mark_loaded(task["task_id"], thread_id="thread-b")

    assert first["last_loaded_thread_id"] == "thread-a"
    assert second["last_loaded_thread_id"] == "thread-b"
    assert second["source_thread_id"] == ""
    snapshot = task_context_snapshot(second)
    assert "last_loaded_thread_id" not in snapshot
    assert snapshot["task_id"] == task["task_id"]


def test_task_store_rejects_cross_project_update(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    task = _create_task(store)

    with pytest.raises(PermissionError):
        store.save(
            task_id=task["task_id"],
            project_id="project-2",
            project_title="Other",
            project_root="/workspace/other",
            title="Auth refactor",
            goal="Finish it",
            summary="Wrong project",
        )
