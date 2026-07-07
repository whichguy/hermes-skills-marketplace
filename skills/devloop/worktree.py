"""worktree.py — minimal git-worktree isolation for devloop runs.

A real run edits code in an isolated git branch/worktree, so it cannot damage the user's working
tree. Checkouts live INSIDE the target repo at <repo>/.worktrees/ (user decision 2026-07-02 —
self-contained per repo), guaranteed invisible to the repo two ways: an immediate LOCAL
.git/info/exclude entry (never dirties tracked files — the dirty-guard below would otherwise
refuse every auto-merge), plus a `.worktrees/` line seeded into the CHECKOUT's tracked .gitignore
so it rides the run's commit into history on merge. devloop's own bookkeeping (.devloop/) is
hidden the same LOCAL way. On COMPLETE the branch AUTO-MERGES into the target's current branch
(merge_branch, fail-safe — user decision 2026-07-01); if the target ADVANCED past the run's fork
point, the combined tree is first re-verified in a throwaway sync checkout (user decision
2026-07-02) — any failure leaves the branch for review.

Lifecycle (deep review 2026-07-01): the BRANCH is the review artifact, the checkout is disposable.
`finalize` commits the run's work onto devloop/<name>, removes the checkout, and keeps the branch
only if it actually holds content ("no artifact -> no branch") — before this, nothing ever
committed (the enclosing repo's fail-closed .gitignore blinded `git status --porcelain` to every
created file), so branches were empty, checkouts held the only copy of the work, and both leaked
forever (41 of each at fix time).

Deliberately minimal (not a port of the legacy sdlc_worktree.py) — KISS.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import state

# Path segments that are tool debris, never the run's work product. Environments/caches matter
# because changed_files is DELIBERATELY gitignore-blind (fail-closed allowlist repos hide real
# work) — without these, a coder-created venv merges wholesale into the target (live acceptance
# catch 2026-07-02: 518 .venv files rode a COMPLETE into the target repo).
_JUNK_SEGMENTS = {".devloop", ".worktrees", "__pycache__", ".pytest_cache", ".ruff_cache", ".git",
                  ".venv", "venv", "node_modules", ".tox", ".nox", ".eggs", ".mypy_cache",
                  ".uv-cache"}

_WT_DIRNAME = ".worktrees"


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)


def _identity():
    """Commit identity for devloop-authored commits/merges, as `git -c` args. Env-overridable
    (DEVLOOP_GIT_NAME / DEVLOOP_GIT_EMAIL — production repos often attribute their automation);
    defaults unchanged."""
    return ("-c", f"user.email={os.environ.get('DEVLOOP_GIT_EMAIL', 'devloop@hermes')}",
            "-c", f"user.name={os.environ.get('DEVLOOP_GIT_NAME', 'devloop')}")


def default_root(repo):
    """Checkouts live INSIDE the target repo (user decision 2026-07-02): <repo>/.worktrees —
    self-contained per repo, and guaranteed ignored (see _ensure_locally_ignored)."""
    return os.path.join(repo, _WT_DIRNAME)


def _ensure_locally_ignored(repo):
    """Guarantee `.worktrees/` never shows up in the enclosing repo's status. If the repo doesn't
    already ignore it (tracked .gitignore, allowlist pattern, or a prior exclude entry), append it
    to .git/info/exclude — the LOCAL, non-committed ignore (merge_branch's dirty-guard would
    otherwise see the checkout as uncommitted work and refuse every auto-merge). Returns True if
    the repo ALREADY ignored it — callers then skip seeding the tracked .gitignore."""
    # Probe a CHILD path: dir-only patterns like ".worktrees/" never match the bare (not yet
    # existing) directory path itself, but always match anything under it.
    ignored = _git(repo, "check-ignore", "-q", "--", f"{_WT_DIRNAME}/probe",
                   check=False).returncode == 0
    if not ignored:
        excl = _git(repo, "rev-parse", "--git-path", "info/exclude", check=False).stdout.strip()
        if excl:
            if not os.path.isabs(excl):
                excl = os.path.join(repo, excl)
            Path(excl).parent.mkdir(parents=True, exist_ok=True)
            with open(excl, "a") as f:
                f.write(f"\n{_WT_DIRNAME}/\n")
    return ignored


def create_worktree(repo, name, root=None, base="HEAD"):
    """Create a worktree of `repo` at <root>/<name> on a new branch devloop/<name>.
    `root` defaults to <repo>/.worktrees (in-repo, user decision 2026-07-02); an explicit root is
    honored (tests, spike harnesses). Hides .devloop/ from the diff and guarantees `.worktrees/`
    is ignored (exclude now, tracked .gitignore via the run's own commit).
    Returns {path, branch, repo, base} — `base` is the resolved fork-point SHA that
    changed_files/finalize diff against."""
    root = root or default_root(repo)
    wt = os.path.join(root, name)
    branch = f"devloop/{name}"
    # Decide BEFORE writing our own exclude entry, else it would mask the answer.
    already_ignored = _ensure_locally_ignored(repo)
    # The branch we DERIVE from (merge_branch's expected_branch guard): if the checkout switches
    # branches mid-run, the COMPLETE work must not auto-merge into the wrong branch. Detached
    # HEAD records "" — merge_branch refuses detached targets on its own.
    start_branch = _git(repo, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip()
    Path(root).mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, wt, base)
    base_sha = _git(repo, "rev-parse", base, check=False).stdout.strip()
    # hide devloop bookkeeping from the diff/merge via a LOCAL (non-committed) ignore.
    # NOTE: for a linked worktree `info/exclude` resolves to the MAIN repo's SHARED file —
    # append idempotently, or every run grows the target repo's exclude by one more line
    # forever (live-caught 2026-07-03: 43 duplicate lines in a long-lived target repo).
    excl = _git(wt, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    if not os.path.isabs(excl):
        excl = os.path.join(wt, excl)
    try:
        existing = open(excl).read().splitlines()
    except OSError:
        existing = []
    if ".devloop/" not in existing:
        with open(excl, "a") as f:
            f.write("\n.devloop/\n")
    # seed_ignore: the repo does NOT ignore .worktrees yet, so finalize should seed the TRACKED
    # .gitignore as part of a CONTENTFUL commit (user ask 2026-07-02: the entry must reach
    # .gitignore, not just the local exclude). Decided here (before our exclude write above and
    # the checkout's shared view of it would mask the answer), applied in finalize — seeding at
    # create time would make every EMPTY run look contentful ("no artifact -> no branch" breaks).
    return {"path": wt, "branch": branch, "repo": repo, "base": base_sha,
            "start_branch": start_branch, "seed_ignore": not already_ignored}


def _junk(path: str) -> bool:
    return any(seg in _JUNK_SEGMENTS for seg in path.split("/"))


def changed_files(wt, base=None):
    """Files added/modified/deleted in the worktree vs `base` (the branch fork point; HEAD if
    omitted). Union of two sources:
      (a) `git diff --name-only <base>` — tracked changes, whether or not already committed;
      (b) `git ls-files --others` WITHOUT --exclude-standard — the enclosing repo's .gitignore
          can be fail-closed (a `/*` allowlist, the ~/.hermes shape), which made the old
          porcelain-based version blind to EVERY file a run creates ("changed 0 file(s)" on a
          successful build). Junk (tool caches, .devloop/) is filtered explicitly instead.
    Best-effort telemetry: a bad ref/repo yields [] rather than raising."""
    ref = base or "HEAD"
    tracked = _git(wt, "diff", "--name-only", ref, check=False).stdout.splitlines()
    untracked = _git(wt, "ls-files", "--others", check=False).stdout.splitlines()
    return sorted({p.strip() for p in (*tracked, *untracked) if p.strip() and not _junk(p.strip())})


def finalize(wt_info: dict, message: str) -> dict:
    """Commit the run's work onto the devloop/<name> branch, remove the checkout, and keep the
    branch only if it holds a commit beyond base. Returns
    {changed: [...], committed: bool, branch_kept: bool, worktree_removed: bool}.

    Fail-SAFE, never a failure path: if there is real work but the commit FAILS, the checkout is
    KEPT (it would otherwise be the only copy of the work) and the branch stays; an empty run
    ("no artifact") removes both checkout and branch so nothing accretes. Bridge runs can never
    resume (names are pid+ns unique), so a removed checkout loses nothing on the success path —
    the committed branch + the durable trace are the continuation artifacts."""
    out = {"changed": [], "committed": False, "branch_kept": False, "worktree_removed": False,
           "events": []}
    path, repo, branch = wt_info.get("path"), wt_info.get("repo"), wt_info.get("branch")
    base = wt_info.get("base")
    if not path or not repo or not os.path.isdir(path):
        return out
    try:
        changed = changed_files(path, base)
        if changed and wt_info.get("seed_ignore"):
            # The run produced real work and the repo doesn't ignore .worktrees yet: seed the
            # TRACKED .gitignore so the entry rides THIS commit into history on merge (user ask
            # 2026-07-02). Only on contentful runs — an empty run must stay branchless.
            gi = os.path.join(path, ".gitignore")
            existing = open(gi).read() if os.path.isfile(gi) else ""
            if f"{_WT_DIRNAME}/" not in existing.splitlines():
                with open(gi, "a") as f:
                    f.write(f"{_WT_DIRNAME}/\n")
            changed = sorted({*changed, ".gitignore"})
        out["changed"] = changed
        if changed:
            _git(path, "add", "-f", "--", *changed, check=False)   # -f: past the repo's fail-closed .gitignore
            r = _git(path, *_identity(),
                     "commit", "-qm", message, check=False)
            out["committed"] = r.returncode == 0
            out["events"].append(state.ev(
                "finalize", "commit", "info" if out["committed"] else "error",
                rc=r.returncode,
                detail="" if out["committed"] else (r.stderr or r.stdout).strip()[:200],
                outcome=str(out["committed"])))
            if not out["committed"]:
                # real work + failed commit -> the checkout is the ONLY copy; keep everything.
                out["branch_kept"] = bool(branch)
                if out["branch_kept"]:
                    out["events"].append(state.ev("finalize", "branch-kept", "info",
                                                  detail=base or branch))
                return out
        if os.environ.get("DEVLOOP_KEEP_WORKTREE") == "1":
            # Post-mortem knob (user ask 2026-07-03): keep the EXACT tree the run produced for
            # inspection. Documented debris — the user removes it; branch semantics unchanged.
            out["worktree_removed"] = False
        else:
            remove_worktree(repo, path)
            out["worktree_removed"] = not os.path.isdir(path)
        if branch:
            head = _git(repo, "rev-parse", branch, check=False).stdout.strip()
            if head and base and head != base:
                out["branch_kept"] = True          # content -> the branch IS the review artifact
                out["events"].append(state.ev("finalize", "branch-kept", "info", detail=head))
            else:
                _git(repo, "branch", "-D", branch, check=False)   # no artifact -> no branch
                out["events"].append(state.ev("finalize", "branch-deleted", "info",
                                              detail="no artifact -> no branch"))
    except Exception:  # noqa: BLE001 — cleanup/telemetry must never fail the run that produced the result
        pass
    return out


# Test files are the ORACLE at merge time too: an LLM resolver/fixer may never rewrite them
# (same forged-green defense as the loop's frozen-tests gate, enforced here in code).
_TEST_FILE_RE = re.compile(r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.py)$")


def _test_files_snapshot(path):
    """{relpath: content-bytes} of every test file under `path` (junk dirs skipped) — the
    merge-layer frozen-tests snapshot taken before any LLM touches the tree."""
    snap = {}
    for dirpath, dirnames, files in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _JUNK_SEGMENTS]
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), path)
            if _TEST_FILE_RE.search(rel.replace(os.sep, "/")):
                try:
                    snap[rel] = open(os.path.join(path, rel), "rb").read()
                except OSError:
                    pass
    return snap


def _restore_test_files(path, snap):
    """Put the snapshotted test files back exactly as they were (LLM edits to tests are undone,
    never trusted). Returns the relpaths that had to be restored."""
    restored = []
    for rel, body in snap.items():
        fp = os.path.join(path, rel)
        try:
            cur = open(fp, "rb").read() if os.path.isfile(fp) else None
        except OSError:
            cur = None
        if cur != body:
            Path(fp).parent.mkdir(parents=True, exist_ok=True)
            with open(fp, "wb") as f:
                f.write(body)
            restored.append(rel)
    return restored


def _resolve_conflicts(path, resolver):
    """LLM-assisted conflict resolution (user decision 2026-07-02: leverage the LLM to do the
    merge / fix merge issues) — with CODE-enforced guards, the model's claim is never trusted:
      * conflicts touching TEST files -> refuse (tests are the oracle; a resolver rewriting them
        is the forged-green hole);
      * after the resolver: every previously-conflicted file must exist with NO conflict markers,
        the index must hold no unmerged entries, and the merge commit must succeed;
      * any resolver crash/refusal -> refuse.
    Returns (ok, why, events). The caller aborts the merge on not-ok."""
    events = []
    conflicted = [ln.strip() for ln in
                  _git(path, "diff", "--name-only", "--diff-filter=U", check=False).stdout.splitlines()
                  if ln.strip()]
    if resolver is None or not conflicted:
        events.append(state.ev("conflict", "resolver-unavailable", "warn"))
        return False, "sync conflict with advanced target — branch left for review", events
    if any(_TEST_FILE_RE.search(p.replace(os.sep, "/")) for p in conflicted):
        why = ("sync conflict touches TEST files (tests are the oracle — the resolver may "
               "not rewrite them); branch left for review")
        events.append(state.ev("conflict", "test-file-touch", "warn", detail=why))
        return False, why, events
    frozen = _test_files_snapshot(path)
    try:
        claimed = resolver(path, conflicted)
    except Exception as e:  # noqa: BLE001 — a crashed resolver must refuse, never crash past the guard
        why = f"conflict resolver crashed: {type(e).__name__}: {e} — branch left for review"
        events.append(state.ev("conflict", "resolver-crashed", "error", detail=str(e)[:300]))
        return False, why, events
    if not claimed:
        why = "conflict resolver failed — branch left for review"
        events.append(state.ev("conflict", "resolver-refused", "warn", detail=why))
        return False, why, events
    if _restore_test_files(path, frozen):
        why = "conflict resolver modified TEST files (restored) — branch left for review"
        events.append(state.ev("conflict", "test-files-modified", "warn", detail=why))
        return False, why, events
    for p in conflicted:
        fp = os.path.join(path, p)
        if not os.path.isfile(fp):
            why = f"resolver deleted conflicted file {p} — branch left for review"
            events.append(state.ev("conflict", "conflicted-file-deleted", "warn", detail=p))
            return False, why, events
        body = open(fp, encoding="utf-8", errors="replace").read()
        if "<<<<<<<" in body or ">>>>>>>" in body:
            why = f"conflict markers remain in {p} — branch left for review"
            events.append(state.ev("conflict", "markers-remain", "warn", detail=p))
            return False, why, events
    _git(path, "add", "-f", "--", *conflicted, check=False)
    if _git(path, "ls-files", "-u", check=False).stdout.strip():
        why = "unresolved index entries remain after resolution — branch left for review"
        events.append(state.ev("conflict", "unresolved-index", "warn", detail=why))
        return False, why, events
    c = _git(path, *_identity(),
             "commit", "-q", "--no-edit", check=False)
    if c.returncode != 0:
        detail = (c.stderr or c.stdout).strip()[:200]
        events.append(state.ev("conflict", "resolution-commit", "error",
                               rc=c.returncode, detail=detail))
        return False, (f"resolution commit failed: {detail} — branch left for review"), events
    events.append(state.ev("conflict", "resolution-commit", "info", rc=c.returncode))
    return True, "", events


def _sync_and_verify(repo, branch, target_tip, regression_check, resolver=None, fixer=None):
    """PRE-MERGE SYNC (user decision 2026-07-02): the target branch ADVANCED past the run's fork
    point, so the combined tree was never verified. Merge the target tip INTO the run branch in a
    throwaway checkout and re-run the whole-suite `regression_check(path) -> (ok, reason)` there.
    A conflict goes to the LLM `resolver` (guarded, _resolve_conflicts); a red combined tree gets
    ONE bounded LLM `fixer` attempt — after which the regression gate re-runs and REMAINS the
    decider (the LLM never self-certifies). Returns (ok, why, notes) with notes ⊆
    {resolved, fixed}. FAIL-SAFE at every exit: an unresolved conflict is aborted (never a
    conflicted tree), a finally-red tree strips the sync commits (`reset --hard` to the pre-sync
    SHA — the review branch stays exactly the run's verified work), and the checkout is always
    removed."""
    notes = {"resolved": False, "fixed": False, "events": []}
    _ensure_locally_ignored(repo)
    root = default_root(repo)
    path = os.path.join(root, branch.rsplit("/", 1)[-1] + "-sync")
    pre = _git(repo, "rev-parse", branch, check=False).stdout.strip()
    # idempotent pre-clean (spike lesson): a stale path/registration from an aborted prior sync
    _git(repo, "worktree", "remove", "--force", path, check=False)
    _git(repo, "worktree", "prune", check=False)
    Path(root).mkdir(parents=True, exist_ok=True)
    r = _git(repo, "worktree", "add", path, branch, check=False)
    if r.returncode != 0:
        notes["events"].append(state.ev("sync", "checkout", "error", rc=r.returncode,
                                        detail=(r.stderr or r.stdout).strip()[:200]))
        return False, (f"sync checkout failed: {(r.stderr or r.stdout).strip()[:200]} — "
                       "branch left for review"), notes
    try:
        m = _git(path, *_identity(),
                 "merge", "--no-ff", "-m", f"devloop: sync target into {branch}",
                 target_tip, check=False)
        if m.returncode != 0:
            notes["events"].append(state.ev("sync", "merge-target", "warn",
                                            rc=m.returncode,
                                            detail=(m.stderr or m.stdout).strip()[:200]))
            ok, why, resolver_events = _resolve_conflicts(path, resolver)
            notes["events"].extend(resolver_events)
            if not ok:
                _git(path, "merge", "--abort", check=False)   # sync conflict: no conflicted tree, ever
                return False, why, notes
            notes["resolved"] = True
        else:
            notes["events"].append(state.ev("sync", "merge-target", "info",
                                            rc=m.returncode))
        try:
            ok, why = regression_check(path)
        except Exception as e:  # noqa: BLE001 — a broken check must FAIL the sync, not crash past it
            ok, why = False, f"regression check crashed: {type(e).__name__}: {e}"
        notes["events"].append(state.ev("sync", "regression-check", "info" if ok else "warn",
                                        detail=why))
        if not ok and fixer is not None:
            notes["events"].append(state.ev("sync", "fixer-attempted", "info", detail=why))
            # ONE bounded fix attempt on the combined tree (user decision 2026-07-02); LLM edits
            # to test files are restored before the re-check — the oracle stays the oracle.
            frozen = _test_files_snapshot(path)
            try:
                attempted = fixer(path, str(why))
            except Exception:  # noqa: BLE001 — a crashed fixer just leaves the red verdict standing
                attempted = False
            if attempted:
                _restore_test_files(path, frozen)
                _git(path, "add", "-A", check=False)
                c = _git(path, *_identity(),
                         "commit", "-qm", f"devloop: post-sync fix for {branch}", check=False)
                if c.returncode != 0:
                    notes["events"].append(state.ev(
                        "sync", "fixer-commit", "error", rc=c.returncode,
                        detail=(c.stderr or c.stdout).strip()[:200]))
                    ok, why = False, ("post-sync fix commit failed — the fix never landed on "
                                      f"the branch; refusing: {(c.stderr or c.stdout).strip()[:200]}")
                else:
                    notes["events"].append(state.ev("sync", "fixer-commit", "info",
                                                    rc=c.returncode))
                    try:
                        ok, why = regression_check(path)   # the GATE decides, not the fixer's claim
                    except Exception as e:  # noqa: BLE001
                        ok, why = False, f"regression check crashed: {type(e).__name__}: {e}"
                    notes["events"].append(state.ev(
                        "sync", "regression-recheck", "info" if ok else "warn", detail=why))
                    notes["fixed"] = ok
        if not ok:
            # strip the sync/fix commits: the branch-for-review is the run's VERIFIED work only
            _git(path, "reset", "--hard", pre, check=False)
            notes["events"].append(state.ev("sync", "reset-strip", "warn", detail=why))
            return False, (f"combined tree failed regression: {str(why)[:300]} — "
                           "branch left for review"), notes
        return True, "", notes
    finally:
        _git(repo, "worktree", "remove", "--force", path, check=False)


def merge_branch(repo: str, branch: str, base: str | None = None,
                 regression_check=None, resolver=None, fixer=None,
                 expected_branch: str | None = None,
                 commit_message: str | None = None) -> dict:
    """AUTO-MERGE a COMPLETE run's branch into the repo's CURRENT branch (user decision
    2026-07-01: COMPLETE means every gate passed — coverage + 2 judges + evidence +
    frozen-tests + whole-suite regression — so the code merges without a manual review step).
    Returns {merged: bool, synced: bool, resolved: bool, fixed: bool, reason: str,
    target: str|None}.

    `base` is the run's fork-point SHA (wt_info["base"]); when the target tip has moved past it
    (or `base` is unknown), the combined tree must be re-verified via `regression_check` before
    any merge (_sync_and_verify — user decision 2026-07-02). No `regression_check` in that
    situation -> REFUSE: a stray caller can't merge unverified combinations (fail-closed).
    `resolver`/`fixer` are optional LLM callables (user decision 2026-07-02) for conflict
    resolution and one bounded red-tree fix — both guarded in code, both decided by the
    regression gate, never by the model's claim.

    `expected_branch` is the branch the run DERIVED from (wt_info["start_branch"]): when
    provided and the target's current branch differs, the merge is refused — a checkout that
    switched branches mid-run must never receive the work (user requirement 2026-07-03).
    Landing is lock-free: the squash is committed via `git commit-tree`, parented on the
    verified `tip`, and published with atomic `git update-ref <ref> <new> <tip>` compare-and-swap.
    A concurrent devloop merge or foreign write that moved HEAD off `tip` makes the CAS refuse
    (rc 128) and leaves the branch for review — no held lock, no timeout.

    FAIL-SAFE by construction — a failed merge degrades to branch-for-review, never worse:
      * detached HEAD            -> refuse (no current branch to merge into);
      * target branch != expected -> refuse (checkout switched branches mid-run);
      * dirty target tree        -> refuse WITHOUT attempting (full porcelain incl. untracked —
                                    an in-flight merge over uncommitted work can clobber it);
      * advanced target          -> sync + re-verify first; conflict or red -> refuse, branch
                                    stays at the run's verified SHA;
      * merge conflict           -> hard reset back to the pre-merge state (a conflicted
                                    SQUASH has no MERGE_HEAD for `merge --abort`; the
                                    dirty-guard above guarantees the tree was clean, so the
                                    reset is exactly "undo the attempt") + the branch
                                    survives for review (race-only once synced);
      * success                  -> ONE SQUASH commit landed via `git commit-tree` (parented on
                                    verified `tip`) + atomic `git update-ref <ref> <new>
                                    <expected-old>` CAS; if the ref left `tip`, CAS refuses and
                                    leaves the branch for review. Then `branch -D`,
                                    gated on the squash commit having actually LANDED
                                    (squashed content is never an ancestor, so `-d` would
                                    always refuse and leak the branch; the explicit
                                    landed-check replaces that old free fail-safe).
    """
    out = {"merged": False, "synced": False, "resolved": False, "fixed": False,
           "reason": "", "target": None, "events": []}
    cur = _git(repo, "symbolic-ref", "--short", "HEAD", check=False)
    if cur.returncode != 0:
        out["events"].append(state.ev("merge", "detached-head", "warn"))
        out["reason"] = "target HEAD is detached; branch left for review"
        return out
    out["target"] = cur.stdout.strip()
    if expected_branch and out["target"] != expected_branch:
        out["events"].append(state.ev("merge", "branch-switched", "warn",
                                      detail=f"expected={expected_branch} actual={out['target']}"))
        out["reason"] = (f"target switched from '{expected_branch}' to '{out['target']}' "
                         "mid-run — merge not attempted; branch left for review")
        return out
    if _git(repo, "status", "--porcelain", check=False).stdout.strip():
        out["events"].append(state.ev("merge", "dirty-target", "warn"))
        out["reason"] = "target tree dirty — merge not attempted; branch left for review"
        return out
    bh = _git(repo, "rev-parse", branch, check=False).stdout.strip()
    if base and bh == base:
        out["events"].append(state.ev("merge", "no-content", "warn"))
        out["reason"] = ("branch has no commits beyond its fork point — nothing to merge; "
                         "refusing (an empty squash would false-report merged)")
        return out
    tip = _git(repo, "rev-parse", "HEAD", check=False).stdout.strip()
    if not base or tip != base:   # target advanced (or fork point unknown) -> re-verify combined tree
        out["events"].append(state.ev(
            "merge", "target-advanced", "info",
            detail=f"base={base[:8] if base else 'none'} tip={tip[:8] if tip else 'none'}"))
        if regression_check is None:
            out["events"].append(state.ev("merge", "sync-refused", "warn",
                                          detail="sync unavailable"))
            out["reason"] = ("target advanced past run base; sync unavailable — "
                             "branch left for review")
            return out
        ok, why, notes = _sync_and_verify(repo, branch, tip, regression_check,
                                          resolver=resolver, fixer=fixer)
        sync_events = notes.pop("events", [])
        out["events"].extend(sync_events)
        if not ok:
            out["events"].append(state.ev("merge", "sync-refused", "warn", detail=why))
        out.update(notes)
        if not ok:
            out["reason"] = why
            return out
        out["synced"] = True
    else:
        out["events"].append(state.ev("merge", "fast-path", "info",
                                      detail="fast-path (tip==base)"))
    r = _git(repo, "merge", "--squash", branch, check=False)
    for _ in range(2):   # bounded retry ONLY for index.lock contention: a FOREIGN git op in
        # flight (devloop-vs-devloop no longer serializes here — the ref-CAS below is the
        # only serialization; this retry just rides out git's own transient index.lock)
        if r.returncode == 0 or "index.lock" not in ((r.stderr or "") + (r.stdout or "")):
            break
        time.sleep(0.5)
        r = _git(repo, "merge", "--squash", branch, check=False)
    if r.returncode != 0:
        # fail-SAFE: never leave a conflicted/staged tree. A conflicted squash has no
        # MERGE_HEAD (`merge --abort` errors), but the dirty-guard above proved the tree
        # was clean pre-attempt, so a hard reset is exactly "undo the attempt".
        _git(repo, "reset", "--hard", "-q", check=False)
        out["reason"] = f"merge failed: {(r.stderr or r.stdout).strip()[:200]}"
        out["events"].append(state.ev("merge", "squash", "error", rc=r.returncode,
                                      detail=(r.stderr or r.stdout).strip()[:200]))
        return out
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        # empty delta: the branch's content is already contained in the target (post-sync
        # edge) — nothing to commit, and an empty squash commit would be noise
        out["reason"] = "squash produced no delta (work already contained in target)"
        out["events"].append(state.ev("merge", "empty-delta", "info"))
    else:
        # CAS LANDING — git's atomic ref compare-and-swap replaces the held lock + the
        # tip-reverify: capture the squashed tree, build a commit parented on `tip` (the
        # HEAD we verified the combined tree against), and move the branch ref ONLY IF it
        # still points at `tip`. `git update-ref <ref> <new> <expected-old>` is atomic —
        # a concurrent devloop merge or a foreign (cron) write that moved HEAD off `tip`
        # makes it fail with rc 128 ("is at X but expected Y") and leaves the ref
        # untouched. We then undo the staged squash and leave the branch for review. On
        # success the index+worktree already hold exactly `new`'s tree (the squash we just
        # staged), so HEAD/index/worktree reconcile with no reset needed.
        tree = _git(repo, "write-tree", check=False).stdout.strip()
        ct = _git(repo, *_identity(), "commit-tree", tree, "-p", tip,
                  "-m", commit_message or f"devloop: squash-merge {branch}", check=False)
        new = ct.stdout.strip()
        if not new:
            _git(repo, "reset", "--hard", "-q", check=False)   # undo the staged squash
            detail = (ct.stderr or ct.stdout).strip()[:200]
            out["reason"] = f"squash commit failed: {detail or 'commit-tree produced no commit'}"
            out["events"].append(state.ev("merge", "squash-commit", "error",
                                          rc=ct.returncode, detail=detail))
            return out
        cas = _git(repo, "update-ref", f"refs/heads/{out['target']}", new, tip, check=False)
        if cas.returncode != 0:
            # the ref update failed. Undo the staged squash and leave the branch for review.
            _git(repo, "reset", "--hard", "-q", check=False)
            err = (cas.stderr or cas.stdout).strip()
            if "expected" in err:
                # git's compare-and-swap mismatch ("is at X but expected Y"): HEAD moved off
                # the verified tip (a concurrent devloop merge or a foreign write).
                out["reason"] = ("target HEAD moved before the merge could land (a concurrent "
                                 "write) — merge not attempted; branch left for review")
                out["events"].append(state.ev("merge", "tip-moved", "warn", detail=err[:200]))
            else:
                # a non-CAS ref-update failure (permission, ref lock, invalid object): report
                # it honestly rather than mislabeling it as a tip move.
                out["reason"] = f"ref update failed: {err[:200]} — branch left for review"
                out["events"].append(state.ev("merge", "ref-update-failed", "error",
                                              rc=cas.returncode, detail=err[:200]))
            return out
        out["events"].append(state.ev("merge", "squash-commit", "info", rc=cas.returncode))
    # the squash commit LANDED (or there was provably nothing to land) -> -D is safe;
    # squashed content is never an ancestor, so -d would always refuse and leak the branch
    _git(repo, "branch", "-D", branch, check=False)
    deleted = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                   check=False)
    if deleted.returncode == 0:
        out["leaked_branch"] = branch
        out["reason"] += "; branch deletion failed — branch leaked, delete manually"
        out["events"].append(state.ev("merge", "branch-delete", "warn", detail=branch))
    else:
        out["events"].append(state.ev("merge", "branch-delete", "info", detail=branch))
    out["merged"] = True
    return out


def remove_worktree(repo, wt):
    """Tear down the worktree checkout (best-effort; leaves the branch)."""
    _git(repo, "worktree", "remove", "--force", wt, check=False)
