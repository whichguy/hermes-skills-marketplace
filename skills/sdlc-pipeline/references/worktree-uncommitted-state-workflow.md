# Worktree Uncommitted-State Workflow — Complete Design

> Produced by DeepSeek V4 Pro (2026-06-29, 201.3s, 28,923 chars) after the user
> corrected the v3.1 design: worktrees stay nested inside the parent project
> directory, not moved to WORKTREE_ROOT or /tmp.

## Recommended Approach: `git diff HEAD` patch + selective file copy

**Verdict: Patch file for tracked changes + selective copy for untracked files.**

Why not the alternatives:

| Approach | Verdict | Reason |
|----------|---------|--------|
| `git stash` + `git stash apply` | **Rejected** | Stash pops changes from parent — orchestrator loses working state. Stash stack is global state — concurrent orchestrators collide. |
| `git add -A && git commit` (current design) | **Rejected as sole approach** | Pollutes git log with checkpoint commits. If orchestrator crashes after commit but before merge, those commits are permanent. Children inherit ALL uncommitted files including `.sdlc/` state files. |
| Raw file copy (`cp -r`) | **Rejected** | Doesn't handle deleted files, doesn't preserve git's knowledge of what changed, `.gitignore` rules must be manually re-implemented. |
| **`git diff HEAD` → patch file → `git apply`** | **ACCEPTED** | Clean, reversible, doesn't mutate parent state. Handles modifications, deletions, and new tracked files. Combined with selective copy for untracked files. |

## Step-by-Step Workflow

### Phase A: Capture uncommitted state from orchestrator worktree

```bash
# Step A1: Capture tracked changes as a patch
cd $ORCHESTRATOR_WORKTREE
git diff HEAD --binary > /tmp/sdlc-uncommitted-$RUN_ID.patch

# Step A2: Capture untracked files list (respecting .gitignore)
git ls-files --others --exclude-standard > /tmp/sdlc-untracked-$RUN_ID.txt

# Step A3: Filter untracked files — EXCLUDE .sdlc/ state files
grep -v '^\.sdlc/' /tmp/sdlc-untracked-$RUN_ID.txt \
  > /tmp/sdlc-untracked-filtered-$RUN_ID.txt
```

### Phase B: Create child worktree and apply state

```bash
# Step B1: Create worktree from the SAME commit the patch was generated from
# CRITICAL: use HEAD (not a branch name) so the patch base matches exactly
cd $REPO_ROOT
git worktree add -b parallel/$TASK_ID $CHILD_WORKTREE_PATH HEAD

# Step B2: Apply the patch in the child worktree
cd $CHILD_WORKTREE_PATH
git apply --index /tmp/sdlc-uncommitted-$RUN_ID.patch

# Step B3: Copy filtered untracked files
while IFS= read -r file; do
  mkdir -p "$CHILD_WORKTREE_PATH/$(dirname "$file")"
  cp "$ORCHESTRATOR_WORKTREE/$file" "$CHILD_WORKTREE_PATH/$file"
done < /tmp/sdlc-untracked-filtered-$RUN_ID.txt

# Step B4: Commit the applied state in the child worktree
cd $CHILD_WORKTREE_PATH
git add -A
git commit -m "checkpoint: inherit orchestrator uncommitted state"
```

### Phase C: Child does its work

Child runs in its worktree. May or may not commit its own work.

### Phase D: Child completes — pull interim changes, merge back

```bash
# Step D1: Fetch latest from origin
cd $CHILD_WORKTREE_PATH
git fetch origin $PARENT_BRANCH

# Step D2: Rebase child's branch onto updated parent
# REBASE (not merge) because:
#   - Keeps child's changes as a linear sequence on top of parent
#   - Makes the final merge back a fast-forward
#   - Conflicts surface at rebase time, not merge time
git rebase origin/$PARENT_BRANCH

# Step D3: Merge child's branch back to parent
cd $REPO_ROOT
git checkout $PARENT_BRANCH
git merge --no-ff parallel/$TASK_ID -m "Merge parallel/$TASK_ID"
```

### Phase E: Cleanup

```bash
cd $REPO_ROOT
git worktree remove --force $CHILD_WORKTREE_PATH
git worktree prune
git branch -d parallel/$TASK_ID
rm -f /tmp/sdlc-uncommitted-$RUN_ID.patch
rm -f /tmp/sdlc-untracked-$RUN_ID.txt
rm -f /tmp/sdlc-untracked-filtered-$RUN_ID.txt
```

