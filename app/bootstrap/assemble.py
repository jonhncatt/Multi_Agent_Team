from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.bootstrap.config import AgentOSAssembleConfig, build_assemble_config
from app.business_modules import AdaptationModule, CodingModule, OfficeModule, ResearchModule
from app.config import AppConfig
from app.contracts import TaskRequest, TaskResponse, ToolContract
from app.kernel import KernelHost
from app.local_tools import LocalToolExecutor
from app.system_modules import MemoryModule, OutputModule, PolicyModule, ToolRuntimeModule
from app.tool_providers import (
    HttpWebProvider,
    LocalFileProvider,
    LocalWorkspaceProvider,
    PatchWriteProvider,
    SessionStoreProvider,
)


_DEFAULT_TOOL_CONTRACTS: tuple[ToolContract, ...] = (
    ToolContract(
        tool_id="workspace.read",
        input_schema={"path": "string", "max_entries": "integer"},
        output_schema={"entries": "array"},
        timeout=10.0,
        retry_policy={"max_retries": 0},
        permission_scope="workspace:read",
        description="List workspace contents through ToolRegistry.",
    ),
    ToolContract(
        tool_id="workspace.write",
        input_schema={"operation": "string"},
        output_schema={"ok": "boolean"},
        timeout=20.0,
        retry_policy={"max_retries": 0},
        permission_scope="workspace:write",
        description="Write or copy files within the workspace.",
    ),
    ToolContract(
        tool_id="file.read",
        input_schema={"path": "string", "operation": "string"},
        output_schema={"text": "string"},
        timeout=15.0,
        retry_policy={"max_retries": 0},
        permission_scope="file:read",
        description="Read document or file content with structured operations.",
    ),
    ToolContract(
        tool_id="code.search",
        input_schema={"query": "string", "root": "string"},
        output_schema={"matches": "array"},
        timeout=15.0,
        retry_policy={"max_retries": 0},
        permission_scope="code:search",
        description="Search source code through the file provider.",
    ),
    ToolContract(
        tool_id="web.search",
        input_schema={"query": "string"},
        output_schema={"results": "array"},
        timeout=12.0,
        retry_policy={"max_retries": 1},
        permission_scope="web:search",
        description="Search the web through a provider-backed capability.",
    ),
    ToolContract(
        tool_id="web.fetch",
        input_schema={"url": "string"},
        output_schema={"text": "string"},
        timeout=15.0,
        retry_policy={"max_retries": 1},
        permission_scope="web:fetch",
        description="Fetch a web page through a provider-backed capability.",
    ),
    ToolContract(
        tool_id="write.patch",
        input_schema={"path": "string"},
        output_schema={"ok": "boolean"},
        timeout=20.0,
        retry_policy={"max_retries": 0},
        permission_scope="workspace:patch",
        description="Apply text replacement style patches.",
    ),
    ToolContract(
        tool_id="session.lookup",
        input_schema={"session_id": "string"},
        output_schema={"turns": "array"},
        timeout=10.0,
        retry_policy={"max_retries": 0},
        permission_scope="session:read",
        description="Read stored session state via ToolRegistry.",
    ),
)


@dataclass(slots=True)
class AgentOSRuntime:
    kernel: KernelHost
    office_module: OfficeModule
    system_modules: dict[str, object]
    business_modules: dict[str, object]
    providers: dict[str, object]
    _legacy_host: Any | None = None
    _legacy_host_factory: Callable[[], Any] | None = None

    def bind_legacy_host(self, host: Any) -> None:
        self._legacy_host = host
        self.office_module.bind_legacy_host(host)

    def get_legacy_host(self) -> Any | None:
        if self._legacy_host is not None:
            return self._legacy_host
        if self._legacy_host_factory is None:
            return None
        self.bind_legacy_host(self._legacy_host_factory())
        return self._legacy_host

    def _require_legacy_host(self) -> Any:
        host = self.get_legacy_host()
        if host is None:
            raise RuntimeError("Legacy host is unavailable from AgentOSRuntime")
        return host

    def legacy_tools(self) -> Any:
        return self._require_legacy_host().tools

    def maybe_compact_session(self, session: dict[str, Any], keep_last_turns: int) -> bool:
        return bool(self._require_legacy_host().maybe_compact_session(session, keep_last_turns))

    def debug_kernel_host_snapshot(self) -> dict[str, Any]:
        return dict(self._require_legacy_host()._debug_kernel_host_snapshot() or {})

    def debug_role_lab_runtime_snapshot(self) -> dict[str, Any]:
        return dict(self._require_legacy_host()._debug_role_lab_runtime_snapshot() or {})

    def debug_tool_registry_snapshot(self) -> dict[str, Any]:
        return dict(self._require_legacy_host()._debug_tool_registry_snapshot() or {})

    def dispatch(self, request: TaskRequest, *, module_id: str | None = None) -> TaskResponse:
        return self.kernel.dispatch(request, module_id=module_id)

    def snapshot(self) -> dict[str, object]:
        return {
            "kernel": self.kernel.health_snapshot(),
            "modules": {
                "system": sorted(self.system_modules.keys()),
                "business": sorted(self.business_modules.keys()),
            },
            "providers": sorted(self.providers.keys()),
            "office_workflow": self.office_module.workflow_plan(),
            "current_execution_path": (
                "FastAPI -> KernelHost.dispatch -> business module handle -> ToolRegistry/ProviderRegistry -> response"
            ),
            "compatibility_shims": [
                "app.agent.OfficeAgent",
                "packages.runtime_core.kernel_host.KernelHost",
            ],
        }


