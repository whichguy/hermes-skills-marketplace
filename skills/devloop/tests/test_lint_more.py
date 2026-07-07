"""More deterministic tests for lint.py — closing confirmed coverage gaps (surviving mutants). NO LLM.

Each test below pins behaviour the existing test_lint.py suite leaves unexercised, in a way that
the hypothetical mutant (old->new) would FAIL:
  - the spawn-failure except branch fail-CLOSES (ok=False) and surfaces the un-spawnable entry;
  - failures() classifies error/None entries AND never flags skipped (tool-absent) entries;
  - extension lookup is case-insensitive (.PY behaves like .py on case-insensitive filesystems);
  - discover().covered honestly reflects bool(runnable), not a hardcoded True;
  - the .js argv builder really runs `node --check <file>` end-to-end (not a vacuous `node --version`).
All real-subprocess paths use stdlib linters / node; the spawn-failure path monkeypatches
lint.subprocess.run (restored in finally) so no real process is ever spawned for that case.
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import lint  # noqa: E402

_BROKEN = "def f(:\n    return 1\n"      # SyntaxError
_CLEAN = "def f():\n    return 1\n"


def _raise_oserror(*a, **k):
    # stand-in for subprocess.run that passes available() but cannot exec (OOM/EMFILE/exec-format)
    raise OSError("exec format error")


# --- gap 1: spawn-failure except branch must set ok=False (fail-CLOSED), never ok=True --------
def test_lint_paths_spawn_failure_fails_closed():
    orig = lint.subprocess.run
    lint.subprocess.run = _raise_oserror
    try:
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.py"); open(good, "w").write(_CLEAN)  # syntactically CLEAN
            ok, res = lint.lint_paths([good])
            # good.py is clean, so the ONLY route to ok=False is the spawn-failure except branch.
            assert ok is False                                          # mutant `ok = True` -> this fails
            errs = [r for r in res if r.get("error")]
            assert len(errs) >= 1                                       # the un-spawnable entr(ies) (.py runs py-syntax + ruff)
            assert all(e["exit_code"] is None for e in errs)           # recorded as un-spawnable, not green
    finally:
        lint.subprocess.run = orig


# --- gap 2: failures() must SURFACE the un-spawnable (error/None) entry -----------------------
def test_failures_flags_unspawnable_error_entry():
    orig = lint.subprocess.run
    lint.subprocess.run = _raise_oserror
    try:
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.py"); open(good, "w").write(_CLEAN)
            _, res = lint.lint_paths([good])
            f = lint.failures(res)
            # the entries have exit_code=None (None in (0,None)) so ONLY the `r.get('error') or` clause
            # flags them; the mutant drops that clause -> failures() == [] -> this assertion fails.
            assert len(f) >= 1                                          # .py runs py-syntax + ruff -> both un-spawnable
            assert all(e.get("error") and e.get("exit_code") is None for e in f)
    finally:
        lint.subprocess.run = orig


# --- gap 3: extension lookup must be case-insensitive (.PY -> .py) ----------------------------
def test_lint_paths_uppercase_extension_is_linted():
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "Bad.PY"); open(bad, "w").write(_BROKEN)   # SyntaxError, UPPERCASE ext
        ok, res = lint.lint_paths([bad])
        # with .lower() dropped, LINTERS.get('.PY') is None -> recorded as skipped -> ok stays True.
        assert ok is False and lint.failures(res)                       # py-syntax (stdlib) caught it
        # control: a CLEAN uppercase-ext file still maps to the linter and passes (ok True), proving
        # the gate isn't just constant-failing on the extension.
        good = os.path.join(d, "Good.PY"); open(good, "w").write(_CLEAN)
        assert lint.lint_paths([good])[0] is True


# --- gap 4: skipped (tool-absent / unmapped) results must NEVER count as failures ------------
def test_failures_never_flags_skipped_results():
    skips = [
        {"path": "x.md", "skipped": "no linter for this file type"},
        {"path": "y.css", "linter": "stylelint", "skipped": "tool not installed"},
    ]
    # exit_code absent -> .get('exit_code') is None -> must classify as NOT a failure.
    assert lint.failures(skips) == []                                   # mutant `not in (0,)` -> non-empty
    # control: a genuine nonzero-exit entry is STILL flagged (guards against a vacuous test).
    assert lint.failures([{"path": "z.py", "linter": "py-syntax", "exit_code": 1, "output": "err"}]) != []


# --- gap 5: discover().covered must reflect bool(runnable), not a hardcoded True --------------
def test_discover_covered_reflects_runtime_availability():
    rep = lint.discover()
    by_ext = {tuple(r["extensions"]): r for r in rep}
    # web-stack tools are absent here -> covered must be False; the mutant forces covered=True.
    assert by_ext[(".css", ".scss", ".less")]["covered"] == lint._on_path("stylelint")
    assert by_ext[(".html", ".htm")]["covered"] == lint._on_path("htmlhint")
    # control: a stdlib-backed language is genuinely covered (True == True), so the equality test
    # above is pinning real availability, not comparing two constant Falses.
    assert by_ext[(".py",)]["covered"] is True


# --- gap 6: the .js builder runs `node --check <file>` end-to-end, not a vacuous argv ---------
def test_lint_paths_js_check_runs_against_the_file():
    if not lint._on_path("node"):
        return                                                          # node absent -> not the path under test
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.js"); open(bad, "w").write("function (\n")   # JS SyntaxError
        ok, res = lint.lint_paths([bad])
        # mutant `['node','--version']` ignores the file and exits 0 -> ok True -> this fails.
        assert ok is False and lint.failures(res)
        good = os.path.join(d, "ok.js"); open(good, "w").write("const x = 1;\n")
        assert lint.lint_paths([good])[0] is True                       # valid JS passes the same builder


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} lint tests passed")
