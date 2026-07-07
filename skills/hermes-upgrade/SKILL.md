---
name: hermes-upgrade
description: Upgrade Hermes Agent to a new version on a fork/clone with local patches — stash, checkout tag, reinstall deps, migrate config, resolve conflicts, restart.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms:
- linux
- macos
metadata:
  hermes:
    tags:
    - hermes
    - upgrade
    - git
    - devops
    category: devops
    related_skills:
    - hermes-agent
    - versioning-hermes-home
    - hermes-config-git-backup
---

# Upgrading Hermes Agent

Upgrade a Hermes Agent installation — especially a fork or clone carrying local
patches — to a newer upstream release tag.

## When this activates

- "upgrade Hermes"
- "update to the latest version"
- "bump Hermes to v0.X.0"
- Any request to move to a newer Hermes release

## The hard rule: `hermes update` doesn't work on forks

The `hermes update` CLI command assumes you're running from the upstream
`nousresearch/hermes-agent` repo. On a fork or clone with local patches,
it will fail or produce unexpected results. **Always use the git-tag workflow
below for forks and local-patch installs.**

## Workflow

### 0. Pre-flight: Is an update even available?

Before diving into the upgrade workflow, determine whether a newer version exists.
The path depends on your deployment model.

#### Docker-based deployments (Watchtower or manual pull)

From inside the container:
```bash
hermes --version    # running version (e.g. "Hermes Agent v0.17.0 (2026.6.19)")
```

Check the latest image on Docker Hub (no auth needed for public repos):
```bash
curl -s "https://hub.docker.com/v2/repositories/nousresearch/hermes-agent/tags/?page_size=3&ordering=last_updated" | python3 -c "
import json,sys
data = json.load(sys.stdin)
for t in data['results']:
    print(f\"{t['name']:20s} {t['last_updated']}\")
"
```

Compare the running version's date (e.g. `2026.6.19`) against the `latest` tag's
`last_updated` date. If `latest` is newer, an update is available.

If Watchtower is running, check its activity:
```bash
# Watchtower typically restarts the container on pull — check boot log
cat /opt/data/logs/container-boot.log | tail -5
# Daily restarts at the same time ≈ Watchtower is active
```

#### Git-based deployments (source checkout)

```bash
cd /path/to/hermes-agent
git remote -v                          # confirm origin
git fetch origin main --quiet
git tag --sort=-creatordate | head -5  # find latest tag
hermes --version                       # current version
git rev-list --count HEAD..origin/main # commits behind upstream
```

### 1. Recon (git-based upgrade)
```bash
cd /path/to/hermes-agent
git stash list                         # any existing stashes?
```

### 2. Stash local changes
```bash
git stash push -m "pre-upgrade local changes"
```
Verify: `git stash list` should show the new entry.

### 3. Check out the new version tag
```bash
git fetch --tags
git checkout -b v0.X.0 v2026.M.D    # branch from tag
```

### 4. Reinstall dependencies
The version bump may bring new or updated Python dependencies:
```bash
uv pip install -e .
```
Verify: `hermes --version` should show the new version.

### 5. Run config migration
```bash
hermes config migrate
```
This updates the config schema if needed. Answer prompts as appropriate.
Verify: `hermes config check` should show the config version as current (✓).

### 6. Re-apply local changes
```bash
git stash pop
```

### 7. Resolve conflicts
Conflicts are common in gateway files (`gateway/platforms/base.py`,
`gateway/platforms/slack.py`, `gateway/run.py`) because upstream rewrites
these frequently. Resolution strategy:

- **Standalone new files** (e.g. `gateway/suggestion_parser.py`,
  `gateway/email_formatting.py`) — these merge cleanly. Keep them.
- **Patched hook points** in gateway files — upstream rewrites often
  invalidate the patch context. If conflicts are in hook-point areas,
  **keep upstream code** (`git checkout --theirs <file>`) and plan to
  re-apply the hook patches against the new codebase.
- **Non-gateway files** (e.g. `tools/send_message_tool.py`,
  `skills/productivity/google-workspace/scripts/google_api.py`) —
  these usually merge cleanly. Review the merged result.

After resolving:
```bash
git add <resolved-files>
git commit -m "local changes: <summary> (re-applied on v0.X.0)"
```

### 8. Drop the stash
```bash
git stash drop
```
Only after confirming the commit looks correct. `git stash pop` on conflict
keeps the stash entry — it won't auto-drop.

