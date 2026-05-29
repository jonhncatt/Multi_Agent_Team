from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


RoleHandler = Callable[..., Any]


@dataclass(slots=True)
class RegisteredRole:
    role: str
    title: str
    kind: str = "agent"
    description: str = ""
    handler: RoleHandler | None = None
    executable: bool = True
    controller_backed: bool = True
    multi_instance_ready: bool = False
    supports_parent_child: bool = False
    runtime_profiles: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


class RoleRegistry:
    def __init__(self) -> None:
        self._roles: dict[str, RegisteredRole] = {}

    def register(self, role: RegisteredRole) -> RegisteredRole:
        key = str(role.role or "").strip().lower()
        if not key:
            raise ValueError("role must not be empty")
        role.role = key
        self._roles[key] = role
        return role

    def get(self, role: str) -> RegisteredRole | None:
        return self._roles.get(str(role or "").strip().lower())

    def require(self, role: str) -> RegisteredRole:
        item = self.get(role)
        if item is None:
            raise KeyError(f"unregistered role: {role}")
        return item

    def roles(self) -> list[RegisteredRole]:
        return [self._roles[key] for key in sorted(self._roles)]

    def snapshot(self) -> dict[str, Any]:
        roles = self.roles()
        kind_counts = {"agent": 0, "processor": 0, "hybrid": 0}
        executable_roles: list[str] = []
        controller_backed_roles: list[str] = []
        multi_instance_roles: list[str] = []
        parent_child_roles: list[str] = []
        controller_gaps: list[str] = []
        entries: list[dict[str, Any]] = []
        for item in roles:
            kind = str(item.kind or "agent").strip().lower()
            if kind not in kind_counts:
                kind = "agent"
            kind_counts[kind] += 1
            if item.executable and item.handler is not None:
                executable_roles.append(item.role)
            if item.controller_backed:
                controller_backed_roles.append(item.role)
            else:
                controller_gaps.append(item.role)
            if item.multi_instance_ready:
                multi_instance_roles.append(item.role)
            if item.supports_parent_child:
                parent_child_roles.append(item.role)
            entries.append(
                {
                    "role": item.role,
                    "title": item.title,
                    "kind": kind,
                    "description": item.description,
                    "executable": item.executable and item.handler is not None,
                    "controller_backed": item.controller_backed,
                    "multi_instance_ready": item.multi_instance_ready,
                    "supports_parent_child": item.supports_parent_child,
                    "runtime_profiles": list(item.runtime_profiles),
                }
            )
        return {
            "registered_roles": len(roles),
            "kind_counts": kind_counts,
            "executable_roles": executable_roles,
            "controller_backed_roles": controller_backed_roles,
            "multi_instance_ready_roles": multi_instance_roles,
            "parent_child_ready_roles": parent_child_roles,
            "controller_gaps": controller_gaps,
            "roles": entries,
        }
