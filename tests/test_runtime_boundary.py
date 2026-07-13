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
        runtime_contract=RuntimeContract(
            permission_profile="default",
            workspace_write_allowed=False,
            shell_allowed=False,
            network_allowed=False,
        ),
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
        "permission_profile": "default",
        "permission_label": "Default",
        "workspace_read_allowed": True,
        "workspace_write_allowed": False,
        "shell_allowed": False,
        "network_allowed": False,
        "browser_allowed": False,
        "network_reason": "profile_disabled",
        "approval_policy": "avoid_unnecessary_confirmation",
        "cwd": str(tmp_path.resolve()),
        "project_root": str(tmp_path.resolve()),
        "file_read_scope": "current project",
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

    default = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="default", workspace_write_allowed=False, shell_allowed=False, network_allowed=False),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    auto = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="auto", workspace_write_allowed=True, shell_allowed=True, network_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
    )
    full = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(permission_profile="full_access", workspace_write_allowed=True, shell_allowed=True, network_allowed=True),
        project_root=tmp_path,
        cwd=tmp_path,
    )

    assert default.workspace_write_allowed is False
    assert default.shell_allowed is False
    assert default.network_allowed is False
    assert default.command_allowed_roots == []
    assert str(extra_root.resolve()) not in default.allowed_roots

    assert auto.workspace_write_allowed is True
    assert auto.shell_allowed is True
    assert auto.network_allowed is False
    assert auto.command_allowed_roots == [str(tmp_path.resolve())]
    assert str(extra_root.resolve()) not in auto.allowed_roots

    assert full.workspace_write_allowed is True
    assert full.shell_allowed is True
    assert full.network_allowed is True
    assert full.command_allowed_roots == [str(tmp_path.resolve()), str(extra_root.resolve())]
    assert str(extra_root.resolve()) in full.allowed_roots
    assert str(extra_root.resolve()) in full.writable_roots


def test_runtime_contract_profiles_apply_capabilities(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    config.web_allow_all_domains = True

    default = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="default"), config=config)
    auto = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="auto"), config=config)
    full = build_full_auto_runtime_contract(settings=ChatSettings(permission_profile="full_access"), config=config)

    assert default.workspace_write_allowed is False
    assert default.shell_allowed is False
    assert default.network_allowed is False
    assert auto.workspace_write_allowed is True
    assert auto.shell_allowed is True
    assert auto.network_allowed is False
    assert full.workspace_write_allowed is True
    assert full.shell_allowed is True
    assert full.network_allowed is True


def test_full_access_allow_any_path_expands_runtime_boundary(tmp_path: Path) -> None:
    config = load_config()
    config.workspace_root = tmp_path
    config.allow_any_path = True

    boundary = build_turn_runtime_boundary(
        config=config,
        runtime_contract=RuntimeContract(
            permission_profile="full_access",
            workspace_write_allowed=True,
            shell_allowed=True,
            network_allowed=True,
        ),
        project_root=tmp_path,
        cwd=tmp_path,
    )

    filesystem_root = Path(tmp_path.anchor or "/").resolve()
    assert boundary.allowed_roots == [str(filesystem_root)]
    assert boundary.writable_roots == [str(filesystem_root)]
    assert boundary.command_allowed_roots == [str(filesystem_root)]
    assert boundary.to_model_view()["file_write_scope"] == "broader access"


def test_runtime_context_uses_supplied_runtime_boundary(tmp_path: Path) -> None:
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

    payload_text = runtime._render_runtime_context(  # noqa: SLF001 - regression test for runtime context wiring
        boundary,
        {"project_root": str(tmp_path), "cwd": str(tmp_path)},
    )

    assert dump_model(boundary.to_model_view())["cwd"] in payload_text
    assert '"permission_profile"' in payload_text
    assert '"network_allowed":false' in payload_text
    assert '"allowed_roots"' not in payload_text
    assert '"writable_roots"' not in payload_text
