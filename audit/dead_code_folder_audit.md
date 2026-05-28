# 死代码目录审计

本次审计是纯扫描（scan-only）。没有删除、重命名或重构任何源码文件。

证据输入：
- `audit/all_tracked_files.txt`：tracked 文件清单。
- `audit/import_reference_map.txt`：Python import 关系映射。
- `audit/test_reference_map.txt` 与 `audit/pytest_collect_only.txt`：测试覆盖和引用信号。
- `audit/dynamic_loading_hits.txt`：动态导入 / manifest / 自动发现路径风险。
- `audit/runtime_entrypoint_map.md`：启动路径与运行时入口上下文。

## 目录：.github
### 观察到的用途
GitHub Actions 工作流配置。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `.github/workflows/regression-ci.yml` | 0 | 0 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：agents
### 观察到的用途
在线运行的 `vintage_programmer` 主 agent 所使用的 Markdown 规范文件和本地化覆盖内容。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：1 处测试引用
- Documentation references：5 处文档 / README 引用
- Dynamic loading risk：high（高）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `agents/vintage_programmer/agent.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/identity.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/en/agent.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/en/identity.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/en/soul.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/en/tools.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/ja-JP/agent.md` | 0 | 1 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/ja-JP/identity.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/ja-JP/soul.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/locales/ja-JP/tools.md` | 0 | 1 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/soul.md` | 0 | 0 | high（高） | keep（保留） | 保留 |
| `agents/vintage_programmer/tools.md` | 0 | 1 | high（高） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：app
### 观察到的用途
主 FastAPI 应用层，包含运行时编排、持久化和前端静态资源服务。
### 当前引用情况
- Imports：129 处外部 import 命中
- Runtime references：102 处运行时 / 配置引用
- Test references：31 处测试引用
- Documentation references：2 处文档 / README 引用
- Dynamic loading risk：medium（中）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `app/__init__.py` | 3 | 1 | low（低） | keep（保留） | 保留 |
| `app/action_validator.py` | 3 | 1 | low（低） | keep（保留） | 保留 |
| `app/answer_stream_state.py` | 1 | 2 | low（低） | keep（保留） | 保留 |
| `app/attachment_argument_rewriter.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/attachment_evidence.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/attachments.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `app/browser_runtime.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/candidate_intents.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/chat_product_runtime.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/codex_runner.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `app/config.py` | 14 | 10 | low（低） | keep（保留） | 保留 |
| `app/context_assembly.py` | 9 | 1 | low（低） | keep（保留） | 保留 |
| `app/context_meter.py` | 2 | 2 | low（低） | keep（保留） | 保留 |
| `app/context_pack.py` | 3 | 4 | low（低） | keep（保留） | 保留 |
| `app/document_text.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `app/evolution.py` | 2 | 1 | low（低） | keep（保留） | 保留 |
| `app/frame_resolver.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/i18n.py` | 10 | 2 | low（低） | keep（保留） | 保留 |
| `app/intent_classifier.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/intent_constants.py` | 4 | 0 | low（低） | keep（保留） | 保留 |
| `app/intent_schema.py` | 10 | 2 | low（低） | keep（保留） | 保留 |
| `app/intent_scorer.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/kernel_robot_main.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/llm_exchange.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/local_tools.py` | 7 | 5 | low（低） | keep（保留） | 保留 |
| `app/main.py` | 2 | 8 | low（低） | keep（保留） | 保留 |
| `app/models.py` | 7 | 3 | low（低） | keep（保留） | 保留 |
| `app/openai_auth.py` | 5 | 1 | low（低） | keep（保留） | 保留 |
| `app/phase_timing.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `app/pipeline_hooks.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/policy_router.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/pricing.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/role_runtime.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/route_trace.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/route_verifier.py` | 1 | 2 | low（低） | keep（保留） | 保留 |
| `app/router_signals.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/runtime_boundary.py` | 3 | 5 | low（低） | keep（保留） | 保留 |
| `app/runtime_contract.py` | 3 | 2 | low（低） | keep（保留） | 保留 |
| `app/runtime_errors.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `app/runtime_hints.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/runtime_trace_labels.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/sandbox.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `app/serialization.py` | 14 | 6 | low（低） | keep（保留） | 保留 |
| `app/session_context.py` | 5 | 1 | low（低） | keep（保留） | 保留 |
| `app/session_migration.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/storage.py` | 2 | 3 | low（低） | keep（保留） | 保留 |
| `app/tool_name_normalizer.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/tool_trace_summary.py` | 4 | 1 | low（低） | keep（保留） | 保留 |
| `app/trace_events.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/update_manager.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `app/vintage_programmer_runtime.py` | 1 | 4 | low（低） | keep（保留） | 保留 |
| `app/workbench.py` | 3 | 1 | low（低） | keep（保留） | 保留 |
### 目录级建议
partially_delete_after_approval（审批后仅删除其中一部分）

说明：本节只列出 `app` 目录下直接审查的 52 个文件；子目录中的 tracked 文件会在各自章节单独覆盖。

## 目录：app/agents
### 观察到的用途
旧的 agent / plugin 脚手架，以及对当前 office 运行时角色系统的兼容包装层。
### 当前引用情况
- Imports：39 处外部 import 命中
- Runtime references：39 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：medium（中）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `app/agents/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/agent_plugin.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/answer_bundle_support.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/citation_support.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/coder_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/coder_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/coder_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/conflict_detector_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/conflict_detector_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/coordinator_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/coordinator_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/coordinator_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/coordinator_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/critic_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/critic_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/critic_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/executor_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/executor_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/executor_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/file_reader_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/fixer_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/manifests/conflict_detector_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/coordinator_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/file_reader_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/fixer_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/planner_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/researcher_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/reviewer_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/revision_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/router_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/structurer_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/summarizer_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/manifests/worker_agent.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/navigator_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/navigator_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/navigator_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/office_specialist_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/office_specialist_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/office_specialist_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/planner_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/planner_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/planner_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/planner_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/planner_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/planning_support.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/plugin_base.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/researcher_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/researcher_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/researcher_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/researcher_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/review_support.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/reviewer_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/reviewer_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/reviewer_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/reviewer_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/reviewer_helpers.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/reviewer_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/revision_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/revision_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/role_catalog.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/role_contracts.py` | 0 | 0 | low（低） | not_safe_to_delete（当前不可删除） | 第 2 阶段不要删除 |
| `app/agents/role_debug_support.py` | 1 | 0 | low（低） | not_safe_to_delete（当前不可删除） | 第 2 阶段不要删除 |
| `app/agents/role_helpers.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/role_registry.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/role_smoke.py` | 0 | 0 | low（低） | not_safe_to_delete（当前不可删除） | 第 2 阶段不要删除 |
| `app/agents/router_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/runtime_controller.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/runtime_profiles.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/specialist_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/structurer_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/structurer_role.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/summarizer_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/summarizer_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/summarizer_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/summarizer_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/tool_user_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/tool_user_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/tool_user_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/worker_agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/worker_agent/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/agents/worker_agent/agent.py` | 0 | 0 | low（低） | safe_to_delete_after_approval（审批后可删） | 在第 2 阶段经 owner 审批后删除 |
| `app/agents/worker_agent/manifest.json` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
### 目录级建议
partially_delete_after_approval（审批后仅删除其中一部分）

## 目录：app/api
### 观察到的用途
指向主 FastAPI app 的轻量兼容入口别名。
### 当前引用情况
- Imports：1 处外部 import 命中
- Runtime references：1 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `app/api/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/api/main.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `app/api/routes/__init__.py` | 0 | 0 | low（低） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
### 目录级建议
needs_runtime_test_before_delete（删除前需要运行时验证）

