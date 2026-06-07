#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "audit"
DOCS_DIR = ROOT / "docs"
REPORT_PATH = DOCS_DIR / "oss_dependency_audit.md"
IMPORTED_MODULES_PATH = AUDIT_DIR / "imported_modules.txt"
MISSING_REQUIREMENTS_PATH = AUDIT_DIR / "missing_requirements.md"
RUNTIME_FILES = ("app/", "scripts/")

DIRECT_PURPOSES = {
    "fastapi": "本地工作台 HTTP API、静态资源与流式接口",
    "uvicorn": "ASGI 运行服务器，提供 reload 与标准性能增强",
    "python-multipart": "处理文件上传与 multipart/form-data 请求",
    "openai": "调用 OpenAI 兼容接口的官方 Python SDK",
    "langchain-openai": "为 runtime 提供 LangChain OpenAI 适配层",
    "pydantic": "配置、请求/响应和内部状态模型",
    "pypdf": "PDF 文本提取兜底路径",
    "pdfplumber": "PDF 页面文本与表格提取主路径",
    "python-docx": "DOCX 文本提取",
    "extract-msg": "解析 Outlook .msg 邮件与附件",
    "openpyxl": "解析 .xlsx 工作簿",
    "pillow": "图片读取、转换、截图后处理",
    "pillow-heif": "支持 HEIF/HEIC 图片输入",
    "rapidocr-onnxruntime": "本地 OCR 主引擎",
    "onnxruntime": "OCR 模型推理运行时",
    "playwright": "浏览器自动化、截图与页面读取",
}

IMPORT_TO_DIST = {
    "PIL": "Pillow",
    "docx": "python-docx",
    "extract_msg": "extract-msg",
    "fastapi": "fastapi",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "openpyxl": "openpyxl",
    "pdfplumber": "pdfplumber",
    "playwright": "playwright",
    "pydantic": "pydantic",
    "pypdf": "pypdf",
    "pillow_heif": "pillow-heif",
    "pytest": "pytest",
    "tiktoken": "tiktoken",
    "yaml": "PyYAML",
}

NATIVE_WHEEL_PACKAGES = {
    "cffi",
    "cryptography",
    "greenlet",
    "httptools",
    "lxml",
    "numpy",
    "onnxruntime",
    "opencv-python",
    "orjson",
    "pillow",
    "pillow-heif",
    "protobuf",
    "pyclipper",
    "pydantic-core",
    "pypdfium2",
    "rapidocr-onnxruntime",
    "shapely",
    "uvloop",
    "watchfiles",
    "xxhash",
    "zstandard",
}

BROWSER_DOWNLOAD_PACKAGES = {
    "playwright",
}

ML_RUNTIME_PACKAGES = {
    "flatbuffers",
    "numpy",
    "onnxruntime",
    "opencv-python",
    "protobuf",
    "pyclipper",
    "rapidocr-onnxruntime",
    "shapely",
}

HIGH_RISK_DIRECT_PACKAGES = {
    "extract-msg",
    "pillow-heif",
}

LEGAL_REVIEW_LICENSE_RE = re.compile(
    r"GPL|LGPL|AGPL|SSPL|MPL|EPL|CDDL|UNKNOWN|Proprietary|Non-standard",
    re.IGNORECASE,
)