def _register_default_tool_contracts(kernel: KernelHost) -> None:
    primary_providers = {
        "workspace.read": "local_workspace_provider",
        "workspace.write": "local_workspace_provider",
        "file.read": "local_file_provider",
        "code.search": "local_file_provider",
        "web.search": "http_web_provider",
        "web.fetch": "http_web_provider",
        "write.patch": "patch_write_provider",
        "session.lookup": "session_store_provider",
    }
    for contract in _DEFAULT_TOOL_CONTRACTS:
        kernel.registry.register_tool_contract(
            contract,
            primary_provider=primary_providers.get(contract.tool_id, ""),
        )


def _build_default_legacy_host_factory(
    app_config: AppConfig,
    *,
    kernel_runtime: Any | None,
) -> Callable[[], Any]:
    def _factory() -> Any:
        from packages.runtime_core.kernel_host import KernelHost as LegacyKernelHost

        return LegacyKernelHost(app_config, kernel_runtime=kernel_runtime)

    return _factory


def assemble_runtime(
    app_config: AppConfig,
    *,
    kernel_runtime: Any | None = None,
    legacy_host: Any | None = None,
    legacy_host_factory: Callable[[], Any] | None = None,
    assemble_config: AgentOSAssembleConfig | None = None,
) -> AgentOSRuntime:
    cfg = assemble_config or build_assemble_config(app_config)
    kernel = KernelHost(kernel_version=cfg.kernel_version)
    shared_executor = LocalToolExecutor(app_config)
    resolved_legacy_host_factory = legacy_host_factory
    if legacy_host is None and resolved_legacy_host_factory is None:
        resolved_legacy_host_factory = _build_default_legacy_host_factory(
            app_config,
            kernel_runtime=kernel_runtime,
        )

    system_modules: dict[str, object] = {
        "memory_module": MemoryModule(),
        "output_module": OutputModule(),
        "tool_runtime_module": ToolRuntimeModule(),
        "policy_module": PolicyModule(),
    }

    office_module = OfficeModule(
        config=app_config,
        legacy_host=legacy_host,
        kernel_runtime=kernel_runtime,
    )
    business_modules: dict[str, object] = {
        "office_module": office_module,
    }
    if cfg.include_research_module:
        business_modules["research_module"] = ResearchModule()
    if cfg.include_coding_module:
        business_modules["coding_module"] = CodingModule()
    if cfg.include_adaptation_module:
        business_modules["adaptation_module"] = AdaptationModule()

    for module in [*system_modules.values(), *business_modules.values()]:
        kernel.register_module(module)  # type: ignore[arg-type]

    providers: dict[str, object] = {
        "local_workspace_provider": LocalWorkspaceProvider(app_config, executor=shared_executor),
        "local_file_provider": LocalFileProvider(app_config, executor=shared_executor),
        "http_web_provider": HttpWebProvider(app_config, executor=shared_executor),
        "patch_write_provider": PatchWriteProvider(app_config, executor=shared_executor),
    }
    if cfg.enable_session_provider:
        providers["session_store_provider"] = SessionStoreProvider(app_config, executor=shared_executor)

    _register_default_tool_contracts(kernel)
    for provider in providers.values():
        kernel.register_provider(provider)  # type: ignore[arg-type]

    kernel.init()

    runtime = AgentOSRuntime(
        kernel=kernel,
        office_module=office_module,
        system_modules=system_modules,
        business_modules=business_modules,
        providers=providers,
        _legacy_host=legacy_host,
        _legacy_host_factory=resolved_legacy_host_factory,
    )
    if legacy_host is not None:
        runtime.bind_legacy_host(legacy_host)
    return runtime
