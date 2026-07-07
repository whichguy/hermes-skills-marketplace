"""Deterministic test of the worktree isolation — a REAL git repo, no LLM.

Proves: an isolated copy of the repo; real code changes show in the diff; devloop's .devloop/
bookkeeping is HIDDEN (won't leak into a merge); clean teardown.
"""
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import worktree  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def test_worktree_isolates_code_and_hides_devloop():
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "x@y.z")
        _git(repo, "config", "user.name", "x")
        open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "init")

        wt = worktree.create_worktree(repo, "t1", os.path.join(root, "wts"))
        assert os.path.exists(os.path.join(wt["path"], "a.py"))      # isolated copy of the repo
        assert wt["branch"] == "devloop/t1"

        # a real code change + devloop bookkeeping inside the worktree
        open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
        os.makedirs(os.path.join(wt["path"], ".devloop", "runs", "r"))
        open(os.path.join(wt["path"], ".devloop", "runs", "r", "trace.jsonl"), "w").write("{}\n")

        changed = worktree.changed_files(wt["path"])
        assert "b.py" in changed                                    # the code change shows
        assert not any(".devloop" in c for c in changed)            # bookkeeping is HIDDEN

        worktree.remove_worktree(repo, wt["path"])
        assert not os.path.exists(wt["path"])                       # clean teardown
        # the original repo working tree is untouched (no b.py)
        assert not os.path.exists(os.path.join(repo, "b.py"))


def _mk_repo(root, gitignore=None):
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "x")
    open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
    if gitignore is not None:
        open(os.path.join(repo, ".gitignore"), "w").write(gitignore)
    _git(repo, "add", "-f", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_changed_files_sees_files_hidden_by_repo_gitignore():
    # THE production bug (deep review 2026-07-01): a fail-closed repo .gitignore (`/*` allowlist,
    # the ~/.hermes shape) made the old porcelain-based changed_files blind to EVERY file a run
    # creates -> "changed 0 file(s)" on successful builds and EMPTY review branches. ls-files
    # --others without --exclude-standard must see them; junk dirs are filtered explicitly.
    # Mutant killed: untracked -> [] (back to gitignore-blind).
    with tempfile.TemporaryDirectory() as root:
        repo = _mk_repo(root, gitignore="/*\n!README\n!.gitignore\n!a.py\n")
        wt = worktree.create_worktree(repo, "g1", os.path.join(root, "wts"))
        open(os.path.join(wt["path"], "new.py"), "w").write("y = 2\n")   # ignored by the repo /*
        os.makedirs(os.path.join(wt["path"], ".devloop"))
        open(os.path.join(wt["path"], ".devloop", "junk"), "w").write("j")
        os.makedirs(os.path.join(wt["path"], "__pycache__"))
        open(os.path.join(wt["path"], "__pycache__", "x.pyc"), "w").write("c")
        # environments are junk too (live acceptance catch 2026-07-02: gitignore-blindness swept
        # a coder-created .venv — 518 files — into the COMPLETE merge)
        os.makedirs(os.path.join(wt["path"], ".venv", "bin"))
        open(os.path.join(wt["path"], ".venv", "bin", "python"), "w").write("x")
        os.makedirs(os.path.join(wt["path"], "node_modules", "left-pad"))
        open(os.path.join(wt["path"], "node_modules", "left-pad", "index.js"), "w").write("x")
        changed = worktree.changed_files(wt["path"], wt["base"])
        assert "new.py" in changed                                        # gitignore no longer blinds us
        assert not any(".devloop" in c or "__pycache__" in c for c in changed)   # junk filtered
        assert not any(".venv" in c or "node_modules" in c for c in changed)     # envs filtered


def test_finalize_commits_work_removes_checkout_keeps_contentful_branch():
    # "The BRANCH is the review artifact; the checkout is disposable." finalize must commit the
    # work, remove the checkout, and keep the branch (it now HOLDS content).
    with tempfile.TemporaryDirectory() as root:
        repo = _mk_repo(root)
        wt = worktree.create_worktree(repo, "f1", os.path.join(root, "wts"))
        open(os.path.join(wt["path"], "b.py"), "w").write("y = 2\n")
        fin = worktree.finalize(wt, "devloop COMPLETE: f1")
        assert fin["committed"] and fin["branch_kept"] and fin["worktree_removed"]
        assert "b.py" in fin["changed"]
        assert not os.path.exists(wt["path"])                             # checkout gone
        show = subprocess.run(["git", "-C", repo, "show", "--stat", "devloop/f1"],
                              capture_output=True, text=True).stdout
        assert "b.py" in show                                             # the branch holds the commit


def test_finalize_empty_run_removes_both_checkout_and_branch():
    # "No artifact -> no branch": an empty run must not accrete an empty branch (the 41-branch
    # noise class this fix killed).
    with tempfile.TemporaryDirectory() as root:
        repo = _mk_repo(root)
        wt = worktree.create_worktree(repo, "f2", os.path.join(root, "wts"))
        fin = worktree.finalize(wt, "devloop HUMAN_REVIEW: f2")
        assert fin["changed"] == [] and not fin["committed"] and not fin["branch_kept"]
        assert fin["worktree_removed"] and not os.path.exists(wt["path"])
        branches = subprocess.run(["git", "-C", repo, "branch", "--list", "devloop/f2"],
                                  capture_output=True, text=True).stdout.strip()
        assert branches == ""                                             # empty branch deleted


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} worktree tests passed")