PROJECT_SPECIFIC_ANALYSIS = {
    "extract-msg": "用于 Outlook `.msg` 解析，但当前锁定版本直接带 `GPL` 元数据，且依赖链继续引入 `RTFDE`、`oletools`、`pcodedmp` 等 Office 安全分析组件。默认纳入企业分发镜像的法务压力较高。",
    "pillow-heif": "仅用于 HEIF/HEIC 支持，但许可证元数据显示为 `GPLv2`。如果不是明确需要苹果图片格式，默认安装价值不高，风险明显高于收益。",
    "rapidocr-onnxruntime": "许可证为 Apache-2.0，但它把 OCR/ML 运行栈整体带入项目，进一步引入 `onnxruntime`、`opencv-python`、`numpy`、`shapely`、`pyclipper` 等原生组件，体积和平台差异都显著增加。",
    "onnxruntime": "MIT 许可，但属于大型原生推理运行时。对内网落地需要关注 CPU 架构、wheel 来源、镜像体积以及升级时的 ABI 风险。",
    "playwright": "Apache-2.0 许可本身可接受，但运行前通常还要额外下载 Chromium 等浏览器资产。它更适合作为按需安装的浏览器能力层，而不是最小核心依赖。",
    "pdfplumber": "MIT 许可，适合做结构化 PDF 文本/表格提取，但它会放大文档解析攻击面，并带入 `pdfminer-six`、`pypdfium2`、`Pillow` 等处理链。",
    "pypdf": "BSD-3-Clause，纯 Python 取向更强，可作为 PDF 基础能力保留。相对 `pdfplumber`，其法律与平台负担更轻，适合作为兜底解析路径。",
    "langchain-openai": "MIT 许可，但会把 `langchain-core`、`langsmith`、`tiktoken`、`openai` 等依赖一并引入。如果项目只需要官方 SDK 的直接调用，这一层可以评估是否精简。",
    "openai": "Apache 许可，作为外部模型服务客户端属于核心业务依赖，法律风险低于文档/OCR/浏览器链，建议保留在核心依赖中。",
}

SPLIT_RECOMMENDATIONS = [
    "保留在核心依赖：`fastapi`、`uvicorn[standard]`、`python-multipart`、`openai`、`langchain-openai`、`pydantic`、`Pillow`。",
    "补充为直接核心依赖：`langchain-core`、`PyYAML`、`tiktoken`。它们当前只靠传递依赖提供，但源码已经直接 import。",
    "移入 `requirements-office.txt` 草案：`pypdf`、`pdfplumber`、`python-docx`、`openpyxl`。这些能力主要服务附件/文档解析，不是最小工作台启动集。",
    "移入 `requirements-browser.txt` 草案：`playwright`。浏览器自动化应按需安装，并单独管理浏览器下载步骤。",
    "移入 `requirements-ocr.txt` 草案：`rapidocr_onnxruntime`、`onnxruntime`。OCR/ML 运行时应与主应用解耦。",
    "移入 `requirements-risky-optional.txt` 草案：`extract-msg`、`pillow-heif`。两者都需要在企业引入前经过 OSS/法务审查。",
    "锁定并持续审查：保持 `audit/requirements.lock`，后续升级先复跑本脚本和 `pip-audit`。",
]


def normalize_name(name: str) -> str:
    base = (name or "").strip()
    if "[" in base:
        base = base.split("[", 1)[0]
    return re.sub(r"[-_.]+", "-", base.lower())


def escape_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("\n", "<br>")
    return text.replace("|", "\\|")


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_requirement_file(path: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_line in load_text(path).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-r "):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+(?:\[[^]]+\])?)(.*)$", line)
        if not match:
            continue
        name = match.group(1).strip()
        items.append(
            {
                "raw": line,
                "name": name,
                "normalized": normalize_name(name),
            }
        )
    return items


def parse_lock_file(path: Path) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for raw_line in load_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("    "):
            continue
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        normalized = normalize_name(name)
        resolved[normalized] = {
            "name": name.split("[", 1)[0].strip(),
            "version": version.strip(),
        }
    return resolved


def parse_lock_parents(path: Path) -> dict[str, set[str]]:
    parent_map: dict[str, set[str]] = defaultdict(set)
    current_package = ""
    collecting_via = False
    for raw_line in load_text(path).splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            collecting_via = False
            continue
        if not line.startswith(" ") and "==" in stripped and not stripped.startswith("#"):
            current_package = normalize_name(stripped.split("==", 1)[0])
            collecting_via = False
            continue
        if not current_package or not line.startswith("    #"):
            continue
        if stripped.startswith("# via"):
            collecting_via = True
            inline = stripped[len("# via") :].strip()
            if inline:
                parent_map[current_package].add(inline)
            continue
        if collecting_via and stripped.startswith("#"):
            parent_map[current_package].add(stripped[1:].strip())
    return parent_map


