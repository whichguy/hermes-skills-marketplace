"""E2E: single function, single file — the simplest happy path.

Task: Create calc.py with a function add(a, b) that returns the sum a + b.
Expected: COMPLETE, add(2,3)==5, add(-1,1)==0
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_simple_add():
    """Dead-simple, unambiguous task. Should reliably COMPLETE with real judges."""
    skip_if_not_enabled()
    root = _e2e_dir("simple_add")
    repo = _git_repo(root)
    out = _run_devloop(repo, "Create calc.py with a function add(a, b) that returns the sum a + b.",
                      root, "addrun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"simple task should COMPLETE: {res['terminal']} (trace {res.get('trace_path')})"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "calc_e2e")
    assert mod.add(2, 3) == 5
    assert mod.add(-1, 1) == 0
    print(f"E2E OK: simple_add — COMPLETE, add(2,3)=={mod.add(2,3)}, add(-1,1)=={mod.add(-1,1)}")