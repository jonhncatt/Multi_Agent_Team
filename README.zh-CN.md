# Vintage Programmer

[日本語 README](README.ja.md)  
[English README](README.en.md)  
[Windows 指南](README.windows.md)  
[发布流程](RELEASING.md)

这是一个本地运行的单主 agent 工作台，默认主 agent 是 `vintage_programmer`。  
当前稳定版本是 `v2.7.0`。

当前工作台形态：
- 左侧线程栏
- 中间全宽工作平面
- 底部常驻 composer
- 底部状态栏
- 右侧 Workbench 抽屉
- 本地 skills / agent spec 可编辑

## 运行

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
./run.sh
```

默认打开：

- <http://127.0.0.1:8080>

### Windows

Windows 默认建议不要激活脚本，直接调用虚拟环境里的 Python：

```powershell
py -3.11 -m venv .venv
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

详细说明见 [README.windows.md](README.windows.md)。

## `.env` 最小配置

OpenAI 官方：

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=你的_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.1-chat
```

如果你不填 `VP_OPENAI_API_KEY`，但本机存在 `VP_CODEX_AUTH_FILE`，程序会自动切到 Codex auth。

OpenAI-compatible 网关：

```env
VP_LLM_PROVIDER=openai_compatible
VP_OPENAI_COMPAT_API_KEY=你的网关_key
VP_OPENAI_COMPAT_BASE_URL=https://your-gateway.example.com/v1
VP_OPENAI_COMPAT_CA_CERT_PATH=/absolute/path/to/your-root-ca.pem
VP_OPENAI_COMPAT_DEFAULT_MODEL=gpt-5.1-chat
```

OpenRouter：

```env
VP_LLM_PROVIDER=openrouter
VP_OPENROUTER_API_KEY=你的_openrouter_key
VP_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
VP_OPENROUTER_DEFAULT_MODEL=google/gemma-4-31b-it:free
VP_OPENROUTER_MODEL_FALLBACKS=nvidia/nemotron-3-super-120b-a12b:free
```

更多示例见 [.env.example](.env.example)。

如果你想固定默认语言，可以在 `.env` 里加上：

```env
VP_DEFAULT_LOCALE=ja-JP
```

支持值是 `zh-CN`、`ja-JP`、`en`。实际语言优先级为：
Settings 当前选择 > 浏览器本地持久化 > 浏览器语言 > `VP_DEFAULT_LOCALE`。

## 多语言策略

- 继续维护一个主仓库，不拆“日语代码库”。
- 只翻译用户可见文本，不改内部类名、函数名、路由名、变量名。
- 前端 UI、后端用户提示、主 agent 默认规范、README 都支持 locale。
- 公司内部分发可直接默认 `ja-JP`，你自己的环境仍可切回中文或英文。

## Agent 规范

主 agent 由四份 markdown 规范定义，运行时会按 locale 优先加载对应版本：

- `agents/vintage_programmer/soul.md`
- `agents/vintage_programmer/identity.md`
- `agents/vintage_programmer/agent.md`
- `agents/vintage_programmer/tools.md`

本地化版本位于：

- `agents/vintage_programmer/locales/ja-JP/`
- `agents/vintage_programmer/locales/en/`

## 本地 Skills

本地 skills 固定放在：

- `workspace/skills/<skill_id>/SKILL.md`

只有 `enabled: true` 且 `bind_to` 包含 `vintage_programmer` 的 skill 会注入主 agent。

## 发布

正式发布流程固定为：

- 在 `codex/*` 候选分支完成改动
- 回归通过后合到 `main`
- 在 `main` 的发布提交上打 annotated tag，例如 `v2.6.0`
- 后续新改动始终从最新 `main` 再切新的 `codex/*` 分支

详细步骤见 [RELEASING.md](RELEASING.md)。