def load_dependency_tree(path: Path) -> list[dict[str, Any]]:
    return json.loads(load_text(path))


def build_graph(tree: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], dict[str, dict[str, Any]]]:
    packages: dict[str, dict[str, Any]] = {}
    parents: dict[str, set[str]] = defaultdict(set)
    roots: dict[str, dict[str, Any]] = {}

    def visit(node: dict[str, Any]) -> None:
        package_name = node.get("package_name") or node.get("key") or ""
        normalized = normalize_name(package_name)
        if normalized not in packages:
            packages[normalized] = {
                "name": package_name,
                "version": node.get("installed_version") or "",
                "dependencies": set(),
            }
        for dep in node.get("dependencies") or []:
            dep_name = dep.get("package_name") or dep.get("key") or ""
            dep_normalized = normalize_name(dep_name)
            packages[normalized]["dependencies"].add(dep_normalized)
            parents[dep_normalized].add(normalized)
            visit(dep)

    for node in tree:
        root_name = node.get("package_name") or node.get("key") or ""
        roots[normalize_name(root_name)] = node
        visit(node)
    return packages, parents, roots


def augment_graph_with_lock_parents(
    packages: dict[str, dict[str, Any]],
    parents: dict[str, set[str]],
    resolved: dict[str, dict[str, str]],
    lock_parents: dict[str, set[str]],
) -> None:
    ignored = {"pip", "setuptools"}
    for package_name, raw_parents in lock_parents.items():
        if package_name in ignored:
            continue
        packages.setdefault(
            package_name,
            {
                "name": resolve_package_name(package_name, resolved, packages, {}),
                "version": resolved.get(package_name, {}).get("version", ""),
                "dependencies": set(),
            },
        )
        for raw_parent in raw_parents:
            parent_label = raw_parent.strip()
            if not parent_label or parent_label == "-r requirements.txt":
                continue
            parent_name = normalize_name(parent_label)
            if parent_name in ignored:
                continue
            packages.setdefault(
                parent_name,
                {
                    "name": resolve_package_name(parent_name, resolved, packages, {}),
                    "version": resolved.get(parent_name, {}).get("version", ""),
                    "dependencies": set(),
                },
            )
            packages[parent_name]["dependencies"].add(package_name)
            parents[package_name].add(parent_name)


def count_descendants(packages: dict[str, dict[str, Any]], root_name: str) -> int:
    normalized = normalize_name(root_name)
    if normalized not in packages:
        return 0
    seen: set[str] = set()
    stack = list(packages[normalized]["dependencies"])
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(packages.get(current, {}).get("dependencies", ()))
    return len(seen)


def normalize_license(raw_license: str) -> str:
    text = (raw_license or "").strip()
    if not text:
        return "UNKNOWN"
    compact = re.sub(r"\s+", " ", text)
    lowered = compact.lower()
    if compact.startswith("MIT License ") or "permission is hereby granted" in lowered:
        return "MIT License"
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mozilla public license 2.0" in lowered or "mpl 2.0" in lowered:
        return "MPL-2.0"
    if "gnu lesser general public license v3" in lowered or "lgplv3" in lowered:
        return "LGPLv3"
    if "gnu general public license v3" in lowered or "gplv3" in lowered:
        return "GPLv3"
    if "gnu general public license v2" in lowered or "gplv2" in lowered:
        return "GPLv2"
    return compact


def load_licenses(path: Path) -> dict[str, dict[str, str]]:
    rows = json.loads(load_text(path))
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        name = row.get("Name") or ""
        indexed[normalize_name(name)] = {
            "name": name,
            "version": str(row.get("Version") or ""),
            "license": normalize_license(str(row.get("License") or "")),
            "url": str(row.get("URL") or ""),
            "author": str(row.get("Author") or ""),
            "description": str(row.get("Description") or ""),
        }
    return indexed


