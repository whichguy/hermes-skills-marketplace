"""E2E: data transformation — flatten a nested list.

Task: Create flatten.py with flatten(nested) that takes a list of arbitrarily
nested lists and returns a flat list of all elements in depth-first order.
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_flatten():
    """Data transformation — tests recursive/nested logic and the designer's
    ability to write tests covering various nesting depths."""
    skip_if_not_enabled()
    root = _e2e_dir("flatten")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create flatten.py with a function flatten(nested) that takes a list of "
        "arbitrarily nested lists and returns a flat list of all elements in "
        "depth-first order. flatten([]) returns []. flatten([1, [2, [3, 4], 5]]) "
        "returns [1, 2, 3, 4, 5].",
        root, "flrun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"flatten task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "fl_e2e")
    assert mod.flatten([]) == []
    assert mod.flatten([1, 2, 3]) == [1, 2, 3]
    assert mod.flatten([1, [2, [3, 4], 5]]) == [1, 2, 3, 4, 5]
    assert mod.flatten([[1, 2], [3, [4, [5]]]]) == [1, 2, 3, 4, 5]
    print(f"E2E OK: flatten — COMPLETE, nested lists flattened correctly")