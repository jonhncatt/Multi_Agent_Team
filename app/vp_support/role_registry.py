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
