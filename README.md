# Multi_Agent_Robot

![Mat Multi_Agent_Robot logo](docs/assets/brand/mat-logo-horizontal.jpg)

[English README](README.en.md)

[![Regression CI](https://github.com/jonhncatt/Multi_Agent_Robot/actions/workflows/regression-ci.yml/badge.svg?branch=main)](https://github.com/jonhncatt/Multi_Agent_Robot/actions/workflows/regression-ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-app-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`Multi_Agent_Robot` 是一个本地 Agent OS 风格系统：底盘稳定、模块可插拔、工具链可演进。

## 快速启动

```bash
git clone https://github.com/jonhncatt/Multi_Agent_Robot.git
cd Multi_Agent_Robot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

主界面：<http://127.0.0.1:8080>  
实验界面：`./run-role-agent-lab.sh` -> <http://127.0.0.1:8081>

## LLM Provider 配置（通用）

从现在开始，推荐使用通用命名的环境变量：

```env
OFFICETOOL_LLM_PROVIDER=openai
OFFICETOOL_LLM_AUTH_MODE=auto
OFFICETOOL_LLM_API_KEY=<YOUR_API_KEY>
OFFICETOOL_LLM_BASE_URL=https://api.openai.com/v1
OFFICETOOL_LLM_MODEL=gpt-5.1-chat
```

说明：
- 当前主链路支持 OpenAI-compatible API 与 Codex auth。
- 旧变量（如 `OPENAI_API_KEY`、`OFFICETOOL_OPENAI_*`）仍保留兼容。
- 未配置 API key 或 Codex auth 时，页面可打开，但 `/api/chat` 无法正常返回模型结果。

## 界面

### Multi_Agent_Robot
![Multi_Agent_Robot home](docs/assets/screenshots/kernel_robot_home.png)

### Multi_Agent_Robot Lab
![Multi_Agent_Robot Lab home](docs/assets/screenshots/role_agent_lab_home.png)

## 常用命令

- 主产品：`./run.sh` 或 `./run-multi-agent-robot.sh`
- 兼容入口：`./run-kernel-robot.sh`
- 最小 smoke：`python scripts/demo_minimal_agent_os.py --check`
- 回归测试：`pytest`

## 项目结构（简版）

- `app/`: Web UI、API、内核、模块装配
- `packages/`: 共享 runtime 与模块边界
- `scripts/`: demo 与运行脚本
- `tests/`: 回归测试
- `docs/`: 架构、模块、运维与路线图

## 更多文档

- 模块接入：`docs/modules/module_integration_guide.md`
- 平台指标：`docs/operations/platform_metrics.md`
- 进化方向（2026）：`docs/roadmap/evolution_direction_2026.md`
- Swarm 路线图：`docs/swarm-roadmap.md`

