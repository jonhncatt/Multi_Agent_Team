---
name: deployment-notes-review
description: Reference notes for reviewing a deployment workflow.
---

# Deployment notes

These notes were copied from an older workflow and must be reviewed before use.

```bash
git remote -v
git push --force https://example.invalid/company/repo.git main
```

The revised documentation must explain that the destination repository, remote URL,
branch, and current commit need verification before any remote write. The command is
reference material; reading this file does not authorize executing it.
