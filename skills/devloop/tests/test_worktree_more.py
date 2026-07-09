"""More deterministic worktree tests — a REAL git repo, no LLM.

Closes two confirmed coverage gaps the base test_worktree.py misses:
  * the LOCAL info/exclude ignore must be APPENDED (additive), never truncated —
    a pre-existing user pattern in the shared exclude must survive create_worktree;
  * the `base` commit-ish is actually passed to `git worktree add`, so a non-default
    base anchors the worktree at the requested commit (not HEAD).
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import worktree  # noqa: E402
import state  # noqa: E402


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], check=check, capture_output=True, text=True)


def _init_repo(repo):
    """A fresh git repo with one committed a.py == 'x = 1\\n'."""
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "x")
    open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")


def _resolve_exclude(wt_path):
    """The info/exclude path as git resolves it from inside the worktree (shared common dir)."""
    excl = subprocess.run(
        ["git", "-C", wt_path, "rev-parse", "--git-path", "info/exclude"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not os.path.isabs(excl):
        excl = os.path.join(wt_path, excl)
    return excl


def test_create_worktree_appends_to_local_exclude_preserving_existing():
    """info/exclude is opened in APPEND mode — a pre-existing local ignore must SURVIVE.
    Kills the `open(excl, "w")` truncation mutant: 'w' wipes the user's prior patterns
    (silent data loss) while still writing .devloop/, so the base suite stays green."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        # seed a pre-existing LOCAL ignore in the shared common-dir exclude BEFORE the worktree
        with open(os.path.join(repo, ".git", "info", "exclude"), "a") as f:
            f.write("keepme-sentinel/\n")

        wt = worktree.create_worktree(repo, "t1", os.path.join(root, "wts"))

        content = open(_resolve_exclude(wt["path"])).read()
        assert "keepme-sentinel/" in content    # pre-existing local ignore SURVIVES (kills 'w')
        assert ".devloop/" in content           # control: our additive ignore was still written


def test_create_worktree_checks_out_requested_base_not_head():
    """The `base` arg is forwarded to `git worktree add`, anchoring the worktree at that
    commit. Kills the dropped-`base` mutant which silently defaults to HEAD."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)                                            # commit 1: a.py == 'x = 1\n'
        base = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        open(os.path.join(repo, "a.py"), "w").write("x = 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "second")                       # commit 2 (HEAD): 'x = 2\n'

        # explicit base -> the OLD commit's content
        wt = worktree.create_worktree(repo, "b1", os.path.join(root, "wts"), base=base)
        assert open(os.path.join(wt["path"], "a.py")).read() == "x = 1\n"   # kills dropped base

        # control: the DEFAULT base (HEAD) yields the NEW content — proves base actually selects
        wt_head = worktree.create_worktree(repo, "b2", os.path.join(root, "wts"))
        assert open(os.path.join(wt_head["path"], "a.py")).read() == "x = 2\n"


# --- the devloop/<name> branch must SURVIVE remove_worktree (checkout disposable, branch isn't) ---
def test_remove_worktree_leaves_branch_for_review():
    # cardinal contract: remove_worktree tears down the CHECKOUT only — the branch is the artifact
    # every fallback relies on (auto-merge degrades to branch-for-review on dirty/conflict/detached
    # targets; HUMAN_REVIEW keeps partial work on it). A future 'cleanup' adding `git branch -D`
    # would pass every other assertion (path gone) yet silently destroy unrecoverable work. This
    # pins the branch's survival across teardown.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        wt = worktree.create_worktree(repo, "t1", os.path.join(root, "wts"))
        branch = subprocess.run(["git", "-C", repo, "branch", "--list", "devloop/t1"],
                                capture_output=True, text=True).stdout.strip()
        assert branch != ""                                         # branch created
        worktree.remove_worktree(repo, wt["path"])
        assert not os.path.exists(wt["path"])                       # working tree gone
        survived = subprocess.run(["git", "-C", repo, "branch", "--list", "devloop/t1"],
                                  capture_output=True, text=True).stdout.strip()
        assert survived != ""                                       # but the BRANCH remains for review


# --- merge_branch: fail-safe auto-merge (2026-07-01) + pre-merge sync (2026-07-02) --------------
def _rev(repo, ref):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", ref],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _porcelain(repo):
    return subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                          capture_output=True, text=True).stdout.strip()


def _green(path):
    return True, ""


def _wt_with_work(root, name="m1", content="y = 2\n", fname="b.py"):
    """A finalized contentful run branch. Returns (repo, branch, base_sha)."""
    repo = os.path.join(root, "repo")
    if not os.path.isdir(repo):
        _init_repo(repo)
    wt = worktree.create_worktree(repo, name, os.path.join(root, "wts"))
    open(os.path.join(wt["path"], fname), "w").write(content)
    fin = worktree.finalize(wt, f"devloop COMPLETE: {name}")
    assert fin["committed"] and fin["branch_kept"]
    return repo, wt["branch"], wt["base"]


def test_merge_branch_happy_fast_path_merges_deletes_branch():
    # Target tip == run base -> NO sync (the tree was already verified as-is): regression_check
    # must not run, the work lands as ONE SQUASH commit (user decision 2026-07-03: no worktree
    # commit noise, no merge commit), the branch is deleted.
    # Mutants killed: merge-skipped; merged=True-on-failure.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        calls = []
        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=lambda p: calls.append(p) or (True, ""))
        assert out["merged"] is True and out["target"]
        assert out["synced"] is False and calls == []                    # fast path: no re-verify
        assert open(os.path.join(repo, "b.py")).read() == "y = 2\n"      # code LANDED
        log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        assert "devloop: squash-merge" in log                            # ONE squash commit
        assert "devloop COMPLETE" not in log                             # no worktree-commit noise
        merges = subprocess.run(["git", "-C", repo, "log", "--merges", "--oneline"],
                                capture_output=True, text=True).stdout
        assert merges.strip() == ""                                      # and NO merge commit
        assert _rev(repo, branch)[0] != 0                                # branch deleted


def test_merge_branch_cas_landing_parents_tip_single_parent_and_clean_tree():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        _, tip = _rev(repo, "HEAD")

        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)

        assert out["merged"] is True and not out["reason"]
        assert _rev(repo, "HEAD^") == (0, tip)
        assert _rev(repo, "HEAD^2")[0] != 0
        message = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "squash-merge" in message
        assert _porcelain(repo) == ""
        assert _rev(repo, branch)[0] != 0


def test_merge_branch_cas_landing_sync_path_leaves_clean_tree():
    """The CAS landing reconciles the target worktree clean on the SYNC path too (target
    advanced -> sync+reverify -> squash+CAS): after landing, the tree is clean, the commit is a
    single-parent squash, and the branch is deleted."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")     # non-conflicting advance -> sync
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        _, tip = _rev(repo, "HEAD")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["merged"] is True and out["synced"] is True and not out["reason"]
        assert _porcelain(repo) == ""                                   # reconciled clean, no reset needed
        assert _rev(repo, "HEAD^") == (0, tip)                          # single parent == the verified tip
        assert _rev(repo, "HEAD^2")[0] != 0                             # NOT a merge commit
        assert _rev(repo, branch)[0] != 0                              # branch deleted


