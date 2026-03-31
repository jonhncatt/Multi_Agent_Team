from __future__ import annotations

from packages.office_modules.office_agent_runtime import OfficeAgent


class _PrimaryToolsStub:
    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": False, "error": f"Unknown tool: {name}"}


class _LangchainToolStub:
    name = "kernel_runtime_status"

    def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "source": "fallback", "arguments": arguments}


def test_execute_tool_call_falls_back_for_case_variant_unknown_tool() -> None:
    agent = OfficeAgent.__new__(OfficeAgent)
    agent.tools = _PrimaryToolsStub()
    fallback_tool = _LangchainToolStub()
    agent._lc_tool_map = {"kernel_runtime_status": fallback_tool}
    agent._lc_tool_map_casefold = {"kernel_runtime_status": fallback_tool}

    result = agent._execute_tool_call("Kernel_runtime_status", {"include_roles": True})

    assert bool(result.get("ok")) is True
    assert result.get("source") == "fallback"
