from __future__ import annotations

from pathlib import Path

from app.action_validator import ActionValidator, ValidationResult, validation_observation
from app.runtime_boundary import RuntimeBoundary
from app.serialization import dump_model


def _tool_specs() -> list[dict]:
    return [
        {
            "name": "update_plan",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "status": {"type": "string"},
                            },
                            "required": ["step", "status"],
                        },
                    }
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_dir",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
                "additionalProperties": False,
            },
        },
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
            "name": "web_download",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "dst_path": {"type": "string"},
                },
                "required": ["url", "dst_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "exec_command",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}, "cwd": {"type": "string", "default": "."}},
                "required": ["cmd"],
                "additionalProperties": False,
            },
        },
        {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    ]


def _validator(tmp_path: Path, **boundary_overrides) -> ActionValidator:
    boundary = RuntimeBoundary(
        allowed_roots=[str(tmp_path)],
        writable_roots=[str(tmp_path / "writable")],
        command_allowed_roots=[str(tmp_path)],
        cwd=str(tmp_path),
        project_root=str(tmp_path),
        **boundary_overrides,
    )
    (tmp_path / "writable").mkdir(exist_ok=True)
    return ActionValidator(
        tool_specs=_tool_specs(),
        allowed_tools=[item["name"] for item in _tool_specs()],
        boundary=boundary,
        locale="en",
    )


def test_unknown_tool_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "missing_tool", "args": {}})

    assert not result.allowed
    assert result.code == "unknown_tool"


def test_tool_not_allowed_rejected(tmp_path: Path) -> None:
    validator = ActionValidator(
        tool_specs=_tool_specs(),
        allowed_tools=["list_dir"],
        boundary=RuntimeBoundary(allowed_roots=[str(tmp_path)], writable_roots=[str(tmp_path)], cwd=str(tmp_path), project_root=str(tmp_path)),
    )

    result = validator.validate_tool_call({"name": "read_file", "args": {"path": "a.txt"}})

    assert not result.allowed
    assert result.code == "tool_not_allowed"


def test_update_plan_missing_plan_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "update_plan", "args": {}})

    assert not result.allowed
    assert result.code == "missing_required_argument"
    assert "plan" in result.message


def test_update_plan_valid_plan_allowed(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call(
        {"name": "update_plan", "args": {"plan": [{"step": "Inspect", "status": "in_progress"}]}}
    )

    assert result.allowed
    assert result.normalized_arguments["plan"][0]["step"] == "Inspect"


def test_list_dir_inside_allowed_root_allowed(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "list_dir", "args": {"path": "."}})

    assert result.allowed
    assert result.code == "allowed"


def test_list_dir_outside_allowed_root_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)

    result = _validator(tmp_path).validate_tool_call({"name": "list_dir", "args": {"path": str(outside)}})

    assert not result.allowed
    assert result.code == "path_outside_allowed_roots"


def test_read_file_path_traversal_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "read_file", "args": {"path": "../secret.txt"}})

    assert not result.allowed
    assert result.code == "path_outside_allowed_roots"


def test_write_file_when_write_disabled_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path, workspace_write_allowed=False).validate_tool_call(
        {"name": "web_download", "args": {"url": "https://example.com/file.txt", "dst_path": "writable/out.txt"}}
    )

    assert not result.allowed
    assert result.code == "workspace_write_not_allowed"


def test_write_file_inside_writable_root_allowed(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call(
        {"name": "web_download", "args": {"url": "https://example.com/file.txt", "dst_path": "writable/out.txt"}}
    )

    assert result.allowed


def test_exec_command_when_shell_disabled_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path, shell_allowed=False).validate_tool_call(
        {"name": "exec_command", "args": {"cmd": "pwd", "cwd": "."}}
    )

    assert not result.allowed
    assert result.code == "shell_not_allowed"


def test_exec_command_safe_command_allowed_when_shell_enabled(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "exec_command", "args": {"cmd": "python -m pytest", "cwd": "."}})

    assert result.allowed


def test_dangerous_command_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call({"name": "exec_command", "args": {"cmd": "sudo rm -rf /", "cwd": "."}})

    assert not result.allowed
    assert result.code == "dangerous_command"


def test_exec_command_path_argument_outside_project_rejected(tmp_path: Path) -> None:
    result = _validator(tmp_path).validate_tool_call(
        {"name": "exec_command", "args": {"cmd": "rg foo /etc", "cwd": "."}}
    )

    assert not result.allowed
    assert result.code == "command_path_outside_allowed_roots"


def test_git_dash_c_outside_project_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-git"
    outside.mkdir(exist_ok=True)

    result = _validator(tmp_path).validate_tool_call(
        {"name": "exec_command", "args": {"cmd": f"git -C {outside} status", "cwd": "."}}
    )

    assert not result.allowed
    assert result.code == "command_path_outside_allowed_roots"


def test_python_script_outside_project_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("print('x')", encoding="utf-8")

    result = _validator(tmp_path).validate_tool_call(
        {"name": "exec_command", "args": {"cmd": f"python {outside}", "cwd": "."}}
    )

    assert not result.allowed
    assert result.code == "command_path_outside_allowed_roots"


def test_network_tool_rejected_when_network_disabled(tmp_path: Path) -> None:
    result = _validator(tmp_path, network_allowed=False).validate_tool_call(
        {"name": "web_fetch", "args": {"url": "https://example.com"}}
    )

    assert not result.allowed
    assert result.code == "network_not_allowed"


def test_validation_result_serializes_cleanly() -> None:
    result = ValidationResult(allowed=False, code="invalid_arguments", message="bad")
    payload = dump_model({"result": result, "observation": validation_observation(result, tool="demo")})

    assert payload["result"]["code"] == "invalid_arguments"
    assert payload["observation"]["type"] == "validation_error"