## Corner Cases (37 identified)

### Patch Capture & Application (C1-C12)

| # | Scenario | Mitigation |
|---|----------|------------|
| C1 | Patch doesn't apply cleanly | Use HEAD for both diff and worktree add — context always matches. Assert same commit hash. |
| C2 | Binary files in uncommitted changes | Use `git diff HEAD --binary` |
| C3 | New untracked files | `git ls-files --others --exclude-standard` + selective copy |
| C4 | Deleted files | `git diff HEAD` shows deletion; `git apply` handles it |
| C5 | Renamed files | `git diff HEAD` shows rename; `git apply` handles it |
| C6 | File mode changes | `git diff HEAD` includes mode changes |
| C7 | Symlink changes | `git diff HEAD` handles symlinks |
| C8 | Empty patch (no uncommitted changes) | Skip patch application, still copy untracked files |
| C9 | Very large patch (>50MB) | Cap patch size; fall back to commit-based approach |
| C10 | Patch contains secrets (.env) | `.env` is typically in `.gitignore`; exclude list catches it |
| C11 | Orchestrator modifies files after capture | Single-threaded during capture→create window — not a real race |
| C12 | `git apply --index` fails on fresh worktree | Cannot happen — fresh worktree has clean index |

### Interim Changes (I1-I10)

| # | Scenario | Mitigation |
|---|----------|------------|
| I1 | Orchestrator committed new files while child ran | Rebase replays child's commits on top — happy path |
| I2 | Orchestrator modified PROJECT.md while child ran | If child didn't touch PROJECT.md: no conflict. If child did: conflict → §4 resolution |
| I3 | Child A merged, Child B still running | Rebase picks up A's changes — core concurrent-children scenario |
| I4 | Both children modified `__init__.py` | Planner must ensure file-independence |
| I5 | Child's rebase has conflicts | See Conflict Resolution below |
| I6 | Orchestrator committed between child merges | Works correctly — intended behavior |
| I7 | Parent branch force-pushed | Should never happen — orchestrator controls parent branch |
| I8 | Child never committed its work | Auto-commit before rebase: `git add -A && git commit -m "child: auto-commit"` |
| I9 | Child produced no files | Skip merge, just clean up worktree |
| I10 | Network failure during `git fetch` | Retry with backoff (3 attempts). If all fail, merge without rebase. |

### Merge Back (M1-M7)

| # | Scenario | Mitigation |
|---|----------|------------|
| M1 | Merge conflict | See Conflict Resolution below |
| M2 | Sequential merge of children A, B, C | Each rebases before merging — conflict-safe |
| M3 | Parallel merge (race condition) | **Never do this.** Merges MUST be sequential. |
| M4 | Merge commit message collision | Use unique messages: `"Merge parallel/{task_id} — {description}"` |
| M5 | Orchestrator has uncommitted changes when merging | Auto-commit first: `git add -A && git commit -m "checkpoint: pre-merge state"` |
| M6 | Merge succeeds but introduces test failures | Run full test suite after EACH child merge (merge-test gate) |
| M7 | Child branch deleted before merge | Guard: check `git branch --list parallel/$TASK_ID` before merging |

### Worktree Lifecycle (W1-W7)

| # | Scenario | Mitigation |
|---|----------|------------|
| W1 | Worktree removal fails — files locked | `--force` handles most cases. Log warning if it still fails. |
| W2 | Child process still running during removal | `as_completed()` guarantees all children exited before cleanup |
| W3 | Orchestrator crashes mid-dispatch | SIGINT/SIGTERM handler + startup cleanup prunes orphaned worktrees |
| W4 | Crash after merge but before worktree removal | Harmless — startup cleanup handles it |
| W5 | Crash after worktree removal but before branch deletion | Harmless — periodic `git branch -d parallel/*` handles it |
| W6 | `git worktree add` fails — path exists | Use unique paths with UUID |
| W7 | `git worktree add` fails — branch exists | Delete stale branch first or use UUID8 (4B combinations) |

### Edge Cases (E1-E7)

