from __future__ import annotations

from app.vp_support.conflict_detector_role import run_conflict_detector_role
from app.vp_support.planner_role import run_planner_role
from app.vp_support.reviewer_role import run_reviewer_role
from app.vp_support.revision_role import run_revision_role
from app.vp_support.role_catalog import ROLE_KINDS, SPECIALIST_LABELS
from app.vp_support.specialist_role import run_specialist_with_context
from app.vp_support.structurer_role import run_structurer_role
from app.vp_support.role_registry import RegisteredRole, RoleHandler, RoleRegistry


def build_vp_role_registry() -> RoleRegistry:
    registry = RoleRegistry()

    def _register(
        role: str,
        *,
        title: str,
        description: str,
        handler: RoleHandler | None,
        executable: bool,
    ) -> None:
        registry.register(
            RegisteredRole(
                role=role,
                title=title,
                kind=str(ROLE_KINDS.get(role, "agent")),
                description=description,
                handler=handler,
                executable=executable,
            )
        )

    _register(
        "router",
        title="Router",
        description="规则与可选 LLM 路由入口。",
        handler=None,
        executable=False,
    )
    _register(
        "coordinator",
        title="Coordinator",
        description="运行时状态机与调度处理器。",
        handler=None,
        executable=False,
    )
    _register(
        "worker",
        title="Worker",
        description="主任务执行与工具循环。",
        handler=None,
        executable=False,
    )
    _register(
        "planner",
        title="Planner",
        description="提炼目标、限制与执行计划。",
        handler=run_planner_role,
        executable=True,
    )
    for specialist, title in SPECIALIST_LABELS.items():
        _register(
            specialist,
            title=title,
            description=f"{title} 专门简报角色。",
            handler=run_specialist_with_context,
            executable=True,
        )
    _register(
        "conflict_detector",
        title="Conflict Detector",
        description="通识与工程知识冲突报警。",
        handler=run_conflict_detector_role,
        executable=True,
    )
    _register(
        "reviewer",
        title="Reviewer",
        description="覆盖度、证据链和交付风险审阅。",
        handler=run_reviewer_role,
        executable=True,
    )
    _register(
        "revision",
        title="Revision",
        description="按审阅结论修订答复。",
        handler=run_revision_role,
        executable=True,
    )
    _register(
        "structurer",
        title="Structurer",
        description="整理结构化证据包与 assertions。",
        handler=run_structurer_role,
        executable=True,
    )
    return registry
