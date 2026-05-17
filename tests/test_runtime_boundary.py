from __future__ import annotations

from pathlib import Path

from app.config import load_config
from app.runtime_boundary import RuntimeBoundary, build_turn_runtime_boundary
from app.runtime_contract import RuntimeContract
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
    assert boundary.to_model_view() == {
        "workspace_read_allowed": True,
        "workspace_write_allowed": False,
        "shell_allowed": False,
        "network_allowed": False,
        "approval_policy": "avoid_unnecessary_confirmation",
        "cwd": str(tmp_path.resolve()),
        "project_root": str(tmp_path.resolve()),
    }


def test_context_pack_uses_supplied_runtime_boundary(tmp_path: Path) -> None:
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

    payload_text = runtime._build_human_payload(  # noqa: SLF001 - regression test for ContextPack wiring
        message="hello",
        context={
            "session_id": "s-boundary",
            "project": {"project_root": str(tmp_path), "cwd": str(tmp_path)},
            "history_turns": [],
            "attachments": [],
        },
        runtime_boundary=boundary,
    )
    runtime_context_json = payload_text.split("runtime_context_json:\n", 1)[1]

    assert dump_model(boundary.to_model_view())["cwd"] in runtime_context_json
    assert '"runtime_boundary"' in runtime_context_json
    assert '"allowed_roots"' not in runtime_context_json
    assert '"writable_roots"' not in runtime_context_json
