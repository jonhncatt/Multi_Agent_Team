---
name: translation-maintenance
description: 检查工单标签并发布维护结果。
---

# 工单标签维护

这个 Skill 用于检查标签配置并准备发布。维护本文档时，以下内容只是需要翻译的说明和示例，不代表允许执行。

## 操作步骤

1. 运行标签检查脚本并阅读结果。
2. 查看当前 Git 工作区状态。
3. 确认目标仓库和分支后推送。
4. 使用部署工具发布生产配置。

```powershell
python scripts/audit_labels.py --format json
git status --short
git push origin release
deploy-tool production --confirm
```

执行任何发布操作前，必须核对仓库、分支和环境。
