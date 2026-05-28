# 运行时入口点映射

| 入口点 | 用途 | 导入 / 加载内容 | 备注 |
|---|---|---|---|
| `app/main.py` | 主 FastAPI HTTP 入口。 | __future__, ast, copy, hashlib, json, os, queue, pathlib, subprocess, threading, time, typing ... | 挂载 `app/static`、提供 `/` 首页，并使用 `agents/vintage_programmer` 初始化 `VintageProgrammerRuntime`。 |
| `app/vintage_programmer_runtime.py` | 主运行时编排类。 | __future__, copy, dataclasses, hashlib, inspect, json, pathlib, re, threading, time, traceback, typing ... | 从 `agents/vintage_programmer` 加载 agent spec 文件，并通过 `packages.office_modules.office_agent_runtime.create_office_runtime_backend` 构建后端。 |
| `run.sh` | 开发启动脚本。 | uvicorn app.main:app | 是 FastAPI app 的 shell 包装层；不引用 `app/agents`。 |
| `run.ps1` | 开发启动脚本。 | uvicorn app.main:app | 是 FastAPI app 的 shell 包装层；不引用 `app/agents`。 |
| `README.md` | 面向用户 / 运维的启动与打包文档。 | run.sh, run.ps1, app.main:app, agents/vintage_programmer | 文档引用的是在线使用的 agent spec 目录 `agents/vintage_programmer`，而不是 `app/agents`。 |
| `README.en.md` | 面向用户 / 运维的启动与打包文档。 | run.sh, run.ps1, app.main:app, agents/vintage_programmer | 文档引用的是在线使用的 agent spec 目录 `agents/vintage_programmer`，而不是 `app/agents`。 |
| `README.ja.md` | 面向用户 / 运维的启动与打包文档。 | run.sh, run.ps1, app.main:app, agents/vintage_programmer | 文档引用的是在线使用的 agent spec 目录 `agents/vintage_programmer`，而不是 `app/agents`。 |
| `README.zh-CN.md` | 面向用户 / 运维的启动与打包文档。 | run.sh, run.ps1, app.main:app, agents/vintage_programmer | 文档引用的是在线使用的 agent spec 目录 `agents/vintage_programmer`，而不是 `app/agents`。 |
| `requirements.txt` | 运行时依赖清单。 | fastapi, uvicorn, openai, playwright, document/image libs | 这里只是依赖声明，不是代码启动入口。 |
| `.github/workflows/regression-ci.yml` | 回归 CI 入口。 | requirements-dev.txt, scripts/check_platform_boundaries.py, pytest | CI 会编译 `app` 和 `scripts`，检查 `app/static/app.js`，并执行 `pytest -q tests`。 另外，推送到 `cleanup/*` 的分支不匹配该 workflow 的 push 分支过滤规则。 |
| `Dockerfile` | 未找到 | 不适用 | 当前分支中不存在该文件。 |
| `docker-compose.yml` | 未找到 | 不适用 | 当前分支中不存在该文件。 |
| `pyproject.toml` | 未找到 | 不适用 | 当前分支中不存在该文件。 |
| `setup.py` | 未找到 | 不适用 | 当前分支中不存在该文件。 |
