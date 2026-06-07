# OSS 依赖审计报告

## 执行摘要

- 审计时间：`2026-06-08T02:01:23+09:00`
- 审计环境：`macOS-26.5-arm64-arm-64bit` / Python `3.11.7` / pip 26.1.2
- 直接依赖数量：`16`
- 解析后的唯一依赖数量：`87`
- 漏洞数量：`0`
- 高风险包数量（按本报告规则）：`4`

### 许可证分布

| License | Package count |
| --- | --- |
| MIT License | 21 |
| MIT | 17 |
| BSD-3-Clause | 12 |
| BSD License | 9 |
| Apache Software License | 7 |
| Apache-2.0 | 3 |
| Apache Software License; MIT License | 2 |
| LGPLv3 | 1 |
| MPL-2.0 | 1 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| GPL | 1 |
| MIT AND PSF-2.0 | 1 |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 1 |
| MPL-2.0 AND (Apache-2.0 OR MIT) | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| GPLv3 | 1 |
| MIT-CMU | 1 |
| GPLv2 | 1 |
| 3-Clause BSD License | 1 |
| BSD-3-Clause, Apache-2.0, dependency licenses | 1 |
| Apache-2.0 AND CNRI-Python | 1 |
| MPL-2.0 AND MIT | 1 |
| PSF-2.0 | 1 |

### 审计结论

- 当前锁定依赖在 `pip-audit` 结果中未发现已知漏洞。
- 主要风险集中在许可证与可选能力链，而不是 CVE：`extract-msg`、`pillow-heif` 及其 Office/OCR 相关传递依赖需要优先处理。
- `langchain-core`、`PyYAML` 与 `tiktoken` 已被源码直接 import，但未在 `requirements.txt` 中直列声明，应尽快补齐。
- 浏览器能力、OCR 能力、Outlook/HEIF 解析能力都适合拆成可选安装集，而不是默认核心依赖。

## 直接依赖表

| Direct dependency | Resolved version | Purpose in this project | License | Transitive dependency count | Vulnerability count | Risk level | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fastapi | 0.136.3 | 本地工作台 HTTP API、静态资源与流式接口 | MIT | 9 | 0 | OK | 保留在 core requirements |
| uvicorn[standard] | 0.49.0 | ASGI 运行服务器，提供 reload 与标准性能增强 | BSD-3-Clause | 11 | 0 | OK | 保留在 core requirements |
| python-multipart | 0.0.32 | 处理文件上传与 multipart/form-data 请求 | Apache-2.0 | 0 | 0 | OK | 保留在 core requirements |
| openai | 2.41.0 | 调用 OpenAI 兼容接口的官方 Python SDK | Apache Software License | 15 | 0 | OK | 保留在 core requirements |
| langchain-openai | 1.2.2 | 为 runtime 提供 LangChain OpenAI 适配层 | MIT License | 35 | 0 | OK | 保留在 core requirements |
| pydantic | 2.13.4 | 配置、请求/响应和内部状态模型 | MIT | 4 | 0 | OK | 保留在 core requirements |
| pypdf | 6.13.0 | PDF 文本提取兜底路径 | BSD-3-Clause | 0 | 0 | OK | 建议放入 office optional 草案 |
| pdfplumber | 0.11.9 | PDF 页面文本与表格提取主路径 | MIT License | 7 | 0 | OK | 建议放入 office optional 草案 |
| python-docx | 1.2.0 | DOCX 文本提取 | MIT License | 2 | 0 | OK | 建议放入 office optional 草案 |
| extract-msg | 0.55.0 | 解析 Outlook .msg 邮件与附件 | GPL | 19 | 0 | High | 移入 risky-optional，进入法务审查并评估替代方案 |
| openpyxl | 3.1.5 | 解析 .xlsx 工作簿 | MIT License | 1 | 0 | OK | 建议放入 office optional 草案 |
| Pillow | 12.2.0 | 图片读取、转换、截图后处理 | MIT-CMU | 0 | 0 | Review | 保留但单独锁定版本并记录平台/二进制来源 |
| pillow-heif | 1.3.0 | 支持 HEIF/HEIC 图片输入 | GPLv2 | 1 | 0 | High | 移入 risky-optional，进入法务审查并评估替代方案 |
| rapidocr_onnxruntime | 1.4.4 | 本地 OCR 主引擎 | Apache-2.0 | 12 | 0 | Review | 移入 ocr optional，仅在需要 OCR 时安装 |
| onnxruntime | 1.26.0 | OCR 模型推理运行时 | MIT License | 4 | 0 | Review | 移入 ocr optional，仅在需要 OCR 时安装 |
| playwright | 1.60.0 | 浏览器自动化、截图与页面读取 | Apache-2.0 | 3 | 0 | Review | 移入 browser optional，浏览器资产单独安装 |

