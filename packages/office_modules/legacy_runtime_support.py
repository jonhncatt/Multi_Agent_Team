from __future__ import annotations

from typing import Any


def compact_legacy_session(agent: Any, session: dict[str, Any], keep_last_turns: int) -> bool:
    turns = session.get("turns", [])
    if len(turns) <= agent.config.summary_trigger_turns:
        return False

    keep = max(2, min(2000, keep_last_turns))
    older = turns[:-keep]
    recent = turns[-keep:]
    if not older:
        return False

    existing_summary = session.get("summary", "")
    session["summary"] = agent._summarize_turns(existing_summary, older)
    session["turns"] = recent
    return True


def legacy_tool_registry_snapshot(agent: Any) -> dict[str, Any]:
    registry = agent._module_registry()
    module = getattr(registry, "tool_registry", None)
    selected_ref = str((registry.selected_refs or {}).get("tool_registry") or "")
    if module is None or not hasattr(module, "describe_tools"):
        return {
            "selected_ref": selected_ref,
            "tool_count": len(agent._lc_tools),
            "tools": [
                {
                    "name": str(getattr(tool, "name", "") or ""),
                    "description": str(getattr(tool, "description", "") or "")[:200],
                }
                for tool in agent._lc_tools
            ],
        }
    payload = module.describe_tools(agent=agent)
    if isinstance(payload, dict):
        payload.setdefault("selected_ref", selected_ref)
        return payload
    return {"selected_ref": selected_ref, "tool_count": len(agent._lc_tools)}


def legacy_role_lab_runtime_snapshot(agent: Any) -> dict[str, Any]:
    return agent._role_runtime_controller.runtime_snapshot()


__all__ = [
    "compact_legacy_session",
    "legacy_role_lab_runtime_snapshot",
    "legacy_tool_registry_snapshot",
]
