# Kimi Git/Code Review — v3.1 Concurrent Dispatch Design (2026-06-29)

**Model:** kimi-k2.7-code:cloud  
**Duration:** 395.5s  
**Output:** 14,584 chars, 320 lines  
**Verdict:** APPROVE WITH CHANGES — 14 issues (2 HIGH, 8 MEDIUM, 4 LOW)

## Scope

Kimi reviewed the `dispatch_parallel_isolated()` function in the v3.1 concurrent dispatch design doc, plus `sdlc_worktree.py` source and DeepSeek's 37-corner-case analysis. Focus: git command correctness, corner conditions, and Python code quality.

## HIGH Severity (must fix before implementation)

### H1: Missing imports — `uuid`, `os`, `subprocess` used without import
`run_id = uuid.uuid4().hex[:8]` is called but `import uuid` is not shown. `subprocess` and `os` also used without imports. If the surrounding module doesn't already import them, first call crashes with `NameError`.

**Fix:** Add imports at function top:
```python
def dispatch_parallel_isolated(...):
    import concurrent.futures
    import fnmatch
    import os
    import shutil
    import subprocess
    import tempfile
    import uuid
```

### H2: Worktree leak on early exception
The `finally` block only cleans worktrees found in `results.items()`. If an exception fires after N worktrees are created but before they're dispatched (e.g., HEAD mismatch on Nth child), the first N-1 worktrees are in `created_worktrees` but never in `results`, so they're never removed.

**Fix:** Track removed worktrees and sweep `created_worktrees` in `finally`:
```python
created_worktrees = []
removed_worktrees = set()

finally:
    # existing per-result cleanup
    for tid, result in results.items():
        ...
        if wt_path:
            try:
                remove_worktree(wt_path)
                removed_worktrees.add(wt_path)
            except Exception:
                pass

    # catch any worktree created before an early exception
    for wt_path in created_worktrees:
        if wt_path not in removed_worktrees:
            try:
                remove_worktree(wt_path)
                removed_worktrees.add(wt_path)
            except Exception:
                pass
```

## MEDIUM Severity (should fix before implementation)

### M1: Mid-rebase detection uses hardcoded `.git/` paths
In linked worktrees, `.git` is a file, not a directory. State is stored under `.git/worktrees/<name>/`. Hardcoded paths miss in-progress rebases.

**Fix:** Use `git rev-parse --git-path`:
```python
for state_name in ["rebase-merge", "rebase-apply", "MERGE_HEAD"]:
    path_r = subprocess.run(
        ["git", "rev-parse", "--git-path", state_name],
        cwd=worktree, capture_output=True, text=True, timeout=10
    )
    state_path = path_r.stdout.strip()
    if state_path and os.path.exists(state_path):
        raise RuntimeError(f"Cannot dispatch: git is in mid-rebase/merge state ({state_name})")
```

### M2: File handle leak in patch application
`subprocess.run(..., stdin=open(patch_file, 'rb'))` called for every child — `subprocess.run` doesn't close the file object, leaking a handle per child.

**Fix:** Read patch once, pass via `input=`:
```python
with open(patch_file, 'rb') as f:
    patch_bytes = f.read()

for i, task in enumerate(tasks):
    if patch_bytes:
        apply_r = subprocess.run(
            ["git", "apply", "--index"],
            cwd=wt_path, input=patch_bytes,
            capture_output=True, text=True, timeout=30,
        )
```

### M3: Untracked files ignored by inherited `.gitignore`
Patch is applied before untracked files are copied. If patch modifies `.gitignore`, `git add -A` silently skips now-ignored files.

**Fix:** Use `git add -f -A` (force-add):
```python
subprocess.run(["git", "add", "-f", "-A"], cwd=wt_path, capture_output=True, timeout=10)
```

### M4: Exclude pattern overmatch — `.sdlc/` catches `.sdlc_backup/`
`f.startswith(pat.rstrip('/'))` for `.sdlc/` matches `.sdlc_backup/foo`.