## 目录：app/static
### 观察到的用途
前端页面壳、样式文件以及 vendored 浏览器库。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：3 处运行时 / 配置引用
- Test references：3 处测试引用
- Documentation references：2 处文档 / README 引用
- Dynamic loading risk：medium（中）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `app/static/app.js` | 2 | 3 | medium（中） | keep（保留） | 保留 |
| `app/static/assets/mat-logo-horizontal.jpg` | 0 | 0 | medium（中） | keep（保留） | 保留 |
| `app/static/favicon.svg` | 1 | 0 | medium（中） | keep（保留） | 保留 |
| `app/static/index.html` | 1 | 1 | medium（中） | keep（保留） | 保留 |
| `app/static/locales.js` | 1 | 1 | medium（中） | keep（保留） | 保留 |
| `app/static/styles.css` | 1 | 1 | medium（中） | keep（保留） | 保留 |
| `app/static/vendor/htm.umd.js` | 1 | 0 | medium（中） | keep（保留） | 保留 |
| `app/static/vendor/marked.umd.js` | 1 | 1 | medium（中） | keep（保留） | 保留 |
| `app/static/vendor/purify.min.js` | 1 | 1 | medium（中） | keep（保留） | 保留 |
| `app/static/vendor/react-dom.production.min.js` | 1 | 0 | medium（中） | keep（保留） | 保留 |
| `app/static/vendor/react.production.min.js` | 1 | 0 | medium（中） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：docs
### 观察到的用途
架构、运维和可观测性文档。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：1 处测试引用
- Documentation references：7 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `docs/architecture/tool_provider_contract.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/assets/brand/mat-logo-horizontal.jpg` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/assets/screenshots/kernel_robot_home.png` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/assets/screenshots/role_agent_lab_home.png` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/internal_design_manual.md` | 0 | 1 | low（低） | keep（保留） | 保留 |
| `docs/observability/trace_guide.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/observability/troubleshooting.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `docs/operations/tool_provider_degradation_guide.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：evals
### 观察到的用途
回归用例清单、夹具文件和回放样本。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：4 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `evals/README.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/cases.json` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `evals/fixtures/generated/.gitkeep` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/fixtures/spec_excerpt.txt` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `evals/fixtures/spec_without_15h.txt` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `evals/gate_cases.json` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/README.md` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/office/office_attachment_followup.json` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/research/research_fetch_failure.json` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/research/research_normal_top_fetch.json` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/swarm/swarm_fanout_merge.json` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/replay_samples/swarm/swarm_serial_replay_conflict.json` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `evals/research_gate_cases.json` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `evals/swarm_gate_cases.json` | 1 | 0 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：packages
### 观察到的用途
共享运行时包，以及历史兼容占位目录。
### 当前引用情况
- Imports：52 处外部 import 命中
- Runtime references：51 处运行时 / 配置引用
- Test references：7 处测试引用
- Documentation references：1 处文档 / README 引用
- Dynamic loading risk：high（高）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/README.md` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/__init__.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
### 目录级建议
needs_runtime_test_before_delete（删除前需要运行时验证）

说明：本节只列出 `packages` 目录下直接审查的 2 个文件；子目录中的 tracked 文件会在各自章节单独覆盖。

## 目录：packages/office_modules
### 观察到的用途
当前运行时实际加载的 office agent 后端包。
### 当前引用情况
- Imports：38 处外部 import 命中
- Runtime references：35 处运行时 / 配置引用
- Test references：6 处测试引用
- Documentation references：1 处文档 / README 引用
- Dynamic loading risk：high（高）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/office_modules/__init__.py` | 0 | 1 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/agent_module.py` | 1 | 0 | high（高） | keep（保留） | 保留 |
| `packages/office_modules/answer_bundle_support.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/citation_support.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/conflict_detector_role.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/execution_engine.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/execution_policy.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/execution_runtime.py` | 4 | 1 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/execution_state.py` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `packages/office_modules/intent_support.py` | 2 | 1 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/legacy_runtime_support.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/manifest.json` | 0 | 0 | high（高） | uncertain_dynamic_usage（存在动态加载不确定性） | 删除前先确认动态加载 / 模块发现路径 |
| `packages/office_modules/memory_module.py` | 1 | 0 | high（高） | keep（保留） | 保留 |
| `packages/office_modules/module_wrapper_surface.py` | 0 | 0 | medium（中） | probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证） | 先做 runtime smoke 和 pytest，再考虑删除 |
| `packages/office_modules/office_agent_runtime.py` | 2 | 2 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/output_module.py` | 1 | 0 | high（高） | keep（保留） | 保留 |
| `packages/office_modules/planner_role.py` | 4 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/planning_support.py` | 7 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/request_analysis.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/review_support.py` | 5 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/reviewer_helpers.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/reviewer_role.py` | 4 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/revision_role.py` | 4 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/role_catalog.py` | 5 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/role_helpers.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/roles.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/router_hints.py` | 2 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/runtime_profiles.py` | 6 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/specialist_role.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/structurer_role.py` | 4 | 0 | low（低） | keep（保留） | 保留 |
| `packages/office_modules/tools.py` | 1 | 3 | high（高） | keep（保留） | 保留 |
### 目录级建议
needs_runtime_test_before_delete（删除前需要运行时验证）

