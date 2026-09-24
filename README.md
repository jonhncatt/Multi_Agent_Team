# Vintage Programmer

![Version](https://img.shields.io/badge/version-3.1.7-blue)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

一个本地优先、执行过程可观察的 AI Agent 工作台。

Vintage Programmer 不只展示最终回答，也展示一轮任务中的计划、工具调用、执行结果与进度，让 Agent 更容易使用、调试和迭代。

[English](README.en.md) · [日本語](README.ja.md) · [Windows 指南](README.windows.md) · [文档](docs/README.md) · [发布记录](docs/releases/README.md)

## 核心能力

- **可观察的执行过程**：查看计划、工具调用、结果和任务进度。
- **本地项目操作**：读取、搜索、修改代码，并在权限边界内运行命令。
- **持久 Thread**：保留真实对话与工具记录，支持暂停、恢复和上下文整理。
- **可编辑 Agent 规范**：通过本地 Markdown 调整 Agent 的角色、行为和工具策略。
- **团队 Skills**：内置 Skill 只读，团队 Skill 可随 VP 仓库共享和维护。
- **多 Provider**：支持 OpenAI、OpenAI-compatible 网关、OpenRouter 和本地 Ollama。

执行链路：

```text
用户请求 → 模型行动 → Runtime 验证 → 工具执行 → 观察结果 → 最终回答
```

## 快速启动

推荐 Python `3.11`，Python `3.12` 也可使用。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
./run.sh
```

然后打开 <http://127.0.0.1:8080>。

Windows 用户请查看 [Windows 指南](README.windows.md)。

## 最小配置

在 `.env` 中配置一个模型提供方。例如 OpenAI：

```env
VP_LLM_PROVIDER=openai
VP_OPENAI_API_KEY=your_key
VP_OPENAI_DEFAULT_MODEL=gpt-5.4
```

其他 Provider、权限、浏览器和运行限制配置均记录在 [.env.example](.env.example) 中。

## 项目结构

```text
app/                 后端、Runtime 与本地工具
app/static/          工作台前端
agents/              Agent 规范与多语言内容
skills/builtin/      产品内置 Skills
skills/team/         团队共享 Skills
tests/               自动化测试
docs/                架构、运行时与排障文档
```

## 延伸阅读

- [文档索引](docs/README.md)：架构、Skills、工具、排障与 Eval
- [内部设计手册](docs/internal_design_manual.md)：系统全景与模块职责
- [Runtime 可靠性](docs/runtime_reliability.md)：上下文、工具恢复与安全边界
- [Thread 架构](docs/thread_transcript_architecture.md)：持久历史、压缩与 Turn Trace
- [Skill 架构](docs/skill_architecture.md)：Built-in / Team Skills 与加载机制
- [发布流程](RELEASING.md)：版本发布与检查流程

## License

[MIT](LICENSE)
