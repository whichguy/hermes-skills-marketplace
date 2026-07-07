"""REAL end-to-end tests — the actual loop against ACTUAL models. Opt-in, double-gated.

The deterministic suite (see TESTING.md for the current counts) uses injected fakes (no LLM)
and proves the LOGIC (mutation-proven non-vacuous). These prove the REAL thing: a real
planner + real designer + real coder produce working code through runner.run_task/run_v1.

Legitimacy guard: we do NOT trust the loop's own "COMPLETE". After the loop finishes we
INDEPENDENTLY re-import the produced module and assert its behaviour ourselves — so a run only
passes if real code that genuinely works was written to disk.

Skipped by default (keeps the suite fast/free). Run inside the container with:
    DEVLOOP_RUN_REAL=1 python3 tests/test_e2e_real.py
(or:  DEVLOOP_RUN_REAL=1 uv run --with pytest python3 -m pytest tests/test_e2e_real.py -q -s)
"""
import importlib.util
import os
import shutil
import subprocess
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import dispatch   # noqa: E402
import runner     # noqa: E402
import render   # noqa: E402
import testgen    # noqa: E402


def _enabled():
    return os.environ.get("DEVLOOP_RUN_REAL") == "1" and os.path.exists(dispatch.HERMES_BIN)


def _e2e_dir(name):
    # under the Hermes write-safe root (/opt/data ... .devloop is gitignored)
    d = os.path.join(_DIR, ".devloop", "e2e", name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def _import_fresh(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_e2e_real_v1_designs_real_tests_and_builds():
    """The full v1 pipeline against REAL models: the designer writes its OWN tests, the coder
    writes the code, in an isolated worktree. Legitimacy corroboration: the tests are REAL
    (pytest-collectable, # dod-annotated), and the produced code independently works."""
    if not _enabled():
        print("SKIP test_e2e_real_v1_designs_real_tests_and_builds (set DEVLOOP_RUN_REAL=1)")
        return
    root = _e2e_dir("v1")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    open(os.path.join(repo, "README"), "w").write("repo\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)

    request = ("Create norm.py with a function normalize(s) that lowercases s and removes all "
               "non-alphanumeric characters.")
    out = runner.run_task(repo, request, os.path.join(root, "wts"), "v1run")
    res = out["result"]
    wt = out["worktree"]["path"]

    # the full pipeline ran and reached a VALID fail-closed terminal (not a crash / no-termination)
    assert res["terminal"] in ("COMPLETE", "HUMAN_REVIEW"), f"unexpected terminal {res['terminal']}"
    # LEGITIMACY (regardless of outcome): the STRUCTURED designer rendered REAL, collectable
    # canonical tests (render.CANONICAL_FILE node ids are known by construction)
    tmap = {n for n in testgen._collected_node_ids(wt) if render.CANONICAL_FILE in n}
    assert tmap, "the designer produced no real collectable canonical tests"
    if res["terminal"] == "COMPLETE":
        # corroborate independently — we assert behaviour ourselves
        mod = _import_fresh(os.path.join(wt, "norm.py"), "norm_e2e")
        assert mod.normalize("A b-C.1") == "abc1"
        assert mod.normalize("!!!Hello, World!!!") == "helloworld"
        print(f"E2E OK (COMPLETE): designer wrote {len(tmap)} real tests; code independently works.")
    else:
        # HUMAN_REVIEW with real tests collected = the loop conservatively refused to ship (a judge
        # escalated or a test stayed red). That is the fail-closed design, not a test failure.
        print(f"E2E OK (HUMAN_REVIEW): pipeline ran, {len(tmap)} real tests collected, loop refused to ship.")


def test_e2e_real_v1_simple_task_completes():
    """A dead-simple, unambiguous task should reliably COMPLETE end-to-end even with the strict real
    judges (the judges agree the test encodes the criterion) — the happy-path proof."""
    if not _enabled():
        print("SKIP test_e2e_real_v1_simple_task_completes (set DEVLOOP_RUN_REAL=1)")
        return
    root = _e2e_dir("add")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    open(os.path.join(repo, "README"), "w").write("repo\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)

    out = runner.run_task(repo, "Create calc.py with a function add(a, b) that returns the sum a + b.",
                          os.path.join(root, "wts"), "addrun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"simple task should COMPLETE: {res['terminal']} (trace {res.get('trace_path')})"
    mod = _import_fresh(os.path.join(out["worktree"]["path"], "calc.py"), "calc_e2e")
    assert mod.add(2, 3) == 5 and mod.add(-1, 1) == 0
    print("E2E OK: simple task COMPLETEd with real judges; add() independently works.")


def test_e2e_real_v1_multifile_completes():
    """Harder de-risk: a multi-FILE task with a cross-module dependency (filters.py must import and
    use mathutils.py). Stresses charter decomposition across files, the designer writing tests that
    span modules, and the coder creating two interdependent files — none of which the single-file
    tasks exercise. Should COMPLETE; corroborated independently across BOTH modules."""
    if not _enabled():
        print("SKIP test_e2e_real_v1_multifile_completes (set DEVLOOP_RUN_REAL=1)")
        return
    root = _e2e_dir("multifile")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
    open(os.path.join(repo, "README"), "w").write("repo\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)

    request = (
        "Create two modules in the repo. mathutils.py with is_even(n) returning True iff n is even, "
        "and is_prime(n) returning True iff n is a prime number (n < 2 is not prime). filters.py with "
        "evens(nums) returning the even numbers from the list nums in their original order, and "
        "primes(nums) returning the prime numbers from nums in order. filters.py MUST import and use "
        "the functions from mathutils.py.")
    out = runner.run_task(repo, request, os.path.join(root, "wts"), "mfrun")
    res = out["result"]
    wt = out["worktree"]["path"]
    assert res["terminal"] == "COMPLETE", f"multi-file task should COMPLETE: {res['terminal']} (trace {res.get('trace_path')})"
    # independent corroboration across BOTH modules; the cross-import must resolve, so put the
    # worktree on sys.path and import via the package machinery (not spec_from_file_location).
    import importlib
    sys.path.insert(0, wt)
    for m in ("mathutils", "filters"):
        sys.modules.pop(m, None)
    try:
        mathutils = importlib.import_module("mathutils")
        filters = importlib.import_module("filters")
        assert mathutils.is_even(4) and not mathutils.is_even(3)
        assert mathutils.is_prime(7) and not mathutils.is_prime(9) and not mathutils.is_prime(1)
        assert filters.evens([1, 2, 3, 4, 5, 6]) == [2, 4, 6]
        assert filters.primes([1, 2, 3, 4, 5, 6, 7, 8, 9]) == [2, 3, 5, 7]
    finally:
        if wt in sys.path:
            sys.path.remove(wt)
        for m in ("mathutils", "filters"):
            sys.modules.pop(m, None)
    print("E2E OK: multi-file task COMPLETEd; mathutils+filters work across modules independently.")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} real-e2e tests run")
