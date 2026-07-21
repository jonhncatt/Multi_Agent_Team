from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex

from app.config import load_config
from app.local_tools import LocalToolExecutor


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s4nHCwAAAAASUVORK5CYII="
)


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


def test_public_tool_specs_expose_new_surface_only(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    tool_names = {str(item.get("name") or "") for item in executor.tool_specs}

    assert {
        "exec_command",
        "write_stdin",
        "apply_patch",
        "read_file",
        "list_dir",
        "glob_file_search",
        "search_contents_in_file",
        "search_contents_in_file_multi",
        "read_section",
        "table_extract",
        "fact_check_file",
        "search_codebase",
        "web_search",
        "web_fetch",
        "web_download",
        "sessions_list",
        "sessions_history",
        "image_inspect",
        "image_read",
        "archive_extract",
        "mail_extract_attachments",
        "update_plan",
        "request_user_input",
        "spawn_subagent",
        "wait_subagents",
        "save_skill",
        "save_task",
    }.issubset(tool_names)
    assert {"load_skill", "run_skill_script"}.isdisjoint(tool_names)
    assert {
        "read_text_file",
        "search_text_in_file",
        "multi_query_search",
        "read_section_by_heading",
        "download_web_file",
        "view_image",
        "list_sessions",
        "read_session_history",
        "search_web",
        "fetch_web",
        "read",
        "search_file",
        "search_file_multi",
    }.isdisjoint(tool_names)


def test_spawn_subagent_delegates_to_runtime_injected_runner(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    calls = []

    def runner(**kwargs):
        calls.append(dict(kwargs))
        return {"ok": True, "status": "completed", "summary": "isolated result"}

    executor.set_runtime_context(
        project_root=str(tmp_path),
        cwd=str(tmp_path),
        subagent_runner=runner,
    )
    result = executor.execute(
        "spawn_subagent",
        {"task": "Inspect parser files", "role": "explorer", "label": "Parser scan"},
    )

    assert result["ok"] is True
    assert result["summary"] == "isolated result"
    assert calls == [
        {"task": "Inspect parser files", "role": "explorer", "label": "Parser scan"}
    ]


def test_wait_subagents_delegates_to_runtime_injected_waiter(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    calls = []

    def waiter(**kwargs):
        calls.append(dict(kwargs))
        return {"ok": True, "completed": True, "results": [{"subagent_id": "child-1"}]}

    executor.set_runtime_context(
        project_root=str(tmp_path),
        cwd=str(tmp_path),
        subagent_waiter=waiter,
    )
    result = executor.execute(
        "wait_subagents",
        {"subagent_ids": ["child-1"], "timeout_seconds": 12},
    )

    assert result["ok"] is True
    assert result["completed"] is True
    assert calls == [{"subagent_ids": ["child-1"], "timeout_seconds": 12.0}]


def test_exec_command_runs_enabled_skill_python_directly_from_business_project(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    project_root.mkdir()
    skill_root = tmp_path / "vp-install" / "skills" / "team" / "scripted"
    script = skill_root / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "print(Path.cwd().name + ':' + sys.argv[1])\n"
        "print(__file__)\n",
        encoding="utf-8",
    )
    executor = LocalToolExecutor(_config(tmp_path))
    boundary = {
        "permission_profile": "auto",
        "workspace_read_allowed": True,
        "workspace_write_allowed": True,
        "shell_allowed": True,
        "network_allowed": False,
        "allowed_roots": [str(project_root)],
        "writable_roots": [str(project_root)],
        "command_allowed_roots": [str(project_root), str(skill_root)],
        "enabled_skill_roots": [str(skill_root)],
        "cwd": str(project_root),
        "project_root": str(project_root),
    }
    executor.set_runtime_context(
        execution_mode="host",
        project_root=str(project_root),
        cwd=str(project_root),
        runtime_boundary=boundary,
        reserved_skill_roots=[str(skill_root.parent.parent), str(skill_root.parent)],
    )

    result = executor.exec_command(
        cmd=f"python {shlex.quote(str(script))} {shlex.quote('hello world')}",
        cwd=str(project_root),
        yield_time_ms=3000,
    )

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "business-project:hello world" in result["output"]
    assert str(script) in result["output"]
    assert Path(result["cwd"]) == project_root.resolve()


def test_exec_command_rejects_disabled_skill_script_path(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    project_root.mkdir()
    skill_root = tmp_path / "skills" / "team" / "disabled"
    script = skill_root / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('should not run')\n", encoding="utf-8")
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(
        execution_mode="host",
        project_root=str(project_root),
        cwd=str(project_root),
        runtime_boundary={
            "permission_profile": "auto",
            "workspace_read_allowed": True,
            "workspace_write_allowed": True,
            "shell_allowed": True,
            "network_allowed": False,
            "allowed_roots": [str(project_root)],
            "writable_roots": [str(project_root)],
            "command_allowed_roots": [str(project_root)],
            "enabled_skill_roots": [],
            "cwd": str(project_root),
            "project_root": str(project_root),
        },
        reserved_skill_roots=[str(skill_root.parent.parent)],
    )

    result = executor.exec_command(
        cmd=f"python {shlex.quote(str(script))}",
        cwd=str(project_root),
        yield_time_ms=3000,
    )

    assert result["ok"] is False
    assert result["error_kind"] == "reserved_skill_path"


def test_read_file_allows_enabled_skill_and_rejects_disabled_skill(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    project_root.mkdir()
    enabled_root = tmp_path / "skills" / "team" / "enabled"
    disabled_root = tmp_path / "skills" / "team" / "disabled"
    enabled_file = enabled_root / "SKILL.md"
    disabled_file = disabled_root / "SKILL.md"
    enabled_root.mkdir(parents=True)
    disabled_root.mkdir(parents=True)
    enabled_file.write_text("# Enabled\n", encoding="utf-8")
    disabled_file.write_text("# Disabled\n", encoding="utf-8")
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(
        execution_mode="host",
        project_root=str(project_root),
        cwd=str(project_root),
        runtime_boundary={
            "permission_profile": "auto",
            "workspace_read_allowed": True,
            "workspace_write_allowed": True,
            "shell_allowed": True,
            "network_allowed": False,
            "allowed_roots": [str(project_root), str(enabled_root)],
            "writable_roots": [str(project_root)],
            "command_allowed_roots": [str(project_root), str(enabled_root)],
            "enabled_skill_roots": [str(enabled_root)],
            "cwd": str(project_root),
            "project_root": str(project_root),
        },
        reserved_skill_roots=[str(tmp_path / "skills")],
    )

    enabled_result = executor.read_file(str(enabled_file))
    disabled_result = executor.read_file(str(disabled_file))

    assert enabled_result["ok"] is True
    assert "# Enabled" in enabled_result["content"]
    assert disabled_result["ok"] is False
    assert "out of allowed roots" in str(disabled_result["error"]).lower()


def test_full_access_reads_writes_and_runs_outside_project_without_environment_flag(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    outside_root = tmp_path / "shared-outside-project"
    project_root.mkdir()
    outside_root.mkdir()
    outside_file = outside_root / "note.txt"
    outside_file.write_text("before\n", encoding="utf-8")
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(
        execution_mode="host",
        project_root=str(project_root),
        cwd=str(project_root),
        permission_profile="full_access",
        runtime_boundary={
            "permission_profile": "full_access",
            "workspace_read_allowed": True,
            "workspace_write_allowed": True,
            "shell_allowed": True,
            "network_allowed": True,
            "allowed_roots": [str(project_root)],
            "writable_roots": [str(project_root)],
            "command_allowed_roots": [str(project_root)],
            "cwd": str(project_root),
            "project_root": str(project_root),
        },
    )

    read_result = executor.read_file(str(outside_file))
    patch_result = executor.apply_patch(
        patch=(
            "*** Begin Patch\n"
            f"*** Update File: {outside_file}\n"
            "@@\n"
            "-before\n"
            "+after\n"
            "*** End Patch\n"
        )
    )
    command_result = executor.exec_command(cmd="pwd", cwd=str(outside_root), yield_time_ms=1000)

    assert read_result["ok"] is True
    assert patch_result["ok"] is True
    assert outside_file.read_text(encoding="utf-8") == "after\n"
    assert command_result["ok"] is True
    assert Path(command_result["cwd"]) == outside_root.resolve()


def test_list_dir_is_available_in_a_read_only_runtime_boundary(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    read_root = tmp_path / "shared-read-only"
    project_root.mkdir()
    read_root.mkdir()
    (read_root / "spec.md").write_text("# Spec\n", encoding="utf-8")
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(
        execution_mode="host",
        project_root=str(project_root),
        cwd=str(project_root),
        runtime_boundary={
            "permission_profile": "default",
            "workspace_read_allowed": True,
            "workspace_write_allowed": False,
            "shell_allowed": False,
            "network_allowed": False,
            "allowed_roots": [str(project_root), str(read_root)],
            "writable_roots": [],
            "command_allowed_roots": [],
            "enabled_skill_roots": [],
            "cwd": str(project_root),
            "project_root": str(project_root),
        },
    )

    result = executor.list_dir(str(read_root))

    assert result["ok"] is True
    assert [entry["name"] for entry in result["entries"]] == ["spec.md"]


def test_sessions_list_applies_limit_after_current_project_filter(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.sessions_dir / "wanted.json").write_text(
        json.dumps(
            {
                "id": "wanted",
                "project_id": "current-project",
                "turns": [{"role": "user", "text": "Wanted"}],
            }
        ),
        encoding="utf-8",
    )
    os.utime(config.sessions_dir / "wanted.json", (1, 1))
    for index in range(3):
        other_path = config.sessions_dir / f"other-{index}.json"
        other_path.write_text(
            json.dumps(
                {
                    "id": f"other-{index}",
                    "project_id": "other-project",
                    "turns": [{"role": "user", "text": "Other"}],
                }
            ),
            encoding="utf-8",
        )
        os.utime(other_path, (10 + index, 10 + index))
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_id="current-project")

    result = executor.sessions_list(limit=1)

    assert result["ok"] is True
    assert [item["session_id"] for item in result["sessions"]] == ["wanted"]


def test_image_read_uses_registered_handler_and_model_hint(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    seen: dict[str, str] = {}

    def _handler(*, path: str, prompt: str, max_output_chars: int, model: str) -> dict[str, object]:
        seen["path"] = path
        seen["prompt"] = prompt
        seen["model"] = model
        seen["max_output_chars"] = str(max_output_chars)
        return {
            "ok": True,
            "visible_text": "HELLO",
            "analysis": "tiny test image",
            "model_capability_status": "ok",
        }

    executor.set_runtime_context(model="gpt-test-image")
    executor.set_image_read_handler(_handler)

    result = executor.image_read(str(image_path), prompt="read it", max_output_chars=1234)

    assert result["ok"] is True
    assert result["visible_text"] == "HELLO"
    assert result["analysis"] == "tiny test image"
    assert result["model_capability_status"] == "ok"
    assert seen["path"] == str(image_path)
    assert seen["prompt"] == "read it"
    assert seen["model"] == "gpt-test-image"
    assert seen["max_output_chars"] == "1234"


def test_execute_image_read_accepts_legacy_image_path_argument(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)
    seen: dict[str, str] = {}

    def _handler(*, path: str, prompt: str, max_output_chars: int, model: str) -> dict[str, object]:
        seen["path"] = path
        seen["prompt"] = prompt
        seen["model"] = model
        seen["max_output_chars"] = str(max_output_chars)
        return {
            "ok": True,
            "visible_text": "LEGACY",
            "analysis": "legacy arg alias",
            "model_capability_status": "ok",
        }

    executor.set_runtime_context(model="gpt-test-image")
    executor.set_image_read_handler(_handler)

    result = executor.execute("image_read", {"image_path": str(image_path), "prompt": "legacy", "max_output_chars": 2222})

    assert result["ok"] is True
    assert result["visible_text"] == "LEGACY"
    assert seen["path"] == str(image_path)
    assert seen["prompt"] == "legacy"
    assert seen["model"] == "gpt-test-image"
    assert seen["max_output_chars"] == "2222"


def test_image_read_resolves_upload_id_to_actual_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    upload_id = "att-image-1"
    stored_path = config.uploads_dir / f"{upload_id}__tiny.png"
    stored_path.write_bytes(_ONE_PIXEL_PNG)
    (config.uploads_dir / "index.json").write_text(
        json.dumps(
            {
                upload_id: {
                    "id": upload_id,
                    "original_name": "tiny.png",
                    "safe_name": "tiny.png",
                    "path": str(stored_path),
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    seen: dict[str, str] = {}

    def _handler(*, path: str, prompt: str, max_output_chars: int, model: str) -> dict[str, object]:
        seen["path"] = path
        _ = (prompt, max_output_chars, model)
        return {
            "ok": True,
            "visible_text": "UPLOAD",
            "analysis": "resolved from upload id",
            "model_capability_status": "ok",
        }

    executor.set_image_read_handler(_handler)

    result = executor.image_read(upload_id)

    assert result["ok"] is True
    assert seen["path"] == str(stored_path.resolve())
    assert result["path"] == str(stored_path.resolve())


def test_image_read_uses_local_ocr_when_no_runtime_handler(tmp_path: Path, monkeypatch) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_rapidocr_ocr",
        lambda self, path, max_output_chars: {
            "ok": True,
            "engine": "rapidocr",
            "available": True,
            "visible_text": "HELLO OCR"[:max_output_chars],
        },
    )

    result = executor.image_read(str(image_path))

    assert result["ok"] is True
    assert result["visible_text"] == "HELLO OCR"
    assert result["read_strategy"] == "ocr_only"
    assert result["fallback_reason"] == "no_runtime_image_reader"
    assert result["ocr_available"] is True
    assert result["engines_tried"] == ["rapidocr"]
    assert result["model_capability_status"] == "not_invoked"
    assert result["summary"] == "image_read · ocr_only · rapidocr"
    assert result["diagnostics"]["visible_text_preview"] == "HELLO OCR"


def test_image_read_falls_back_to_tesseract_when_rapidocr_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_rapidocr_ocr",
        lambda self, path, max_output_chars: {
            "ok": False,
            "engine": "rapidocr",
            "available": False,
            "error": "rapidocr unavailable",
        },
    )
    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_tesseract_ocr",
        lambda self, path, max_output_chars: {
            "ok": True,
            "engine": "tesseract",
            "available": True,
            "visible_text": "TESSERACT OCR"[:max_output_chars],
        },
    )

    result = executor.image_read(str(image_path))

    assert result["ok"] is True
    assert result["visible_text"] == "TESSERACT OCR"
    assert result["read_strategy"] == "ocr_only"
    assert result["engines_tried"] == ["rapidocr", "tesseract"]
    assert result["ocr_available"] is True


def test_image_read_stays_successful_when_model_visual_path_is_unsupported(tmp_path: Path, monkeypatch) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_rapidocr_ocr",
        lambda self, path, max_output_chars: {
            "ok": True,
            "engine": "rapidocr",
            "available": True,
            "visible_text": "LOCAL OCR"[:max_output_chars],
        },
    )

    def _handler(*, path: str, prompt: str, max_output_chars: int, model: str) -> dict[str, object]:
        _ = (path, prompt, max_output_chars, model)
        return {
            "ok": False,
            "error": "vision unsupported",
            "model_capability_status": "unsupported_by_model",
            "visible_text": "",
            "analysis": "",
        }

    executor.set_image_read_handler(_handler)
    result = executor.image_read(str(image_path))

    assert result["ok"] is True
    assert result["visible_text"] == "LOCAL OCR"
    assert result["read_strategy"] == "ocr_only"
    assert result["model_capability_status"] == "unsupported_by_model"
    assert result["fallback_reason"] == "unsupported_by_model"


def test_image_read_reports_ocr_unavailable_without_runtime_handler(tmp_path: Path, monkeypatch) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    image_path = tmp_path / "tiny.png"
    image_path.write_bytes(_ONE_PIXEL_PNG)

    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_rapidocr_ocr",
        lambda self, path, max_output_chars: {
            "ok": False,
            "engine": "rapidocr",
            "available": False,
            "error": "rapidocr unavailable",
        },
    )
    monkeypatch.setattr(
        LocalToolExecutor,
        "_run_tesseract_ocr",
        lambda self, path, max_output_chars: {
            "ok": False,
            "engine": "tesseract",
            "available": False,
            "error": "tesseract missing",
        },
    )

    result = executor.image_read(str(image_path))

    assert result["ok"] is False
    assert result["fallback_reason"] == "ocr_unavailable"
    assert result["ocr_available"] is False
    assert result["summary"] == "image_read · ocr_unavailable"
    assert "rapidocr unavailable" in str(result["error"])
    assert result["diagnostics"]["fallback_reason"] == "ocr_unavailable"


def test_ocr_status_prefers_rapidocr_and_reports_fallbacks(tmp_path: Path, monkeypatch) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    monkeypatch.setattr(LocalToolExecutor, "_probe_rapidocr_status", staticmethod(lambda: (True, "")))
    monkeypatch.setattr(LocalToolExecutor, "_probe_tesseract_status", staticmethod(lambda: (False, "tesseract is not installed")))

    status = executor.ocr_status()

    assert status["rapidocr_available"] is True
    assert status["tesseract_available"] is False
    assert status["default_engine"] == "rapidocr"
    assert status["warning"] == ""


def test_read_file_and_search_tools_use_canonical_names(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    code_path = tmp_path / "app.py"
    code_path.write_text("def build_progress():\n    return 'progress checklist'\n", encoding="utf-8")

    read_result = executor.read_file(str(code_path))
    search_result = executor.search_contents_in_file(str(code_path), "progress checklist")
    multi_result = executor.search_contents_in_file_multi(str(code_path), ["build_progress", "checklist"])

    assert read_result["ok"] is True
    assert read_result["tool_name"] == "read_file"
    assert "progress checklist" in str(read_result.get("content") or "")
    assert search_result["ok"] is True
    assert search_result["tool_name"] == "search_contents_in_file"
    assert search_result["match_count"] >= 1
    assert multi_result["ok"] is True
    assert multi_result["tool_name"] == "search_contents_in_file_multi"
    assert multi_result["match_count"] >= 2


def test_list_dir_lists_children_and_glob_file_search_finds_matches(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    list_result = executor.list_dir(".")
    glob_result = executor.glob_file_search("**/*.py")

    assert list_result["ok"] is True
    assert list_result["tool_name"] == "list_dir"
    assert {item["name"] for item in list_result["entries"]} >= {"src", "README.md"}
    assert {item["type"] for item in list_result["entries"]} >= {"directory", "file"}
    assert glob_result["ok"] is True
    assert glob_result["tool_name"] == "glob_file_search"
    assert "src/main.py" in glob_result["matches"]


def test_list_dir_rejects_non_directory_and_glob_file_search_handles_no_matches(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello\n", encoding="utf-8")

    list_result = executor.list_dir(str(file_path))
    glob_result = executor.glob_file_search("**/*.js")

    assert list_result["ok"] is False
    assert "Not a directory" in str(list_result["error"])
    assert glob_result["ok"] is True
    assert glob_result["tool_name"] == "glob_file_search"
    assert glob_result["count"] == 0
    assert glob_result["matches"] == []


def test_removed_legacy_public_tool_names_return_unknown_tool(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    sample_path = tmp_path / "README.md"
    sample_path.write_text("demo\n", encoding="utf-8")

    for name, arguments in (
        ("read_text_file", {"path": str(sample_path)}),
        ("search_text_in_file", {"path": str(sample_path), "query": "demo"}),
        ("multi_query_search", {"path": str(sample_path), "queries": ["demo"]}),
        ("read_section_by_heading", {"path": str(sample_path), "heading": "demo"}),
        ("download_web_file", {"url": "https://example.com"}),
        ("view_image", {"path": str(sample_path)}),
        ("list_sessions", {"max_sessions": 5}),
        ("read_session_history", {"session_id": "demo"}),
        ("search_web", {"query": "demo"}),
        ("fetch_web", {"url": "https://example.com"}),
        ("read", {"path": str(sample_path)}),
        ("search_file", {"path": str(sample_path), "query": "demo"}),
        ("search_file_multi", {"path": str(sample_path), "queries": ["demo"]}),
    ):
        result = executor.execute(name, arguments)
        assert result["ok"] is False
        assert result["error"]["kind"] == "unknown_tool"
        assert result["error"]["tool"] == name


def test_read_file_rejects_directory_path(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))

    result = executor.read_file(str(tmp_path))

    assert result["ok"] is False
    assert "Use list_dir instead" in str(result["error"])


def test_glob_file_search_returns_project_relative_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    app_dir = tmp_path / "app"
    app_dir.mkdir(exist_ok=True)
    (app_dir / "local_tools.py").write_text("x = 1\n", encoding="utf-8")
    (app_dir / "runtime.py").write_text("y = 2\n", encoding="utf-8")

    result = executor.glob_file_search(pattern="*.py", path="app")

    assert result["ok"] is True
    assert "app/local_tools.py" in result["matches"]
    assert "app/runtime.py" in result["matches"]
    assert not any(str(tmp_path) in item for item in result["matches"])
    assert result["root_ref"] == "project_root"


def test_list_dir_returns_project_relative_entry_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    app_dir = tmp_path / "app"
    app_dir.mkdir(exist_ok=True)
    (app_dir / "local_tools.py").write_text("x = 1\n", encoding="utf-8")

    result = executor.list_dir(path="app")

    assert result["ok"] is True
    assert result["path"] == "app"
    assert result["root_ref"] == "project_root"
    entry_paths = {str(item.get("path") or "") for item in result["entries"]}
    assert "app/local_tools.py" in entry_paths
    assert not any(str(tmp_path) in path for path in entry_paths)


def test_read_file_returns_project_relative_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    app_dir = tmp_path / "app"
    app_dir.mkdir(exist_ok=True)
    (app_dir / "local_tools.py").write_text("hello\n", encoding="utf-8")

    result = executor.read_file(path="app/local_tools.py")

    assert result["ok"] is True
    assert result["path"] == "app/local_tools.py"
    assert result["root_ref"] == "project_root"
    assert result["resolved_path"] == str((app_dir / "local_tools.py").resolve())


def test_search_codebase_returns_project_relative_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    app_dir = tmp_path / "app"
    app_dir.mkdir(exist_ok=True)
    target = app_dir / "runtime.py"
    target.write_text("def target_function():\n    return 1\n", encoding="utf-8")

    result = executor.search_codebase(query="target_function", root=".")

    assert result["ok"] is True
    assert result["matches"]
    assert result["matches"][0]["path"] == "app/runtime.py"
    assert str(tmp_path) not in result["matches"][0]["path"]


def test_broad_glob_in_large_directory_returns_guidance(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    for index in range(600):
        (tmp_path / f"file_{index}.txt").write_text(str(index), encoding="utf-8")

    result = executor.glob_file_search(pattern="**/*", path=".")

    assert result["ok"] is False
    assert result["error"]["kind"] == "broad_glob_on_large_directory"
    assert result["total_matches"] >= 600
    assert "suggested_next_steps" in result
    assert len(json.dumps(result, ensure_ascii=False)) < 20000


def test_broad_glob_in_small_directory_still_works(tmp_path: Path) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    executor.set_runtime_context(project_root=str(tmp_path), cwd=str(tmp_path))
    for index in range(5):
        (tmp_path / f"file_{index}.txt").write_text(str(index), encoding="utf-8")

    result = executor.glob_file_search(pattern="**/*", path=".")

    assert result["ok"] is True
    for index in range(5):
        assert f"file_{index}.txt" in result["matches"]


def test_read_file_returns_email_meta_and_attachment_list(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    executor = LocalToolExecutor(config)
    msg_path = tmp_path / "sample.msg"
    msg_path.write_bytes(b"fake-msg")

    def _fake_extract(path: str, max_chars: int = 0) -> dict[str, object]:
        _ = max_chars
        return {
            "content": "Subject: Demo\n\nBody",
            "email_meta": {
                "subject": "Demo",
                "sender": "alice@example.com",
                "to": "bob@example.com",
                "cc": "",
                "date": "2026-04-19T10:00:00Z",
                "class_type": "IPM.Note",
            },
            "attachment_list": [
                {"name": "chart.png", "size": 123, "mime_hint": "image/png"},
            ],
        }

    monkeypatch.setattr("app.attachments.extract_outlook_msg_payload", _fake_extract)

    result = executor.read_file(str(msg_path))

    assert result["ok"] is True
    assert result["tool_name"] == "read_file"
    assert result["source_format"] == "msg_text_extracted"
    assert result["email_meta"]["subject"] == "Demo"
    assert result["attachment_list"][0]["name"] == "chart.png"
    assert "Body" in str(result.get("content") or "")


def test_apply_patch_supports_check_create_update_and_delete(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    add_patch = "*** Begin Patch\n*** Add File: notes.txt\n+hello\n*** End Patch\n"
    update_patch = "*** Begin Patch\n*** Update File: notes.txt\n@@\n-hello\n+hello world\n*** End Patch\n"
    delete_patch = "*** Begin Patch\n*** Delete File: notes.txt\n*** End Patch\n"

    cwd = str(tmp_path)
    check_result = executor.apply_patch(add_patch, cwd=cwd, check=True)
    assert check_result["ok"] is True
    assert check_result["summary"] == "patch validated"
    assert (tmp_path / "notes.txt").exists() is False

    add_result = executor.apply_patch(add_patch, cwd=cwd)

    assert add_result["ok"] is True
    assert add_result["summary"] == "patch applied"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello\n"
    update_result = executor.apply_patch(update_patch, cwd=cwd)
    assert update_result["ok"] is True
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello world\n"
    delete_result = executor.apply_patch(delete_patch, cwd=cwd)
    assert delete_result["ok"] is True
    assert (tmp_path / "notes.txt").exists() is False


def test_apply_patch_returns_structured_failure_for_missing_target(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    delete_patch = "*** Begin Patch\n*** Delete File: missing.txt\n*** End Patch\n"

    result = executor.apply_patch(delete_patch, cwd=str(tmp_path))

    assert result["ok"] is False
    assert "File not found: missing.txt" in str(result["error"])
    assert result["files"] == []


def test_apply_patch_add_existing_file_returns_actionable_structured_failure(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    target = tmp_path / "existing.txt"
    target.write_text("keep me\n", encoding="utf-8")
    add_patch = "*** Begin Patch\n*** Add File: existing.txt\n+replacement\n*** End Patch\n"

    result = executor.apply_patch(add_patch, cwd=str(tmp_path))

    assert result["ok"] is False
    assert result["error"]["kind"] == "file_already_exists"
    assert result["error"]["operation"] == "add"
    assert "*** Update File: existing.txt" in result["error"]["recovery"]
    assert target.read_text(encoding="utf-8") == "keep me\n"


def test_apply_patch_requires_runtime_write_scope_for_team_and_rejects_project_skill_paths(tmp_path: Path) -> None:
    executor = LocalToolExecutor(_config(tmp_path))
    team_root = tmp_path / "vp-install" / "skills" / "team"
    executor.set_runtime_context(
        project_root=str(tmp_path),
        cwd=str(tmp_path),
        runtime_boundary={
            "workspace_write_allowed": True,
            "allowed_roots": [str(tmp_path), str(team_root)],
            "writable_roots": [str(tmp_path), str(team_root)],
            "command_allowed_roots": [str(tmp_path), str(team_root)],
            "team_skill_write_allowed": False,
        },
        reserved_skill_roots=[str(team_root)],
        team_skill_roots=[str(team_root)],
    )

    team_result = executor.apply_patch(
        "*** Begin Patch\n*** Add File: vp-install/skills/team/demo/SKILL.md\n+# Team\n*** End Patch\n",
        cwd=str(tmp_path),
    )
    project_result = executor.apply_patch(
        "*** Begin Patch\n*** Add File: .agents/skills/demo/SKILL.md\n+# Project\n*** End Patch\n",
        cwd=str(tmp_path),
    )

    assert team_result["ok"] is False
    assert team_result["error"]["kind"] == "reserved_skill_path"
    assert "RuntimeBoundary writable scope" in team_result["error"]["message"]
    assert "cannot edit bundled scripts" in team_result["error"]["recovery"]
    assert project_result["ok"] is False
    assert project_result["error"]["kind"] == "reserved_skill_path"
    assert not (tmp_path / ".agents").exists()


def test_apply_patch_updates_existing_team_skill_script_when_runtime_boundary_allows(tmp_path: Path) -> None:
    project_root = tmp_path / "business-project"
    project_root.mkdir()
    team_root = tmp_path / "vp-install" / "skills" / "team"
    skill_root = team_root / "scripted"
    script = skill_root / "scripts" / "collect_env.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('old')\n", encoding="utf-8")
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(
        project_root=str(project_root),
        cwd=str(project_root),
        runtime_boundary={
            "workspace_write_allowed": True,
            "allowed_roots": [str(project_root), str(skill_root)],
            "writable_roots": [str(project_root), str(skill_root)],
            "command_allowed_roots": [str(project_root), str(skill_root)],
            "team_skill_write_allowed": True,
        },
        reserved_skill_roots=[str(team_root)],
        builtin_skill_roots=[str(tmp_path / "vp-install" / "skills" / "builtin")],
        team_skill_roots=[str(team_root)],
    )
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {script}\n"
        "@@\n"
        "-print('old')\n"
        "+import os\n"
        "+print(os.environ.get('VP_MODE', ''))\n"
        "*** End Patch\n"
    )

    result = executor.apply_patch(patch, cwd=str(project_root))

    assert result["ok"] is True
    assert "os.environ.get" in script.read_text(encoding="utf-8")


def test_apply_patch_never_modifies_builtin_skill_even_if_root_is_writable(tmp_path: Path) -> None:
    builtin_root = tmp_path / "skills" / "builtin"
    skill_file = builtin_root / "protected" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# Protected\n", encoding="utf-8")
    executor = LocalToolExecutor(_config(tmp_path))
    executor.set_runtime_context(
        project_root=str(tmp_path),
        cwd=str(tmp_path),
        runtime_boundary={
            "workspace_write_allowed": True,
            "allowed_roots": [str(tmp_path), str(builtin_root)],
            "writable_roots": [str(tmp_path), str(builtin_root)],
            "command_allowed_roots": [str(tmp_path), str(builtin_root)],
            "team_skill_write_allowed": True,
        },
        reserved_skill_roots=[str(builtin_root)],
        builtin_skill_roots=[str(builtin_root)],
        team_skill_roots=[str(tmp_path / "skills" / "team")],
    )
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {skill_file}\n"
        "@@\n"
        "-# Protected\n"
        "+# Changed\n"
        "*** End Patch\n"
    )

    result = executor.apply_patch(patch, cwd=str(tmp_path))

    assert result["ok"] is False
    assert result["error"]["kind"] == "reserved_skill_path"
    assert "read-only" in result["error"]["message"]
    assert skill_file.read_text(encoding="utf-8") == "# Protected\n"
