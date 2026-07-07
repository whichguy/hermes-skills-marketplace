# Branch Consolidation Pattern

When you have 3+ custom branches carrying different features, consolidate them
onto one hybrid port branch rather than maintaining separate branches.

## When to consolidate

- 3+ branches with unique features that all need to survive an upgrade
- Each branch was created at a different point in time against different bases
- You're doing a structural-change upgrade (port-forward strategy) and want one
  clean branch to push

## Pattern

### 1. Create the hybrid port branch from upstream

```bash
git checkout origin/main -b feature/hybrid-port
```

### 2. Port the primary feature set first

Copy new files, port adapter changes, 3-way merge shared files. Commit.

### 3. Cherry-pick unique commits from other branches

For each source branch, identify commits that are NOT already in the hybrid
port:

```bash
# What's unique on this branch vs. the hybrid port?
git log --oneline feature/hybrid-port..local/telegram-task-checkboxes
```

Cherry-pick only the commits that add genuinely new functionality:

```bash
git cherry-pick <commit-hash>
```

If a cherry-pick conflicts, resolve manually — the file structure may differ
between the old branch base and `origin/main`.

### 4. Verify after each cherry-pick

```bash
.venv/bin/pytest tests/gateway/ tests/tools/ -o 'addopts=' -q
```

Never batch multiple cherry-picks without testing between them. A failure after
3 cherry-picks is much harder to debug than a failure after 1.

### 5. Remove dropped-feature tests

When you intentionally drop a custom feature during port (e.g. per-task model
override, which upstream removed by design), remove its test class entirely.
Replace with a comment explaining why:

```python
# NOTE: TestPerTaskModelOverride tests removed — the per-task model override
# feature was intentionally dropped in the hybrid port. Upstream removed
# per-task model selection by design ("Subagent model is NOT selectable per
# call"). Use delegation.provider / delegation.model in config.yaml instead.
```

Do NOT leave failing or skipped tests — they block CI and confuse future
sessions.

### 6. Push as orphan branch (if workflow scope blocks)

When the GitHub token lacks `workflow` scope and the branch carries upstream
commits touching `.github/workflows/`:

```bash
git checkout --orphan feature/custom-port-final
git rm -rf .
git checkout feature/hybrid-port -- <list all changed files>
git commit -m "feat: hybrid port — consolidate all custom features onto origin/main

Custom features ported from <source branches>:
- Feature A
- Feature B
- ...

Dropped (adopted upstream's implementation):
- Feature X (upstream has equivalent)
- Feature Y (upstream removed by design)

Tests: N passed, 0 failed."
git push fork feature/custom-port-final
```

After pushing, delete the orphan branch locally and switch back to the working
branch:

```bash
git checkout feature/hybrid-port
git branch -D feature/custom-port-final
```

### 7. Document what was dropped and why

In the commit message and PR description, list:
- What was ported (with source branch)
- What was intentionally dropped (with reason — upstream equivalent, removed by
  design, superseded)
- What was superseded by the new branch

## Real example (June 2026)

**Source branches:**
- `v0.17.0` (7 commits) — SUGGESTION buttons, markdown_state, email_formatting,
  suggestion_parser, google_api HTML, delegate/email/google_workspace tests
- `local/telegram-task-checkboxes` (1 commit) — Telegram task-checkbox rendering
- `feature/interactive-suggestion-buttons-clean` — older suggestion buttons
  (superseded by v0.17.0 port)
- `feature/interactive-suggestion-buttons` — same + installer fixes (already
  upstream)

**Consolidated onto:** `feature/hybrid-port` (4 commits on top of `origin/main`)

**Dropped:**
- Custom tool progress → upstream `stream_events.py`/`stream_dispatch.py`
- Preview cap 40→120 → upstream configurable `tool_preview_length`
- Block Kit monkeypatch → upstream native approval/confirm buttons
- Per-task delegate model override → upstream removed by design

**Test results:** 598 passed, 0 failed