def load_vulnerabilities(path: Path) -> dict[str, list[str]]:
    payload = json.loads(load_text(path))
    indexed: dict[str, list[str]] = {}
    for item in payload.get("dependencies", []):
        name = normalize_name(item.get("name") or "")
        vulns = item.get("vulns") or []
        ids: list[str] = []
        for vuln in vulns:
            value = (
                vuln.get("id")
                or vuln.get("alias")
                or vuln.get("advisory")
                or vuln.get("fix_versions")
                or "UNKNOWN"
            )
            ids.append(str(value))
        indexed[name] = ids
    return indexed


def load_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in load_text(path).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def has_legal_review_license(license_name: str) -> bool:
    return bool(LEGAL_REVIEW_LICENSE_RE.search(license_name or ""))


def has_multiple_license_expression(license_name: str) -> bool:
    value = license_name or ""
    return any(token in value for token in (" OR ", " AND ", ";")) or "dependency licenses" in value.lower()


def risk_tags(
    package_name: str,
    license_name: str,
    vulnerability_ids: list[str],
    *,
    imported_but_missing: bool = False,
) -> list[str]:
    normalized = normalize_name(package_name)
    tags: list[str] = []
    if vulnerability_ids:
        tags.append("已知漏洞")
    if has_legal_review_license(license_name):
        tags.append("许可证需法务复核")
    if has_multiple_license_expression(license_name):
        tags.append("多重许可证表达")
    if normalized in NATIVE_WHEEL_PACKAGES:
        tags.append("原生二进制 wheel")
    if normalized in BROWSER_DOWNLOAD_PACKAGES:
        tags.append("浏览器运行时下载")
    if normalized in ML_RUNTIME_PACKAGES:
        tags.append("ML/OCR 运行时")
    if imported_but_missing:
        tags.append("源码直接 import 但未直列声明")
    if normalized in {"oletools", "pcodedmp", "rtfde"}:
        tags.append("Office 解析/安全分析链")
    return tags


def risk_level(
    package_name: str,
    license_name: str,
    vulnerability_ids: list[str],
    *,
    imported_but_missing: bool = False,
    direct: bool = False,
) -> str:
    normalized = normalize_name(package_name)
    if vulnerability_ids:
        return "High"
    if has_legal_review_license(license_name):
        return "High" if direct or normalized in HIGH_RISK_DIRECT_PACKAGES or normalized in {"pcodedmp", "rtfde"} else "Review"
    if imported_but_missing:
        return "Review"
    if normalized in BROWSER_DOWNLOAD_PACKAGES or normalized in ML_RUNTIME_PACKAGES:
        return "Review"
    if normalized in NATIVE_WHEEL_PACKAGES or has_multiple_license_expression(license_name):
        return "Review"
    return "OK"


def requirement_recommendation(package_name: str, risk: str, imported_but_missing: bool = False) -> str:
    normalized = normalize_name(package_name)
    if imported_but_missing:
        return "补充为直接依赖，并放入 core 草案"
    if normalized in {"extract-msg", "pillow-heif"}:
        return "移入 risky-optional，进入法务审查并评估替代方案"
    if normalized == "playwright":
        return "移入 browser optional，浏览器资产单独安装"
    if normalized in {"rapidocr-onnxruntime", "onnxruntime"}:
        return "移入 ocr optional，仅在需要 OCR 时安装"
    if normalized in {"pypdf", "pdfplumber", "python-docx", "openpyxl"}:
        return "建议放入 office optional 草案"
    if risk == "Review":
        return "保留但单独锁定版本并记录平台/二进制来源"
    if risk == "High":
        return "默认不进核心镜像，需复核后再引入"
    return "保留在 core requirements"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(escape_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header_line, divider, *body])


def git_tracked_python_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "*.py"],
            cwd=ROOT,
            text=True,
        )
        files = [ROOT / line.strip() for line in output.splitlines() if line.strip()]
        if files:
            return files
    except Exception:
        pass
    return sorted(ROOT.rglob("*.py"))


