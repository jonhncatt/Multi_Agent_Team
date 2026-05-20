from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.runtime_boundary import RuntimeBoundary, build_turn_runtime_boundary
from app.runtime_contract import RuntimeContract, build_full_auto_runtime_contract
from app.models import ChatSettings
from app.serialization import dump_model
from app.vintage_programmer_runtime import VintageProgrammerRuntime


class _FakeTools:
    tool_specs: list[dict[str, object]] = []


class _FakeBackend:
    tools = _FakeTools()


def test_turn_runtime_boundary_includes_project_and_attachment_roots(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    attachment_dir = tmp_path / "uploads"
    attachment_dir.mkdir()
    attachment_path = attachment_dir / "image.png"
    attachment_path.write_bytes(b"fake")

    boundary = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(workspace_write_allowed=False, shell_allowed=False, network_allowed=False),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[{"path": str(attachment_path), "kind": "image"}],
    )

    assert isinstance(boundary, RuntimeBoundary)
    assert str(tmp_path.resolve()) in boundary.allowed_roots
    assert str(attachment_dir.resolve()) in boundary.allowed_roots
    assert boundary.writable_roots == []
    assert boundary.shell_allowed is False
    model_view = boundary.to_model_view()
    assert model_view == {
        "permission_profile": "code",
        "workspace_read_allowed": True,
        "workspace_write_allowed": False,
        "shell_allowed": False,
        "network_allowed": False,
        "approval_policy": "avoid_unnecessary_confirmation",
        "cwd": str(tmp_path.resolve()),
        "project_root": str(tmp_path.resolve()),
        "file_read_scope": "current project + imported files",
        "file_write_scope": "none",
        "command_scope": "none",
    }


def test_permission_profiles_shape_runtime_boundary(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    config.uploads_dir = tmp_path / ".uploads"
    config.uploads_dir.mkdir()
    extra_root = tmp_path.parent / "explicit-extra"
    extra_root.mkdir(exist_ok=True)
    config.allowed_roots = [tmp_path, extra_root]

    chat = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="chat", workspace_write_allowed=False, shell_allowed=False, network_allowed=False),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    code = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="code", workspace_write_allowed=True, shell_allowed=True, network_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    full = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="full_dev", workspace_write_allowed=True, shell_allowed=True, network_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
    )

    assert chat.workspace_write_allowed is False
    assert chat.shell_allowed is False
    assert chat.command_allowed_roots == []
    assert str(extra_root.resolve()) not in chat.allowed_roots

    assert code.workspace_write_allowed is True
    assert code.shell_allowed is True
    assert code.network_allowed is False
    assert code.command_allowed_roots == [str(tmp_path.resolve())]
    assert str(extra_root.resolve()) not in code.allowed_roots

    assert full.workspace_write_allowed is True
    assert full.shell_allowed is True
    assert full.network_allowed is True
    assert full.command_allowed_roots == [str(tmp_path.resolve())]
    assert str(extra_root.resolve()) in full.allowed_roots


def test_runtime_contract_profiles_apply_capabilities(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    config.web_allow_all_domains = True

    chat = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="chat"), config=config)
    code = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="code"), config=config)
    full = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="full_dev"), config=config)

    assert chat.workspace_write_allowed is False
    assert chat.shell_allowed is False
    assert chat.network_allowed is False
    assert code.workspace_write_allowed is True
    assert code.shell_allowed is True
    assert code.network_allowed is False
    assert full.workspace_write_allowed is True
    assert full.shell_allowed is True
    assert full.network_allowed is True


def test_model_context_uses_supplied_runtime_boundary(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    runtime = VintageProgrammerRuntime(config=config, kernel_runtime=object(), agent_dir=tmp_path, backend=_FakeBackend())
    boundary = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(shell_allowed=False, network_allowed=False),
        project_root=tmp_path,
        cwd=tmp_path,
        attachments=[],
    )

    payload_text = runtime._build_human_payload(  # noqa: SLF001 - regression test for ModelContext wiring
        message="hello",
        context={
            "session_id": "s-boundary",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        runtime_boundary=boundary,
    )
    model_context_json = payload_text.split("model_context_json:\n", 1)[1]

    assert dump_model(boundary.to_model_view())["cwd"] in model_context_json
    assert '"permissions"' in model_context_json
    assert '"allowed_roots"' not in model_context_json
    assert '"writable_roots"' not in model_context_json