## 完整传递依赖表

| Package | Version | Required by | License | Vulnerability IDs | Risk level | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| extract-msg | 0.55.0 | requirements.txt | GPL | - | High | 直接依赖；许可证需法务复核 |
| pcodedmp | 1.2.6 | oletools | GPLv3 | - | High | 许可证需法务复核；Office 解析/安全分析链 |
| pillow-heif | 1.3.0 | requirements.txt | GPLv2 | - | High | 直接依赖；许可证需法务复核；原生二进制 wheel |
| rtfde | 0.1.2.2 | extract-msg | LGPLv3 | - | High | 许可证需法务复核；Office 解析/安全分析链 |
| certifi | 2026.5.20 | httpcore, httpx, requests | MPL-2.0 | - | Review | 许可证需法务复核 |
| cffi | 2.0.0 | cryptography | MIT | - | Review | 原生二进制 wheel |
| cryptography | 48.0.0 | msoffcrypto-tool, pdfminer-six | Apache-2.0 OR BSD-3-Clause | - | Review | 多重许可证表达；原生二进制 wheel |
| flatbuffers | 25.12.19 | onnxruntime | Apache Software License | - | Review | ML/OCR 运行时 |
| greenlet | 3.5.1 | playwright | MIT AND PSF-2.0 | - | Review | 多重许可证表达；原生二进制 wheel |
| httptools | 0.8.0 | uvicorn | MIT | - | Review | 原生二进制 wheel |
| langchain-core | 1.4.1 | langchain-openai | MIT License | - | Review | 源码直接 import 但未直列声明 |
| lxml | 6.1.1 | python-docx | BSD-3-Clause | - | Review | 原生二进制 wheel |
| numpy | 2.4.6 | onnxruntime, opencv-python, rapidocr-onnxruntime, shapely | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | - | Review | 多重许可证表达；原生二进制 wheel；ML/OCR 运行时 |
| onnxruntime | 1.26.0 | rapidocr-onnxruntime | MIT License | - | Review | 直接依赖；原生二进制 wheel；ML/OCR 运行时 |
| opencv-python | 4.13.0.92 | rapidocr-onnxruntime | Apache Software License | - | Review | 原生二进制 wheel；ML/OCR 运行时 |
| orjson | 3.11.9 | langsmith | MPL-2.0 AND (Apache-2.0 OR MIT) | - | Review | 许可证需法务复核；多重许可证表达；原生二进制 wheel |
| packaging | 26.2 | langchain-core, langsmith, onnxruntime | Apache-2.0 OR BSD-2-Clause | - | Review | 多重许可证表达 |
| pillow | 12.2.0 | pdfplumber, pillow-heif, rapidocr-onnxruntime | MIT-CMU | - | Review | 直接依赖；原生二进制 wheel |
| playwright | 1.60.0 | requirements.txt | Apache-2.0 | - | Review | 直接依赖；浏览器运行时下载 |
| protobuf | 7.35.0 | onnxruntime | 3-Clause BSD License | - | Review | 原生二进制 wheel；ML/OCR 运行时 |
| pyclipper | 1.4.0 | rapidocr-onnxruntime | MIT License | - | Review | 原生二进制 wheel；ML/OCR 运行时 |
| pydantic-core | 2.46.4 | pydantic | MIT | - | Review | 原生二进制 wheel |
| pypdfium2 | 5.9.0 | pdfplumber | BSD-3-Clause, Apache-2.0, dependency licenses | - | Review | 多重许可证表达；原生二进制 wheel |
| pyyaml | 6.0.3 | langchain-core, rapidocr-onnxruntime, uvicorn | MIT License | - | Review | 源码直接 import 但未直列声明 |
| rapidocr-onnxruntime | 1.4.4 | requirements.txt | Apache-2.0 | - | Review | 直接依赖；原生二进制 wheel；ML/OCR 运行时 |
| regex | 2026.5.9 | tiktoken | Apache-2.0 AND CNRI-Python | - | Review | 多重许可证表达 |
| shapely | 2.1.2 | rapidocr-onnxruntime | BSD License | - | Review | 原生二进制 wheel；ML/OCR 运行时 |
| sniffio | 1.3.1 | openai | Apache Software License; MIT License | - | Review | 多重许可证表达 |
| tiktoken | 0.13.0 | langchain-openai | MIT License | - | Review | 源码直接 import 但未直列声明 |
| tqdm | 4.68.1 | openai, rapidocr-onnxruntime | MPL-2.0 AND MIT | - | Review | 许可证需法务复核；多重许可证表达 |
| uvloop | 0.22.1 | uvicorn | Apache Software License; MIT License | - | Review | 多重许可证表达；原生二进制 wheel |
| watchfiles | 1.2.0 | uvicorn | MIT License | - | Review | 原生二进制 wheel |
| xxhash | 3.7.0 | langsmith | BSD License | - | Review | 原生二进制 wheel |
| zstandard | 0.25.0 | langsmith | BSD-3-Clause | - | Review | 原生二进制 wheel |
| annotated-doc | 0.0.4 | fastapi | MIT | - | OK | - |
| annotated-types | 0.7.0 | pydantic | MIT License | - | OK | - |
| anyio | 4.13.0 | httpx, openai, starlette, watchfiles | MIT | - | OK | - |
| beautifulsoup4 | 4.13.5 | extract-msg | MIT License | - | OK | - |
| charset-normalizer | 3.4.7 | pdfminer-six, requests | MIT | - | OK | - |
| click | 8.4.1 | uvicorn | BSD-3-Clause | - | OK | - |
| colorclass | 2.2.2 | oletools | MIT License | - | OK | - |
| compressed-rtf | 1.0.7 | extract-msg | MIT | - | OK | - |
| distro | 1.9.0 | openai | Apache Software License | - | OK | - |
| easygui | 0.98.3 | oletools | BSD License | - | OK | - |
| ebcdic | 1.1.1 | extract-msg | BSD License | - | OK | - |
| et-xmlfile | 2.0.0 | openpyxl | MIT License | - | OK | - |
| fastapi | 0.136.3 | requirements.txt | MIT | - | OK | 直接依赖 |
| h11 | 0.16.0 | httpcore, uvicorn | MIT License | - | OK | - |
| httpcore | 1.0.9 | httpx | BSD-3-Clause | - | OK | - |
| httpx | 0.28.1 | langsmith, openai | BSD License | - | OK | - |
| idna | 3.18 | anyio, httpx, requests | BSD-3-Clause | - | OK | - |
| jiter | 0.15.0 | openai | MIT | - | OK | - |
| jsonpatch | 1.33 | langchain-core | BSD License | - | OK | - |
| jsonpointer | 3.1.1 | jsonpatch | BSD License | - | OK | - |
| langchain-openai | 1.2.2 | requirements.txt | MIT License | - | OK | 直接依赖 |
| langchain-protocol | 0.0.16 | langchain-core | MIT License | - | OK | - |
| langsmith | 0.8.9 | langchain-core | MIT | - | OK | - |
| lark | 1.3.1 | rtfde | MIT License | - | OK | - |
| msoffcrypto-tool | 6.0.0 | oletools | MIT License | - | OK | - |
| olefile | 0.47 | extract-msg, msoffcrypto-tool, oletools | BSD License | - | OK | - |
| oletools | 0.60.2 | pcodedmp, rtfde | BSD License | - | OK | Office 解析/安全分析链 |
| openai | 2.41.0 | langchain-openai | Apache Software License | - | OK | 直接依赖 |
| openpyxl | 3.1.5 | requirements.txt | MIT License | - | OK | 直接依赖 |
| pdfminer-six | 20251230 | pdfplumber | MIT | - | OK | - |
| pdfplumber | 0.11.9 | requirements.txt | MIT License | - | OK | 直接依赖 |
| pycparser | 3.0 | cffi | BSD-3-Clause | - | OK | - |
| pydantic | 2.13.4 | fastapi, langchain-core, langsmith, openai | MIT | - | OK | 直接依赖 |
| pyee | 13.0.1 | playwright | MIT License | - | OK | - |
| pyparsing | 3.3.2 | oletools | MIT | - | OK | - |
| pypdf | 6.13.0 | requirements.txt | BSD-3-Clause | - | OK | 直接依赖 |
| python-docx | 1.2.0 | requirements.txt | MIT License | - | OK | 直接依赖 |
| python-dotenv | 1.2.2 | uvicorn | BSD-3-Clause | - | OK | - |
| python-multipart | 0.0.32 | requirements.txt | Apache-2.0 | - | OK | 直接依赖；文件上传链路 |
| red-black-tree-mod | 1.22 | extract-msg | MIT | - | OK | - |
| requests | 2.34.2 | langsmith, requests-toolbelt, tiktoken | Apache Software License | - | OK | - |
| requests-toolbelt | 1.0.0 | langsmith | Apache Software License | - | OK | - |
| six | 1.17.0 | rapidocr-onnxruntime | MIT License | - | OK | - |
| soupsieve | 2.8.4 | beautifulsoup4 | MIT | - | OK | - |
| starlette | 1.2.1 | fastapi | BSD-3-Clause | - | OK | - |
| tenacity | 9.1.4 | langchain-core | Apache Software License | - | OK | - |
| typing-extensions | 4.15.0 | anyio, beautifulsoup4, fastapi, langchain-core, langchain-protocol, openai, pydantic, pydantic-core, pyee, python-docx, starlette, typing-inspection | PSF-2.0 | - | OK | - |
| typing-inspection | 0.4.2 | fastapi, pydantic | MIT | - | OK | - |
| tzlocal | 5.3.1 | extract-msg | MIT License | - | OK | - |
| urllib3 | 2.7.0 | requests | MIT | - | OK | - |
| uuid-utils | 0.16.0 | langchain-core, langsmith | BSD-3-Clause | - | OK | - |
| uvicorn | 0.49.0 | requirements.txt | BSD-3-Clause | - | OK | 直接依赖 |
| websockets | 16.0 | langsmith, uvicorn | BSD-3-Clause | - | OK | - |

