from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Literal
import uuid


TraceStatus = Literal[
    "pending",
    "running",
    "success",
    "failed",
    "blocked",
    "cancelled",
    "skipped",
]

ActivityEventType = Literal[
    "activity.started",
    "activity.delta",
    "activity.done",
    "answer.started",
    "answer.delta",
    "answer.done",
]


@dataclass(slots=True)
class TraceEvent:
    id: str
    run_id: str
    type: str
    title: str
    detail: str = ""
    status: TraceStatus = "running"
    timestamp: float = field(default_factory=time.time)
    duration_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    visible: bool = True


def make_trace_event(
    *,
    run_id: str,
    type: str,
    title: str,
    detail: str = "",
    status: TraceStatus = "running",
    duration_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    parent_id: str | None = None,
    visible: bool = True,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "run_id": str(run_id or ""),
        "type": str(type or ""),
        "title": str(title or ""),
        "detail": str(detail or ""),
        "status": status,
        "timestamp": time.time(),
        "duration_ms": duration_ms,
        "payload": dict(payload or {}),
        "parent_id": str(parent_id or "") or None,
        "visible": bool(visible),
    }


def make_activity_event(
    *,
    run_id: str,
    type: ActivityEventType,
    title: str,
    stage: str,
    detail: str = "",
    status: TraceStatus = "running",
    duration_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    parent_id: str | None = None,
    visible: bool = True,
    sequence: int | None = None,
) -> dict[str, Any]:
    normalized_payload = dict(payload or {})
    activity_payload = dict(normalized_payload.get("activity") or {})
    activity_payload["stage"] = str(stage or "")
    if sequence is not None:
        activity_payload["sequence"] = max(0, int(sequence))
    normalized_payload["activity"] = activity_payload
    return make_trace_event(
        run_id=run_id,
        type=type,
        title=title,
        detail=detail,
        status=status,
        duration_ms=duration_ms,
        payload=normalized_payload,
        parent_id=parent_id,
        visible=visible,
    )
