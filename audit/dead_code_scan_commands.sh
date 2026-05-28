#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p audit

git ls-files > audit/all_tracked_files.txt

git grep -n "from app.agents\|import app.agents\|app/agents\|agents/" \
  | grep -v '^audit/' \
  > audit/app_agents_reference_hits.txt || true
git grep -n "from packages.office_modules\|import packages.office_modules\|office_modules" \
  | grep -v '^audit/' \
  > audit/office_modules_reference_hits.txt || true
git grep -n "from packages.runtime_core\|import packages.runtime_core\|runtime_core" \
  | grep -v '^audit/' \
  > audit/runtime_core_reference_hits.txt || true

python - <<'PY' > audit/import_reference_map.txt
import ast
from pathlib import Path

for path in sorted(Path(".").rglob("*.py")):
    if any(part in {".git", ".venv", "__pycache__", ".pytest_cache", "audit"} for part in path.parts):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{path}: PARSE_ERROR: {exc}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                print(f"{path}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(alias.name for alias in node.names)
            print(f"{path}: from {mod} import {names}")
PY

git grep -n "app.agents\|app/agents\|office_modules\|runtime_core\|legacy\|deprecated" tests \
  > audit/test_reference_map.txt || true
python -m pytest --collect-only -q > audit/pytest_collect_only.txt || true

git grep -n "importlib\|__import__\|pkgutil\|load_module\|module_name\|agent_dir\|agents_dir\|manifest\|rglob\|glob" \
  | grep -v '^audit/' \
  > audit/dynamic_loading_hits.txt || true

python - <<'PY'
from __future__ import annotations

import ast
import csv
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(".").resolve()
AUDIT = REPO / "audit"

tracked = [line.strip() for line in (AUDIT / "all_tracked_files.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
scan_tracked = [rel for rel in tracked if not rel.startswith("audit/")]

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".sh",
    ".ps1",
    ".js",
    ".css",
    ".html",
    ".svg",
    ".gitkeep",
}
ROOT_TEXT_FILES = {
    "README.md",
    "README.en.md",
    "README.ja.md",
    "README.zh-CN.md",
    "README.windows.md",
    "NOTICE",
    "LICENSE",
    "RELEASING.md",
    "requirements.txt",
    "requirements-dev.txt",
    "run.sh",
    "run.ps1",
}
ROOT_DOC_KEEP = {
    "README.md",
    "README.en.md",
    "README.ja.md",
    "README.zh-CN.md",
    "README.windows.md",
    "RELEASING.md",
    "LICENSE",
    "NOTICE",
    "requirements.txt",
    "requirements-dev.txt",
}
PROTECTED_FILES = {
    "NOTICE",
    "OSS_REVIEW.md",
    "THIRD_PARTY_ATTRIBUTIONS.md",
}
COMPATIBILITY_PLACEHOLDERS = {
    "packages/agent-core/README.md",
    "packages/office-modules/README.md",
    "packages/runtime-core/README.md",
}
APP_AGENTS_BLOCKERS = {
    "app/agents/role_contracts.py",
    "app/agents/role_debug_support.py",
    "app/agents/role_smoke.py",
}
RECURSIVE_SECTIONS = {
    ".github",
    "agents",
    "app/agents",
    "app/api",
    "app/static",
    "docs",
    "evals",
    "packages/office_modules",
    "packages/runtime_core",
    "scripts",
    "tests",
    "workspace",
    "packages/agent-core",
    "packages/office-modules",
    "packages/runtime-core",
    "packages/kernel-robot",
    "packages/role-agent-lab",
    "app/bootstrap",
    "app/business_modules",
    "app/kernel",
    "app/llm",
    "app/modules",
    "workspace/skills",
    "artifacts",
    "output",
}
SECTION_ORDER = [
    ".github",
    "agents",
    "app",
    "app/agents",
    "app/api",
    "app/static",
    "app/templates",
    "app/bootstrap",
    "app/business_modules",
    "app/kernel",
    "app/llm",
    "app/modules",
    "docs",
    "evals",
    "packages",
    "packages/office_modules",
    "packages/runtime_core",
    "packages/agent-core",
    "packages/office-modules",
    "packages/runtime-core",
    "packages/kernel-robot",
    "packages/role-agent-lab",
    "tests",
    "tests/kernel",
    "tests/migration",
    "tests/operations",
    "tests/replay",
    "tests/swarm",
    "workspace",
    "workspace/skills",
    "scripts",
    "artifacts",
    "output",
]
PURPOSE_MAP = {
    ".github": "GitHub Actions 工作流配置。",
    "agents": "在线运行的 `vintage_programmer` 主 agent 所使用的 Markdown 规范文件和本地化覆盖内容。",
    "app": "主 FastAPI 应用层，包含运行时编排、持久化和前端静态资源服务。",
    "app/agents": "旧的 agent / plugin 脚手架，以及对当前 office 运行时角色系统的兼容包装层。",
    "app/api": "指向主 FastAPI app 的轻量兼容入口别名。",
    "app/static": "前端页面壳、样式文件以及 vendored 浏览器库。",
    "app/templates": "审计范围要求检查的模板目录；当前分支中不存在。",
    "app/bootstrap": "磁盘上仍存在的旧产品壳区域，但当前分支没有 tracked 文件。",
    "app/business_modules": "磁盘上仍存在的旧产品壳区域，但当前分支没有 tracked 文件。",
    "app/kernel": "磁盘上仍存在的旧产品壳区域，但当前分支没有 tracked 文件。",
    "app/llm": "磁盘上仍存在的旧产品壳区域，但当前分支没有 tracked 文件。",
    "app/modules": "磁盘上仍存在的旧产品壳区域，但当前分支没有 tracked 文件。",
    "docs": "架构、运维和可观测性文档。",
    "evals": "回归用例清单、夹具文件和回放样本。",
    "packages": "共享运行时包，以及历史兼容占位目录。",
    "packages/office_modules": "当前运行时实际加载的 office agent 后端包。",
    "packages/runtime_core": "能力包加载器、blackboard 和工具执行基础设施。",
    "packages/agent-core": "历史连字符命名的兼容占位目录，用于迁移期文档说明。",
    "packages/office-modules": "历史连字符命名的兼容占位目录，用于迁移期文档说明。",
    "packages/runtime-core": "历史连字符命名的兼容占位目录，用于迁移期文档说明。",
    "packages/kernel-robot": "已移除的旧产品壳目录；磁盘上只剩一个空目录。",
    "packages/role-agent-lab": "已移除的旧产品壳目录；磁盘上只剩一个空目录。",
    "tests": "单测、集成测试、路由测试和回归测试。",
    "tests/kernel": "磁盘上仍存在的旧测试目录，但当前分支没有 tracked 文件。",
    "tests/migration": "磁盘上仍存在的旧测试目录，但当前分支没有 tracked 文件。",
    "tests/operations": "磁盘上仍存在的旧测试目录，但当前分支没有 tracked 文件。",
    "tests/replay": "磁盘上仍存在的旧测试目录，但当前分支没有 tracked 文件。",
    "tests/swarm": "磁盘上仍存在的旧测试目录，但当前分支没有 tracked 文件。",
    "workspace": "本地可编辑的 workbench 工作区，主要用于 skills。",
    "workspace/skills": "本地 skill 草稿和实验目录；当前分支没有 tracked 文件。",
    "scripts": "仓库维护脚本和边界检查脚本。",
    "artifacts": "磁盘上的生成产物，如 eval 汇总和 trace 文件；未纳入 git 跟踪。",
    "output": "磁盘上的输出产物，如截图和本地导出内容；未纳入 git 跟踪。",
}


def module_id(rel: str) -> str:
    path = Path(rel)
    if path.name == "__init__.py":
        return ".".join(path.parent.parts)
    return ".".join(path.with_suffix("").parts)


def current_package(rel: str) -> list[str]:
    path = Path(rel)
    if path.name == "__init__.py":
        return list(path.parent.parts)
    return list(path.parent.parts)


module_to_file: dict[str, str] = {}
for rel in scan_tracked:
    if rel.endswith(".py"):
        module_to_file[module_id(rel)] = rel

contents: dict[str, str] = {}
for rel in scan_tracked:
    path = REPO / rel
    if path.suffix.lower() in TEXT_SUFFIXES or rel in ROOT_TEXT_FILES:
        try:
            contents[rel] = path.read_text(encoding="utf-8")
        except Exception:
            continue

import_referrers: dict[str, set[str]] = defaultdict(set)


def resolve_from_module(rel: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return str(node.module or "")
    pkg = current_package(rel)
    pop_count = max(0, node.level - 1)
    if pop_count:
        pkg = pkg[:-pop_count]
    if node.module:
        return ".".join([*pkg, str(node.module)])
    return ".".join(pkg)


for rel in scan_tracked:
    if not rel.endswith(".py"):
        continue
    try:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = str(alias.name or "").strip()
                if target in module_to_file:
                    import_referrers[module_to_file[target]].add(rel)
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve_from_module(rel, node)
            if resolved in module_to_file:
                import_referrers[module_to_file[resolved]].add(rel)
            for alias in node.names:
                child = str(alias.name or "").strip()
                if not child or child == "*":
                    continue
                candidate = f"{resolved}.{child}" if resolved else child
                if candidate in module_to_file:
                    import_referrers[module_to_file[candidate]].add(rel)

basename_counts = Counter(Path(rel).name for rel in scan_tracked)
ignored_basename_refs = {
    "__init__.py",
    "README.md",
    "README.en.md",
    "README.ja.md",
    "README.zh-CN.md",
    "README.windows.md",
    "manifest.json",
    ".gitkeep",
    "SKILL.md",
}
path_referrers: dict[str, set[str]] = defaultdict(set)
for rel, text in contents.items():
    for target in scan_tracked:
        if rel == target:
            continue
        target_name = Path(target).name
        if target in text:
            path_referrers[target].add(rel)
            continue
        if basename_counts[target_name] == 1 and target_name not in ignored_basename_refs and target_name in text:
            path_referrers[target].add(rel)


def ref_category(source: str) -> str:
    if source.startswith("tests/"):
        return "test"
    if source.startswith("docs/") or source.startswith("README") or source.endswith(".md") and "/" not in source:
        return "doc"
    if source.startswith(".github/") or source in {"run.sh", "run.ps1", "requirements.txt", "requirements-dev.txt"}:
        return "config"
    if source.startswith("scripts/"):
        return "config"
    return "runtime"


all_referrers: dict[str, set[str]] = defaultdict(set)
for target in scan_tracked:
    all_referrers[target].update(import_referrers.get(target, set()))
    all_referrers[target].update(path_referrers.get(target, set()))

runtime_refs: dict[str, set[str]] = defaultdict(set)
test_refs: dict[str, set[str]] = defaultdict(set)
doc_refs: dict[str, set[str]] = defaultdict(set)
config_refs: dict[str, set[str]] = defaultdict(set)

for target, referrers in all_referrers.items():
    for source in referrers:
        category = ref_category(source)
        if category == "runtime":
            runtime_refs[target].add(source)
        elif category == "test":
            test_refs[target].add(source)
        elif category == "doc":
            doc_refs[target].add(source)
        elif category == "config":
            config_refs[target].add(source)


def dynamic_risk(rel: str) -> str:
    path = Path(rel)
    if rel.startswith("agents/vintage_programmer/"):
        return "high"
    if rel.startswith("workspace/skills/") or path.name == "SKILL.md":
        return "high"
    if rel in {"packages/office_modules/manifest.json", "packages/office_addons/manifest.json"}:
        return "high"
    if rel.startswith("app/agents/manifests/") or path.name == "manifest.json" and rel.startswith("app/agents/"):
        return "medium"
    if rel.startswith("app/static/"):
        return "medium"
    if rel.startswith("packages/office_modules/") and path.name in {"agent_module.py", "memory_module.py", "output_module.py", "tools.py"}:
        return "high"
    if rel.startswith("packages/office_modules/") and path.name in {"module_wrapper_surface.py", "execution_state.py"}:
        return "medium"
    if "locales/" in rel and rel.endswith(".md"):
        return "high"
    return "low"


def effective_runtime_referrers(rel: str) -> set[str]:
    refs = set(runtime_refs.get(rel, set())) | set(config_refs.get(rel, set()))
    if rel.startswith("app/agents/"):
        refs = {src for src in refs if not src.startswith("app/agents/")}
    if rel.startswith("app/api/"):
        refs = {src for src in refs if not src.startswith("app/api/")}
    return refs


def effective_test_referrers(rel: str) -> set[str]:
    refs = set(test_refs.get(rel, set()))
    if rel.startswith("app/agents/"):
        refs = {src for src in refs if not src.startswith("app/agents/")}
    if rel.startswith("app/api/"):
        refs = {src for src in refs if not src.startswith("app/api/")}
    return refs


def effective_doc_referrers(rel: str) -> set[str]:
    refs = set(doc_refs.get(rel, set()))
    if rel.startswith("app/agents/"):
        refs = {src for src in refs if not src.startswith("app/agents/")}
    if rel.startswith("app/api/"):
        refs = {src for src in refs if not src.startswith("app/api/")}
    return refs


def classification(rel: str) -> str:
    live_runtime_refs = effective_runtime_referrers(rel)
    live_test_refs = effective_test_referrers(rel)
    if rel in PROTECTED_FILES:
        return "keep"
    if rel in ROOT_DOC_KEEP:
        return "keep"
    if rel.endswith(".gitkeep"):
        return "keep"
    if rel.startswith("agents/vintage_programmer/"):
        return "keep"
    if rel.startswith("app/static/"):
        return "keep"
    if rel.startswith("tests/"):
        return "keep"
    if rel.startswith("docs/"):
        return "keep"
    if rel.endswith("__init__.py") and not rel.startswith("app/agents/") and not rel.startswith("app/api/") and rel not in COMPATIBILITY_PLACEHOLDERS:
        return "keep"
    if rel in COMPATIBILITY_PLACEHOLDERS:
        return "needs_owner_confirmation"
    if rel in APP_AGENTS_BLOCKERS:
        return "not_safe_to_delete"
    if live_runtime_refs or live_test_refs:
        return "keep"
    risk = dynamic_risk(rel)
    if rel.startswith("app/agents/"):
        if rel.endswith("__init__.py"):
            return "probably_safe_but_needs_runtime_check"
        if risk == "high":
            return "uncertain_dynamic_usage"
        if risk == "medium":
            return "probably_safe_but_needs_runtime_check"
        return "safe_to_delete_after_approval"
    if rel in {"app/api/main.py", "app/api/__init__.py", "app/api/routes/__init__.py", "app/role_runtime.py"}:
        return "probably_safe_but_needs_runtime_check"
    if rel == "app/kernel_robot_main.py":
        return "safe_to_delete_after_approval"
    if rel.startswith("app/api/"):
        return "probably_safe_but_needs_runtime_check"
    if rel.startswith("packages/office_modules/"):
        if risk == "high":
            return "uncertain_dynamic_usage"
        return "probably_safe_but_needs_runtime_check"
    if rel.startswith("packages/runtime_core/"):
        return "probably_safe_but_needs_runtime_check"
    if rel.startswith("packages/office_addons/"):
        return "uncertain_dynamic_usage"
    if rel.startswith("packages/"):
        return "needs_owner_confirmation"
    if rel.startswith("app/"):
        if risk == "high":
            return "uncertain_dynamic_usage"
        if risk == "medium":
            return "probably_safe_but_needs_runtime_check"
        return "safe_to_delete_after_approval"
    if rel.startswith("evals/") or rel.startswith(".github/") or rel.startswith("scripts/"):
        return "keep"
    if rel.endswith(".md"):
        return "needs_owner_confirmation"
    return "keep"


def recommendation_for(label: str) -> str:
    return {
        "keep": "保留",
        "safe_to_delete_after_approval": "在第 2 阶段经 owner 审批后删除",
        "probably_safe_but_needs_runtime_check": "先做 runtime smoke 和 pytest，再考虑删除",
        "uncertain_dynamic_usage": "删除前先确认动态加载 / 模块发现路径",
        "needs_owner_confirmation": "删除前需要 owner 明确确认",
        "not_safe_to_delete": "第 2 阶段不要删除",
    }[label]


def classification_display(label: str) -> str:
    return {
        "keep": "keep（保留）",
        "safe_to_delete_after_approval": "safe_to_delete_after_approval（审批后可删）",
        "probably_safe_but_needs_runtime_check": "probably_safe_but_needs_runtime_check（大概率可删，但需先做运行验证）",
        "uncertain_dynamic_usage": "uncertain_dynamic_usage（存在动态加载不确定性）",
        "needs_owner_confirmation": "needs_owner_confirmation（需要 owner 确认）",
        "not_safe_to_delete": "not_safe_to_delete（当前不可删除）",
    }[label]


def folder_recommendation_display(label: str) -> str:
    return {
        "keep": "keep（保留）",
        "delete_after_approval": "delete_after_approval（审批后整目录可删）",
        "partially_delete_after_approval": "partially_delete_after_approval（审批后仅删除其中一部分）",
        "needs_owner_confirmation": "needs_owner_confirmation（需要 owner 确认）",
        "needs_runtime_test_before_delete": "needs_runtime_test_before_delete（删除前需要运行时验证）",
    }[label]


def risk_display(label: str) -> str:
    return {
        "low": "low（低）",
        "medium": "medium（中）",
        "high": "high（高）",
        "n/a": "不适用",
    }.get(label, label)


def short_ref_list(items: set[str], limit: int = 3) -> str:
    if not items:
        return "none"
    rows = sorted(items)
    preview = ", ".join(rows[:limit])
    if len(rows) > limit:
        preview += f", +{len(rows) - limit} more"
    return preview


def evidence_for(rel: str) -> str:
    parts: list[str] = []
    combined = effective_runtime_referrers(rel)
    if combined:
        parts.append(f"runtime/config refs: {short_ref_list(combined)}")
    live_tests = effective_test_referrers(rel)
    if live_tests:
        parts.append(f"test refs: {short_ref_list(live_tests)}")
    live_docs = effective_doc_referrers(rel)
    if live_docs:
        parts.append(f"doc refs: {short_ref_list(live_docs)}")
    if rel == "app/agents/role_contracts.py":
        parts.append("required by the `role_debug_support` -> `role_smoke` contract-validation chain")
    if rel == "app/agents/role_smoke.py":
        parts.append("required by the `role_debug_support` debug smoke path")
    parts.append(f"dynamic risk: {dynamic_risk(rel)}")
    return "; ".join(parts)


file_info: dict[str, dict[str, object]] = {}
for rel in scan_tracked:
    label = classification(rel)
    file_info[rel] = {
        "static_refs": len(effective_runtime_referrers(rel)),
        "test_refs": len(effective_test_referrers(rel)),
        "doc_refs": len(effective_doc_referrers(rel)),
        "dynamic_risk": dynamic_risk(rel),
        "classification": label,
        "recommendation": recommendation_for(label),
        "evidence": evidence_for(rel),
    }

existing_top_dirs = sorted(
    p.name
    for p in REPO.iterdir()
    if p.is_dir() and p.name not in {".git", ".venv", "__pycache__", ".pytest_cache", ".playwright-cli", "audit"}
)
sections: list[str] = []
for folder in SECTION_ORDER:
    if folder in sections:
        continue
    if (REPO / folder).exists() or any(rel.startswith(folder + "/") for rel in scan_tracked):
        sections.append(folder)
for folder in existing_top_dirs:
    if folder not in sections:
        sections.append(folder)


def tracked_under(folder: str) -> list[str]:
    prefix = folder.rstrip("/") + "/"
    return [rel for rel in scan_tracked if rel.startswith(prefix)]


def section_files(folder: str) -> list[str]:
    direct = [rel for rel in scan_tracked if Path(rel).parent.as_posix() == folder]
    recursive = tracked_under(folder)
    if folder in RECURSIVE_SECTIONS or not direct:
        return recursive
    return direct


def folder_recommendation(folder: str, files: list[str]) -> str:
    if not files:
        return "needs_owner_confirmation"
    labels = {str(file_info[item]["classification"]) for item in files}
    if labels == {"keep"}:
        return "keep"
    if labels <= {"safe_to_delete_after_approval"}:
        return "delete_after_approval"
    if "not_safe_to_delete" in labels and labels & {"safe_to_delete_after_approval", "probably_safe_but_needs_runtime_check", "uncertain_dynamic_usage"}:
        return "partially_delete_after_approval"
    if labels & {"uncertain_dynamic_usage", "probably_safe_but_needs_runtime_check"}:
        return "needs_runtime_test_before_delete"
    if "needs_owner_confirmation" in labels:
        return "needs_owner_confirmation"
    if "safe_to_delete_after_approval" in labels:
        return "partially_delete_after_approval"
    return "keep"


def folder_dynamic_risk(folder: str, files: list[str]) -> str:
    risks = {str(file_info[item]["dynamic_risk"]) for item in files}
    if "high" in risks:
        return "high"
    if "medium" in risks:
        return "medium"
    return "low"


def summarize_folder(folder: str, files: list[str]) -> str:
    if folder in PURPOSE_MAP:
        return PURPOSE_MAP[folder]
    if not files:
        return "当前分支下该目录没有 tracked 文件。"
    suffix_counts = Counter(Path(item).suffix or "(no suffix)" for item in files)
    top_suffixes = ", ".join(f"{ext}:{count}" for ext, count in suffix_counts.most_common(3))
    return f"包含 {len(files)} 个 tracked 文件（按后缀统计：{top_suffixes}）。"


entrypoint_targets = [
    "app/main.py",
    "app/vintage_programmer_runtime.py",
    "run.sh",
    "run.ps1",
    "README.md",
    "README.en.md",
    "README.ja.md",
    "README.zh-CN.md",
    "requirements.txt",
]
workflow_files = sorted(str(path.relative_to(REPO)) for path in (REPO / ".github" / "workflows").glob("*.yml"))
entrypoint_targets.extend(workflow_files)
entrypoint_targets.extend(["Dockerfile", "docker-compose.yml", "pyproject.toml", "setup.py"])


def python_import_preview(rel: str, limit: int = 12) -> str:
    try:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    except Exception:
        return "n/a"
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in modules:
                    modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            target = resolve_from_module(rel, node) if node.level else str(node.module or "")
            if target and target not in modules:
                modules.append(target)
    return ", ".join(modules[:limit]) + (" ..." if len(modules) > limit else "")


runtime_entry_rows: list[tuple[str, str, str, str]] = []
for rel in entrypoint_targets:
    path = REPO / rel
    if not path.exists():
        runtime_entry_rows.append((rel, "未找到", "不适用", "当前分支中不存在该文件。"))
        continue
    if rel == "app/main.py":
        runtime_entry_rows.append((
            rel,
            "主 FastAPI HTTP 入口。",
            python_import_preview(rel),
            "挂载 `app/static`、提供 `/` 首页，并使用 `agents/vintage_programmer` 初始化 `VintageProgrammerRuntime`。",
        ))
    elif rel == "app/vintage_programmer_runtime.py":
        runtime_entry_rows.append((
            rel,
            "主运行时编排类。",
            python_import_preview(rel),
            "从 `agents/vintage_programmer` 加载 agent spec 文件，并通过 `packages.office_modules.office_agent_runtime.create_office_runtime_backend` 构建后端。",
        ))
    elif rel in {"run.sh", "run.ps1"}:
        runtime_entry_rows.append((
            rel,
            "开发启动脚本。",
            "uvicorn app.main:app",
            "是 FastAPI app 的 shell 包装层；不引用 `app/agents`。",
        ))
    elif rel.startswith("README"):
        runtime_entry_rows.append((
            rel,
            "面向用户 / 运维的启动与打包文档。",
            "run.sh, run.ps1, app.main:app, agents/vintage_programmer",
            "文档引用的是在线使用的 agent spec 目录 `agents/vintage_programmer`，而不是 `app/agents`。",
        ))
    elif rel.startswith(".github/workflows/"):
        note = "CI 会编译 `app` 和 `scripts`，检查 `app/static/app.js`，并执行 `pytest -q tests`。"
        text = path.read_text(encoding="utf-8")
        if "branches:" in text and "cleanup/" not in text:
            note += " 另外，推送到 `cleanup/*` 的分支不匹配该 workflow 的 push 分支过滤规则。"
        runtime_entry_rows.append((
            rel,
            "回归 CI 入口。",
            "requirements-dev.txt, scripts/check_platform_boundaries.py, pytest",
            note,
        ))
    elif rel == "requirements.txt":
        runtime_entry_rows.append((
            rel,
            "运行时依赖清单。",
            "fastapi, uvicorn, openai, playwright, document/image libs",
            "这里只是依赖声明，不是代码启动入口。",
        ))
    else:
        runtime_entry_rows.append((rel, "审计范围要求列出的仓库入口项。", "不适用", "文件存在，但不视为实际代码启动路径。"))

runtime_map_lines = [
    "# 运行时入口点映射",
    "",
    "| 入口点 | 用途 | 导入 / 加载内容 | 备注 |",
    "|---|---|---|---|",
]
for entry, purpose, loads, notes in runtime_entry_rows:
    runtime_map_lines.append(f"| `{entry}` | {purpose} | {loads} | {notes} |")
(AUDIT / "runtime_entrypoint_map.md").write_text("\n".join(runtime_map_lines) + "\n", encoding="utf-8")


csv_rows: list[dict[str, object]] = []
folder_csv_allowlist = {
    "app/agents",
    "app/api",
    "app/bootstrap",
    "app/business_modules",
    "app/kernel",
    "app/llm",
    "app/modules",
    "packages/agent-core",
    "packages/office-modules",
    "packages/runtime-core",
    "packages/kernel-robot",
    "packages/role-agent-lab",
    "workspace/skills",
    "artifacts",
    "output",
}
for folder in sections:
    files = tracked_under(folder)
    exists = (REPO / folder).exists()
    folder_label = folder_recommendation(folder, files)
    if folder in folder_csv_allowlist and folder_label != "keep":
        folder_recommendation_text = {
            "delete_after_approval": "Delete folder in phase 2 after approval",
            "partially_delete_after_approval": "Delete only selected files/subfolders in phase 2",
            "needs_runtime_test_before_delete": "Run runtime smoke + pytest before folder cleanup",
            "needs_owner_confirmation": "Owner decision required",
            "keep": "Retain",
        }[folder_label]
        if folder == "app/agents":
            folder_recommendation_text = "Do not delete the whole folder; only remove approved subfiles"
        csv_rows.append({
            "path": folder,
            "type": "dir",
            "folder": folder,
            "static_refs": sum(len(runtime_refs.get(item, set()) | config_refs.get(item, set())) for item in files),
            "test_refs": sum(len(test_refs.get(item, set())) for item in files),
            "doc_refs": sum(len(doc_refs.get(item, set())) for item in files),
            "dynamic_risk": folder_dynamic_risk(folder, files) if files else "low",
            "classification": "needs_owner_confirmation" if not files else ("not_safe_to_delete" if folder == "app/agents" else ("probably_safe_but_needs_runtime_check" if folder_label == "needs_runtime_test_before_delete" else ("safe_to_delete_after_approval" if folder_label == "delete_after_approval" else "needs_owner_confirmation"))),
            "recommendation": folder_recommendation_text,
            "evidence": "Folder exists on disk but has no tracked files in this branch." if not files else f"Folder recommendation derived from {len(files)} tracked files; dynamic risk {folder_dynamic_risk(folder, files)}.",
        })

for rel, info in sorted(file_info.items()):
    if info["classification"] == "keep":
        continue
    csv_rows.append({
        "path": rel,
        "type": "file",
        "folder": str(Path(rel).parent),
        "static_refs": info["static_refs"],
        "test_refs": info["test_refs"],
        "doc_refs": info["doc_refs"],
        "dynamic_risk": info["dynamic_risk"],
        "classification": info["classification"],
        "recommendation": info["recommendation"],
        "evidence": info["evidence"],
    })

with (AUDIT / "dead_code_candidates.csv").open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=[
            "path",
            "type",
            "folder",
            "static_refs",
            "test_refs",
            "doc_refs",
            "dynamic_risk",
            "classification",
            "recommendation",
            "evidence",
        ],
    )
    writer.writeheader()
    writer.writerows(csv_rows)


def render_file_row(rel: str) -> str:
    info = file_info[rel]
    return (
        f"| `{rel}` | {info['static_refs']} | {info['test_refs']} | {risk_display(str(info['dynamic_risk']))} | "
        f"{classification_display(str(info['classification']))} | {info['recommendation']} |"
    )


audit_lines: list[str] = [
    "# 死代码目录审计",
    "",
    "本次审计是纯扫描（scan-only）。没有删除、重命名或重构任何源码文件。",
    "",
    "证据输入：",
    "- `audit/all_tracked_files.txt`：tracked 文件清单。",
    "- `audit/import_reference_map.txt`：Python import 关系映射。",
    "- `audit/test_reference_map.txt` 与 `audit/pytest_collect_only.txt`：测试覆盖和引用信号。",
    "- `audit/dynamic_loading_hits.txt`：动态导入 / manifest / 自动发现路径风险。",
    "- `audit/runtime_entrypoint_map.md`：启动路径与运行时入口上下文。",
    "",
]

for folder in sections:
    exists = (REPO / folder).exists()
    recursive_files = tracked_under(folder)
    files = section_files(folder)
    audit_lines.append(f"## 目录：{folder}")
    audit_lines.append("### 观察到的用途")
    audit_lines.append(summarize_folder(folder, recursive_files))
    audit_lines.append("### 当前引用情况")
    if not exists and not recursive_files:
        audit_lines.append("- Imports：不适用")
        audit_lines.append("- Runtime references：不适用")
        audit_lines.append("- Test references：不适用")
        audit_lines.append("- Documentation references：不适用")
        audit_lines.append("- Dynamic loading risk：不适用")
    else:
        runtime_count = len({src for rel in recursive_files for src in runtime_refs.get(rel, set()) | config_refs.get(rel, set())})
        test_count = len({src for rel in recursive_files for src in test_refs.get(rel, set())})
        doc_count = len({src for rel in recursive_files for src in doc_refs.get(rel, set())})
        import_count = len({src for rel in recursive_files for src in import_referrers.get(rel, set())})
        audit_lines.append(f"- Imports：{import_count} 处外部 import 命中")
        audit_lines.append(f"- Runtime references：{runtime_count} 处运行时 / 配置引用")
        audit_lines.append(f"- Test references：{test_count} 处测试引用")
        audit_lines.append(f"- Documentation references：{doc_count} 处文档 / README 引用")
        audit_lines.append(f"- Dynamic loading risk：{risk_display(folder_dynamic_risk(folder, recursive_files) if recursive_files else 'low')}")
    audit_lines.append("### 已审查文件")
    audit_lines.append("| 文件 | 静态引用数 | 测试引用数 | 动态使用风险 | 分类 | 建议 |")
    audit_lines.append("|---|---:|---:|---|---|---|")
    if not exists and not recursive_files:
        audit_lines.append(f"| `{folder}` | 0 | 0 | 不适用 | {classification_display('needs_owner_confirmation')} | 当前分支中未找到该目录 |")
    elif not files:
        audit_lines.append(f"| `{folder}` | 0 | 0 | {risk_display('low')} | {classification_display('needs_owner_confirmation')} | 目录在磁盘上存在，但当前分支没有 tracked 文件 |")
    else:
        for rel in files:
            audit_lines.append(render_file_row(rel))
    audit_lines.append("### 目录级建议")
    recommendation = folder_recommendation(folder, recursive_files)
    if not exists and not recursive_files:
        audit_lines.append(folder_recommendation_display("needs_owner_confirmation"))
        audit_lines.append("")
        audit_lines.append("说明：当前分支中未找到该目录。")
    else:
        audit_lines.append(folder_recommendation_display(recommendation))
        if recursive_files and len(files) != len(recursive_files):
            audit_lines.append("")
            audit_lines.append(f"说明：本节只列出 `{folder}` 目录下直接审查的 {len(files)} 个文件；子目录中的 tracked 文件会在各自章节单独覆盖。")
    audit_lines.append("")

app_agents_files = tracked_under("app/agents")
app_agents_by_class: dict[str, list[str]] = defaultdict(list)
for rel in app_agents_files:
    app_agents_by_class[str(file_info[rel]["classification"])].append(rel)

audit_lines.extend([
    "## app/agents 删除就绪度",
    "",
    "整目录结论：当前分支状态下，`app/agents` 的整体判定是 `not_safe_to_delete（当前不可删除）`。",
    "",
    "阻塞证据：",
    "- `packages/office_modules/office_agent_runtime.py` 仍然导入 `app.agents.role_debug_support`，并调用其中的 debug helper。",
    "- `app.agents.role_debug_support` 依赖 `app.agents.role_smoke` 和 `app.agents.role_contracts`。",
    "- 除了这条 debug 依赖链，没有发现测试或配置路径还依赖其余旧的 plugin 风格 agents。",
    "",
])
for label in [
    "safe_to_delete_after_approval",
    "probably_safe_but_needs_runtime_check",
    "uncertain_dynamic_usage",
    "not_safe_to_delete",
    "needs_owner_confirmation",
]:
    rows = sorted(app_agents_by_class.get(label, []))
    audit_lines.append(f"### {classification_display(label)}")
    if not rows:
        audit_lines.append("- 无")
    else:
        for rel in rows:
            audit_lines.append(f"- `{rel}`")
    audit_lines.append("")


def batch_paths(labels: set[str]) -> list[str]:
    return sorted(rel for rel, info in file_info.items() if str(info["classification"]) in labels)


batch1 = batch_paths({"safe_to_delete_after_approval"})
batch2 = batch_paths({"probably_safe_but_needs_runtime_check", "uncertain_dynamic_usage"})
batch3 = batch_paths({"needs_owner_confirmation"})
batch4 = batch_paths({"keep", "not_safe_to_delete"})

audit_lines.extend([
    "# 建议的第 2 阶段删除计划",
    "## Batch 1：明显未使用，且适合优先审批删除",
])
if batch1:
    for rel in batch1:
        audit_lines.append(f"- `{rel}`")
else:
    audit_lines.append("- 无")

audit_lines.append("## Batch 2：大概率未使用，但删除前需要运行时验证")
if batch2:
    for rel in batch2:
        audit_lines.append(f"- `{rel}`")
else:
    audit_lines.append("- 无")

audit_lines.append("## Batch 3：需要 owner 明确确认")
if batch3:
    for rel in batch3:
        audit_lines.append(f"- `{rel}`")
else:
    audit_lines.append("- 无")

audit_lines.append("## 不要删除")
for rel in batch4:
    if rel.startswith("audit/"):
        continue
    audit_lines.append(f"- `{rel}`")

(AUDIT / "dead_code_folder_audit.md").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")
PY
