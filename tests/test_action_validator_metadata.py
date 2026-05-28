from __future__ import annotations

from pathlib import Path

from app.action_validator import ActionValidator
from app.runtime_boundary import RuntimeBoundary


def _tool_specs() -> list[dict]:
    return [
        {
            "name": "read_file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "apply_patch",
            "parameters": {
                "type": "object",
                "properties": {"patch": {"type": "string"}},
                "required": ["patch"],
                "additionalProperties": False,
            },
        },
        {
            "name": "browser_open",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
        {
            "name": "custom_tool",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    ]


def _validator(tmp_path: Path, *, allowed_tools: list[str] | None = None, **boundary_overrides) -> ActionValidator:
    browser_allowed = bool(boundary_overrides.pop("browser_allowed", True))
    boundary = RuntimeBoundary(
        allowed_roots=[str(tmp_path)],
        writable_roots=[str(tmp_path)],
        command_allowed_roots=[str(tmp_path)],
        cwd=str(tmp_path),
        project_root=str(tmp_path),
        browser_allowed=browser_allowed,
        **boundary_overrides,
    )
    return ActionValidator(
        tool_specs=_tool_specs(),
        allowed_tools=allowed_tools or [item["name"] for item in _tool_specs()],
        boundary=boundary,
        locale="en",
    )


def test_unknown_tool_rejected_before_metadata_check(tmp_path: Path) -> None:
    result = _validator(tmp_path, workspace_write_allowed=False).validate_tool_call({"name": "missing_tool", "args": {}})

    assert not result.allowed
    assert result.code == "unknown_tool"
    assert result.schema_validation["checked"] is False


def test_tool_not_allowed_rejected_before_metadata_check(tmp_path: Path) -> None:
    result = _validator(
        tmp_path,
        allowed_tools=["read_file"],
        workspace_write_allowed=False,
    ).validate_tool_call({"name": "apply_patch", "args": {}})

    assert not result.allowed
    assert result.code == "tool_not_allowed"
    assert result.schema_validation["checked"] is False


def test_metadata_capability_rejects_workspace_write_when_not_allowed(tmp_path: Path) -> None:
    result = _validator(tmp_path, workspace_write_allowed=False).validate_tool_call({"name": "apply_patch", "args": {}})

    assert not result.allowed
    assert result.code == "workspace_write_not_allowed"
    assert result.schema_validation["checked"] is False


def test_browser_capability_check_can_deny_browser_tools(tmp_path: Path) -> None:
    result = _validator(tmp_path, browser_allowed=False, network_allowed=True).validate_tool_call(
        {"name": "browser_open", "args": {"url": "https://example.com"}}
    )

    assert not result.allowed
    assert result.code == "browser_not_allowed"
    assert result.schema_validation["checked"] is False


def test_schema_validation_still_rejects_invalid_arguments(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "read_file", "args": {}})

    assert not result.allowed
    assert result.code == "missing_required_argument"
    assert result.schema_validation["checked"] is True


def test_path_boundary_validation_still_runs_after_metadata_check(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = _validator(tmp_path).validate_tool_call({"name": "read_file", "args": {"path": str(outside)}})

    assert not result.allowed
    assert result.code == "path_outside_allowed_roots"


def test_missing_metadata_preserves_current_behavior(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "custom_tool", "args": {"value": "ok"}})

    assert result.allowed
    assert result.code == "allowed"