def test_merge_branch_real_squash_conflict_resets_clean_and_keeps_branch():
    """A GENUINE squash conflict (add/add on b.py) has no MERGE_HEAD; the code resets --hard
    (not merge --abort) to clean the tree, refuses ('merge failed'), and keeps the branch for
    review. Proves the conflicted-squash cleanup on a real conflicted tree, not a simulated rc."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)   # branch adds b.py = "y = 2\n"
        orig = worktree._git
        injected = {"done": False}

        def fake(repo_arg, *args, **kw):
            if not injected["done"] and args and args[0] == "merge" and "--squash" in args:
                # a foreign writer lands a CONFLICTING b.py just before our squash, so the real
                # `merge --squash branch` hits an add/add conflict against the moved HEAD.
                with open(os.path.join(repo_arg, "b.py"), "w") as f:
                    f.write("foreign = 999\n")
                subprocess.run(["git", "-C", repo_arg, "add", "b.py"],
                               capture_output=True, text=True)
                subprocess.run(["git", "-C", repo_arg, "commit", "-qm", "foreign conflicting write"],
                               capture_output=True, text=True)
                injected["done"] = True
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig

        assert injected["done"] is True
        assert out["merged"] is False and "merge failed" in out["reason"]
        assert _porcelain(repo) == ""                                   # conflicted tree reset CLEAN
        assert "<<<<<<<" not in open(os.path.join(repo, "b.py")).read() # no markers linger
        assert _rev(repo, branch)[0] == 0                              # branch kept for review


def test_merge_branch_advanced_target_syncs_reverifies_then_merges():
    # THE pre-merge sync contract (user decision 2026-07-02): a non-conflicting target advance
    # is merged INTO the run branch first, the whole-suite check runs on the COMBINED tree, and
    # only then does the work merge back. Mutant killed: advanced-detection dropped (an advanced
    # target would merge with no combined-tree verification — see red test below).
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")           # non-conflicting advance
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        calls = []
        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=lambda p: calls.append(p) or (True, ""))
        assert out["merged"] is True and out["synced"] is True
        assert len(calls) == 1                                           # combined tree re-verified once
        assert calls and all(os.path.realpath(p) != os.path.realpath(repo) for p in calls)
        assert open(os.path.join(repo, "b.py")).read() == "y = 2\n"      # run's work landed
        assert open(os.path.join(repo, "d.py")).read() == "z = 3\n"      # target's advance kept
        log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        assert "devloop: squash-merge" in log                            # squash commit is the provenance
        assert "devloop: sync target into" not in log                    # sync commit flattened away
        assert _rev(repo, branch)[0] != 0                                # branch deleted after merge
        assert not os.path.isdir(os.path.join(repo, ".worktrees", "m1-sync"))   # sync checkout gone


def test_merge_branch_red_combined_tree_refuses_and_strips_sync_commit():
    # A green run + a green target can still be a RED combination. The gate refuses the merge and
    # the review branch is reset to the run's VERIFIED work (no sync commit pollution).
    # Mutants killed: red-still-merges; reset-on-red dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        _, pre = _rev(repo, branch)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=lambda p: (False, "1 failed: test_b"))
        assert out["merged"] is False and "failed regression" in out["reason"]
        assert _rev(repo, branch) == (0, pre)                            # branch = pre-sync SHA exactly
        assert _porcelain(repo) == ""                                    # target tree clean
        assert not os.path.isfile(os.path.join(repo, "b.py"))            # nothing landed


def test_merge_branch_sync_conflict_without_resolver_aborts_keeps_branch():
    # A conflicting target advance with NO resolver -> the sync merge is ABORTED (tree left
    # clean), the branch survives at its verified SHA, target content untouched.
    # Mutants killed: sync-conflict check dropped; sync-abort dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root, content="y = 2\n")
        _, pre = _rev(repo, branch)
        open(os.path.join(repo, "b.py"), "w").write("y = 999\n")         # conflicting advance
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "conflicting advance")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["merged"] is False and "sync conflict" in out["reason"]
        assert _porcelain(repo) == ""                                    # NEVER a conflicted tree
        assert open(os.path.join(repo, "b.py")).read() == "y = 999\n"    # target untouched
        assert _rev(repo, branch) == (0, pre)                            # branch KEPT, unpolluted


def test_merge_branch_advanced_without_check_refuses_fail_closed():
    # A stray caller (no regression_check) can never merge into an ADVANCED target: the combined
    # tree would be unverified. Mutant killed: fail-closed missing-check path dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        out = worktree.merge_branch(repo, branch, base=base)
        assert out["merged"] is False and "sync unavailable" in out["reason"]
        assert _rev(repo, branch)[0] == 0                                # branch left for review


def test_merge_branch_unknown_base_is_conservative_sync():
    # No fork-point SHA -> can't prove the target didn't move -> take the sync path anyway
    # (an already-contained tip is a no-op merge; the re-verify is the cost of certainty).
    with tempfile.TemporaryDirectory() as root:
        repo, branch, _ = _wt_with_work(root)
        calls = []
        out = worktree.merge_branch(repo, branch,
                                    regression_check=lambda p: calls.append(p) or (True, ""))
        assert out["merged"] is True and out["synced"] is True and len(calls) == 1


def test_merge_branch_dirty_target_refuses_without_attempting():
    # Uncommitted work in the target tree -> the merge is not even attempted (an in-flight
    # merge can clobber it). Mutant killed: dirty-guard dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "wip.txt"), "w").write("uncommitted\n")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["merged"] is False and "not attempted" in out["reason"]
        assert open(os.path.join(repo, "wip.txt")).read() == "uncommitted\n"   # preserved
        log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        assert "devloop: squash-merge" not in log                        # nothing landed


def test_merge_branch_detached_head_refuses():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        _git(repo, "checkout", "-q", head)                               # detach
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["merged"] is False and "detached" in out["reason"]


# --- LLM conflict resolution + post-sync fix (user decision 2026-07-02) — guarded in CODE ------
def test_sync_conflict_resolved_by_llm_merges():
    # The resolver EDITS the conflicted file; the code layer verifies (no markers, index clean,
    # commit ok) and the regression gate still decides. Mutant killed: resolver result trusted
    # without the marker/index checks (see marker test below).
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root, content="y = 2\n")
        open(os.path.join(repo, "b.py"), "w").write("y = 999\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "conflicting advance")

        def resolver(path, conflicted):
            assert conflicted == ["b.py"]
            open(os.path.join(path, "b.py"), "w").write("y = 3  # reconciled\n")
            return True

        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green,
                                    resolver=resolver)
        assert out["merged"] is True and out["synced"] is True and out["resolved"] is True
        assert open(os.path.join(repo, "b.py")).read() == "y = 3  # reconciled\n"
        assert _porcelain(repo) == ""


def test_sync_conflict_resolver_leaving_markers_is_refused():
    # A resolver that CLAIMS success but leaves conflict markers must be refused by the CODE
    # check — the model's claim is never trusted. Mutant killed: marker guard dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root, content="y = 2\n")
        _, pre = _rev(repo, branch)
        open(os.path.join(repo, "b.py"), "w").write("y = 999\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "conflicting advance")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green,
                                    resolver=lambda path, conflicted: True)   # lies, edits nothing
        assert out["merged"] is False and "markers remain" in out["reason"]
        assert _porcelain(repo) == ""                                    # aborted cleanly
        assert _rev(repo, branch) == (0, pre)                            # branch unpolluted


def test_sync_conflict_on_test_files_never_reaches_the_resolver():
    # Tests are the ORACLE: a conflict that touches a test file is human territory — the
    # resolver (which could rewrite the oracle) must never even be invoked.
    # Mutant killed: test-file conflict guard dropped.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root, content="def test_a():\n    assert True\n",
                                           fname="test_feature.py")
        open(os.path.join(repo, "test_feature.py"), "w").write("def test_a():\n    assert 1\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "conflicting test advance")
        called = []
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green,
                                    resolver=lambda path, conflicted: called.append(1) or True)
        assert called == []                                              # resolver NEVER invoked
        assert out["merged"] is False and "TEST files" in out["reason"]
        assert _porcelain(repo) == ""


def test_resolver_touching_other_test_files_is_restored_and_refused():
    # The resolver resolves the real conflict but ALSO rewrites an unrelated test file -> the
    # merge-layer frozen-tests guard restores the original and refuses. Mutant killed:
    # merge-layer test snapshot/restore dropped.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        open(os.path.join(repo, "test_seed.py"), "w").write("def test_s():\n    assert True\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "seed test")
        repo, branch, base = _wt_with_work(root, content="y = 2\n")
        open(os.path.join(repo, "b.py"), "w").write("y = 999\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "conflicting advance")

        def sneaky(path, conflicted):
            open(os.path.join(path, "b.py"), "w").write("y = 3\n")               # legit part
            open(os.path.join(path, "test_seed.py"), "w").write("def test_s():\n    assert False\n")
            return True

        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green,
                                    resolver=sneaky)
        assert out["merged"] is False and "modified TEST files" in out["reason"]
        assert _porcelain(repo) == ""
        assert "assert True" in open(os.path.join(repo, "test_seed.py")).read()  # oracle intact


def test_red_combined_tree_fixed_by_llm_then_gate_decides():
    # ONE bounded fixer attempt; the regression gate re-runs and DECIDES. A fixer edit to a test
    # file is restored before the re-check (the oracle stays the oracle).
    # Mutants killed: fixer re-check dropped (LLM claim merges); fixer test-restore dropped.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        open(os.path.join(repo, "test_seed.py"), "w").write("def test_s():\n    assert True\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "seed test")
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")

        checks = []

        def check(path):
            checks.append(open(os.path.join(path, "test_seed.py")).read())
            return (False, "1 failed") if len(checks) == 1 else (True, "")

        def fixer(path, why):
            assert "1 failed" in why
            open(os.path.join(path, "fixed.py"), "w").write("ok = 1\n")           # the fix
            open(os.path.join(path, "test_seed.py"), "w").write("SABOTAGE\n")     # must be undone
            return True

        out = worktree.merge_branch(repo, branch, base=base, regression_check=check, fixer=fixer)
        assert out["merged"] is True and out["fixed"] is True
        assert len(checks) == 2                                          # gate re-ran after the fix
        assert "assert True" in checks[1]                                # re-check saw RESTORED tests
        assert open(os.path.join(repo, "fixed.py")).read() == "ok = 1\n" # fix landed via the merge
        assert "assert True" in open(os.path.join(repo, "test_seed.py")).read()


def test_fixer_that_does_not_turn_the_gate_green_is_refused():
    # The fixer commits a REAL change (so the commit lands) but the suite stays red on the
    # re-check -> refuse, branch reset to verified work. The real-file fixer keeps this on the
    # red-RE-CHECK refusal path (exercising the gate re-run), distinct from the empty-commit
    # fail-closed path covered by test_post_sync_fixer_commit_failure_is_refused_without_recheck.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        _, pre = _rev(repo, branch)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")

        def _fixer(path, why):
            open(os.path.join(path, "attempted_fix.py"), "w").write("patched = 1\n")
            return True

        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=lambda p: (False, "still red"),
                                    fixer=_fixer)
        assert out["merged"] is False and "failed regression" in out["reason"]
        assert _rev(repo, branch) == (0, pre)                            # fix/sync commits stripped


def test_merge_branch_refuses_when_foreign_write_moves_head_during_verify():
    # A foreign write moving HEAD off the verified tip during verification is caught by the
    # ref-CAS at landing time, without a lock or separate pre-check.
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")     # advance target -> sync runs
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")

        def check_that_moves_head(path):
            # a foreign writer commits to `repo` DURING verification, moving HEAD
            open(os.path.join(repo, "foreign.py"), "w").write("f = 1\n")
            _git(repo, "add", "."); _git(repo, "commit", "-qm", "foreign concurrent write")
            return True, ""

        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=check_that_moves_head)
        assert out["merged"] is False and "moved before the merge could land" in out["reason"]
        assert any(e["step"] == "tip-moved" for e in out["events"])       # diagnosable via the CAS
        assert _rev(repo, branch)[0] == 0                                # branch left for review


def test_merge_branch_cas_refuses_when_head_moves_after_precheck_before_ref_update():
    """Deterministically prove the ref CAS closes the pre-check's residual TOCTOU window:
    a move after the pre-check but before update-ref, which a held lock or pre-check cannot."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        _, tip = _rev(repo, "HEAD")
        orig = worktree._git
        injected = {"done": False}

        def fake(repo_arg, *args, **kw):
            if (not injected["done"] and args and args[0] == "update-ref"
                    and str(args[1]).startswith("refs/heads/")):
                target_ref, expected_old = args[1], args[3]
                foreign = subprocess.run(
                    ["git", "-C", repo_arg, "commit-tree", expected_old + "^{tree}",
                     "-p", expected_old, "-m", "foreign cron write"],
                    capture_output=True, text=True).stdout.strip()
                subprocess.run(["git", "-C", repo_arg, "update-ref", target_ref, foreign],
                               capture_output=True, text=True)
                injected["done"] = True
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig

        assert injected["done"] is True
        assert out["merged"] is False
        assert "moved" in out["reason"]
        assert any(e["step"] == "tip-moved" and e["level"] == "warn"
                   for e in out["events"])
        assert _rev(repo, branch)[0] == 0
        message = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert message == "foreign cron write"
        assert subprocess.run(
            ["git", "-C", repo, "cat-file", "-e", "HEAD:b.py"],
            capture_output=True, text=True).returncode != 0
        assert _porcelain(repo) == ""

    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["merged"] is True and not out["reason"]
        assert _rev(repo, branch)[0] != 0
        message = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert "squash-merge" in message


