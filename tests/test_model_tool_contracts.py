from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from app.config import load_config
from app.local_tools import (
    APPLY_PATCH_ARGUMENT_DESCRIPTION,
    APPLY_PATCH_TOOL_DESCRIPTION,
    LocalToolExecutor,
)
from app.vp_runtime_backend import VPRuntimeBackend


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


def _tool_surfaces(tmp_path: Path):
    executor = LocalToolExecutor(_config(tmp_path))
    backend = VPRuntimeBackend(executor.config, tool_executor=executor)
    model_specs = {
        item["function"]["name"]: item["function"]
        for item in (
            convert_to_openai_tool(tool)
            for tool in backend.build_langchain_tools()
        )
    }
    runtime_specs = {
        str(item.get("name") or ""): item
        for item in executor.tool_specs
        if str(item.get("name") or "")
    }
    return backend, model_specs, runtime_specs


def _missing_property_descriptions(schema: dict[str, Any], prefix: str = "") -> list[str]:
    missing: list[str] = []
    for name, prop in dict(schema.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        if not str(prop.get("description") or "").strip():
            missing.append(path)
        if prop.get("type") == "object":
            missing.extend(_missing_property_descriptions(prop, path))
        items = prop.get("items")
        if isinstance(items, dict) and items.get("type") == "object":
            missing.extend(_missing_property_descriptions(items, f"{path}[]"))
    return missing


def _empty_enum_values(value: Any, prefix: str = "") -> list[str]:
    invalid: list[str] = []
    if isinstance(value, dict):
        enum_values = value.get("enum")
        if isinstance(enum_values, list) and any(item == "" for item in enum_values):
            invalid.append(prefix or "<root>")
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            invalid.extend(_empty_enum_values(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            invalid.extend(_empty_enum_values(child, f"{prefix}[{index}]"))
    return invalid


def test_every_runtime_tool_has_one_model_visible_contract(tmp_path: Path) -> None:
    backend, model_specs, runtime_specs = _tool_surfaces(tmp_path)

    assert set(model_specs) == set(runtime_specs)
    assert len(model_specs) == 36
    for name, model_spec in model_specs.items():
        assert str(model_spec.get("description") or "").strip(), name
        assert _missing_property_descriptions(model_spec["parameters"]) == [], name
        model_fields = set(dict(model_spec["parameters"].get("properties") or {}))
        runtime_fields = set(dict(runtime_specs[name]["parameters"].get("properties") or {}))
        assert model_fields <= runtime_fields, name
        assert _empty_enum_values(model_spec) == [], name
        assert _empty_enum_values(runtime_specs[name]) == [], name

    for tool in backend.build_langchain_tools():
        callable_fields = set(inspect.signature(tool.func).parameters)
        assert set(tool.args_schema.model_fields) <= callable_fields, tool.name


def test_apply_patch_contract_exposes_operation_selection_and_grammar(tmp_path: Path) -> None:
    _, model_specs, runtime_specs = _tool_surfaces(tmp_path)
    model_spec = model_specs["apply_patch"]
    runtime_spec = runtime_specs["apply_patch"]

    assert model_spec["description"] == APPLY_PATCH_TOOL_DESCRIPTION
    assert runtime_spec["description"] == APPLY_PATCH_TOOL_DESCRIPTION
    assert model_spec["parameters"]["properties"]["patch"]["description"] == APPLY_PATCH_ARGUMENT_DESCRIPTION
    assert runtime_spec["parameters"]["properties"]["patch"]["description"] == APPLY_PATCH_ARGUMENT_DESCRIPTION
    for marker in (
        "*** Add File:",
        "*** Update File:",
        "*** Delete File:",
        "*** Begin Patch",
        "*** End Patch",
        "@@",
        "*** Move to:",
    ):
        assert marker in f"{model_spec['description']} {APPLY_PATCH_ARGUMENT_DESCRIPTION}"
    assert "existing or previously read file" in model_spec["description"]
    assert "Never use Add File to replace an existing file" in model_spec["description"]


def test_structured_choices_are_visible_to_the_model(tmp_path: Path) -> None:
    _, specs, _ = _tool_surfaces(tmp_path)

    plan_item = specs["update_plan"]["parameters"]["properties"]["plan"]["items"]
    assert plan_item["properties"]["status"]["enum"] == ["pending", "in_progress", "completed"]
    questions = specs["request_user_input"]["parameters"]["properties"]["questions"]
    assert (questions["minItems"], questions["maxItems"]) == (1, 3)
    assert (questions["items"]["properties"]["options"]["minItems"], questions["items"]["properties"]["options"]["maxItems"]) == (2, 3)
    assert specs["spawn_subagent"]["parameters"]["properties"]["role"]["enum"] == [
        "explorer",
        "tester",
        "analyst",
        "summarizer",
    ]
    assert specs["browser_wait"]["parameters"]["properties"]["state"]["enum"] == [
        "attached",
        "detached",
        "visible",
        "hidden",
    ]
    assert specs["browser_scroll"]["parameters"]["properties"]["direction"]["enum"] == [
        "down",
        "up",
        "left",
        "right",
    ]
    assert specs["list_tasks"]["parameters"]["properties"]["project_scope"]["enum"] == [
        "current_project",
        "all_projects",
    ]
    assert specs["list_tasks"]["parameters"]["properties"]["detail_level"]["enum"] == [
        "summary",
        "full",
    ]
    assert "enum" not in specs["list_tasks"]["parameters"]["properties"]["status"]


def test_tool_contracts_expose_non_obvious_side_effects_and_limits(tmp_path: Path) -> None:
    _, specs, _ = _tool_surfaces(tmp_path)

    assert "does not allocate a PTY" in specs["exec_command"]["parameters"]["properties"]["tty"]["description"]
    assert "purpose" in specs["exec_command"]["parameters"]["required"]
    assert "display-only" in specs["exec_command"]["parameters"]["properties"]["purpose"]["description"]
    assert "untrusted" in specs["web_download"]["description"]
    assert "untrusted provenance" in specs["archive_extract"]["description"]
    assert "current project" in specs["sessions_list"]["description"]
    assert "heuristic" in specs["fact_check_file"]["description"]
    assert "OpenXML Excel" in specs["table_extract"]["parameters"]["properties"]["path"]["description"]
    assert "frontmatter" in specs["save_skill"]["parameters"]["properties"]["body"]["description"]
    assert "overwrite is true" in specs["save_skill"]["description"]


def test_nested_structured_arguments_reach_runtime_as_plain_dicts(tmp_path: Path) -> None:
    backend, _, _ = _tool_surfaces(tmp_path)
    tools = {tool.name: tool for tool in backend.build_langchain_tools()}

    plan_result = json.loads(
        tools["update_plan"].invoke(
            {"plan": [{"step": "Inspect contracts", "status": "completed"}]}
        )
    )
    question_result = json.loads(
        tools["request_user_input"].invoke(
            {
                "questions": [
                    {
                        "header": "Choice",
                        "id": "next_step",
                        "question": "Which direction should we take?",
                        "options": [
                            {"label": "A", "description": "Take the first direction."},
                            {"label": "B", "description": "Take the second direction."},
                        ],
                    }
                ]
            }
        )
    )

    assert plan_result["ok"] is True
    assert plan_result["plan"] == [{"step": "Inspect contracts", "status": "completed"}]
    assert question_result["ok"] is True
    assert question_result["questions"][0]["id"] == "next_step"