### 9. Restart the gateway
The new version won't take effect until the gateway restarts:
```bash
docker compose restart hermes-gateway
# or: hermes gateway restart
```

## When a simple rebase won't work: major structural changes

Sometimes upstream doesn't just edit files — it **moves** them. The most common
case is a plugin migration: platform adapters relocated from
`gateway/platforms/<x>.py` → `plugins/platforms/<x>/adapter.py`. A `git rebase`
or `git stash pop` against such a gap will produce catastrophic conflicts
because your patches target files that no longer exist at the old paths.

### Detection: is this a structural-change upgrade?

Before attempting any merge, run reconnaissance:

```bash
cd /path/to/hermes-agent
MERGE_BASE=$(git merge-base HEAD origin/main)
COMMITS_BEHIND=$(git rev-list --count $MERGE_BASE..origin/main)

# If >100 commits behind, check for structural changes:
# 1. Did any files your branch touches get deleted/moved upstream?
git diff --name-status $MERGE_BASE..origin/main -- gateway/platforms/ | grep "^D"
# 2. Did new plugin directories appear?
git ls-tree -d origin/main plugins/platforms/ 2>/dev/null
# 3. Compare file sizes — large deltas signal rewrites
git show origin/main:gateway/run.py | wc -l    # upstream
git show HEAD:gateway/run.py | wc -l            # yours
# 4. Check if class names survived the move
git show origin/main:plugins/platforms/slack/adapter.py | grep "^class "
git show HEAD:gateway/platforms/slack.py | grep "^class "
```

If files were **deleted** from `gateway/platforms/` and reappeared under
`plugins/platforms/`, you have a structural-change upgrade. Do NOT attempt
`git rebase` or `git stash pop` — use the port-forward strategy below.

### Port-forward strategy (for structural-change upgrades)

Instead of rebasing your branch onto upstream, create a **fresh branch from
upstream** and port your changes onto it file-by-file:

1. **Branch fresh from upstream:**
   ```bash
   git checkout origin/main -b feature/port-to-main
   ```

2. **Copy new files directly** (files that only exist in your branch, no
   upstream equivalent). These have zero conflict:
   ```bash
   git checkout OLD_BRANCH -- gateway/markdown_state.py gateway/email_formatting.py ...
   git add <files>
   git commit -m "port: copy new files from v0.17.0 custom branch"
   ```

3. **Port adapter changes to new plugin paths.** For each moved file, diff
   your changes against the merge base, then manually apply to the new path:
   ```bash
   git diff $MERGE_BASE OLD_BRANCH -- gateway/platforms/slack.py > /tmp/slack.patch
   # Manually apply to plugins/platforms/slack/adapter.py
   # The new file has diverged — patch won't apply cleanly
   ```

4. **3-way merge shared files** (files both sides modified):
   ```bash
   git show origin/main:gateway/stream_consumer.py > /tmp/upstream.py
   git show OLD_BRANCH:gateway/stream_consumer.py > /tmp/ours.py
   git show $MERGE_BASE:gateway/stream_consumer.py > /tmp/base.py
   git merge-file -L ours -L base -L upstream /tmp/ours.py /tmp/base.py /tmp/upstream.py
   cp /tmp/ours.py gateway/stream_consumer.py
   ```

5. **Write a reconciliation plan first.** For gaps >100 commits with
   structural changes, write a plan document (e.g. `RECONCILE_PLAN.md`)
   cataloging every file, its conflict risk, and the port strategy. This
   prevents mid-port confusion and gives the user visibility into effort.

6. **Verify with the test suite** before pushing:
   ```bash
   python -m pytest tests/gateway/ -o 'addopts=' -q
   ```

7. **Use delegate_task for the porting work.** For large ports (4+ files,
   complex diffs), dispatch a coding subagent with the full context and
   explicit per-file instructions. This keeps your context window clean and
   lets the subagent work through the mechanical edits while you stay
   responsive. Provide: the branch name, file paths, exact insertion points
   (line numbers or surrounding code), and the full implementation to port
   (via `git show <old-branch>:<path>` references).

### Effort calibration

| Gap size | Structural change? | Strategy | Typical effort |
|----------|-------------------|----------|----------------|
| <50 commits | No | `git stash pop` + resolve | 15–30 min |
| 50–200 commits | No | `git rebase` or stash-pop | 30–60 min |
| 200+ commits | No | Stash-pop with careful conflict resolution | 1–2 hrs |
| Any size | **Yes** (files moved/deleted) | Port-forward | 2–4 hrs |