## 高风险 / 法务复核清单

以下条目命中至少一个规则：受限许可证、原生二进制 wheel、浏览器/运行时下载、ML 运行时、多重许可证表达或元数据不清晰。

| Package | Version | License | Flags |
| --- | --- | --- | --- |
| certifi | 2026.5.20 | MPL-2.0 | 许可证需法务复核 |
| cffi | 2.0.0 | MIT | 原生二进制 wheel |
| cryptography | 48.0.0 | Apache-2.0 OR BSD-3-Clause | 多重许可证表达；原生二进制 wheel |
| extract-msg | 0.55.0 | GPL | 许可证需法务复核 |
| flatbuffers | 25.12.19 | Apache Software License | ML/OCR 运行时 |
| greenlet | 3.5.1 | MIT AND PSF-2.0 | 多重许可证表达；原生二进制 wheel |
| httptools | 0.8.0 | MIT | 原生二进制 wheel |
| lxml | 6.1.1 | BSD-3-Clause | 原生二进制 wheel |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 多重许可证表达；原生二进制 wheel；ML/OCR 运行时 |
| onnxruntime | 1.26.0 | MIT License | 原生二进制 wheel；ML/OCR 运行时 |
| opencv-python | 4.13.0.92 | Apache Software License | 原生二进制 wheel；ML/OCR 运行时 |
| orjson | 3.11.9 | MPL-2.0 AND (Apache-2.0 OR MIT) | 许可证需法务复核；多重许可证表达；原生二进制 wheel |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | 多重许可证表达 |
| pcodedmp | 1.2.6 | GPLv3 | 许可证需法务复核；Office 解析/安全分析链 |
| pillow | 12.2.0 | MIT-CMU | 原生二进制 wheel |
| pillow-heif | 1.3.0 | GPLv2 | 许可证需法务复核；原生二进制 wheel |
| playwright | 1.60.0 | Apache-2.0 | 浏览器运行时下载 |
| protobuf | 7.35.0 | 3-Clause BSD License | 原生二进制 wheel；ML/OCR 运行时 |
| pyclipper | 1.4.0 | MIT License | 原生二进制 wheel；ML/OCR 运行时 |
| pydantic-core | 2.46.4 | MIT | 原生二进制 wheel |
| pypdfium2 | 5.9.0 | BSD-3-Clause, Apache-2.0, dependency licenses | 多重许可证表达；原生二进制 wheel |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | 原生二进制 wheel；ML/OCR 运行时 |
| regex | 2026.5.9 | Apache-2.0 AND CNRI-Python | 多重许可证表达 |
| rtfde | 0.1.2.2 | LGPLv3 | 许可证需法务复核；Office 解析/安全分析链 |
| shapely | 2.1.2 | BSD License | 原生二进制 wheel；ML/OCR 运行时 |
| sniffio | 1.3.1 | Apache Software License; MIT License | 多重许可证表达 |
| tqdm | 4.68.1 | MPL-2.0 AND MIT | 许可证需法务复核；多重许可证表达 |
| uvloop | 0.22.1 | Apache Software License; MIT License | 多重许可证表达；原生二进制 wheel |
| watchfiles | 1.2.0 | MIT License | 原生二进制 wheel |
| xxhash | 3.7.0 | BSD License | 原生二进制 wheel |
| zstandard | 0.25.0 | BSD-3-Clause | 原生二进制 wheel |

