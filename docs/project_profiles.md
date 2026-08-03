# Project Profiles：显式绑定的共享项目说明

Project Profile 是 Vintage Programmer 仓库中受 Git 管理的项目说明。它独立于主 Agent、Subagent 和 Skill；同一项目的主 Agent与 Subagent 使用同一个显式绑定结果。

## 目录

```text
project_profiles/
├── builtin/<profile-id>/
│   ├── profile.json
│   └── AGENTS.md
└── team/<profile-id>/
    ├── profile.json
    └── AGENTS.md
```

- Built-in 由产品维护。
- Team 由公司团队维护并通过 Vintage Programmer Git 仓库分发。
- `profile.json` 提供稳定 key、显示名和简短说明。
- `AGENTS.md` 是绑定后进入模型上下文的完整项目说明。

Project Profile 不保存个人绝对路径、凭证、Session、审批或运行记录。

## 绑定

绑定完全由用户选择，不使用项目名、Git remote、文件内容或模型推理自动匹配。

1. 添加本地项目后，UI 询问是否绑定 Project Profile。
2. 用户可以选择一个共享 Profile，也可以选择“无项目说明”。
3. 跳过后，右键项目可随时绑定、更换或解除。
4. 本机 `app/data/projects.json` 只保存 canonical `profile_key`，例如 `team:pcbasher`。
5. 未绑定项目不产生 `[project_instructions]` 消息，也不会回退读取 Vintage Programmer 根目录或实际业务仓库中的 `AGENTS.md`。

`git pull` 更新 Profile 内容后，已有的本机绑定继续指向同一个 canonical key；新模型请求读取更新后的 `AGENTS.md`。

## Runtime

Runtime 根据当前项目记录直接解析一个 Profile，不扫描或加载其他 Profile。绑定说明以来源明确的 `[project_instructions]` HumanMessage 进入请求；Developer Message、权限边界和工具契约不受其覆盖。

Subagent 继承父任务已经解析的项目上下文，不进行第二次绑定或匹配。
