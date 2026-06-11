from __future__ import annotations

import inspect

from app.local_tools import LocalToolExecutor


CANONICAL_TOOL_NAMES = {
    "exec_command",
    "write_stdin",
    "apply_patch",
    "read_file",
    "list_dir",
    "glob_file_search",
    "search_contents_in_file",
    "search_contents_in_file_multi",
    "read_section",
    "search_codebase",
    "table_extract",
    "fact_check_file",
    "web_search",
    "web_fetch",
    "web_download",
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_wait",
    "browser_scroll",
    "browser_snapshot",
    "browser_screenshot",
    "image_inspect",
    "image_read",
    "sessions_list",
    "sessions_history",
    "archive_extract",
    "mail_extract_attachments",
    "update_plan",
    "request_user_input",
}

FORBIDDEN_PUBLIC_METHODS = {
    "run_shell",
    "list_directory",
    "doc_index_build",
    "copy_file",
    "extract_zip",
    "extract_msg_attachments",
    "write_text_file",
    "append_text_file",
    "replace_in_file",
    "list_skills",
    "read_skill",
    "write_skill",
    "toggle_skill",
    "list_agent_specs",
    "read_agent_spec",
    "write_agent_spec",
}

ALLOWED_PUBLIC_NON_TOOL_METHODS = {
    "clear_runtime_context",
    "docker_available",
    "docker_status",
    "execute",
    "ocr_status",
    "set_image_read_handler",
    "set_runtime_context",
}


def _public_methods() -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(LocalToolExecutor, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_local_tool_executor_has_no_public_noncanonical_tool_methods() -> None:
    assert _public_methods().isdisjoint(FORBIDDEN_PUBLIC_METHODS)


def test_local_tool_executor_canonical_public_methods_exist() -> None:
    for name in CANONICAL_TOOL_NAMES:
        assert hasattr(LocalToolExecutor, name)


def test_public_tool_like_methods_are_canonical_only() -> None:
    unexpected = _public_methods() - CANONICAL_TOOL_NAMES - ALLOWED_PUBLIC_NON_TOOL_METHODS

    assert unexpected == set()


def test_cleanup_helpers_are_private_only() -> None:
    assert hasattr(LocalToolExecutor, "_list_dir_impl")
    assert hasattr(LocalToolExecutor, "_archive_extract_impl")
    assert hasattr(LocalToolExecutor, "_mail_extract_attachments_impl")
    assert not hasattr(LocalToolExecutor, "list_directory")
    assert not hasattr(LocalToolExecutor, "extract_zip")
    assert not hasattr(LocalToolExecutor, "extract_msg_attachments")
