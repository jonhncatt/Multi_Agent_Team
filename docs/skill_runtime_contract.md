# Skill Runtime Contract

Vintage Programmer 将 Skill 包、业务 Project 和凭证分成三个独立域。

## 路径规则

| 内容 | 位置来源 | 运行时变量 |
| --- | --- | --- |
| `SKILL.md`、`scripts/`、`references/` | 当前 Skill 目录 | `VP_SKILL_ROOT` |
| 当前执行脚本 | Runtime 已验证的脚本绝对路径 | `VP_SKILL_SCRIPT` |
| 业务仓库根目录 | 当前选择的 Project | `VP_PROJECT_ROOT` |
| 命令工作目录 | 当前 Turn 的业务 cwd | `VP_PROJECT_CWD` |

Agent 必须使用 Runtime 提供的绝对 `SKILL.md` 路径，不得先在业务 Project 中搜索同名 Skill。直接运行已启用 Skill 的 Python、Shell、Node 或 PowerShell 脚本时，Runtime 注入以上四个非密钥变量；命令 cwd 仍保持业务 Project。

Skill 自带资源相对于 `VP_SKILL_ROOT` 或脚本自身位置解析。任务输入、输出和待修改文件相对于 `VP_PROJECT_ROOT` / `VP_PROJECT_CWD` 解析。

## 凭证规则

- 默认只加载 Vintage Programmer 安装仓库根目录的 `.env`。
- 可在启动 VP 的进程环境中设置绝对 `VP_DOTENV_PATH`，使用仓库外的凭证文件。
- 不读取启动目录或当前业务 Project 的 `.env`。
- `.env` 只在 VP 启动时加载；修改后必须重启。
- Skill 只读取继承环境变量，不查找、打开或解析 `.env`。
- Skill 不得打印、记录、返回或写入密钥；报错只说明缺少哪个变量。
- Team Skill Git 仓库只保存变量名和配置说明，不保存变量值。

## Python 模板

```python
from __future__ import annotations

import os
from pathlib import Path


SKILL_ROOT = Path(
    os.environ.get("VP_SKILL_ROOT", Path(__file__).resolve().parents[1])
).resolve()
PROJECT_ROOT = Path(
    os.environ.get("VP_PROJECT_ROOT", os.getcwd())
).resolve()


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}. "
            "Configure it in the Vintage Programmer environment and restart VP."
        )
    return value


API_KEY = require_env("EXAMPLE_API_KEY")
RULES_PATH = SKILL_ROOT / "references" / "rules.md"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "result.json"
```

不要在脚本中调用 `load_dotenv()`、`find_dotenv()`，也不要使用 `Path(".env")`。不要把密钥放到命令参数中。

## 现有 Skill 迁移清单

1. 删除搜索 Project、用户目录或父目录中 `SKILL.md` / `.env` 的逻辑。
2. 将 `scripts/foo.py`、`references/foo.md` 等相对路径改为基于脚本位置或 `VP_SKILL_ROOT`。
3. 将业务输入输出路径改为基于 `VP_PROJECT_ROOT` 或 `VP_PROJECT_CWD`。
4. 将凭证读取改为 `os.environ.get("VARIABLE_NAME")`；删除 dotenv 加载代码。
5. 缺少凭证时只报告变量名和“配置后重启 VP”，不得报告尝试过的 `.env` 路径。
6. 检查日志、异常和命令参数，确保不会出现密钥值。
7. 在至少两个不同 Project 中执行同一个 Skill，确认 Skill 路径与凭证行为不随 Project 改变。
