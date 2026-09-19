# Releasing Elite Journal Helper

## 1. Update the version

Edit `src/elite_journal_helper/version.py`:

```python
__version__ = "X.Y.Z"
```

The UI and CLI both use this value; do not maintain a second hard-coded release version.

## 2. Update the changelog

Add the new release at the top of `CHANGELOG.md` with the date and concise user-facing changes.

## 3. Run release checks

```bash
./scripts/check-release.sh
```

The script checks Python syntax, tests, Git whitespace, CLI version output, and verifies that `ed_journal_probe.py` is the only Python file in the repository root.

## 4. Review the worktree

```bash
git status
git diff --check
git diff
```

Do not ship backup folders, `.bak` files, patches, caches, runtime databases, or local logs.

## 5. Commit and push

Example for v3.2.8:

```bash
git add -A
git commit -m "Release v3.2.8"
git push origin main
```

## 6. Tag and publish

```bash
git tag -a v3.2.8 -m "Elite Journal Helper v3.2.8"
git push origin v3.2.8
```

With GitHub CLI installed:

```bash
gh release create v3.2.8 \
  --title "Elite Journal Helper v3.2.8" \
  --notes-file CHANGELOG.md
```