## 目录：packages/runtime_core
### 观察到的用途
能力包加载器、blackboard 和工具执行基础设施。
### 当前引用情况
- Imports：13 处外部 import 命中
- Runtime references：12 处运行时 / 配置引用
- Test references：1 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/runtime_core/__init__.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `packages/runtime_core/blackboard.py` | 3 | 0 | low（低） | keep（保留） | 保留 |
| `packages/runtime_core/capability_loader.py` | 9 | 1 | low（低） | keep（保留） | 保留 |
| `packages/runtime_core/legacy_host_support.py` | 1 | 0 | low（低） | keep（保留） | 保留 |
| `packages/runtime_core/tool_execution_bus.py` | 2 | 1 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：packages/agent-core
### 观察到的用途
历史连字符命名的兼容占位目录，用于迁移期文档说明。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/agent-core/README.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 删除前需要 owner 明确确认 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：packages/office-modules
### 观察到的用途
历史连字符命名的兼容占位目录，用于迁移期文档说明。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/office-modules/README.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 删除前需要 owner 明确确认 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：packages/runtime-core
### 观察到的用途
历史连字符命名的兼容占位目录，用于迁移期文档说明。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `packages/runtime-core/README.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 删除前需要 owner 明确确认 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：tests
### 观察到的用途
单测、集成测试、路由测试和回归测试。
### 当前引用情况
- Imports：6 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：6 处测试引用
- Documentation references：1 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `tests/__init__.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/conftest.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/docs/test_console_workstation_shell.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/docs/test_markdown_packaging.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/integration/test_chat_vintage_programmer_api.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/modules/test_office_runtime_contract.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/modules/test_request_analysis_guards.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/modules/test_tool_registration.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/__init__.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/support.py` | 0 | 6 | low（低） | keep（保留） | 保留 |
| `tests/router/test_followup_inheritance.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_grounded_generation.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_low_confidence_fallback.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_mixed_intents.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_single_turn_intents.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_translation_task_control.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/router/test_verifier_guards.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_action_validator.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_answer_stream_state.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_attachment_argument_rewriter.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_chat_product_boundaries.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_compaction_context_pack.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_context_meter.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_context_pack.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_context_pack_minimal.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_frontend_locale_regressions.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_llm_exchange.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_local_tool_executor_projects.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_local_tools_exec_command.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_local_tools_public_surface.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_runtime_boundary.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_runtime_hints.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_runtime_trace_labels.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_safe_serialization_static.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_serialization.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_session_context_task_reset.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_session_migration.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_tool_execution_bus.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_tool_name_normalizer.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_tool_trace_summary.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_trace_events.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_update_manager.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_update_plan_stability.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_upload_store.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_vintage_programmer_runtime.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
| `tests/test_vp_env_config.py` | 0 | 0 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：scripts
### 观察到的用途
仓库维护脚本和边界检查脚本。
### 当前引用情况
- Imports：1 处外部 import 命中
- Runtime references：1 处运行时 / 配置引用
- Test references：1 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `scripts/check_platform_boundaries.py` | 1 | 1 | low（低） | keep（保留） | 保留 |
### 目录级建议
keep（保留）