def test_post_sync_fixer_commit_failure_is_refused_without_recheck():
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        open(os.path.join(repo, "test_seed.py"), "w").write("def test_s():\n    assert True\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "seed test")
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        hook = os.path.join(repo, ".git", "hooks", "pre-commit")
        open(hook, "w").write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        checks = []

        def check(path):
            checks.append(path)
            return False, "still red"

        def fixer(path, why):
            open(os.path.join(path, "fixed.py"), "w").write("ok = 1\n")
            return True

        out = worktree.merge_branch(repo, branch, base=base,
                                    regression_check=check, fixer=fixer)
        assert out["merged"] is False and "post-sync fix commit failed" in out["reason"]
        assert out["fixed"] is False
        assert checks and len(checks) == 1                               # failed commit skips re-check
        assert _rev(repo, branch)[0] == 0                                # branch survives for review


# --- in-repo .worktrees + guaranteed ignore (user decision 2026-07-02) --------------------------
def test_create_worktree_default_root_is_in_repo_and_invisible():
    # No explicit root -> <repo>/.worktrees; the enclosing repo's status stays EMPTY while the
    # checkout is alive (the local exclude entry — a visible checkout would trip merge_branch's
    # dirty-guard and block every auto-merge). Mutant killed: exclude write dropped.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        wt = worktree.create_worktree(repo, "d1")
        assert wt["path"] == os.path.join(repo, ".worktrees", "d1")
        assert os.path.isfile(os.path.join(wt["path"], "a.py"))          # a real checkout
        assert _porcelain(repo) == ""                                    # invisible to the repo
        assert wt["seed_ignore"] is True                                 # repo didn't ignore it before


def test_gitignore_seed_rides_contentful_run_into_target_history():
    # The user ask (2026-07-02): `.worktrees/` must land in the TRACKED .gitignore — seeded by
    # finalize as part of a contentful commit, merged into history like any other run work.
    # Mutant killed: finalize seed dropped.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        wt = worktree.create_worktree(repo, "s1")                        # in-repo default root
        open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
        fin = worktree.finalize(wt, "devloop COMPLETE: s1")
        assert ".gitignore" in fin["changed"] and "b.py" in fin["changed"]
        out = worktree.merge_branch(repo, wt["branch"], base=wt["base"], regression_check=_green)
        assert out["merged"] is True
        assert ".worktrees/" in open(os.path.join(repo, ".gitignore")).read().splitlines()


def test_gitignore_not_touched_when_repo_already_ignores_worktrees():
    # A repo that already ignores .worktrees (tracked entry or allowlist) gets NO seed — never a
    # dup line, never gratuitous .gitignore churn in the run's diff.
    # Mutant killed: already-ignored check inverted.
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        open(os.path.join(repo, ".gitignore"), "w").write(".worktrees/\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "ignore worktrees")
        wt = worktree.create_worktree(repo, "s2")
        assert wt["seed_ignore"] is False
        open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
        fin = worktree.finalize(wt, "devloop COMPLETE: s2")
        assert ".gitignore" not in fin["changed"]                        # untouched
        out = worktree.merge_branch(repo, wt["branch"], base=wt["base"], regression_check=_green)
        assert out["merged"] is True
        assert open(os.path.join(repo, ".gitignore")).read() == ".worktrees/\n"


# --- C3/C4 production hardening (2026-07-03): branch guard + merge serialization ---------------
def test_merge_branch_refuses_when_target_switched_branches_mid_run():
    """C3: the run derived from start_branch; if the checkout switched branches mid-run the
    COMPLETE work must NOT land on the new branch. Mutants killed: expected_branch guard
    dropped; start_branch recording dropped."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        wt = worktree.create_worktree(repo, "sw1", os.path.join(root, "wts"))
        assert wt["start_branch"]                                    # derivation IS tracked
        open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
        fin = worktree.finalize(wt, "devloop COMPLETE: sw1")
        assert fin["committed"] and fin["branch_kept"]
        _git(repo, "checkout", "-qb", "other")                       # checkout switched mid-run
        out = worktree.merge_branch(repo, wt["branch"], base=wt["base"],
                                    regression_check=_green,
                                    expected_branch=wt["start_branch"])
        assert out["merged"] is False
        assert wt["start_branch"] in out["reason"] and "other" in out["reason"]
        assert _rev(repo, wt["branch"])[0] == 0                      # branch kept for review
        assert not os.path.exists(os.path.join(repo, "b.py"))        # nothing landed on 'other'
        # CONTROL: back on the derivation branch, the same merge proceeds normally.
        _git(repo, "checkout", "-q", wt["start_branch"])
        out2 = worktree.merge_branch(repo, wt["branch"], base=wt["base"],
                                     regression_check=_green,
                                     expected_branch=wt["start_branch"])
        assert out2["merged"] is True


def test_keep_worktree_env_preserves_checkout():
    """C7: DEVLOOP_KEEP_WORKTREE=1 keeps the exact run tree for post-mortems (documented
    debris); commit + branch semantics unchanged. Mutant killed: keep knob ignored."""
    saved = os.environ.pop("DEVLOOP_KEEP_WORKTREE", None)
    try:
        os.environ["DEVLOOP_KEEP_WORKTREE"] = "1"
        with tempfile.TemporaryDirectory() as root:
            repo = os.path.join(root, "repo")
            _init_repo(repo)
            wt = worktree.create_worktree(repo, "kw1", os.path.join(root, "wts"))
            open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
            fin = worktree.finalize(wt, "devloop COMPLETE: kw1")
            assert fin["committed"] and fin["branch_kept"]
            assert fin["worktree_removed"] is False
            assert os.path.isdir(wt["path"])                     # the exact tree survives
    finally:
        os.environ.pop("DEVLOOP_KEEP_WORKTREE", None)
        if saved is not None:
            os.environ["DEVLOOP_KEEP_WORKTREE"] = saved


def test_commit_identity_env_knobs():
    """C6: DEVLOOP_GIT_NAME/EMAIL override the devloop commit identity for production repos
    that attribute automation; defaults unchanged. Mutant killed: env knob dropped."""
    saved = {k: os.environ.pop(k, None) for k in ("DEVLOOP_GIT_NAME", "DEVLOOP_GIT_EMAIL")}
    try:
        assert worktree._identity() == ("-c", "user.email=devloop@hermes",
                                        "-c", "user.name=devloop")
        os.environ["DEVLOOP_GIT_NAME"] = "relbot"
        os.environ["DEVLOOP_GIT_EMAIL"] = "relbot@corp"
        with tempfile.TemporaryDirectory() as root:
            repo, branch, base = _wt_with_work(root)
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
            assert out["merged"] is True
            author = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%an <%ae>"],
                                    capture_output=True, text=True).stdout.strip()
            assert author == "relbot <relbot@corp>"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_create_worktree_exclude_seeding_is_idempotent():
    """Linked worktrees share the MAIN repo's info/exclude and create_worktree appended
    `.devloop/` unconditionally — one duplicate line per run, forever, in every target repo
    (live-caught: 43 copies in a long-lived target). Two runs must leave exactly ONE line.
    Mutant killed: idempotence check dropped."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        for name in ("i1", "i2"):
            wt = worktree.create_worktree(repo, name, os.path.join(root, "wts"))
            worktree.finalize(wt, f"devloop RUN: {name}")
        excl = open(os.path.join(repo, ".git", "info", "exclude")).read().splitlines()
        assert excl.count(".devloop/") == 1


def test_merge_branch_empty_delta_counts_merged_without_commit():
    """Post-sync edge: the branch's content is already contained in the target — the squash
    stages nothing, no empty commit is created, and the run still counts merged (the work IS
    in the target). Mutant killed: empty-delta gate dropped (commit of nothing would fail the
    whole merge)."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        # land the branch's ENTIRE content on the target out-of-band -> true containment
        # (writing just b.py isn't enough: finalize also seeded .gitignore on the branch)
        _git(repo, "merge", "--squash", branch)
        _git(repo, "commit", "-qm", "target already got the work")
        _, head_before = _rev(repo, "HEAD")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert _rev(repo, "HEAD") == (0, head_before)                  # empty delta: no ref move, CAS bypassed
        assert _porcelain(repo) == ""                                  # tree stays clean
        assert out["merged"] is True and "no delta" in out["reason"]
        log = subprocess.run(["git", "-C", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        assert "devloop: squash-merge" not in log                        # no noise commit
        assert _rev(repo, branch)[0] != 0                                # branch still deleted


def test_merge_branch_refuses_branch_with_no_commits_beyond_base():
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        wt = worktree.create_worktree(repo, "empty", os.path.join(root, "wts"))
        calls = []
        out = worktree.merge_branch(
            repo, wt["branch"], base=wt["base"],
            regression_check=lambda p: calls.append(p) or (True, ""))
        assert out["merged"] is False and "nothing to merge" in out["reason"]
        assert calls == []
        assert _rev(repo, wt["branch"]) == (0, wt["base"])


def test_finalize_commit_failure_keeps_checkout_and_contentless_branch():
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        hook = os.path.join(repo, ".git", "hooks", "pre-commit")
        open(hook, "w").write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        wt = worktree.create_worktree(repo, "commit-fails", os.path.join(root, "wts"))
        open(os.path.join(wt["path"], "work.py"), "w").write("answer = 42\n")
        fin = worktree.finalize(wt, "must fail")
        assert fin["committed"] is False and fin["branch_kept"] is True
        assert os.path.isdir(wt["path"])
        assert _rev(repo, wt["branch"]) == (0, wt["base"])


def test_merge_branch_failed_squash_commit_resets_and_keeps_branch():
    """A squash whose commit-tree fails must undo the staged squash (clean tree), keep the branch
    for review, and NEVER report merged. Mutants killed: staged-squash reset dropped (a
    failed commit leaves a staged half-merge behind); commit-failure gate dropped (branch -D
    fires and merged=True on a commit that never landed)."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        orig = worktree._git

        def fake(repo_arg, *args, **kw):
            if "commit-tree" in args:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="simulated commit failure")
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig
        assert out["merged"] is False and "squash commit failed" in out["reason"]
        dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        assert dirty == ""                                               # staged squash undone
        assert _rev(repo, branch)[0] == 0                                # branch kept for review


def test_merge_branch_non_index_lock_squash_failure_resets_and_keeps_branch():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        orig = worktree._git
        state = {"failed": 0}

        def fake(repo_arg, *args, **kw):
            if "merge" in args and "--squash" in args and state["failed"] == 0:
                staged = orig(repo_arg, *args, **kw)
                assert staged.returncode == 0
                state["failed"] = 1
                return subprocess.CompletedProcess(
                    args, 1, stdout="", stderr="fatal: some other real conflict")
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig
        assert state["failed"] == 1
        assert out["merged"] is False and "merge failed" in out["reason"]
        assert _porcelain(repo) == ""
        assert _rev(repo, branch)[0] == 0


def test_merge_branch_reports_branch_delete_leak_after_landed_squash():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        orig = worktree._git

        def fake(repo_arg, *args, **kw):
            if len(args) >= 3 and args[:2] == ("branch", "-D"):
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig
        assert out["merged"] is True
        assert out["leaked_branch"] == branch
        assert "branch deletion failed" in out["reason"]
        assert _rev(repo, branch)[0] == 0


def test_merge_branch_retries_final_merge_on_index_lock():
    """C4: a FOREIGN git process's transient index.lock must not degrade a fully verified
    COMPLETE to branch-for-review — the final merge retries, bounded, and ONLY for index.lock.
    Mutants killed: retry loop dropped; index.lock trigger inverted."""
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        orig = worktree._git
        state = {"failed": 0}

        def fake(repo_arg, *args, **kw):
            if "merge" in args and "--squash" in args and state["failed"] == 0:
                state["failed"] = 1
                return subprocess.CompletedProcess(
                    args, 128, stdout="",
                    stderr="fatal: Unable to create '.git/index.lock': File exists.")
            return orig(repo_arg, *args, **kw)

        worktree._git = fake
        try:
            out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        finally:
            worktree._git = orig
        assert state["failed"] == 1                                  # the lock failure DID fire
        assert out["merged"] is True                                 # ...and was retried past


def test_diagnostic_events_happy_fast_path_are_info_only():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert any(e["phase"] == "merge" and e["step"] == "squash-commit"
                   and e["level"] == "info" for e in out["events"])
        assert not any(e["level"] in ("warn", "error") for e in out["events"])


def test_diagnostic_events_advanced_target_green_include_sync_info():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        out = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert out["synced"] is True
        assert any(e["phase"] == "sync" and e["step"] in ("merge-target", "regression-check")
                   and e["level"] == "info" for e in out["events"])


def test_diagnostic_events_red_combined_tree_include_reason_warning():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        out = worktree.merge_branch(
            repo, branch, base=base,
            regression_check=lambda path: (False, "some red reason"))
        assert out["merged"] is False
        assert any(e["level"] == "warn" and "some red reason" in e["detail"]
                   for e in out["events"])


def test_diagnostic_events_failed_fixer_commit_include_error_rc():
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        open(os.path.join(repo, "test_seed.py"), "w").write(
            "def test_s():\n    assert True\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "seed test")
        repo, branch, base = _wt_with_work(root)
        open(os.path.join(repo, "d.py"), "w").write("z = 3\n")
        _git(repo, "add", "."); _git(repo, "commit", "-qm", "target advance")
        hook = os.path.join(repo, ".git", "hooks", "pre-commit")
        open(hook, "w").write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)

        def fixer(path, why):
            open(os.path.join(path, "fixed.py"), "w").write("ok = 1\n")
            return True

        out = worktree.merge_branch(
            repo, branch, base=base,
            regression_check=lambda path: (False, "still red"), fixer=fixer)
        assert any(e["phase"] == "sync" and e["step"] == "fixer-commit"
                   and e["level"] == "error" and e["rc"] not in (None, 0)
                   for e in out["events"])


def test_diagnostic_events_detached_head_and_no_content_are_warnings():
    with tempfile.TemporaryDirectory() as root:
        repo, branch, base = _wt_with_work(root)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        _git(repo, "checkout", "-q", head)
        detached = worktree.merge_branch(repo, branch, base=base, regression_check=_green)
        assert any(e["step"] == "detached-head" and e["level"] == "warn"
                   for e in detached["events"])

    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); _init_repo(repo)
        wt = worktree.create_worktree(repo, "empty", os.path.join(root, "wts"))
        empty = worktree.merge_branch(repo, wt["branch"], base=wt["base"],
                                      regression_check=_green)
        assert any(e["step"] == "no-content" and e["level"] == "warn"
                   for e in empty["events"])