## 项目特定依赖分析

### `extract-msg`

- 版本：`0.55.0`
- 许可证：`GPL`
- 结论：用于 Outlook `.msg` 解析，但当前锁定版本直接带 `GPL` 元数据，且依赖链继续引入 `RTFDE`、`oletools`、`pcodedmp` 等 Office 安全分析组件。默认纳入企业分发镜像的法务压力较高。

### `pillow-heif`

- 版本：`1.3.0`
- 许可证：`GPLv2`
- 结论：仅用于 HEIF/HEIC 支持，但许可证元数据显示为 `GPLv2`。如果不是明确需要苹果图片格式，默认安装价值不高，风险明显高于收益。

### `rapidocr-onnxruntime`

- 版本：`1.4.4`
- 许可证：`Apache-2.0`
- 结论：许可证为 Apache-2.0，但它把 OCR/ML 运行栈整体带入项目，进一步引入 `onnxruntime`、`opencv-python`、`numpy`、`shapely`、`pyclipper` 等原生组件，体积和平台差异都显著增加。

### `onnxruntime`

- 版本：`1.26.0`
- 许可证：`MIT License`
- 结论：MIT 许可，但属于大型原生推理运行时。对内网落地需要关注 CPU 架构、wheel 来源、镜像体积以及升级时的 ABI 风险。

