from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class BlackboardEvent:
    ts: str
    kind: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Blackboard:
    request_id: str
    session_id: str = ""
    user_message: str = ""
    attachment_ids: list[str] = field(default_factory=list)
    selected_agent_module_id: str = ""
    selected_tool_module_id: str = ""
    selected_output_module_id: str = ""
    selected_memory_module_id: str = ""
    selected_capability_modules: list[str] = field(default_factory=list)
    active_module_ids: list[str] = field(default_factory=list)
    status: str = "created"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    effective_model: str = ""
    route_state: dict[str, Any] = field(default_factory=dict)
    execution_plan: list[str] = field(default_factory=list)
    execution_trace: list[str] = field(default_factory=list)
    tool_event_count: int = 0
    tool_usage: dict[str, int] = field(default_factory=dict)
    tool_module_usage: dict[str, int] = field(default_factory=dict)
    answer_bundle: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    events: list[BlackboardEvent] = field(default_factory=list)
    last_error: str = ""

    @classmethod
    def create(
        cls,
        *,
        session_id: str | None,
        user_message: str,
        attachment_ids: list[str] | None,
        selected_agent_module_id: str,
        selected_tool_module_id: str,
        selected_output_module_id: str = "",
        selected_memory_module_id: str = "",
        selected_capability_modules: list[str] | None = None,
    ) -> "Blackboard":
        board = cls(
            request_id=f"bb-{uuid4().hex[:12]}",
            session_id=str(session_id or "").strip(),
            user_message=str(user_message or ""),
            attachment_ids=[str(item or "").strip() for item in (attachment_ids or []) if str(item or "").strip()],
            selected_agent_module_id=str(selected_agent_module_id or "").strip(),
            selected_tool_module_id=str(selected_tool_module_id or "").strip(),
            selected_output_module_id=str(selected_output_module_id or "").strip(),
            selected_memory_module_id=str(selected_memory_module_id or "").strip(),
            selected_capability_modules=[
                str(item or "").strip() for item in (selected_capability_modules or []) if str(item or "").strip()
            ],
        )
        board.set_active_modules(
            [
                board.selected_agent_module_id,
                board.selected_tool_module_id,
                board.selected_output_module_id,
                board.selected_memory_module_id,
            ]
        )
        return board

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def add_event(self, kind: str, detail: str = "", **data: Any) -> None:
        self.events.append(BlackboardEvent(ts=_now_iso(), kind=str(kind or ""), detail=str(detail or ""), data=dict(data)))
        self.touch()

    def set_route_state(self, route_state: dict[str, Any] | None) -> None:
        self.route_state = dict(route_state or {})
        self.touch()

    def set_execution_plan(self, execution_plan: list[str] | None) -> None:
        self.execution_plan = [str(item or "") for item in (execution_plan or []) if str(item or "").strip()]
        self.touch()

    def set_active_modules(self, module_ids: list[str] | None, *, reason: str = "") -> None:
        normalized = []
        seen: set[str] = set()
        for item in module_ids or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if normalized == self.active_module_ids:
            return
        self.active_module_ids = normalized
        if reason:
            self.add_event("active_modules_updated", reason, active_modules=list(self.active_module_ids))
        else:
            self.touch()

    def record_tool_event(self, event: Any) -> None:
        name = str(getattr(event, "name", "") or "").strip()
        module_id = str(getattr(event, "module_id", "") or "").strip()
        if name:
            self.tool_usage[name] = int(self.tool_usage.get(name) or 0) + 1
        if module_id:
            self.tool_module_usage[module_id] = int(self.tool_module_usage.get(module_id) or 0) + 1
            self.set_active_modules(
                [
                    *self.active_module_ids,
                    module_id,
                ]
            )
        self.tool_event_count = sum(int(value or 0) for value in self.tool_usage.values())
        self.touch()

    def start(self) -> None:
        self.status = "running"
        self.add_event("run_started", "kernel dispatched primary agent module")

    def complete(
        self,
        *,
        effective_model: str,
        route_state: dict[str, Any] | None,
        execution_plan: list[str] | None,
        execution_trace: list[str] | None,
        tool_events: list[Any] | None,
        answer_bundle: dict[str, Any] | None,
    ) -> None:
        self.status = "completed"
        self.effective_model = str(effective_model or "")
        self.route_state = dict(route_state or {})
        self.execution_plan = [str(item or "") for item in (execution_plan or []) if str(item or "").strip()]
        self.execution_trace = [str(item or "") for item in (execution_trace or []) if str(item or "").strip()]
        if tool_events and not self.tool_usage:
            for event in tool_events:
                self.record_tool_event(event)
        self.tool_event_count = max(self.tool_event_count, len(tool_events or []))
        self.answer_bundle = dict(answer_bundle or {})
        self.add_event(
            "run_completed",
            "primary agent module completed",
            tool_event_count=self.tool_event_count,
            execution_plan_count=len(self.execution_plan),
        )

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.last_error = str(error or "")
        self.add_event("run_failed", self.last_error)

    def snapshot(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "user_message_preview": self.user_message[:160],
            "attachment_ids": list(self.attachment_ids),
            "selected_agent_module_id": self.selected_agent_module_id,
            "selected_tool_module_id": self.selected_tool_module_id,
            "selected_output_module_id": self.selected_output_module_id,
            "selected_memory_module_id": self.selected_memory_module_id,
            "selected_capability_modules": list(self.selected_capability_modules),
            "active_module_ids": list(self.active_module_ids),
            "effective_model": self.effective_model,
            "route_state": dict(self.route_state),
            "execution_plan": list(self.execution_plan),
            "execution_trace_tail": list(self.execution_trace[-8:]),
            "tool_event_count": self.tool_event_count,
            "tool_usage": dict(self.tool_usage),
            "tool_module_usage": dict(self.tool_module_usage),
            "answer_bundle_summary": str((self.answer_bundle or {}).get("summary") or "").strip(),
            "last_error": self.last_error,
            "notes": list(self.notes),
            "events": [
                {"ts": item.ts, "kind": item.kind, "detail": item.detail, "data": dict(item.data)} for item in self.events[-12:]
            ],
        }