def test_diagnostic_event_rejects_bad_level():
    # NOTE: the raise must happen OUTSIDE the try (an `assert False` fallback INSIDE the try
    # would be caught by the same `except AssertionError`, making this vacuous even if
    # state.ev never validated anything).
    raised = False
    try:
        state.ev("merge", "x", "bogus")
    except AssertionError:
        raised = True
    assert raised, "state.ev should have raised AssertionError for an invalid level"


# --- _resolve_conflicts: LLM conflict resolution guard (P2 from advisor review) ----

def _repo_with_conflict(repo):
    """Create a git repo with a merge conflict on a.py (not a test file).
    Uses the existing _init_repo (which creates a.py and commits it), then
    branches to create the conflict."""
    # _init_repo already did: a.py='x=1', committed on default branch
    _init_repo(repo)
    # Create a feature branch that changes a.py
    _git(repo, "checkout", "-q", "-b", "feature")
    with open(os.path.join(repo, "a.py"), "w") as f:
        f.write("x = 2\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "feature change")
    # Back to default branch, change a.py differently
    try:
        _git(repo, "checkout", "-q", "main")
    except Exception:
        _git(repo, "checkout", "-q", "master")
    with open(os.path.join(repo, "a.py"), "w") as f:
        f.write("x = 3\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "main change")
    # Merge feature into main → conflict
    _git(repo, "merge", "feature", check=False)  # this will fail with conflict
    return repo


def test_resolve_conflicts_no_resolver_refuses():
    """No resolver provided → refuse, branch left for review."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        ok, why, events = worktree._resolve_conflicts(repo, None)
        assert ok is False
        assert "branch left for review" in why


def test_resolve_conflicts_test_file_conflict_refuses():
    """Conflict touching a test file → refuse (tests are the oracle)."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)  # creates a.py, commits on default branch
        # feature branch changes a.py AND adds test_a.py
        _git(repo, "checkout", "-q", "-b", "feature")
        with open(os.path.join(repo, "test_a.py"), "w") as f:
            f.write("assert True\n")
        _git(repo, "add", "test_a.py")
        _git(repo, "commit", "-q", "-m", "feature adds test")
        # main branch changes test_a.py differently
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "test_a.py"), "w") as f:
            f.write("assert False\n")
        _git(repo, "add", "test_a.py")
        _git(repo, "commit", "-q", "-m", "main changes test")
        _git(repo, "merge", "feature", check=False)
        # Now resolve with a dummy resolver — should refuse because test file
        ok, why, events = worktree._resolve_conflicts(repo, lambda p, c: True)
        assert ok is False
        assert "TEST" in why or "test" in why.lower()


