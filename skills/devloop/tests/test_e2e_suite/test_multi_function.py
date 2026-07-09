"""E2E: multiple functions in one file.

Task: Create calc.py with add(a,b), subtract(a,b), multiply(a,b), divide(a,b).
Tests the designer's ability to handle multiple criteria in a single file
and the coder's ability to produce all four functions correctly.
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_multi_function_calc():
    """Four functions in one file — stresses charter decomposition into multiple
    criteria and the coder producing all of them correctly."""
    skip_if_not_enabled()
    root = _e2e_dir("multi_func")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create calc.py with four functions: add(a, b) returning a+b, "
        "subtract(a, b) returning a-b, multiply(a, b) returning a*b, "
        "and divide(a, b) returning a/b. divide should raise ValueError if b is 0.",
        root, "calc4run")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"multi-function task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "calc4_e2e")
    assert mod.add(2, 3) == 5
    assert mod.subtract(10, 4) == 6
    assert mod.multiply(3, 4) == 12
    assert mod.divide(10, 2) == 5
    try:
        mod.divide(1, 0)
        assert False, "divide by zero should raise ValueError"
    except ValueError:
        pass
    print(f"E2E OK: multi_function_calc — COMPLETE, all 4 functions work")