The bottleneck is always `gateway/run.py` (18k+ lines) and the moved adapter
files. Budget most of the time for these.

See `references/plugin-migration-example.md` for a concrete real-world example
of the port-forward strategy applied to the v0.17.0 → main plugin migration.
See `references/branch-consolidation.md` for the pattern of merging multiple
custom branches into one hybrid port branch.

## Pitfalls

- **`hermes update` on a fork** — this command assumes upstream repo structure.
  On forks, use the git-tag workflow instead.
- **Stash conflicts on gateway files** — `base.py`, `slack.py`, and `run.py`
  are rewritten frequently upstream. Hook-point patches (suggestion-stripper,
  formatting hooks) will almost always conflict. Keep upstream and re-patch.
- **Structural-change upgrades (plugin migrations, file relocations)** — when
  upstream moved files your branch touches, `git rebase` and `git stash pop`
  will fail catastrophically. Use the port-forward strategy instead: branch
  fresh from upstream, copy new files, port diffs to new paths, 3-way merge
  shared files. Always write a reconciliation plan first.
- **"The new tag will include these changes" — verify, don't assume.** Users
  sometimes believe upstream has already absorbed their custom work into the
  next release. This is rarely true for fork-specific features (SUGGESTION:
  buttons, email formatting, markdown state tracking). Always diff the user's
  branch against `origin/main` to confirm what's actually upstream vs. unique.
  Dispatch a code-review subagent (Kimi) to audit the diff if the gap is large.
- **Docker daemon not running** — on some hosts (e.g. OrbStack without Docker
  engine), `docker` commands fail. Check with `docker info` before attempting
  Docker-based version checks. Fall back to git-based checks inside the
  container (`hermes --version`, `git tag`, `git rev-list`).
- **Forgetting `uv pip install -e .`** — the version bump changes the installed
  package metadata. Skipping this leaves the old version reported by
  `hermes --version` even though the code is new.
- **Skipping `hermes config migrate`** — new versions may add or change config
  keys. Running migrate ensures the config schema matches the code.
- **Gateway not restarted** — the running gateway process still has the old
  code loaded. Restart is required.
- **Stash left behind** — `git stash pop` on conflict keeps the stash entry.
  Drop it after resolving (`git stash drop`).
- **GitHub push blocked by `workflow` scope** — when the branch carries
  upstream commits that touch `.github/workflows/`, GitHub rejects the push
  with: `refusing to allow an OAuth App to create or update workflow without
  'workflow' scope`. Two fixes:
  1. **Refresh the token** (preferred): `gh auth refresh --scopes workflow --hostname github.com`
  2. **Orphan-branch workaround** (when interactive auth isn't possible):
     ```bash
     git checkout --orphan feature/custom-port-final
     git rm -rf .
     git checkout <source-branch> -- <changed-files...>
     git commit -m "feat: ..."
     git push fork feature/custom-port-final
     ```
     This creates a branch with no ancestry — no workflow files, no push
     rejection. The downside: the PR loses commit history context. Use only
     when token refresh isn't feasible (e.g. inside a container without
     browser access for OAuth). Name the orphan branch descriptively
     (e.g. `feature/custom-port-final`) — avoid `-orphan` suffix, it's
     noise. After pushing, delete the orphan branch locally and switch
     back to the working branch.
- **Dropped-feature tests must be removed, not skipped** — when you
  intentionally drop a custom feature during port (e.g. per-task model
  override, which upstream removed by design), remove its test class
  entirely. Do NOT leave it as failing or skipped tests — they'll block
  CI and confuse future sessions. Replace the class with a comment
  explaining why it was removed and what config to use instead.
- **Branch consolidation** — when you have 3+ custom branches carrying
  different features, consolidate them onto one hybrid port branch rather
  than maintaining separate branches. Cherry-pick unique commits from each
  source branch, verify tests after each cherry-pick, and push a single
  consolidated branch. See `references/branch-consolidation.md` for the
  full pattern.

## Verification checklist

- [ ] `hermes --version` shows the new version
- [ ] `hermes config check` shows config version as current (✓)
- [ ] `git log --oneline -3` shows the carry commit on top of the release tag
- [ ] Local changes are present and functional
- [ ] Gateway restarted and healthy