def test_resolve_conflicts_resolver_crash_refuses():
    """A crashed resolver → refuse, never crash past the guard."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        def crash(p, c):
            raise RuntimeError("LLM API down")
        ok, why, events = worktree._resolve_conflicts(repo, crash)
        assert ok is False
        assert "crashed" in why.lower()


def test_resolve_conflicts_resolver_returns_false_refuses():
    """Resolver returns False → refuse."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        ok, why, events = worktree._resolve_conflicts(repo, lambda p, c: False)
        assert ok is False
        assert "failed" in why.lower() or "refused" in why.lower()


def test_resolve_conflicts_resolver_succeeds():
    """A resolver that actually resolves the conflict → ok=True."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        def good_resolver(path, conflicted):
            # Write a resolved version of each conflicted file
            for p in conflicted:
                with open(os.path.join(path, p), "w") as f:
                    f.write("x = 42\n")  # resolved: no conflict markers
            return True
        ok, why, events = worktree._resolve_conflicts(repo, good_resolver)
        assert ok is True
        assert why == ""


def test_resolve_conflicts_markers_remain_refuses():
    """Resolver claims success but leaves conflict markers → refuse."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        def lying_resolver(path, conflicted):
            for p in conflicted:
                with open(os.path.join(path, p), "w") as f:
                    f.write("<<<<<<< HEAD\nx = 2\n=======\nx = 3\n>>>>>>> feature\n")
            return True
        ok, why, events = worktree._resolve_conflicts(repo, lying_resolver)
        assert ok is False
        assert "markers remain" in why.lower()


