# Multi_Agent_Robot

![Mat Multi_Agent_Robot logo](docs/assets/brand/mat-logo-horizontal.jpg)

[中文 README](README.md)

[![Regression CI](https://github.com/jonhncatt/Multi_Agent_Robot/actions/workflows/regression-ci.yml/badge.svg?branch=main)](https://github.com/jonhncatt/Multi_Agent_Robot/actions/workflows/regression-ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-app-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`Multi_Agent_Robot` is a local Agent OS-style system: stable core, pluggable modules, and evolvable tool paths.

## Quick Start

```bash
git clone https://github.com/jonhncatt/Multi_Agent_Robot.git
cd Multi_Agent_Robot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

Main UI: <http://127.0.0.1:8080>  
Lab UI: `./run-role-agent-lab.sh` -> <http://127.0.0.1:8081>

## LLM Provider Config (Generic)

Use provider-agnostic env keys as the default:

```env
OFFICETOOL_LLM_PROVIDER=openai
OFFICETOOL_LLM_AUTH_MODE=auto
OFFICETOOL_LLM_API_KEY=<YOUR_API_KEY>
OFFICETOOL_LLM_BASE_URL=https://api.openai.com/v1
OFFICETOOL_LLM_MODEL=gpt-5.1-chat
```

Notes:
- The current runtime path supports OpenAI-compatible API and Codex auth.
- Legacy keys (`OPENAI_API_KEY`, `OFFICETOOL_OPENAI_*`) are still supported.
- The UI can boot without credentials, but `/api/chat` will not return model output until auth is configured.

## UI

### Multi_Agent_Robot
![Multi_Agent_Robot home](docs/assets/screenshots/kernel_robot_home.png)

### Multi_Agent_Robot Lab
![Multi_Agent_Robot Lab home](docs/assets/screenshots/role_agent_lab_home.png)

## Common Commands

- Main product: `./run.sh` or `./run-multi-agent-robot.sh`
- Compatibility alias: `./run-kernel-robot.sh`
- Minimal smoke: `python scripts/demo_minimal_agent_os.py --check`
- Regression tests: `pytest`

## Project Layout (Short)

- `app/`: UI, API, kernel, module assembly
- `packages/`: shared runtime and boundaries
- `scripts/`: demos and run scripts
- `tests/`: regression coverage
- `docs/`: architecture, modules, operations, roadmap

## More Docs

- Module integration: `docs/modules/module_integration_guide.md`
- Platform metrics: `docs/operations/platform_metrics.md`
- Evolution direction (2026): `docs/roadmap/evolution_direction_2026.md`
- Swarm roadmap: `docs/swarm-roadmap.md`