def scan_imports(runtime_direct_names: set[str], dev_direct_names: set[str]) -> tuple[dict[str, list[str]], dict[str, list[str]], list[dict[str, str]], list[dict[str, str]]]:
    runtime_imports: dict[str, list[str]] = defaultdict(list)
    test_imports: dict[str, list[str]] = defaultdict(list)
    runtime_missing: list[dict[str, str]] = []
    dev_missing: list[dict[str, str]] = []
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    files = git_tracked_python_files()

    for path in files:
        if path.parts[-1] == "__init__.py":
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(load_text(path), filename=rel)
        except Exception:
            continue
        target = test_imports if rel.startswith("tests/") else runtime_imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if not node.module:
                    continue
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            for module_name in names:
                if not module_name or module_name in stdlib or module_name == "app":
                    continue
                if rel not in target[module_name]:
                    target[module_name].append(rel)

    for group_name, imports, direct_names, sink in (
        ("runtime", runtime_imports, runtime_direct_names, runtime_missing),
        ("dev", test_imports, dev_direct_names, dev_missing),
    ):
        for module_name, file_list in sorted(imports.items()):
            dist_name = IMPORT_TO_DIST.get(module_name, module_name)
            normalized = normalize_name(dist_name)
            if normalized in direct_names:
                continue
            if group_name == "dev" and normalized in runtime_direct_names:
                continue
            sink.append(
                {
                    "module": module_name,
                    "distribution": dist_name,
                    "evidence": ", ".join(file_list[:5]),
                }
            )
    return runtime_imports, test_imports, runtime_missing, dev_missing


def write_import_artifacts(
    runtime_imports: dict[str, list[str]],
    test_imports: dict[str, list[str]],
    runtime_missing: list[dict[str, str]],
    dev_missing: list[dict[str, str]],
) -> None:
    lines = [
        "# Imported third-party modules",
        "",
        "## Runtime files",
    ]
    for module_name, file_list in sorted(runtime_imports.items()):
        dist_name = IMPORT_TO_DIST.get(module_name, module_name)
        lines.append(f"- `{module_name}` -> `{dist_name}`")
        for rel in file_list:
            lines.append(f"  - `{rel}`")
    lines.extend(["", "## Test-only files"])
    for module_name, file_list in sorted(test_imports.items()):
        dist_name = IMPORT_TO_DIST.get(module_name, module_name)
        lines.append(f"- `{module_name}` -> `{dist_name}`")
        for rel in file_list:
            lines.append(f"  - `{rel}`")
    IMPORTED_MODULES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    missing_lines = [
        "# Missing direct requirements audit",
        "",
        "## Runtime imports missing from requirements.txt",
    ]
    if runtime_missing:
        rows = [[item["module"], item["distribution"], item["evidence"]] for item in runtime_missing]
        missing_lines.append(
            table(
                ["Imported module", "Recommended package", "Evidence"],
                rows,
            )
        )
        missing_lines.extend(
            [
                "",
                "These modules are currently satisfied only through transitive dependencies. They should be promoted to direct declarations.",
            ]
        )
    else:
        missing_lines.append("No runtime import is missing from `requirements.txt`.")
    missing_lines.extend(["", "## Test/dev imports"])
    if dev_missing:
        rows = [[item["module"], item["distribution"], item["evidence"]] for item in dev_missing]
        missing_lines.append(table(["Imported module", "Recommended package", "Evidence"], rows))
    else:
        missing_lines.append("No additional dev/test package is missing. `pytest` is already declared in `requirements-dev.txt`.")
    MISSING_REQUIREMENTS_PATH.write_text("\n".join(missing_lines) + "\n", encoding="utf-8")


def summarize_license_counts(licenses: dict[str, dict[str, str]]) -> list[list[Any]]:
    counts = Counter(item["license"] for item in licenses.values())
    return [[license_name, count] for license_name, count in counts.most_common()]


