"""E2E: error handling — division by zero raises ValueError.

Task: Create safe_div.py with safe_divide(a, b) that returns a/b, raising
ValueError with message "cannot divide by zero" when b is 0.
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_error_handling():
    """Error handling — tests the designer's ability to verify exception-raising
    behavior, not just return-value correctness."""
    skip_if_not_enabled()
    root = _e2e_dir("error_handling")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create safe_div.py with a function safe_divide(a, b) that returns a divided by b. "
        "If b is 0, raise ValueError with the message 'cannot divide by zero'.",
        root, "sdun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"error handling task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "sd_e2e")
    assert mod.safe_divide(10, 2) == 5
    assert mod.safe_divide(7, 1) == 7
    try:
        mod.safe_divide(1, 0)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "cannot divide by zero" in str(e), f"wrong error message: {e}"
    print(f"E2E OK: error_handling — COMPLETE, ValueError raised correctly")