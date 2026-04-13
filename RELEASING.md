# Releasing Vintage Programmer

This repository uses a minimal release flow:

1. Land release-candidate work on a `codex/*` branch.
2. Keep local runtime state out of Git.
3. Run the release gates locally.
4. Open a PR into `main`.
5. Merge to `main` only after the regression checks are green.
6. Create an annotated tag on the release commit, for example `v1.0.0`.
7. Start the next change from a fresh `codex/*` branch cut from updated `main`.

## Keep Local State Out Of Git

These paths are local runtime state and should not be released:

- `app/data/apps/`
- `app/data/projects.json`
- `workspace/`

If files from those paths were tracked in older revisions, remove them from the index with `git rm --cached` and keep the ignore rules in place.

## Release Gates

Run these before opening or merging the release PR:

```bash
python3 -m py_compile app/main.py app/config.py app/models.py
node --check app/static/app.js
pytest -q
```

Also require GitHub `Regression CI` to pass on the release PR before merging.

## Release Steps

From the release-candidate branch:

```bash
git push origin <candidate-branch>
gh pr create --base main --fill
```

After CI is green and the PR is approved:

```bash
gh pr merge --merge --delete-branch
git checkout main
git pull --ff-only origin main
git tag -a v1.0.0 -m "Vintage Programmer v1.0.0"
git push origin main
git push origin v1.0.0
```

## After Release

Start the next change from `main`:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b codex/<next-topic>
```

Use hotfix branches from `main` for post-release fixes. Do not stack new feature work on the old release branch.
