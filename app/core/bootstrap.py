from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from app.config import AppConfig
from app.core.module_loader import ModuleLoader
from app.core.module_manifest import ActiveModuleManifest, write_active_manifest
from app.core.module_registry import KernelModuleRegistry
from app.core.module_types import ModuleHealthSnapshot, ModuleRuntimeContext
from app.core.supervisor import KernelSupervisor


@dataclass(slots=True)
class KernelRuntime:
    context: ModuleRuntimeContext
    loader: ModuleLoader
    supervisor: KernelSupervisor
    registry: KernelModuleRegistry

    def reload_registry(self) -> KernelModuleRegistry:
        self.registry = self.supervisor.load_registry()
        return self.registry

    def health_snapshot(self) -> ModuleHealthSnapshot:
        return self.supervisor.health_snapshot(self.registry)

    def record_module_failure(self, *, kind: str, requested_ref: str, fallback_ref: str = "", error: str, mode: str | None = None) -> None:
        self.supervisor.record_runtime_failure(
            kind=kind,
            requested_ref=requested_ref,
            fallback_ref=fallback_ref,
            error=error,
            mode=mode,
        )
        self.reload_registry()

    def record_module_success(self, *, kind: str, selected_ref: str, mode: str | None = None) -> None:
        self.supervisor.record_runtime_success(kind=kind, selected_ref=selected_ref, mode=mode)

    def load_shadow_manifest(self) -> ActiveModuleManifest:
        return self.supervisor.load_shadow_manifest()

    def write_shadow_manifest(self, manifest: ActiveModuleManifest) -> None:
        self.supervisor.write_shadow_manifest(manifest)

    def validate_shadow_manifest(self) -> dict[str, object]:
        return self.supervisor.validate_shadow_manifest()

    def validate_active_manifest(self) -> dict[str, object]:
        return self.supervisor.validate_active_manifest()

    def promote_shadow_manifest(self) -> dict[str, object]:
        result = self.supervisor.promote_shadow_manifest()
        if result.get("ok"):
            self.reload_registry()
        return result

    def rollback_active_manifest(self) -> dict[str, object]:
        result = self.supervisor.rollback_active_manifest()
        if result.get("ok"):
            self.reload_registry()
        return result

    def stage_shadow_manifest(self, *, overrides: dict[str, object] | None = None) -> dict[str, object]:
        shadow = self.load_shadow_manifest()
        payload = dict(overrides or {})
        for key in ("router", "policy", "attachment_context", "finalizer", "tool_registry"):
            value = str(payload.get(key) or "").strip()
            if value:
                setattr(shadow, key, value)
        providers = dict(shadow.providers)
        raw_providers = payload.get("providers")
        if isinstance(raw_providers, dict):
            for mode, ref in raw_providers.items():
                mode_text = str(mode or "").strip()
                ref_text = str(ref or "").strip()
                if mode_text and ref_text:
                    providers[mode_text] = ref_text
        shadow.providers = providers
        self.write_shadow_manifest(shadow)
        validation = self.validate_shadow_manifest()
        return {
            "ok": bool(validation.get("ok")),
            "shadow_manifest": shadow.to_dict(),
            "validation": validation,
        }

    def _last_shadow_run_path(self) -> Path:
        return self.context.runtime_dir / "last_shadow_run.json"

    def _upgrade_runs_dir(self) -> Path:
        return self.context.runtime_dir / "upgrade_runs"

    def _last_upgrade_run_path(self) -> Path:
        return self.context.runtime_dir / "last_upgrade_run.json"

    def _repair_runs_dir(self) -> Path:
        return self.context.runtime_dir / "repair_runs"

    def _last_repair_run_path(self) -> Path:
        return self.context.runtime_dir / "last_repair_run.json"

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _read_json_dict(self, path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def read_last_shadow_run(self) -> dict[str, object]:
        return self._read_json_dict(self._last_shadow_run_path())

    def read_last_upgrade_run(self) -> dict[str, object]:
        return self._read_json_dict(self._last_upgrade_run_path())

    def list_upgrade_runs(self, *, limit: int = 20) -> list[dict[str, object]]:
        max_items = max(1, min(200, int(limit)))
        files = sorted(self._upgrade_runs_dir().glob("*.json"), key=lambda path: path.name, reverse=True)
        out: list[dict[str, object]] = []
        for path in files:
            payload = self._read_json_dict(path)
            if payload:
                out.append(payload)
            if len(out) >= max_items:
                break
        return out

    def find_upgrade_run(self, run_id: str | None) -> dict[str, object]:
        wanted = str(run_id or "").strip()
        if not wanted:
            return self.read_last_upgrade_run()
        path = self._upgrade_runs_dir() / f"{wanted}.json"
        if path.is_file():
            return self._read_json_dict(path)
        for item in self.list_upgrade_runs(limit=200):
            if str(item.get("run_id") or "").strip() == wanted:
                return item
        return {}

    def read_last_repair_run(self) -> dict[str, object]:
        return self._read_json_dict(self._last_repair_run_path())

    def list_repair_runs(self, *, limit: int = 20) -> list[dict[str, object]]:
        max_items = max(1, min(200, int(limit)))
        files = sorted(self._repair_runs_dir().glob("*.json"), key=lambda path: path.name, reverse=True)
        out: list[dict[str, object]] = []
        for path in files:
            payload = self._read_json_dict(path)
            if payload:
                out.append(payload)
            if len(out) >= max_items:
                break
        return out

    def _pipeline_run_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]

    def _pipeline_failure_text(self, payload: dict[str, object] | None) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("error", "reason"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        errors = payload.get("errors")
        if isinstance(errors, list):
            parts = [str(item).strip() for item in errors if str(item).strip()]
            if parts:
                return "; ".join(parts[:3])
        validation = payload.get("validation")
        if isinstance(validation, dict):
            errors = validation.get("errors")
            if isinstance(errors, list):
                parts = [str(item).strip() for item in errors if str(item).strip()]
                if parts:
                    return "; ".join(parts[:3])
        return ""

    def _pipeline_manifest_labels(self, validation: dict[str, object] | None) -> list[str]:
        if not isinstance(validation, dict):
            return []
        errors = validation.get("errors")
        if not isinstance(errors, list):
            return []
        labels: list[str] = []
        for item in errors:
            text = str(item or "").strip()
            if not text:
                continue
            label = text.split(":", 1)[0].strip()
            if label and label not in labels:
                labels.append(label)
        return labels

    def _safe_active_override_for_label(self, label: str, active_manifest: ActiveModuleManifest) -> tuple[str, str] | None:
        raw = str(label or "").strip()
        if not raw:
            return None
        if raw.startswith("provider:"):
            mode = raw.split(":", 1)[1].strip()
            if mode:
                ref = str(active_manifest.providers.get(mode) or "").strip()
                if ref:
                    return (f"providers.{mode}", ref)
            return None
        if raw in {"router", "policy", "attachment_context", "finalizer", "tool_registry"}:
            ref = str(getattr(active_manifest, raw, "") or "").strip()
            if ref:
                return (raw, ref)
        return None

    def _classify_pipeline_failure(
        self,
        *,
        stage: dict[str, object],
        validation: dict[str, object],
        smoke: dict[str, object],
        replay: dict[str, object],
        promotion: dict[str, object],
    ) -> dict[str, object]:
        if not bool(validation.get("ok")):
            return {
                "ok": False,
                "category": "manifest_validation",
                "failed_stage": "validation",
                "reason": self._pipeline_failure_text(validation) or "manifest_validation_failed",
                "retryable": True,
                "blocking_modules": self._pipeline_manifest_labels(validation),
            }
        if not bool(stage.get("ok")):
            return {
                "ok": False,
                "category": "stage_failed",
                "failed_stage": "stage",
                "reason": self._pipeline_failure_text(stage) or "stage_failed",
                "retryable": True,
                "blocking_modules": self._pipeline_manifest_labels(validation),
            }
        if smoke and not bool(smoke.get("ok")):
            return {
                "ok": False,
                "category": "shadow_smoke",
                "failed_stage": "smoke",
                "reason": self._pipeline_failure_text(smoke) or "shadow_smoke_failed",
                "retryable": True,
                "blocking_modules": [],
            }
        if replay and not bool(replay.get("ok")):
            return {
                "ok": False,
                "category": "shadow_replay",
                "failed_stage": "replay",
                "reason": self._pipeline_failure_text(replay) or "shadow_replay_failed",
                "retryable": True,
                "blocking_modules": [],
            }
        if promotion and not bool(promotion.get("ok")):
            return {
                "ok": False,
                "category": "promotion_failed",
                "failed_stage": "promotion",
                "reason": self._pipeline_failure_text(promotion) or "shadow_promotion_failed",
                "retryable": False,
                "blocking_modules": [],
            }
        return {
            "ok": True,
            "category": "none",
            "failed_stage": "",
            "reason": "",
            "retryable": False,
            "blocking_modules": [],
        }

    def _remediation_hints(
        self,
        *,
        classification: dict[str, object],
        validation: dict[str, object],
        smoke: dict[str, object],
        replay: dict[str, object],
        promote_if_healthy: bool,
    ) -> list[str]:
        category = str(classification.get("category") or "")
        blocking_modules = [str(item).strip() for item in classification.get("blocking_modules") or [] if str(item).strip()]
        hints: list[str] = []
        if category == "manifest_validation":
            if blocking_modules:
                hints.append(f"先修 shadow manifest 里这些模块引用: {', '.join(blocking_modules)}。")
            hints.append("优先查看 validation.errors，确认模块版本目录、manifest entrypoint 和接口方法是否齐全。")
            hints.append("manifest 未通过前不要 promote，保持 active manifest 不动。")
        elif category == "shadow_smoke":
            provider = smoke.get("provider")
            if isinstance(provider, dict) and provider.get("ok") is False and not provider.get("skipped"):
                hints.append("先修 provider 路径；当前 shadow smoke 已在最小请求上失败。")
            hints.append("查看 smoke.error、selected_modules 和 module_health，确认是模块逻辑错误还是 provider 初始化失败。")
            hints.append("修完后先重新跑 shadow smoke，再决定是否进入 replay。")
        elif category == "shadow_replay":
            hints.append("优先比对 replay.source_run_id 对应的 shadow log 和 replay.execution_trace，确认回放输入是否完整。")
            hints.append("如果 smoke 通过但 replay 失败，问题通常在多轮状态、附件上下文或最终整理链。")
        elif category == "promotion_failed":
            hints.append("先确认 validation/smoke/replay 全部为 ok，再检查 promote 的 rollback_pointer 和 active manifest 写入权限。")
        elif category == "stage_failed":
            hints.append("先确认 shadow manifest override 是否写入了有效模块引用。")
        elif category == "none" and promote_if_healthy:
            hints.append("当前 shadow pipeline 已通过；如果后续要切换 live，可直接 promote。")
        if category != "none":
            hints.append("修完后重新跑 /api/kernel/shadow/pipeline，让内核产出新的 upgrade attempt。")
        return hints

    def run_shadow_smoke(
        self,
        *,
        user_message: str = "给我今天的新闻",
        validate_provider: bool = True,
    ) -> dict[str, object]:
        from app.agent import OfficeAgent
        from app.models import ChatSettings

        shadow_manifest = self.load_shadow_manifest()
        validation = self.supervisor.validate_manifest(shadow_manifest)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        run_dir = self.context.runtime_dir / "shadow_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, object] = {
            "ok": False,
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "shadow_manifest": shadow_manifest.to_dict(),
            "validation": validation,
            "runtime_dir": str(run_dir),
        }

        if not validation.get("ok"):
            payload["error"] = "shadow_manifest_invalid"
            self._write_json(run_dir / "smoke_result.json", payload)
            self._write_json(self._last_shadow_run_path(), payload)
            return payload

        smoke_config = replace(
            self.supervisor._config,
            runtime_dir=run_dir,
            active_manifest_path=run_dir / "active_manifest.json",
            shadow_manifest_path=run_dir / "shadow_manifest.json",
            rollback_pointer_path=run_dir / "rollback_pointer.json",
            module_health_path=run_dir / "module_health.json",
        )
        write_active_manifest(smoke_config.active_manifest_path, shadow_manifest)
        write_active_manifest(smoke_config.shadow_manifest_path, shadow_manifest)

        try:
            smoke_runtime = build_kernel_runtime(smoke_config)
            active_validation = smoke_runtime.validate_active_manifest()
            smoke_agent = OfficeAgent(smoke_config, kernel_runtime=smoke_runtime)
            settings = ChatSettings()
            route = smoke_agent._route_request_by_rules(
                user_message=user_message,
                attachment_metas=[],
                settings=settings,
            )
            finalizer_preview = smoke_agent._sanitize_final_answer_text(
                '{"rows":[{"姓名":"张三","分数":95},{"姓名":"李四","分数":88}]}',
                user_message="把数据整理成表格",
                attachment_metas=[],
            )
            provider_info: dict[str, object] = {}
            auth_summary = smoke_agent._debug_openai_auth_summary()
            if validate_provider and bool(auth_summary.get("available")):
                try:
                    runner = smoke_agent._build_llm(
                        model=smoke_config.default_model,
                        max_output_tokens=256,
                        use_responses_api=False,
                    )
                    provider_info = {
                        "ok": True,
                        "mode": str(auth_summary.get("mode") or ""),
                        "runner_class": runner.__class__.__name__,
                    }
                except Exception as exc:
                    provider_info = {
                        "ok": False,
                        "mode": str(auth_summary.get("mode") or ""),
                        "error": str(exc),
                    }
            else:
                provider_info = {
                    "ok": False,
                    "skipped": True,
                    "mode": str(auth_summary.get("mode") or ""),
                    "reason": str(auth_summary.get("reason") or ""),
                }

            payload.update(
                {
                    "ok": True,
                    "route_task_type": str(route.get("task_type") or ""),
                    "route_execution_policy": str(route.get("execution_policy") or ""),
                    "finalizer_preview": str(finalizer_preview or "")[:400],
                    "provider": provider_info,
                    "selected_modules": dict(smoke_runtime.registry.selected_refs),
                    "module_health": dict(smoke_runtime.health_snapshot().module_health),
                    "active_validation": active_validation,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            payload.update(
                {
                    "ok": False,
                    "error": str(exc),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        self._write_json(run_dir / "smoke_result.json", payload)
        self._write_json(self._last_shadow_run_path(), payload)
        return payload

    def run_shadow_replay(self, *, replay_record: dict[str, object]) -> dict[str, object]:
        from app.agent import OfficeAgent
        from app.models import ChatSettings

        shadow_manifest = self.load_shadow_manifest()
        validation = self.supervisor.validate_manifest(shadow_manifest)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        run_dir = self.context.runtime_dir / "shadow_runs" / f"replay-{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, object] = {
            "ok": False,
            "run_id": run_id,
            "source_run_id": str(replay_record.get("run_id") or ""),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "shadow_manifest": shadow_manifest.to_dict(),
            "validation": validation,
            "runtime_dir": str(run_dir),
        }
        if not validation.get("ok"):
            payload["error"] = "shadow_manifest_invalid"
            self._write_json(run_dir / "replay_result.json", payload)
            self._write_json(self._last_shadow_run_path(), payload)
            return payload

        smoke_config = replace(
            self.supervisor._config,
            runtime_dir=run_dir,
            active_manifest_path=run_dir / "active_manifest.json",
            shadow_manifest_path=run_dir / "shadow_manifest.json",
            rollback_pointer_path=run_dir / "rollback_pointer.json",
            module_health_path=run_dir / "module_health.json",
        )
        write_active_manifest(smoke_config.active_manifest_path, shadow_manifest)
        write_active_manifest(smoke_config.shadow_manifest_path, shadow_manifest)

        try:
            shadow_runtime = build_kernel_runtime(smoke_config)
            shadow_agent = OfficeAgent(smoke_config, kernel_runtime=shadow_runtime)
            settings_payload = replay_record.get("settings")
            settings = ChatSettings(**settings_payload) if isinstance(settings_payload, dict) else ChatSettings()
            attachment_metas = replay_record.get("attachment_metas")
            history_turns_before = replay_record.get("history_turns_before")
            route_state_input = replay_record.get("route_state_input")
            result = shadow_agent.run_chat(
                history_turns=list(history_turns_before) if isinstance(history_turns_before, list) else [],
                summary=str(replay_record.get("summary_before") or ""),
                user_message=str(replay_record.get("message") or replay_record.get("message_preview") or ""),
                attachment_metas=list(attachment_metas) if isinstance(attachment_metas, list) else [],
                settings=settings,
                session_id=str(replay_record.get("session_id") or ""),
                route_state=dict(route_state_input) if isinstance(route_state_input, dict) else {},
                progress_cb=None,
            )
            (
                text,
                tool_events,
                _attachment_note,
                execution_plan,
                execution_trace,
                pipeline_hooks,
                _debug_flow,
                _agent_panels,
                active_roles,
                current_role,
                _role_states,
                answer_bundle,
                token_usage,
                effective_model,
                route_state,
            ) = result
            payload.update(
                {
                    "ok": True,
                    "effective_model": effective_model,
                    "text_preview": str(text or "")[:600],
                    "tool_event_count": len(tool_events),
                    "execution_plan": execution_plan,
                    "execution_trace": execution_trace[-10:],
                    "pipeline_hook_count": len(pipeline_hooks),
                    "active_roles": active_roles,
                    "current_role": current_role,
                    "answer_bundle": answer_bundle,
                    "token_usage": token_usage,
                    "route_state": route_state,
                    "selected_modules": dict(shadow_runtime.registry.selected_refs),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            payload.update(
                {
                    "ok": False,
                    "error": str(exc),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        self._write_json(run_dir / "replay_result.json", payload)
        self._write_json(self._last_shadow_run_path(), payload)
        return payload

    def run_shadow_contracts(self) -> dict[str, object]:
        shadow_manifest = self.load_shadow_manifest()
        payload = self.supervisor.probe_manifest_contracts(shadow_manifest)
        payload["shadow_manifest"] = shadow_manifest.to_dict()
        payload["checked_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    def run_shadow_pipeline(
        self,
        *,
        overrides: dict[str, object] | None = None,
        smoke_message: str = "给我今天的新闻",
        validate_provider: bool = True,
        replay_record: dict[str, object] | None = None,
        promote_if_healthy: bool = False,
    ) -> dict[str, object]:
        run_id = self._pipeline_run_id()
        started_at = datetime.now(timezone.utc).isoformat()
        stage = self.stage_shadow_manifest(overrides=overrides or {})
        validation = stage.get("validation") if isinstance(stage.get("validation"), dict) else self.validate_shadow_manifest()
        contracts = self.run_shadow_contracts()
        smoke: dict[str, object] = {}
        replay: dict[str, object] = {}
        promotion: dict[str, object] = {}

        if bool(validation.get("ok")) and bool(contracts.get("ok")):
            smoke = self.run_shadow_smoke(
                user_message=smoke_message,
                validate_provider=bool(validate_provider),
            )
            if isinstance(replay_record, dict) and replay_record:
                replay = self.run_shadow_replay(replay_record=replay_record)
            if req_ready := (
                bool(promote_if_healthy)
                and bool(smoke.get("ok"))
                and (not replay or bool(replay.get("ok")))
            ):
                promotion = self.promote_shadow_manifest()
            else:
                req_ready = False
        else:
            req_ready = False

        overall_ok = bool(stage.get("ok")) and bool(validation.get("ok"))
        overall_ok = overall_ok and bool(contracts.get("ok"))
        if smoke:
            overall_ok = overall_ok and bool(smoke.get("ok"))
        if replay:
            overall_ok = overall_ok and bool(replay.get("ok"))
        if promotion:
            overall_ok = overall_ok and bool(promotion.get("ok"))

        classification = self._classify_pipeline_failure(
            stage=stage,
            validation=validation,
            smoke=smoke,
            replay=replay,
            promotion=promotion,
        )
        remediation_hints = self._remediation_hints(
            classification=classification,
            validation=validation,
            smoke=smoke,
            replay=replay,
            promote_if_healthy=bool(promote_if_healthy),
        )
        payload: dict[str, object] = {
            "ok": overall_ok,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "target_overrides": dict(overrides or {}),
            "smoke_message": str(smoke_message or ""),
            "validate_provider": bool(validate_provider),
            "replay_source_run_id": str(replay_record.get("run_id") or "") if isinstance(replay_record, dict) else "",
            "promote_if_healthy": bool(promote_if_healthy),
            "promotion_attempted": bool(req_ready),
            "stage": stage,
            "validation": validation,
            "contracts": contracts,
            "smoke": smoke,
            "replay": replay,
            "promotion": promotion,
            "failure_classification": classification,
            "remediation_hints": remediation_hints,
        }
        self._write_json(self._upgrade_runs_dir() / f"{run_id}.json", payload)
        self._write_json(self._last_upgrade_run_path(), payload)
        return payload

    def run_shadow_auto_repair(
        self,
        *,
        base_upgrade_run: dict[str, object] | None = None,
        replay_record: dict[str, object] | None = None,
        smoke_message: str | None = None,
        validate_provider: bool | None = None,
        promote_if_healthy: bool | None = None,
        max_attempts: int = 1,
    ) -> dict[str, object]:
        base = dict(base_upgrade_run or self.read_last_upgrade_run())
        repair_run_id = self._pipeline_run_id()
        started_at = datetime.now(timezone.utc).isoformat()
        if not base:
            payload = {
                "ok": False,
                "run_id": repair_run_id,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "reason": "missing_base_upgrade_run",
            }
            self._write_json(self._repair_runs_dir() / f"{repair_run_id}.json", payload)
            self._write_json(self._last_repair_run_path(), payload)
            return payload

        classification = base.get("failure_classification")
        classification = dict(classification) if isinstance(classification, dict) else {}
        category = str(classification.get("category") or "")
        blocking_modules = [str(item).strip() for item in classification.get("blocking_modules") or [] if str(item).strip()]
        active_manifest = self.supervisor.load_active_manifest()
        attempt_limit = max(1, min(5, int(max_attempts)))
        attempts: list[dict[str, object]] = []
        applied_overrides: dict[str, object] = {}
        strategy = ""
        current_base = base

        for attempt_index in range(1, attempt_limit + 1):
            current_classification = current_base.get("failure_classification")
            current_classification = dict(current_classification) if isinstance(current_classification, dict) else {}
            current_category = str(current_classification.get("category") or "")
            current_blocks = [str(item).strip() for item in current_classification.get("blocking_modules") or [] if str(item).strip()]

            repair_plan: dict[str, object] = {"ok": False, "reason": "unsupported_failure_category", "strategy": "", "overrides": {}}
            if current_category in {"manifest_validation", "stage_failed"} and current_blocks:
                overrides: dict[str, object] = {}
                provider_overrides: dict[str, str] = {}
                for label in current_blocks:
                    override = self._safe_active_override_for_label(label, active_manifest)
                    if not override:
                        continue
                    key, ref = override
                    if key.startswith("providers."):
                        provider_overrides[key.split(".", 1)[1]] = ref
                    else:
                        overrides[key] = ref
                if provider_overrides:
                    overrides["providers"] = provider_overrides
                if overrides:
                    repair_plan = {
                        "ok": True,
                        "reason": "reset_blocking_modules_to_active",
                        "strategy": "reset_blocking_modules_to_active",
                        "overrides": overrides,
                    }
            elif current_category == "shadow_smoke":
                provider_info = current_base.get("smoke")
                provider_info = dict(provider_info) if isinstance(provider_info, dict) else {}
                provider_payload = provider_info.get("provider")
                provider_payload = dict(provider_payload) if isinstance(provider_payload, dict) else {}
                mode = str(provider_payload.get("mode") or "").strip()
                if mode:
                    active_ref = str(active_manifest.providers.get(mode) or "").strip()
                    if active_ref:
                        repair_plan = {
                            "ok": True,
                            "reason": "reset_provider_to_active",
                            "strategy": "reset_provider_to_active",
                            "overrides": {"providers": {mode: active_ref}},
                        }

            attempt_record: dict[str, object] = {
                "attempt_index": attempt_index,
                "category": current_category,
                "blocking_modules": current_blocks,
                "plan": repair_plan,
            }
            attempts.append(attempt_record)
            if not bool(repair_plan.get("ok")):
                break

            override_payload = dict(repair_plan.get("overrides") or {})
            if override_payload == applied_overrides:
                attempt_record["plan"] = dict(repair_plan) | {"ok": False, "reason": "duplicate_repair_plan"}
                break

            applied_overrides = override_payload
            strategy = str(repair_plan.get("strategy") or "")
            repaired_pipeline = self.run_shadow_pipeline(
                overrides=applied_overrides,
                smoke_message=str(smoke_message or current_base.get("smoke_message") or "给我今天的新闻"),
                validate_provider=bool(validate_provider if validate_provider is not None else current_base.get("validate_provider", True)),
                replay_record=replay_record,
                promote_if_healthy=bool(promote_if_healthy if promote_if_healthy is not None else current_base.get("promote_if_healthy", False)),
            )
            attempt_record["pipeline_run_id"] = str(repaired_pipeline.get("run_id") or "")
            attempt_record["pipeline_ok"] = bool(repaired_pipeline.get("ok"))
            current_base = repaired_pipeline
            if bool(repaired_pipeline.get("ok")):
                break

        payload = {
            "ok": bool(current_base.get("ok")),
            "run_id": repair_run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "base_upgrade_run_id": str(base.get("run_id") or ""),
            "base_failure_classification": classification,
            "strategy": strategy,
            "applied_overrides": applied_overrides,
            "attempts": attempts,
            "repaired_pipeline": current_base if isinstance(current_base, dict) else {},
        }
        self._write_json(self._repair_runs_dir() / f"{repair_run_id}.json", payload)
        self._write_json(self._last_repair_run_path(), payload)
        return payload


def build_kernel_runtime(config: AppConfig) -> KernelRuntime:
    context = ModuleRuntimeContext(
        workspace_root=config.workspace_root,
        modules_dir=config.modules_dir,
        runtime_dir=config.runtime_dir,
    )
    loader = ModuleLoader(context)
    supervisor = KernelSupervisor(config, context=context, loader=loader)
    registry = supervisor.load_registry()
    return KernelRuntime(context=context, loader=loader, supervisor=supervisor, registry=registry)