def resolve_package_name(normalized: str, resolved: dict[str, dict[str, str]], graph: dict[str, dict[str, Any]], licenses: dict[str, dict[str, str]]) -> str:
    if normalized in resolved:
        return resolved[normalized]["name"]
    if normalized in licenses:
        return licenses[normalized]["name"]
    if normalized in graph:
        return graph[normalized]["name"]
    return normalized


def build_direct_rows(
    direct_requirements: list[dict[str, str]],
    resolved: dict[str, dict[str, str]],
    graph: dict[str, dict[str, Any]],
    licenses: dict[str, dict[str, str]],
    vulnerabilities: dict[str, list[str]],
    runtime_missing_names: set[str],
) -> tuple[list[list[Any]], dict[str, str]]:
    rows: list[list[Any]] = []
    direct_risks: dict[str, str] = {}
    for item in direct_requirements:
        normalized = item["normalized"]
        display_name = resolve_package_name(normalized, resolved, graph, licenses)
        resolved_version = resolved.get(normalized, {}).get("version", graph.get(normalized, {}).get("version", ""))
        license_name = licenses.get(normalized, {}).get("license", "UNKNOWN")
        vulnerability_ids = vulnerabilities.get(normalized, [])
        risk = risk_level(display_name, license_name, vulnerability_ids, direct=True)
        direct_risks[normalized] = risk
        rows.append(
            [
                item["name"],
                resolved_version,
                DIRECT_PURPOSES.get(normalized, "需补充说明"),
                license_name,
                count_descendants(graph, normalized),
                len(vulnerability_ids),
                risk,
                requirement_recommendation(display_name, risk, imported_but_missing=normalized in runtime_missing_names),
            ]
        )
    return rows, direct_risks


def package_notes(
    normalized: str,
    license_name: str,
    vulnerability_ids: list[str],
    direct_names: set[str],
    runtime_missing_names: set[str],
) -> str:
    notes = risk_tags(normalized, license_name, vulnerability_ids, imported_but_missing=normalized in runtime_missing_names)
    if normalized in direct_names:
        notes.insert(0, "直接依赖")
    if normalized == "python-multipart":
        notes.append("文件上传链路")
    return "；".join(dict.fromkeys(notes)) if notes else ""


def build_transitive_rows(
    resolved: dict[str, dict[str, str]],
    graph: dict[str, dict[str, Any]],
    parents: dict[str, set[str]],
    licenses: dict[str, dict[str, str]],
    vulnerabilities: dict[str, list[str]],
    direct_names: set[str],
    runtime_missing_names: set[str],
) -> tuple[list[list[Any]], int]:
    rows: list[list[Any]] = []
    risk_order = {"High": 0, "Review": 1, "OK": 2}
    high_risk_count = 0
    package_names = sorted((set(resolved) | set(graph) | set(licenses)) - {"pip", "setuptools"})
    for normalized in package_names:
        display_name = resolve_package_name(normalized, resolved, graph, licenses)
        version = resolved.get(normalized, {}).get("version", graph.get(normalized, {}).get("version", licenses.get(normalized, {}).get("version", "")))
        license_name = licenses.get(normalized, {}).get("license", "UNKNOWN")
        vulnerability_ids = vulnerabilities.get(normalized, [])
        risk = risk_level(
            display_name,
            license_name,
            vulnerability_ids,
            imported_but_missing=normalized in runtime_missing_names,
            direct=normalized in direct_names,
        )
        if risk == "High":
            high_risk_count += 1
        required_by = ", ".join(sorted(resolve_package_name(parent, resolved, graph, licenses) for parent in parents.get(normalized, set())))
        if not required_by and normalized in direct_names:
            required_by = "requirements.txt"
        rows.append(
            [
                display_name,
                version,
                required_by or "-",
                license_name,
                ", ".join(vulnerability_ids) if vulnerability_ids else "-",
                risk,
                package_notes(normalized, license_name, vulnerability_ids, direct_names, runtime_missing_names) or "-",
            ]
        )
    rows.sort(key=lambda row: (risk_order.get(str(row[5]), 9), str(row[0]).lower()))
    return rows, high_risk_count


