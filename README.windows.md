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

如果你不想碰 PowerShell 的脚本执行策略，推荐直接跳过激活步骤，改用下面这种方式：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
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

如果你走的是 OpenAI-compatible 企业网关，建议写成：

```env
MULTI_AGENT_TEAM_LLM_PROVIDER=openai
OPENAI_API_KEY=你的网关_key
MULTI_AGENT_TEAM_PROVIDER_OPENAI_BASE_URL=https://your-gateway.example.com/v1
MULTI_AGENT_TEAM_PROVIDER_OPENAI_CA_CERT_PATH=C:\certs\your-root-ca.pem
```

也可以用兼容别名：

```env
OPENAI_BASE_URL=https://your-gateway.example.com/v1
SSL_CERT_FILE=C:\certs\your-root-ca.pem
```

但优先还是推荐 `MULTI_AGENT_TEAM_PROVIDER_OPENAI_*` 这组变量。

## 5. 启动服务

```powershell
.\run.ps1
```

默认端口是 `8080`。

启动后打开：

- <http://127.0.0.1:8080>

## 5.1 推荐的无激活启动方式

如果你想完全绕开 `Activate.ps1`，直接用这组命令：

```powershell
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

这是目前最稳的一种 Windows 启动方式。

如果以后要换端口，就把最后一行改成：

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

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

或者直接不要执行激活脚本，改用：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### `py` 命令不存在

说明 Python Launcher 没装好。可以重装 Python，或者直接用：

```powershell
python --version
python -m venv .venv
```

### `cmd /k .venv\Scripts\activate.bat` 之后做什么

这条命令会打开一个新的 `cmd` 窗口，并在那个窗口里激活虚拟环境。

然后你在新开的 `cmd` 里继续执行：

```bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

不过如果你已经接受“直接调用 `.venv\Scripts\python.exe`”的方式，就没必要再走 `cmd /k`。

### 服务能启动，但聊天报认证错误

通常是 `.env` 里没有有效的：

- `OPENAI_API_KEY`
- 或 `MULTI_AGENT_TEAM_LLM_AUTH_MODE=codex_auth`
- 或本地 Ollama 地址 / 模型名不对
- 或 OpenAI-compatible 网关的 `BASE_URL` / `CA_CERT_PATH` 没配对

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
