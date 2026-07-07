"""Deterministic tests for scripts/devloop_cli.py — the prompt-callable entrypoint. No LLM.

The CLI owns two correctness properties (both mutant-pinned):
  * NEVER implicit cwd: no --repo -> the SCRATCH sentinel (the legacy cwd-if-git fallback could
    target the ~/.hermes DATA repo from an agent session — the verified hazard);
  * exit 0 IFF error is None AND terminal == COMPLETE (a non-COMPLETE exit 0 is a
    false-complete at the shell boundary).
"""
import json
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "scripts"))

import devloop_bridge as br   # noqa: E402
import devloop_cli as cli     # noqa: E402


class _FakeBridge:
    """Injectable bridge capturing the dispatch; result is scripted per test."""
    SCRATCH = br.SCRATCH
    _WRITE_SAFE = "/tmp/fake-write-safe"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def call_guarded(self, fn, *a, **k):
        self.calls.append((getattr(fn, "__name__", str(fn)), a, k))
        return self.result

    def run_build(self, *a, **k):   # identity only; dispatched through call_guarded
        raise AssertionError("must go through call_guarded")

    def run_debug(self, *a, **k):
        raise AssertionError("must go through call_guarded")


def _res(terminal="COMPLETE", error=None, needs_human=False, merged=None, **extra):
    if merged is None:
        merged = terminal == "COMPLETE"      # default: a COMPLETE landed its merge
    return {"content": f"devloop {terminal} — x", "error": error,
            "devloop_result": {"terminal": terminal, "needs_human": needs_human,
                               "merged": merged, **extra}}


def test_no_repo_forces_scratch_even_from_a_git_cwd():
    # THE hazard killer: run the CLI while chdir'd INTO a git repo — the bridge must still
    # receive the SCRATCH sentinel, never a cwd-derived path. Mutant killed:
    # `repo = br.SCRATCH` -> `repo = None` (implicit cwd resurrected).
    fake = _FakeBridge(_res())
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        old = os.getcwd()
        os.chdir(d)
        try:
            rc = cli.main(["do a thing"], bridge=fake)
        finally:
            os.chdir(old)
    assert rc == 0
    (fname, args, kwargs) = fake.calls[0]
    assert fname == "run_build"
    assert kwargs["repo"] is fake.SCRATCH                       # sentinel, not a path, not None


def test_repo_validation_refusals_exit_2_and_never_run():
    fake = _FakeBridge(_res())
    # (a) missing dir
    rc = cli.main(["x", "--repo", "/nonexistent/nope"], bridge=fake)
    assert rc == 2 and fake.calls == []
    # (b) exists but not a git repo
    with tempfile.TemporaryDirectory() as d:
        rc = cli.main(["x", "--repo", d], bridge=fake)
        assert rc == 2 and fake.calls == []
    # (c) the write-safe root itself is refused
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        fake._WRITE_SAFE = d
        rc = cli.main(["x", "--repo", d], bridge=fake)
        assert rc == 2 and fake.calls == []


def test_valid_repo_passes_realpath_through():
    fake = _FakeBridge(_res())
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        rc = cli.main(["x", "--repo", d], bridge=fake)
    assert rc == 0
    assert fake.calls[0][2]["repo"] == os.path.realpath(d)


def test_debug_flags_route_to_run_debug():
    fake = _FakeBridge(_res())
    cli.main(["fix it", "--debug-code", "def f(): pass", "--error", "AssertionError"], bridge=fake)
    fname, args, kwargs = fake.calls[0]
    assert fname == "run_debug"
    assert kwargs["code"] == "def f(): pass" and kwargs["error_feedback"] == "AssertionError"


def test_exit_codes_are_a_correctness_contract():
    # 0 IFF error None AND terminal COMPLETE AND merged (the code actually LANDED);
    # 2 = needs-input; 1 = anything else — including a COMPLETE whose auto-merge degraded to
    # branch-for-review (the asked-for outcome did not happen).
    # Mutant killed: the exit mapping forced to 0 (shell-boundary false-complete).
    assert cli.main(["x"], bridge=_FakeBridge(_res("COMPLETE"))) == 0
    assert cli.main(["x"], bridge=_FakeBridge(_res("COMPLETE", merged=False))) == 1
    assert cli.main(["x"], bridge=_FakeBridge(_res("HUMAN_REVIEW", needs_human=True))) == 2
    assert cli.main(["x"], bridge=_FakeBridge(_res("NO_TERMINATION", error="bug sentinel"))) == 1
    assert cli.main(["x"], bridge=_FakeBridge(_res("COMPLETE", error="devloop runtime error"))) == 1
    # a fail-closed engine CRASH (failure_result) is exit 1: its terminal is HUMAN_REVIEW but
    # needs_human is explicitly False — the terminal label alone must never read as exit-2
    # needs-input. Mutant killed: failure_result `"needs_human": False` -> True.
    assert cli.main(["x"], bridge=_FakeBridge(br.failure_result("engine crashed"))) == 1


def test_repo_inside_enclosing_repo_is_refused():
    # git's upward walk: a PLAIN dir inside some enclosing git repo must be refused — the live
    # acceptance-run catch: targeting it would cut devloop branches off the ENCLOSING repo
    # (in production: the ~/.hermes data repo). Mutant killed: toplevel check dropped.
    fake = _FakeBridge(_res())
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        sub = os.path.join(d, "plain-subdir")
        os.makedirs(sub)
        rc = cli.main(["x", "--repo", sub], bridge=fake)
        assert rc == 2 and fake.calls == []


def test_json_output_is_parseable_and_rerun_line_carries_request(capsys=None):
    import io
    from contextlib import redirect_stdout
    fake = _FakeBridge(_res("HUMAN_REVIEW", needs_human=True))
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["add a frobnicator to the widget"], bridge=fake)
    out = buf.getvalue()
    assert "add a frobnicator to the widget — ANSWERS:" in out   # copy-pasteable continuation
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["x", "--json"], bridge=_FakeBridge(_res()))
    parsed = json.loads(buf.getvalue())
    assert parsed["devloop_result"]["terminal"] == "COMPLETE"


def test_keep_branch_exit_contract_and_threading():
    """C5: --keep-branch is threaded to the bridge, and exit 0 requires the branch to have been
    ACTUALLY kept — a hollow 0 with no kept branch would be a shell-boundary false-complete.
    Mutants killed: kept_branch clause weakened; keep_branch threading dropped."""
    fake = _FakeBridge(_res("COMPLETE", merged=False, kept_branch=True))
    assert cli.main(["x", "--keep-branch"], bridge=fake) == 0
    assert fake.calls[0][2]["keep_branch"] is True               # threaded through run_build
    # COMPLETE but nothing kept (e.g. no artifact) -> 1, never a hollow 0
    assert cli.main(["x", "--keep-branch"],
                    bridge=_FakeBridge(_res("COMPLETE", merged=False, kept_branch=False))) == 1
    # a kept branch WITHOUT the flag never grants 0 (the user asked for a merge)
    assert cli.main(["x"],
                    bridge=_FakeBridge(_res("COMPLETE", merged=False, kept_branch=True))) == 1
    # default path unchanged: no flag -> keep_branch=False reaches the bridge
    fake2 = _FakeBridge(_res("COMPLETE"))
    assert cli.main(["x"], bridge=fake2) == 0
    assert fake2.calls[0][2]["keep_branch"] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} cli tests passed")