**Fix:** Use helper that checks trailing slash:
```python
UNTRACKED_EXCLUDE = [
    '.sdlc/', '__pycache__/', '*.pyc', '.pytest_cache/',
    '.mypy_cache/', '.ruff_cache/', '*.egg-info/',
    'venv/', '.venv/', 'env/', 'node_modules/',
    '.env', '.env.*', '*.log', '.DS_Store',
]

def _is_excluded(path: str, pattern: str) -> bool:
    if pattern.endswith('/'):
        return path.startswith(pattern) or path.startswith(pattern.rstrip('/') + '/')
    return fnmatch.fnmatch(path, pattern)
```

### M5: Silent git failures — many returncodes unchecked
`subprocess.run` called without `check=True`; if `git commit` fails (missing user.name, gpg sign failure), function silently continues with dirty worktree.

**Fix:** Add `_git_or_raise()` helper:
```python
def _git_or_raise(cmd, cwd, timeout=10, ignore_nothing=False):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr or "").lower()
        if ignore_nothing and ("nothing to commit" in err or "nothing added" in err):
            return r
        raise RuntimeError(f"git {' '.join(cmd)} failed in {cwd}: {r.stderr}")
    return r
```

### M6: `git rebase --continue` returncode ignored
After resolving `.sdlc/` conflicts, `git rebase --continue` is called but returncode unchecked. If it fails, code falls through to `git merge` while still mid-rebase.

**Fix:** Check continue result, abort + fail on error:
```python
continue_r = subprocess.run(
    ["git", "rebase", "--continue"], cwd=wt_path,
    capture_output=True, text=True, timeout=30
)
if continue_r.returncode != 0:
    subprocess.run(["git", "rebase", "--abort"], cwd=wt_path, capture_output=True, timeout=10)
    result["merge_success"] = False
    result["merge_conflicts"] = continue_r.stderr or "rebase --continue failed"
    failed_tids.append(tid)
    try:
        remove_worktree(wt_path)
    except Exception:
        pass
    continue
```

### M7: Child branch not deleted after merge
`remove_worktree()` removes the worktree directory but not the git branch. Merged child branches accumulate and can collide.

**Fix:** Delete branch after successful merge:
```python
if merge_r.returncode == 0:
    result["merge_success"] = True
    subprocess.run(
        ["git", "branch", "-d", child_branch],
        cwd=worktree, capture_output=True, timeout=10
    )
```

### M8: `_merge_failures` key collision
If a planner emits `task_id="_merge_failures"`, the task result and metadata list collide.

**Fix:** Use namespaced key:
```python
_MERGE_FAILURES_KEY = "__sdlc_merge_failures__"
results[_MERGE_FAILURES_KEY] = failed_tids
```

## LOW Severity

| # | Issue | Fix |
|---|---|---|
| L1 | Dead variable `branch_name` computed but never used | Remove it |
| L2 | `shutil.copy2` follows symlinks instead of preserving | Check `os.path.islink()` + `os.symlink()` |
| L3 | Task dicts mutated in place (caller's dicts modified) | Shallow-copy each task: `task = dict(task)` |
| L4 | No patch size cap (DeepSeek C9/E6) | Cap at 50MB, fallback to commit-based |

## Verified Correct ✅

Kimi confirmed 14 items are correct:
- `git diff HEAD --binary` captures staged + unstaged + binary + deletions
- `git apply --index` works on fresh worktree
- HEAD hash assertion is correct
- Pre-merge commit correctly placed per-child (not before loop)
- `git rebase base_ref` works when `base_ref` is the parent branch
- Sequential merges in `finally` block are guaranteed (no concurrent merge race)
- `git merge --no-ff child_branch` from parent worktree is correct
- Worktree paths with spaces handled safely (list args + os.path.join)
- `.gitignore` changes applied via patch work correctly
- Empty-patch guard `os.path.getsize > 0` correctly skips `git apply`
- Auto-commit after apply captures both patched + copied files
- After successful rebase, `git branch --show-current` still returns child's branch
- `git merge --abort` only called after merge failure (merge in progress)
- `remove_worktree(wt_path)` safe after branch merged (but doesn't delete branch)

## Top 3 Fixes

1. **H2** — Close the created-worktree cleanup gap in `finally`
2. **H1** — Add missing imports (`import uuid` before `run_id = uuid.uuid4().hex[:8]`)
3. **M1** — Fix mid-rebase/merge detection to use `git rev-parse --git-path`