def test_resolve_conflicts_resolver_deletes_conflicted_file_refuses():
    """Resolver deletes a conflicted file → refuse (file missing after resolution)."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _repo_with_conflict(repo)
        def deleting_resolver(path, conflicted):
            for p in conflicted:
                os.remove(os.path.join(path, p))
            return True
        ok, why, events = worktree._resolve_conflicts(repo, deleting_resolver)
        assert ok is False
        assert "deleted" in why.lower()
        assert any(e["step"] == "conflicted-file-deleted" for e in events)


# --- _sync_and_verify: pre-merge sync safety net (P2 from advisor review) ----------

def test_sync_and_verify_clean_merge_passes():
    """A clean merge (no conflicts) with passing regression → ok=True."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)  # creates a.py, commits on default branch
        # Create branch
        _git(repo, "checkout", "-q", "-b", "run1")
        with open(os.path.join(repo, "b.py"), "w") as f:
            f.write("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "run1 work")
        # Target advances
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "c.py"), "w") as f:
            f.write("z = 3\n")
        _git(repo, "add", "c.py")
        _git(repo, "commit", "-q", "-m", "target advance")
        target_tip = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
        # Sync: merge target into run1 — should be clean (no overlap)
        ok, why, notes = worktree._sync_and_verify(
            repo, "run1", target_tip, lambda p: (True, "green"))
        assert ok is True


