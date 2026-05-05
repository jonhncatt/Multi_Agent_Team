from __future__ import annotations

import base64
import json
from pathlib import Path

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
    config.shadow_logs_dir = tmp_path / "shadow_logs"
    config.token_stats_path = tmp_path / "token_stats.json"
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    config.shadow_logs_dir.mkdir(parents=True, exist_ok=True)
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
    }.issubset(tool_names)
    assert {
        "read_text_file",
        "search_text_in_file",
        "multi_query_search",
        "read_section_by_heading",
        "download_web_file",
        "view_image",
        "list_sessions",
        "read_session_history",
        "read",
        "search_file",
        "search_file_multi",
    }.isdisjoint(tool_names)


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
    assert any(path.endswith("/src/main.py") for path in glob_result["matches"])


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
