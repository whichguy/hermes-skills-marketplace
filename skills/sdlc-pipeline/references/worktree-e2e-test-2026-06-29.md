# Worktree Uncommitted-State E2E Test Suite (2026-06-29)

10-test E2E suite validating the patch-file worktree workflow for concurrent
SDLC dispatch. All 10 tests pass. Test file: `/tmp/sdlc-worktree-e2e-test.py`
(455 lines).

## Test Structure

Each test creates a fresh git repo, simulates orchestrator state (uncommitted
changes, untracked files), captures state via `git diff HEAD --binary` +
`git ls-files --others --exclude-standard`, creates a child worktree from HEAD,
applies the patch + copies untracked files, auto-commits, simulates child work,
then merges back via rebase + merge.

Helper methods:
- `_capture_state(worktree)` → (patch_file, untracked_files, head_hash)
- `_create_child_worktree(head_hash, task_id)` → (wt_path, branch)
- `_apply_state_to_child(worktree, child_wt, patch_file, untracked, head_hash, task_id)`
- `_merge_child_back(worktree, child_wt, child_branch, base_ref=None)` — auto-detects branch
- `_cleanup_worktree(child_wt, child_branch)`

## Test Results (10/10 pass)

| # | Test | What It Validates |
|---|---|---|
| 1 | Uncommitted tracked file | `git diff HEAD --binary` captures modification; child inherits via `git apply --index` |
| 2 | Uncommitted untracked file | PROJECT.md + config.yaml copied to child via `shutil.copy2` |
| 3 | `.sdlc/` exclusion | `.sdlc/LEARNINGS.jsonl` and `.sdlc/STATUS.json` NOT copied; PROJECT.md IS copied |
| 4 | Empty patch | No uncommitted changes → empty patch handled gracefully; child still works |
| 5 | Failed child | No work produced → skip merge, cleanup worktree + branch |
| 6 | Concurrent children | Child A merges → Child B rebases onto updated parent → both merge clean |
| 7 | Child doesn't commit | Auto-commit catches uncommitted child work before rebase |
| 8 | Binary file | `--binary` flag handles binary diff correctly |
| 9 | Deleted file | `git apply` handles file deletion in patch |
| 10 | Child modifies inherited file | No conflict — child builds on top of inherited state |

## Bugs Found During Testing

### Bug 1: Hardcoded "main" branch (5 failures)
`git init` creates "master" by default. Tests 01, 04, 06, 07, 10 all failed
with `fatal: invalid upstream 'main'`. Fix: `_get_parent_branch()` uses
`git branch --show-current` dynamically. `_merge_child_back()` accepts
`base_ref=None` and auto-detects.

### Bug 2: Dirty working tree blocks merge (tests 01, 10)
`git merge` fails with "Your local changes would be overwritten by merge" when
the parent worktree has uncommitted changes. Fix: pre-merge auto-commit in
`_merge_child_back()` — `git add -A && git diff --cached --quiet || git commit -m "checkpoint: pre-merge state"`.
This is corner case M5 from DeepSeek's 37-corner-case analysis.

## Key Design Decisions Validated

1. **Patch file over git stash/commit** — doesn't mutate parent state or pollute history
2. **Rebase (not merge)** for pulling interim changes from other children
3. **Auto-commit child's uncommitted work** before rebase
4. **`.sdlc/` exclusion** — orchestrator-internal state stays out of child worktrees
5. **Pre-merge commit** — prevents dirty-working-tree merge failures
6. **HEAD hash validation** — ensures patch base matches child worktree base
7. **Binary-safe** — `--binary` flag handles non-text diffs