def test_sync_and_verify_regression_fail_strips_commits():
    """A clean merge but failing regression → ok=False, sync commits stripped."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        _git(repo, "checkout", "-q", "-b", "run1")
        with open(os.path.join(repo, "b.py"), "w") as f:
            f.write("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "run1 work")
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "c.py"), "w") as f:
            f.write("z = 3\n")
        _git(repo, "add", "c.py")
        _git(repo, "commit", "-q", "-m", "target advance")
        target_tip = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
        ok, why, notes = worktree._sync_and_verify(
            repo, "run1", target_tip, lambda p: (False, "tests failed"))
        assert ok is False
        assert "failed regression" in why or "branch left for review" in why


def test_sync_and_verify_fixer_success():
    """Fixer fixes the combined tree and regression passes on re-check → ok=True."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        _git(repo, "checkout", "-q", "-b", "run1")
        with open(os.path.join(repo, "b.py"), "w") as f:
            f.write("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "run1 work")
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "c.py"), "w") as f:
            f.write("z = 3\n")
        _git(repo, "add", "c.py")
        _git(repo, "commit", "-q", "-m", "target advance")
        target_tip = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()

        call_count = [0]
        def flaky_regression(path):
            call_count[0] += 1
            if call_count[0] == 1:
                return (False, "initial fail")
            return (True, "fixed")

        def fixer(path, why):
            # Actually make a change so the fixer commit has something to commit
            with open(os.path.join(path, "fixer_marker.py"), "w") as f:
                f.write("# fixed\n")
            return True

        ok, why, notes = worktree._sync_and_verify(
            repo, "run1", target_tip, flaky_regression, fixer=fixer)
        assert ok is True
        assert notes["fixed"] is True


