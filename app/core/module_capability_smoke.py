from __future__ import annotations

from typing import Any


def _check(label: str, kind: str, ok: bool, detail: str = "", **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": label,
        "kind": kind,
        "ok": bool(ok),
        "detail": str(detail or ""),
    }
    payload.update(extra)
    return payload


def run_module_capability_smoke(*, runtime: Any, agent: Any, settings: Any, artifact_root: Any) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    selected_refs = dict(getattr(runtime.registry, "selected_refs", {}) or {})
    router = runtime.registry.router
    policy = runtime.registry.policy
    finalizer = runtime.registry.finalizer
    tool_registry = runtime.registry.tool_registry
    attachment_meta = {
        "id": "contract-doc-1",
        "original_name": "design.pdf",
        "kind": "document",
        "size": 4096,
        "suffix": ".pdf",
        "path": str(artifact_root / "design.pdf"),
    }

    try:
        route = router.route(
            agent=agent,
            user_message="给我今天的新闻",
            attachment_metas=[],
            settings=settings,
            route_state={},
        )
        checks.append(
            _check(
                "router:web_news",
                "router",
                str(route.get("task_type") or "") == "web_news"
                and str(route.get("execution_policy") or "") == "web_news_brief",
                detail=str(route.get("task_type") or ""),
                resolved_ref=str(selected_refs.get("router") or ""),
                task_type=str(route.get("task_type") or ""),
                execution_policy=str(route.get("execution_policy") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("router:web_news", "router", False, detail=str(exc), resolved_ref=str(selected_refs.get("router") or "")))

    try:
        route = router.route(
            agent=agent,
            user_message="根据原文定位这句话在哪一页，并给出处",
            attachment_metas=[attachment_meta],
            settings=settings,
            route_state={},
        )
        checks.append(
            _check(
                "router:evidence_lookup",
                "router",
                str(route.get("task_type") or "") == "evidence_lookup",
                detail=str(route.get("task_type") or ""),
                resolved_ref=str(selected_refs.get("router") or ""),
                task_type=str(route.get("task_type") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("router:evidence_lookup", "router", False, detail=str(exc), resolved_ref=str(selected_refs.get("router") or "")))

    try:
        route = router.route(
            agent=agent,
            user_message="解释这份设计文档的整体思路",
            attachment_metas=[attachment_meta],
            settings=settings,
            route_state={},
        )
        task_type = str(route.get("task_type") or "")
        primary_intent = str(route.get("primary_intent") or "")
        checks.append(
            _check(
                "router:attachment_explain",
                "router",
                primary_intent == "understanding" and task_type != "evidence_lookup",
                detail=task_type,
                resolved_ref=str(selected_refs.get("router") or ""),
                task_type=task_type,
                primary_intent=primary_intent,
            )
        )
    except Exception as exc:
        checks.append(_check("router:attachment_explain", "router", False, detail=str(exc), resolved_ref=str(selected_refs.get("router") or "")))

    try:
        normalized = policy.normalize_route(
            agent=agent,
            route={"task_type": "web_news", "execution_policy": "web_news_brief"},
            fallback={"task_type": "web_news", "execution_policy": "web_news_brief"},
            settings=settings,
        )
        checks.append(
            _check(
                "policy:web_news",
                "policy",
                str(normalized.get("execution_policy") or "") == "web_news_brief"
                and not bool(normalized.get("use_reviewer"))
                and not bool(normalized.get("use_revision")),
                detail=str(normalized.get("execution_policy") or ""),
                resolved_ref=str(selected_refs.get("policy") or ""),
                execution_policy=str(normalized.get("execution_policy") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("policy:web_news", "policy", False, detail=str(exc), resolved_ref=str(selected_refs.get("policy") or "")))

    try:
        normalized = policy.normalize_route(
            agent=agent,
            route={"task_type": "evidence_lookup", "execution_policy": "evidence_full_pipeline"},
            fallback={"task_type": "evidence_lookup", "execution_policy": "evidence_full_pipeline"},
            settings=settings,
        )
        checks.append(
            _check(
                "policy:evidence_lookup",
                "policy",
                str(normalized.get("execution_policy") or "") == "evidence_full_pipeline"
                and bool(normalized.get("use_reviewer"))
                and bool(normalized.get("use_revision")),
                detail=str(normalized.get("execution_policy") or ""),
                resolved_ref=str(selected_refs.get("policy") or ""),
                execution_policy=str(normalized.get("execution_policy") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("policy:evidence_lookup", "policy", False, detail=str(exc), resolved_ref=str(selected_refs.get("policy") or "")))

    try:
        sanitized = finalizer.sanitize(
            agent=agent,
            text='{"rows":[{"姓名":"张三","分数":95},{"姓名":"李四","分数":88}]}',
            user_message="把数据整理成表格",
            attachment_metas=[],
        )
        checks.append(
            _check(
                "finalizer:table",
                "finalizer",
                "| 姓名 | 分数 |" in str(sanitized),
                detail=str(sanitized)[:120],
                resolved_ref=str(selected_refs.get("finalizer") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("finalizer:table", "finalizer", False, detail=str(exc), resolved_ref=str(selected_refs.get("finalizer") or "")))

    try:
        sanitized = finalizer.sanitize(
            agent=agent,
            text='{"subject":"测试邮件","to":["a@example.com"],"body":"你好，请查收。"}',
            user_message="帮我写一封邮件",
            attachment_metas=[],
        )
        checks.append(
            _check(
                "finalizer:mail",
                "finalizer",
                str(sanitized).startswith("邮件主题：测试邮件"),
                detail=str(sanitized)[:120],
                resolved_ref=str(selected_refs.get("finalizer") or ""),
            )
        )
    except Exception as exc:
        checks.append(_check("finalizer:mail", "finalizer", False, detail=str(exc), resolved_ref=str(selected_refs.get("finalizer") or "")))

    try:
        tools = tool_registry.build_langchain_tools(agent=agent)
        described = tool_registry.describe_tools(agent=agent)
        described_tools = list(described.get("tools") or []) if isinstance(described, dict) else []
        checks.append(
            _check(
                "tool_registry:describe",
                "tool_registry",
                bool(tools) and int(described.get("tool_count") or 0) == len(tools) and bool(described_tools),
                detail=f"tool_count={len(tools)}",
                resolved_ref=str(selected_refs.get("tool_registry") or ""),
                tool_count=len(tools),
                described_count=int(described.get("tool_count") or 0) if isinstance(described, dict) else 0,
            )
        )
    except Exception as exc:
        checks.append(_check("tool_registry:describe", "tool_registry", False, detail=str(exc), resolved_ref=str(selected_refs.get("tool_registry") or "")))

    auth_summary = agent.debug_openai_auth_summary()
    for mode in sorted((runtime.registry.providers or {}).keys()):
        provider = runtime.registry.providers.get(mode)
        label = f"provider:{mode}:runner_interface"
        try:
            auth = agent.resolve_auth(mode)
            if not bool(getattr(auth, "available", False)):
                raise RuntimeError(str(getattr(auth, "reason", "") or f"{mode} auth unavailable"))
            runner = provider.build_runner(  # type: ignore[union-attr]
                agent=agent,
                auth=auth,
                model=agent.default_model(),
                max_output_tokens=64,
                use_responses_api=False,
            )
            checks.append(
                _check(
                    label,
                    "provider",
                    callable(getattr(runner, "invoke", None)) and callable(getattr(runner, "bind_tools", None)),
                    detail=runner.__class__.__name__,
                    resolved_ref=str(selected_refs.get(f"provider:{mode}") or ""),
                    runner_class=runner.__class__.__name__,
                )
            )
        except Exception as exc:
            mode_matches = str(auth_summary.get("mode") or "").strip() == mode
            available = bool(auth_summary.get("available"))
            skipped = not (mode_matches and available)
            checks.append(
                _check(
                    label,
                    "provider",
                    skipped,
                    detail=str(exc),
                    resolved_ref=str(selected_refs.get(f"provider:{mode}") or ""),
                    skipped=skipped,
                )
            )

    return checks