### `playwright`

- 版本：`1.60.0`
- 许可证：`Apache-2.0`
- 结论：Apache-2.0 许可本身可接受，但运行前通常还要额外下载 Chromium 等浏览器资产。它更适合作为按需安装的浏览器能力层，而不是最小核心依赖。

### `pdfplumber`

- 版本：`0.11.9`
- 许可证：`MIT License`
- 结论：MIT 许可，适合做结构化 PDF 文本/表格提取，但它会放大文档解析攻击面，并带入 `pdfminer-six`、`pypdfium2`、`Pillow` 等处理链。

### `pypdf`

- 版本：`6.13.0`
- 许可证：`BSD-3-Clause`
- 结论：BSD-3-Clause，纯 Python 取向更强，可作为 PDF 基础能力保留。相对 `pdfplumber`，其法律与平台负担更轻，适合作为兜底解析路径。

### `langchain-openai`

- 版本：`1.2.2`
- 许可证：`MIT License`
- 结论：MIT 许可，但会把 `langchain-core`、`langsmith`、`tiktoken`、`openai` 等依赖一并引入。如果项目只需要官方 SDK 的直接调用，这一层可以评估是否精简。

### `openai`

- 版本：`2.41.0`
- 许可证：`Apache Software License`
- 结论：Apache 许可，作为外部模型服务客户端属于核心业务依赖，法律风险低于文档/OCR/浏览器链，建议保留在核心依赖中。

## import 覆盖检查

- 详细列表：`audit/imported_modules.txt`
- 缺失声明报告：`audit/missing_requirements.md`

### 运行时缺失的直接声明

| Imported module | Recommended package | Evidence |
| --- | --- | --- |
| langchain_core | langchain-core | app/vp_runtime_backend.py |
| tiktoken | tiktoken | app/context_meter.py |
| yaml | PyYAML | app/workbench.py |

## 建议与后续动作

- 保留在核心依赖：`fastapi`、`uvicorn[standard]`、`python-multipart`、`openai`、`langchain-openai`、`pydantic`、`Pillow`。
- 补充为直接核心依赖：`langchain-core`、`PyYAML`、`tiktoken`。它们当前只靠传递依赖提供，但源码已经直接 import。
- 移入 `requirements-office.txt` 草案：`pypdf`、`pdfplumber`、`python-docx`、`openpyxl`。这些能力主要服务附件/文档解析，不是最小工作台启动集。
- 移入 `requirements-browser.txt` 草案：`playwright`。浏览器自动化应按需安装，并单独管理浏览器下载步骤。
- 移入 `requirements-ocr.txt` 草案：`rapidocr_onnxruntime`、`onnxruntime`。OCR/ML 运行时应与主应用解耦。
- 移入 `requirements-risky-optional.txt` 草案：`extract-msg`、`pillow-heif`。两者都需要在企业引入前经过 OSS/法务审查。
- 锁定并持续审查：保持 `audit/requirements.lock`，后续升级先复跑本脚本和 `pip-audit`。

## 测试结果

- 命令：`./audit/.venv-lock/bin/python -m pytest -q`
- 结果：`401 passed, 1 warning in 41.76s`
- 备注：`pytest` 仅作为审计期 dev-only 工具安装在 `audit/.venv-lock` 中，不属于运行时依赖。