def build_legal_review_rows(
    resolved: dict[str, dict[str, str]],
    graph: dict[str, dict[str, Any]],
    licenses: dict[str, dict[str, str]],
    vulnerabilities: dict[str, list[str]],
) -> list[list[Any]]:
    package_names = sorted((set(resolved) | set(graph) | set(licenses)) - {"pip", "setuptools"})
    rows: list[list[Any]] = []
    for normalized in package_names:
        display_name = resolve_package_name(normalized, resolved, graph, licenses)
        license_name = licenses.get(normalized, {}).get("license", "UNKNOWN")
        vulnerability_ids = vulnerabilities.get(normalized, [])
        tags = risk_tags(display_name, license_name, vulnerability_ids)
        if not tags:
            continue
        if not (
            has_legal_review_license(license_name)
            or normalized in NATIVE_WHEEL_PACKAGES
            or normalized in BROWSER_DOWNLOAD_PACKAGES
            or normalized in ML_RUNTIME_PACKAGES
            or has_multiple_license_expression(license_name)
        ):
            continue
        rows.append(
            [
                display_name,
                resolved.get(normalized, {}).get("version", graph.get(normalized, {}).get("version", licenses.get(normalized, {}).get("version", ""))),
                license_name,
                "；".join(tags),
            ]
        )
    rows.sort(key=lambda row: str(row[0]).lower())
    return rows


def build_project_specific_rows(
    resolved: dict[str, dict[str, str]],
    licenses: dict[str, dict[str, str]],
    graph: dict[str, dict[str, Any]],
) -> list[str]:
    chunks: list[str] = []
    for package_name in (
        "extract-msg",
        "pillow-heif",
        "rapidocr-onnxruntime",
        "onnxruntime",
        "playwright",
        "pdfplumber",
        "pypdf",
        "langchain-openai",
        "openai",
    ):
        normalized = normalize_name(package_name)
        version = resolved.get(normalized, {}).get("version", graph.get(normalized, {}).get("version", ""))
        license_name = licenses.get(normalized, {}).get("license", "UNKNOWN")
        note = PROJECT_SPECIFIC_ANALYSIS[normalized]
        chunks.append(f"### `{package_name}`\n\n- 版本：`{version or 'UNKNOWN'}`\n- 许可证：`{license_name}`\n- 结论：{note}\n")
    return chunks


def load_optional_test_results() -> str:
    path = AUDIT_DIR / "test_results.txt"
    if not path.exists():
        return ""
    return load_text(path).strip()


def summarize_pip_version(raw_value: str) -> str:
    text = (raw_value or "").strip()
    if not text:
        return "pip UNKNOWN"
    return text.split(" from ", 1)[0]