def test_sync_and_verify_fixer_crash_refuses():
    """Fixer crashes during the one bounded attempt → ok=False, regression stays red."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        _git(repo, "checkout", "-q", "-b", "run1")
        with open(os.path.join(repo, "b.py"), "w") as f:
            f.write("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "run1 work")
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "c.py"), "w") as f:
            f.write("z = 3\n")
        _git(repo, "add", "c.py")
        _git(repo, "commit", "-q", "-m", "target advance")
        target_tip = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()

        check_calls = []
        def red_check(path):
            check_calls.append(path)
            return (False, "still red")

        def crashing_fixer(path, why):
            raise RuntimeError("fixer exploded")

        ok, why, notes = worktree._sync_and_verify(
            repo, "run1", target_tip, red_check, fixer=crashing_fixer)
        assert ok is False
        assert notes["fixed"] is False
        assert len(check_calls) == 1  # no re-check after crashed fixer


def test_sync_and_verify_fixer_succeeds_recheck_fails_strips_commits():
    """Fixer commits a real change but the regression re-check still fails → ok=False,
    sync/fix commits stripped from the branch."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        _git(repo, "checkout", "-q", "-b", "run1")
        with open(os.path.join(repo, "b.py"), "w") as f:
            f.write("y = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "run1 work")
        try:
            _git(repo, "checkout", "-q", "main")
        except Exception:
            _git(repo, "checkout", "-q", "master")
        with open(os.path.join(repo, "c.py"), "w") as f:
            f.write("z = 3\n")
        _git(repo, "add", "c.py")
        _git(repo, "commit", "-q", "-m", "target advance")
        target_tip = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()

        run_head_before = subprocess.run(
            ["git", "-C", repo, "rev-parse", "run1"],
            capture_output=True, text=True).stdout.strip()

        check_calls = []
        def always_red(path):
            check_calls.append(path)
            return (False, "still red")

        def fixer(path, why):
            with open(os.path.join(path, "fixer_marker.py"), "w") as f:
                f.write("# attempted fix\n")
            return True

        ok, why, notes = worktree._sync_and_verify(
            repo, "run1", target_tip, always_red, fixer=fixer)
        assert ok is False
        assert notes["fixed"] is False
        assert len(check_calls) == 2  # initial + post-fixer re-check

        run_head_after = subprocess.run(
            ["git", "-C", repo, "rev-parse", "run1"],
            capture_output=True, text=True).stdout.strip()
        assert run_head_after == run_head_before  # sync/fix commits stripped


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} worktree tests passed")
