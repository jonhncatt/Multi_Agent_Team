# Vintage Programmer Windows 指南

这份说明只针对 Windows PowerShell。

## 1. 准备环境

建议：

- Windows 11
- PowerShell 7 或 Windows PowerShell 5.1
- Python 3.11

先确认 Python 可用：

```powershell
py -3.11 --version
```

如果这条命令不可用，先安装 Python，并确保安装时勾选了 `Add python.exe to PATH`。

## 2. 进入项目目录

```powershell
cd C:\path\to\new_validation_agent
```

## 3. 创建虚拟环境并安装依赖

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果激活脚本被系统拦住，先执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

然后再执行：

```powershell
.venv\Scripts\Activate.ps1
```

## 4. 配置 `.env`

复制环境模板：

```powershell
Copy-Item .env.example .env
```

最简单的 OpenAI 配置只需要改这两行：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=你的_key
```

如果你已经在 Codex 里登录过，也可以用：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
MULTI_AGENT_TEAM_LLM_AUTH_MODE=codex_auth
```

如果你要接本地 Ollama：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=ollama
MULTI_AGENT_TEAM_PROVIDER_OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
MULTI_AGENT_TEAM_DEFAULT_MODEL=qwen2.5-coder:7b
```

## 5. 启动服务

```powershell
.\run.ps1
```

默认端口是 `8080`。

启动后打开：

- <http://127.0.0.1:8080>

## 6. 快速检查

先看健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8080/api/health
```

如果你只想看返回内容：

```powershell
(Invoke-WebRequest http://127.0.0.1:8080/api/health).Content
```

## 7. 常见问题

### PowerShell 不允许执行脚本

执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### `py` 命令不存在

说明 Python Launcher 没装好。可以重装 Python，或者直接用：

```powershell
python --version
python -m venv .venv
```

### 服务能启动，但聊天报认证错误

通常是 `.env` 里没有有效的：

- `OPENAI_API_KEY`
- 或 `MULTI_AGENT_TEAM_LLM_AUTH_MODE=codex_auth`
- 或本地 Ollama 地址 / 模型名不对

### 想换端口

在 `.env` 里加：

```env
MULTI_AGENT_TEAM_APP_PORT=9000
```

然后重新执行：

```powershell
.\run.ps1
```

## 8. 当前 Windows 入口

- 启动脚本：[run.ps1](run.ps1)
- 环境模板：[.env.example](.env.example)
- 主服务入口：[app/main.py](app/main.py)