| # | Scenario | Mitigation |
|---|----------|------------|
| E1 | Empty repo (no commits) | Create initial empty commit, then proceed |
| E2 | Detached HEAD state | Detect and refuse concurrent dispatch — require named branch |
| E3 | Orchestrator mid-rebase/merge | Detect `.git/rebase-merge` or `.git/MERGE_HEAD` — refuse dispatch |
| E4 | Patch file corrupted | Check with `git apply --check` before applying |
| E5 | Child worktree on different filesystem | Acceptable — WORKTREE_ROOT is configurable |
| E6 | `/tmp` is tmpfs, patch too large | Use persistent temp directory: `$WORKTREE_ROOT/.patches/` |
| E7 | `.gitignore` changed between capture and creation | Patch includes `.gitignore` changes — child gets updated version |

## Conflict Resolution Strategy

### Rebase Conflicts (Step D2)

Priority order:
1. **AUTO-RESOLVE:** `.sdlc/` conflicts → keep child's version
2. **AUTO-RESOLVE:** PROJECT.md conflicts (child didn't intentionally modify) → keep parent's version
3. **ABORT + SKIP:** Source file conflicts → abort rebase, skip merge, flag for HUMAN_REVIEW
4. **NEVER:** attempt automatic merge conflict resolution on source code

### Merge Conflicts (Step D3)

1. ABORT merge immediately: `git merge --abort`
2. Record failure: `result["merge_success"] = False`
3. Feed conflicting task_id back to PLAN
4. Planner is told: "These modules conflicted — keep them separate"
5. Do NOT leave repo in conflicted merge state

### Merge-Test Gate

After each child merge, before merging the next child:
- Run full test suite
- If tests break → enter DEBUG state, stop merging remaining children
- This catches integration bugs early (child A + child B work individually but break together)

## What to Copy vs Exclude

### MUST copy

| File/Pattern | Reason |
|-------------|--------|
| `PROJECT.md` | Child needs project spec |
| `*.py` (uncommitted source/test files) | Partial code from previous phases |
| `pyproject.toml`, `setup.cfg`, `tox.ini` | Build configuration |
| `requirements.txt`, `requirements*.txt` | Dependencies |
| `Makefile`, `Justfile` | Build commands |
| `README.md`, `*.md` (except `.sdlc/`) | Documentation |
| `config/*.yaml`, `config/*.json` | Configuration |
| `.gitignore` modifications | If orchestrator updated it |

### MUST exclude

| File/Pattern | Reason |
|-------------|--------|
| `.sdlc/**` | State files — orchestrator-internal, would bias child |
| `.git/**` | Git internals |
| `__pycache__/**`, `*.pyc` | Build artifacts |
| `.pytest_cache/**`, `.mypy_cache/**`, `.ruff_cache/**` | Tool caches |
| `*.egg-info/**` | Package metadata |
| `venv/**`, `.venv/**`, `env/**` | Virtual environments |
| `node_modules/**` | Node dependencies |
| `.env`, `.env.*` | Secrets |
| `*.log` | Log files |
| `.DS_Store` | macOS metadata |

## Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Patch doesn't apply | HIGH | LOW | Use HEAD for both diff and worktree add. Assert same commit hash. |
| Child inherits stale PROJECT.md | MEDIUM | MEDIUM | Acceptable — child was dispatched with a specific task |
| Rebase conflict on shared files | MEDIUM | MEDIUM | Planner ensures file-independence. Conflict → skip, feed back to PLAN |
| Integration bugs after parallel merges | HIGH | MEDIUM | Merge-test gate: run tests after EACH child merge |
| Orchestrator crash leaves orphaned worktrees | LOW | LOW | SIGINT/SIGTERM handler + startup cleanup |
| Large binary files in patch | MEDIUM | LOW | `--binary` flag, cap at 50MB, fall back to commit-based |
| Child process still running during cleanup | MEDIUM | LOW | `as_completed()` guarantees exit before cleanup |
| Empty repo | MEDIUM | LOW | Detect and create initial empty commit |
| Detached HEAD | LOW | LOW | Detect and refuse concurrent dispatch |
| Concurrent git operations on shared repo | HIGH | VERY LOW | All git ops are sequential in orchestrator's main thread |

## Design Decision: Worktrees Nested Inside Parent

Per user directive (2026-06-29): worktrees stay nested inside the parent project
directory, NOT moved to WORKTREE_ROOT or /tmp. The child worktree path is a
subdirectory of the parent project:

```
/opt/data/projects/<project>/
├── .git/                    # parent repo
├── src/                     # orchestrator's working files
├── .sdlc/                   # orchestrator state
└── worktrees/               # child worktrees (nested)
    └── parallel/<task-id>/  # child's isolated worktree
```

This keeps everything self-contained within the project directory. No separate
WORKTREE_ROOT, no /tmp leakage.
