from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductProfile:
    key: str
    runtime_dir_name: str
    app_title: str
    page_title: str
    sidebar_title: str
    sidebar_hint: str
    kernel_title: str
    kernel_subtitle: str
    role_title: str
    role_legend: str
    show_kernel_console: bool
    show_role_board: bool
    default_port: int


KERNEL_ROBOT_PROFILE = ProductProfile(
    key="kernel_robot",
    app_title="Multi Agent Team Kernel Robot",
    page_title="Multi Agent Team Kernel Robot",
    sidebar_title="Multi Agent Team Kernel Robot",
    sidebar_hint="机械式主核保持稳定，模块独立装配与升级，个体进化全部先在 shadow 中验证。",
    kernel_title="KernelHost / Blackboard / Capability Modules",
    kernel_subtitle="主核负责驱动、保护和回滚；模块像载荷一样按需装载，并通过黑板交换状态。",
    role_title="Multi_Agent_Robot Lab",
    role_legend="默认隐藏实验视图。Multi_Agent_Robot 以主核、模块舱、运行面板为主界面。",
    show_kernel_console=True,
    show_role_board=False,
    default_port=8080,
)


ROLE_AGENT_LAB_PROFILE = ProductProfile(
    key="role_agent_lab",
    app_title="Multi Agent Team Role-Agent Lab",
    page_title="Multi Agent Team Role-Agent Lab",
    sidebar_title="Multi Agent Team Role-Agent Lab",
    sidebar_hint="保留 Router / Planner / Worker / Reviewer 等角色链路，聚焦独立 agent 注册、runtime 管控和 Stage 4 多实例准备。",
    kernel_title="共享底盘概览",
    kernel_subtitle="这里仍然使用同一套 runtime-core，但主视图聚焦 role-agent 编排实验、实例级 runtime 和 Stage 4 readiness。",
    role_title="Multi_Agent_Robot Lab",
    role_legend="role = 流程岗位；agent = LLM 驱动；processor = 非 LLM；这里用于观察注册角色、实例级 runtime 与执行分工。",
    show_kernel_console=False,
    show_role_board=True,
    default_port=8081,
)


PRODUCT_PROFILES = {
    MULTI_AGENT_ROBOT_PROFILE.key: MULTI_AGENT_ROBOT_PROFILE,
    ROLE_AGENT_LAB_PROFILE.key: ROLE_AGENT_LAB_PROFILE,
}

PRODUCT_PROFILE_ALIASES = {
    "kernel_robot": MULTI_AGENT_ROBOT_PROFILE.key,
    "multi_agent_robot": MULTI_AGENT_ROBOT_PROFILE.key,
    "role_agent_lab": ROLE_AGENT_LAB_PROFILE.key,
}


def get_product_profile(profile_key: str | None = None) -> ProductProfile:
    raw = str(profile_key or os.environ.get("VP_APP_PROFILE") or "").strip().lower()
    return PRODUCT_PROFILES.get(raw, KERNEL_ROBOT_PROFILE)


def _workspace_root_from_env() -> Path:
    raw = os.environ.get("VP_WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve()


def _set_default_env(key: str, value: str, *, force: bool = False) -> None:
    if force:
        os.environ[key] = value
        return
    os.environ.setdefault(key, value)


def apply_product_profile_env(profile_key: str, *, force: bool = False) -> ProductProfile:
    profile = get_product_profile(profile_key)
    workspace_root = _workspace_root_from_env()
    data_root = (workspace_root / "app" / "data" / "apps" / (profile.runtime_dir_name or profile.key)).resolve()

    canonical = {
        "APP_PROFILE": profile.key,
        "RUNTIME_DIR": str(data_root / "runtime"),
        "EVOLUTION_DIR": str(data_root / "evolution"),
        "SESSIONS_DIR": str(data_root / "sessions"),
        "UPLOADS_DIR": str(data_root / "uploads"),
        "SHADOW_LOGS_DIR": str(data_root / "shadow_logs"),
        "TOKEN_STATS_PATH": str(data_root / "token_stats.json"),
    }
    for suffix, value in canonical.items():
        _set_default_env(f"VP_{suffix}", value, force=force)
    return profile


def ensure_product_profile_env(default_profile: str = KERNEL_ROBOT_PROFILE.key) -> ProductProfile:
    existing = str(os.environ.get("VP_APP_PROFILE") or "").strip().lower()
    return apply_product_profile_env(existing or default_profile, force=False)