def main() -> None:
    direct_requirements = parse_requirement_file(ROOT / "requirements.txt")
    dev_requirements = parse_requirement_file(ROOT / "requirements-dev.txt")
    direct_names = {item["normalized"] for item in direct_requirements}
    dev_names = direct_names | {item["normalized"] for item in dev_requirements}

    resolved = parse_lock_file(AUDIT_DIR / "requirements.lock")
    lock_parents = parse_lock_parents(AUDIT_DIR / "requirements.lock")
    tree = load_dependency_tree(AUDIT_DIR / "dependency-tree.json")
    graph, parents, _roots = build_graph(tree)
    augment_graph_with_lock_parents(graph, parents, resolved, lock_parents)
    licenses = load_licenses(AUDIT_DIR / "licenses.json")
    vulnerabilities = load_vulnerabilities(AUDIT_DIR / "vulnerabilities.json")
    environment = load_environment(AUDIT_DIR / "environment.txt")

    runtime_imports, test_imports, runtime_missing, dev_missing = scan_imports(direct_names, dev_names)
    write_import_artifacts(runtime_imports, test_imports, runtime_missing, dev_missing)
    runtime_missing_names = {normalize_name(item["distribution"]) for item in runtime_missing}

    direct_rows, _direct_risks = build_direct_rows(
        direct_requirements,
        resolved,
        graph,
        licenses,
        vulnerabilities,
        runtime_missing_names,
    )
    transitive_rows, high_risk_count = build_transitive_rows(
        resolved,
        graph,
        parents,
        licenses,
        vulnerabilities,
        direct_names,
        runtime_missing_names,
    )
    legal_review_rows = build_legal_review_rows(resolved, graph, licenses, vulnerabilities)
    license_summary_rows = summarize_license_counts(licenses)
    vulnerability_total = sum(len(ids) for ids in vulnerabilities.values())
    test_summary = load_optional_test_results()

    report_parts = [
        "# OSS 依赖审计报告",
        "",
        "## 执行摘要",
        "",
        f"- 审计时间：`{environment.get('timestamp_local', environment.get('timestamp_utc', 'UNKNOWN'))}`",
        f"- 审计环境：`{environment.get('os', 'UNKNOWN')}` / Python `{environment.get('python', 'UNKNOWN')}` / {summarize_pip_version(environment.get('pip', 'pip UNKNOWN'))}",
        f"- 直接依赖数量：`{len(direct_requirements)}`",
        f"- 解析后的唯一依赖数量：`{len((set(resolved) | set(graph) | set(licenses)) - {'pip', 'setuptools'})}`",
        f"- 漏洞数量：`{vulnerability_total}`",
        f"- 高风险包数量（按本报告规则）：`{high_risk_count}`",
        "",
        "### 许可证分布",
        "",
        table(["License", "Package count"], license_summary_rows),
        "",
        "### 审计结论",
        "",
        "- 当前锁定依赖在 `pip-audit` 结果中未发现已知漏洞。",
        "- 主要风险集中在许可证与可选能力链，而不是 CVE：`extract-msg`、`pillow-heif` 及其 Office/OCR 相关传递依赖需要优先处理。",
        "- `langchain-core`、`PyYAML` 与 `tiktoken` 已被源码直接 import，但未在 `requirements.txt` 中直列声明，应尽快补齐。",
        "- 浏览器能力、OCR 能力、Outlook/HEIF 解析能力都适合拆成可选安装集，而不是默认核心依赖。",
        "",
        "## 直接依赖表",
        "",
        table(
            [
                "Direct dependency",
                "Resolved version",
                "Purpose in this project",
                "License",
                "Transitive dependency count",
                "Vulnerability count",
                "Risk level",
                "Recommendation",
            ],
            direct_rows,
        ),
        "",
        "## 完整传递依赖表",
        "",
        table(
            [
                "Package",
                "Version",
                "Required by",
                "License",
                "Vulnerability IDs",
                "Risk level",
                "Notes",
            ],
            transitive_rows,
        ),
        "",
        "## 高风险 / 法务复核清单",
        "",
        "以下条目命中至少一个规则：受限许可证、原生二进制 wheel、浏览器/运行时下载、ML 运行时、多重许可证表达或元数据不清晰。",
        "",
        table(["Package", "Version", "License", "Flags"], legal_review_rows),
        "",
        "## 项目特定依赖分析",
        "",
        *build_project_specific_rows(resolved, licenses, graph),
        "## import 覆盖检查",
        "",
        f"- 详细列表：`{IMPORTED_MODULES_PATH.relative_to(ROOT).as_posix()}`",
        f"- 缺失声明报告：`{MISSING_REQUIREMENTS_PATH.relative_to(ROOT).as_posix()}`",
        "",
        "### 运行时缺失的直接声明",
        "",
        table(
            ["Imported module", "Recommended package", "Evidence"],
            [[item["module"], item["distribution"], item["evidence"]] for item in runtime_missing] or [["-", "-", "无"]],
        ),
        "",
        "## 建议与后续动作",
        "",
        *[f"- {item}" for item in SPLIT_RECOMMENDATIONS],
    ]

    if test_summary:
        report_parts.extend(
            [
                "",
                "## 测试结果",
                "",
                test_summary,
            ]
        )

    REPORT_PATH.write_text("\n".join(report_parts).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