## 目录：.env.example
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `.env.example` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：.gitignore
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `.gitignore` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：LICENSE
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `LICENSE` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：NOTICE
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `NOTICE` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：README.en.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `README.en.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：README.ja.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `README.ja.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：README.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `README.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：README.windows.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `README.windows.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：README.zh-CN.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `README.zh-CN.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：RELEASING.md
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `RELEASING.md` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：requirements-dev.txt
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `requirements-dev.txt` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：requirements.txt
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `requirements.txt` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：run.ps1
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `run.ps1` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## 目录：run.sh
### 观察到的用途
当前分支下该目录没有 tracked 文件。
### 当前引用情况
- Imports：0 处外部 import 命中
- Runtime references：0 处运行时 / 配置引用
- Test references：0 处测试引用
- Documentation references：0 处文档 / README 引用
- Dynamic loading risk：low（低）
### 已审查文件
| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |
|---|---:|---:|---|---|---|
| `run.sh` | 0 | 0 | low（低） | needs_owner_confirmation（需要 owner 确认） | 目录在磁盘上存在，但当前分支没有 tracked 文件 |
### 目录级建议
needs_owner_confirmation（需要 owner 确认）

## app/agents 删除就绪度

整目录结论：当前分支状态下，`app/agents` 的整体判定是 `not_safe_to_delete（当前不可删除）`。

阻塞证据：
- `packages/office_modules/office_agent_runtime.py` 仍然导入 `app.agents.role_debug_support`，并调用其中的 debug helper。
- `app.agents.role_debug_support` 依赖 `app.agents.role_smoke` 和 `app.agents.role_contracts`。
- 除了这条 debug 依赖链，没有发现测试或配置路径还依赖其余旧的 plugin 风格 agents。

### safe_to_delete_after_approval（审批后可删）
- `app/agents/agent_plugin.py`
- `app/agents/answer_bundle_support.py`
- `app/agents/citation_support.py`
- `app/agents/coder_agent/agent.py`
- `app/agents/conflict_detector_agent.py`
- `app/agents/conflict_detector_role.py`
- `app/agents/coordinator_agent.py`
- `app/agents/coordinator_agent/agent.py`
- `app/agents/critic_agent/agent.py`
- `app/agents/executor_agent/agent.py`
- `app/agents/file_reader_agent.py`
- `app/agents/fixer_agent.py`
- `app/agents/navigator_agent/agent.py`
- `app/agents/office_specialist_agent/agent.py`
- `app/agents/planner_agent.py`
- `app/agents/planner_agent/agent.py`
- `app/agents/planner_role.py`
- `app/agents/planning_support.py`
- `app/agents/plugin_base.py`
- `app/agents/researcher_agent.py`
- `app/agents/researcher_agent/agent.py`
- `app/agents/review_support.py`
- `app/agents/reviewer_agent.py`
- `app/agents/reviewer_agent/agent.py`
- `app/agents/reviewer_helpers.py`
- `app/agents/reviewer_role.py`
- `app/agents/revision_agent.py`
- `app/agents/revision_role.py`
- `app/agents/role_catalog.py`
- `app/agents/role_helpers.py`
- `app/agents/role_registry.py`
- `app/agents/router_agent.py`
- `app/agents/runtime_controller.py`
- `app/agents/runtime_profiles.py`
- `app/agents/specialist_role.py`
- `app/agents/structurer_agent.py`
- `app/agents/structurer_role.py`
- `app/agents/summarizer_agent.py`
- `app/agents/summarizer_agent/agent.py`
- `app/agents/tool_user_agent/agent.py`
- `app/agents/worker_agent.py`
- `app/agents/worker_agent/agent.py`

### probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证）
- `app/agents/__init__.py`
- `app/agents/coder_agent/__init__.py`
- `app/agents/coder_agent/manifest.json`
- `app/agents/coordinator_agent/__init__.py`
- `app/agents/coordinator_agent/manifest.json`
- `app/agents/critic_agent/__init__.py`
- `app/agents/critic_agent/manifest.json`
- `app/agents/executor_agent/__init__.py`
- `app/agents/executor_agent/manifest.json`
- `app/agents/manifests/conflict_detector_agent.json`
- `app/agents/manifests/coordinator_agent.json`
- `app/agents/manifests/file_reader_agent.json`
- `app/agents/manifests/fixer_agent.json`
- `app/agents/manifests/planner_agent.json`
- `app/agents/manifests/researcher_agent.json`
- `app/agents/manifests/reviewer_agent.json`
- `app/agents/manifests/revision_agent.json`
- `app/agents/manifests/router_agent.json`
- `app/agents/manifests/structurer_agent.json`
- `app/agents/manifests/summarizer_agent.json`
- `app/agents/manifests/worker_agent.json`
- `app/agents/navigator_agent/__init__.py`
- `app/agents/navigator_agent/manifest.json`
- `app/agents/office_specialist_agent/__init__.py`
- `app/agents/office_specialist_agent/manifest.json`
- `app/agents/planner_agent/__init__.py`
- `app/agents/planner_agent/manifest.json`
- `app/agents/researcher_agent/__init__.py`
- `app/agents/researcher_agent/manifest.json`
- `app/agents/reviewer_agent/__init__.py`
- `app/agents/reviewer_agent/manifest.json`
- `app/agents/summarizer_agent/__init__.py`
- `app/agents/summarizer_agent/manifest.json`
- `app/agents/tool_user_agent/__init__.py`
- `app/agents/tool_user_agent/manifest.json`
- `app/agents/worker_agent/__init__.py`
- `app/agents/worker_agent/manifest.json`

### uncertain_dynamic_usage（存在动态加载不确定性）
- 无

### not_safe_to_delete（当前不可删除）
- `app/agents/role_contracts.py`
- `app/agents/role_debug_support.py`
- `app/agents/role_smoke.py`

### needs_owner_confirmation（需要 owner 确认）
- 无

# 建议的第 2 阶段删除计划
## Batch 1：明显未使用，且适合优先审批删除
- `app/agents/agent_plugin.py`
- `app/agents/answer_bundle_support.py`
- `app/agents/citation_support.py`
- `app/agents/coder_agent/agent.py`
- `app/agents/conflict_detector_agent.py`
- `app/agents/conflict_detector_role.py`
- `app/agents/coordinator_agent.py`
- `app/agents/coordinator_agent/agent.py`
- `app/agents/critic_agent/agent.py`
- `app/agents/executor_agent/agent.py`
- `app/agents/file_reader_agent.py`
- `app/agents/fixer_agent.py`
- `app/agents/navigator_agent/agent.py`
- `app/agents/office_specialist_agent/agent.py`
- `app/agents/planner_agent.py`
- `app/agents/planner_agent/agent.py`
- `app/agents/planner_role.py`
- `app/agents/planning_support.py`
- `app/agents/plugin_base.py`
- `app/agents/researcher_agent.py`
- `app/agents/researcher_agent/agent.py`
- `app/agents/review_support.py`
- `app/agents/reviewer_agent.py`
- `app/agents/reviewer_agent/agent.py`
- `app/agents/reviewer_helpers.py`
- `app/agents/reviewer_role.py`
- `app/agents/revision_agent.py`
- `app/agents/revision_role.py`
- `app/agents/role_catalog.py`
- `app/agents/role_helpers.py`
- `app/agents/role_registry.py`
- `app/agents/router_agent.py`
- `app/agents/runtime_controller.py`
- `app/agents/runtime_profiles.py`
- `app/agents/specialist_role.py`
- `app/agents/structurer_agent.py`
- `app/agents/structurer_role.py`
- `app/agents/summarizer_agent.py`
- `app/agents/summarizer_agent/agent.py`
- `app/agents/tool_user_agent/agent.py`
- `app/agents/worker_agent.py`
- `app/agents/worker_agent/agent.py`
- `app/kernel_robot_main.py`
## Batch 2：大概率未使用，但删除前需要运行时验证
- `app/agents/__init__.py`
- `app/agents/coder_agent/__init__.py`
- `app/agents/coder_agent/manifest.json`
- `app/agents/coordinator_agent/__init__.py`
- `app/agents/coordinator_agent/manifest.json`
- `app/agents/critic_agent/__init__.py`
- `app/agents/critic_agent/manifest.json`
- `app/agents/executor_agent/__init__.py`
- `app/agents/executor_agent/manifest.json`
- `app/agents/manifests/conflict_detector_agent.json`
- `app/agents/manifests/coordinator_agent.json`
- `app/agents/manifests/file_reader_agent.json`
- `app/agents/manifests/fixer_agent.json`
- `app/agents/manifests/planner_agent.json`
- `app/agents/manifests/researcher_agent.json`
- `app/agents/manifests/reviewer_agent.json`
- `app/agents/manifests/revision_agent.json`
- `app/agents/manifests/router_agent.json`
- `app/agents/manifests/structurer_agent.json`
- `app/agents/manifests/summarizer_agent.json`
- `app/agents/manifests/worker_agent.json`
- `app/agents/navigator_agent/__init__.py`
- `app/agents/navigator_agent/manifest.json`
- `app/agents/office_specialist_agent/__init__.py`
- `app/agents/office_specialist_agent/manifest.json`
- `app/agents/planner_agent/__init__.py`
- `app/agents/planner_agent/manifest.json`
- `app/agents/researcher_agent/__init__.py`
- `app/agents/researcher_agent/manifest.json`
- `app/agents/reviewer_agent/__init__.py`
- `app/agents/reviewer_agent/manifest.json`
- `app/agents/summarizer_agent/__init__.py`
- `app/agents/summarizer_agent/manifest.json`
- `app/agents/tool_user_agent/__init__.py`
- `app/agents/tool_user_agent/manifest.json`
- `app/agents/worker_agent/__init__.py`
- `app/agents/worker_agent/manifest.json`
- `app/api/__init__.py`
- `app/api/main.py`
- `app/api/routes/__init__.py`
- `app/role_runtime.py`
- `packages/office_addons/manifest.json`
- `packages/office_modules/execution_state.py`
- `packages/office_modules/manifest.json`
- `packages/office_modules/module_wrapper_surface.py`
## Batch 3：需要 owner 明确确认
- `packages/agent-core/README.md`
- `packages/office-modules/README.md`
- `packages/runtime-core/README.md`
## 不要删除
- `.env.example`
- `.github/workflows/regression-ci.yml`
- `.gitignore`
- `LICENSE`
- `NOTICE`
- `README.en.md`
- `README.ja.md`
- `README.md`
- `README.windows.md`
- `README.zh-CN.md`
- `RELEASING.md`
- `agents/vintage_programmer/agent.md`
- `agents/vintage_programmer/identity.md`
- `agents/vintage_programmer/locales/en/agent.md`
- `agents/vintage_programmer/locales/en/identity.md`
- `agents/vintage_programmer/locales/en/soul.md`
- `agents/vintage_programmer/locales/en/tools.md`
- `agents/vintage_programmer/locales/ja-JP/agent.md`
- `agents/vintage_programmer/locales/ja-JP/identity.md`
- `agents/vintage_programmer/locales/ja-JP/soul.md`
- `agents/vintage_programmer/locales/ja-JP/tools.md`
- `agents/vintage_programmer/soul.md`
- `agents/vintage_programmer/tools.md`
- `app/__init__.py`
- `app/action_validator.py`
- `app/adapters/__init__.py`
- `app/adapters/auth/__init__.py`
- `app/adapters/http/__init__.py`
- `app/adapters/llm/__init__.py`
- `app/adapters/storage/__init__.py`
- `app/agents/role_contracts.py`
- `app/agents/role_debug_support.py`
- `app/agents/role_smoke.py`
- `app/answer_stream_state.py`
- `app/attachment_argument_rewriter.py`
- `app/attachment_evidence.py`
- `app/attachments.py`
- `app/browser_runtime.py`
- `app/candidate_intents.py`
- `app/chat_product_runtime.py`
- `app/codex_runner.py`
- `app/config.py`
- `app/context_assembly.py`
- `app/context_meter.py`
- `app/context_pack.py`
- `app/contracts/__init__.py`
- `app/contracts/errors.py`
- `app/contracts/health.py`
- `app/contracts/manifest.py`
- `app/contracts/module.py`
- `app/contracts/provider_contract.py`
- `app/contracts/task.py`
- `app/contracts/tool.py`
- `app/contracts/tool_contract.py`
- `app/core/__init__.py`
- `app/data/document_cache/.gitkeep`
- `app/data/evolution/.gitkeep`
- `app/data/runtime/.gitkeep`
- `app/data/sessions/.gitkeep`
- `app/data/shadow_logs/.gitkeep`
- `app/data/uploads/.gitkeep`
- `app/document_text.py`
- `app/evolution.py`
- `app/frame_resolver.py`
- `app/i18n.py`
- `app/intent_classifier.py`
- `app/intent_constants.py`
- `app/intent_schema.py`
- `app/intent_scorer.py`
- `app/llm_exchange.py`
- `app/local_tools.py`
- `app/main.py`
- `app/models.py`
- `app/openai_auth.py`
- `app/phase_timing.py`
- `app/pipeline_hooks.py`
- `app/policy_router.py`
- `app/pricing.py`
- `app/route_trace.py`
- `app/route_verifier.py`
- `app/router_signals.py`
- `app/runtime_boundary.py`
- `app/runtime_contract.py`
- `app/runtime_errors.py`
- `app/runtime_hints.py`
- `app/runtime_trace_labels.py`
- `app/sandbox.py`
- `app/serialization.py`
- `app/session_context.py`
- `app/session_migration.py`
- `app/static/app.js`
- `app/static/assets/mat-logo-horizontal.jpg`
- `app/static/favicon.svg`
- `app/static/index.html`
- `app/static/locales.js`
- `app/static/styles.css`
- `app/static/vendor/htm.umd.js`
- `app/static/vendor/marked.umd.js`
- `app/static/vendor/purify.min.js`
- `app/static/vendor/react-dom.production.min.js`
- `app/static/vendor/react.production.min.js`
- `app/storage.py`
- `app/system_modules/__init__.py`
- `app/system_modules/memory_module/__init__.py`
- `app/system_modules/memory_module/manifest.py`
- `app/system_modules/memory_module/module.py`
- `app/system_modules/output_module/__init__.py`
- `app/system_modules/output_module/manifest.py`
- `app/system_modules/output_module/module.py`
- `app/system_modules/policy_module/__init__.py`
- `app/system_modules/policy_module/manifest.py`
- `app/system_modules/policy_module/module.py`
- `app/system_modules/tool_runtime_module/__init__.py`
- `app/system_modules/tool_runtime_module/manifest.py`
- `app/system_modules/tool_runtime_module/module.py`
- `app/tool_name_normalizer.py`
- `app/tool_providers/__init__.py`
- `app/tool_providers/file_provider.py`
- `app/tool_providers/session_provider.py`
- `app/tool_providers/web_provider.py`
- `app/tool_providers/workspace_provider.py`
- `app/tool_providers/write_provider.py`
- `app/tool_trace_summary.py`
- `app/trace_events.py`
- `app/update_manager.py`
- `app/vintage_programmer_runtime.py`
- `app/workbench.py`
- `docs/architecture/tool_provider_contract.md`
- `docs/assets/brand/mat-logo-horizontal.jpg`
- `docs/assets/screenshots/kernel_robot_home.png`
- `docs/assets/screenshots/role_agent_lab_home.png`
- `docs/internal_design_manual.md`
- `docs/observability/trace_guide.md`
- `docs/observability/troubleshooting.md`
- `docs/operations/tool_provider_degradation_guide.md`
- `evals/README.md`
- `evals/cases.json`
- `evals/fixtures/generated/.gitkeep`
- `evals/fixtures/spec_excerpt.txt`
- `evals/fixtures/spec_without_15h.txt`
- `evals/gate_cases.json`
- `evals/replay_samples/README.md`
- `evals/replay_samples/office/office_attachment_followup.json`
- `evals/replay_samples/research/research_fetch_failure.json`
- `evals/replay_samples/research/research_normal_top_fetch.json`
- `evals/replay_samples/swarm/swarm_fanout_merge.json`
- `evals/replay_samples/swarm/swarm_serial_replay_conflict.json`
- `evals/research_gate_cases.json`
- `evals/swarm_gate_cases.json`
- `packages/README.md`
- `packages/__init__.py`
- `packages/agent_core/__init__.py`
- `packages/agent_core/orchestration.py`
- `packages/agent_core/role_registry.py`
- `packages/agent_core/role_runtime.py`
- `packages/agent_core/runtime_controller.py`
- `packages/office_addons/__init__.py`
- `packages/office_modules/__init__.py`
- `packages/office_modules/agent_module.py`
- `packages/office_modules/answer_bundle_support.py`
- `packages/office_modules/citation_support.py`
- `packages/office_modules/conflict_detector_role.py`
- `packages/office_modules/execution_engine.py`
- `packages/office_modules/execution_policy.py`
- `packages/office_modules/execution_runtime.py`
- `packages/office_modules/intent_support.py`
- `packages/office_modules/legacy_runtime_support.py`
- `packages/office_modules/memory_module.py`
- `packages/office_modules/office_agent_runtime.py`
- `packages/office_modules/output_module.py`
- `packages/office_modules/planner_role.py`
- `packages/office_modules/planning_support.py`
- `packages/office_modules/request_analysis.py`
- `packages/office_modules/review_support.py`
- `packages/office_modules/reviewer_helpers.py`
- `packages/office_modules/reviewer_role.py`
- `packages/office_modules/revision_role.py`
- `packages/office_modules/role_catalog.py`
- `packages/office_modules/role_helpers.py`
- `packages/office_modules/roles.py`
- `packages/office_modules/router_hints.py`
- `packages/office_modules/runtime_profiles.py`
- `packages/office_modules/specialist_role.py`
- `packages/office_modules/structurer_role.py`
- `packages/office_modules/tools.py`
- `packages/runtime_core/__init__.py`
- `packages/runtime_core/blackboard.py`
- `packages/runtime_core/capability_loader.py`
- `packages/runtime_core/legacy_host_support.py`
- `packages/runtime_core/tool_execution_bus.py`
- `requirements-dev.txt`
- `requirements.txt`
- `run.ps1`
- `run.sh`
- `scripts/check_platform_boundaries.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/docs/test_console_workstation_shell.py`
- `tests/docs/test_markdown_packaging.py`
- `tests/integration/test_chat_vintage_programmer_api.py`
- `tests/modules/test_office_runtime_contract.py`
- `tests/modules/test_request_analysis_guards.py`
- `tests/modules/test_tool_registration.py`
- `tests/router/__init__.py`
- `tests/router/support.py`
- `tests/router/test_followup_inheritance.py`
- `tests/router/test_grounded_generation.py`
- `tests/router/test_low_confidence_fallback.py`
- `tests/router/test_mixed_intents.py`
- `tests/router/test_single_turn_intents.py`
- `tests/router/test_translation_task_control.py`
- `tests/router/test_verifier_guards.py`
- `tests/test_action_validator.py`
- `tests/test_answer_stream_state.py`
- `tests/test_attachment_argument_rewriter.py`
- `tests/test_chat_product_boundaries.py`
- `tests/test_compaction_context_pack.py`
- `tests/test_context_meter.py`
- `tests/test_context_pack.py`
- `tests/test_context_pack_minimal.py`
- `tests/test_frontend_locale_regressions.py`
- `tests/test_llm_exchange.py`
- `tests/test_local_tool_executor_projects.py`
- `tests/test_local_tools_exec_command.py`
- `tests/test_local_tools_public_surface.py`
- `tests/test_runtime_boundary.py`
- `tests/test_runtime_hints.py`
- `tests/test_runtime_trace_labels.py`
- `tests/test_safe_serialization_static.py`
- `tests/test_serialization.py`
- `tests/test_session_context_task_reset.py`
- `tests/test_session_migration.py`
- `tests/test_tool_execution_bus.py`
- `tests/test_tool_name_normalizer.py`
- `tests/test_tool_trace_summary.py`
- `tests/test_trace_events.py`
- `tests/test_update_manager.py`
- `tests/test_update_plan_stability.py`
- `tests/test_upload_store.py`
- `tests/test_vintage_programmer_runtime.py`
- `tests/test_vp_env_config.py`
