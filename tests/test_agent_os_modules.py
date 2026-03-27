from __future__ import annotations

from typing import Any

from app.bootstrap import AgentOSAssembleConfig, assemble_runtime
from app.config import load_config
from app.contracts import TaskRequest
from tests.support_agent_os import bind_fake_research_provider


class DummyLegacyHost:
    def run_chat(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        _ = args, kwargs
        return (
            "dummy response",
            [],
            "",
            [],
            [],
            [],
            [],
            [],
            ["router", "planner", "worker"],
            "worker",
            [],
            {},
            {},
            "gpt-test",
            {},
        )

    def maybe_compact_session(self, session: dict[str, Any], keep_last_turns: int) -> bool:
        _ = keep_last_turns
        session["compacted"] = True
        return True

    def _debug_kernel_host_snapshot(self) -> dict[str, Any]:
        return {"host": "ok"}

    def _debug_role_lab_runtime_snapshot(self) -> dict[str, Any]:
        return {"role_lab": "ok"}

    def _debug_tool_registry_snapshot(self) -> dict[str, Any]:
        return {"tool_registry": "ok"}

    @property
    def tools(self) -> Any:
        class _Tools:
            @staticmethod
            def docker_status() -> tuple[bool, str]:
                return True, "ok"

        return _Tools()


def test_modules_init_invoke_and_health() -> None:
    cfg = load_config()
    runtime = assemble_runtime(
        cfg,
        legacy_host=DummyLegacyHost(),
        assemble_config=AgentOSAssembleConfig(
            include_research_module=True,
            include_coding_module=True,
            include_adaptation_module=True,
            enable_session_provider=False,
        ),
    )

    snapshot = runtime.kernel.health_snapshot()
    assert snapshot["ok"] is True

    system_ids = {item.manifest.module_id for item in runtime.kernel.registry.list_modules(kind="system")}
    assert {"memory_module", "output_module", "tool_runtime_module", "policy_module"} <= system_ids

    office_resp = runtime.kernel.invoke(
        "office_module",
        TaskRequest(
            task_id="t-office",
            task_type="chat",
            message="hello",
            context={"history_turns": [], "summary": "", "session_id": "s-1"},
        ),
    )
    assert office_resp.ok is True
    assert office_resp.text == "dummy response"

    bind_fake_research_provider(runtime)
    research_resp = runtime.kernel.invoke(
        "research_module",
        TaskRequest(
            task_id="t-research_module",
            task_type="task.research",
            message="ping",
        ),
    )
    assert research_resp.ok is True
    assert research_resp.payload["module_id"] == "research_module"
    assert research_resp.payload["research"]["source_count"] >= 1

    for module_id in ("coding_module", "adaptation_module"):
        resp = runtime.kernel.invoke(
            module_id,
            TaskRequest(task_id=f"t-{module_id}", task_type="test", message="ping"),
        )
        assert resp.ok is False
        assert "not implemented yet" in resp.error


def test_agent_os_runtime_exposes_legacy_facade_methods() -> None:
    runtime = assemble_runtime(load_config(), legacy_host=DummyLegacyHost())

    session = {"turns": []}
    assert runtime.maybe_compact_session(session, 10) is True
    assert session["compacted"] is True
    assert runtime.debug_kernel_host_snapshot() == {"host": "ok"}
    assert runtime.debug_role_lab_runtime_snapshot() == {"role_lab": "ok"}
    assert runtime.debug_tool_registry_snapshot() == {"tool_registry": "ok"}
    assert runtime.legacy_tools().docker_status() == (True, "ok")
