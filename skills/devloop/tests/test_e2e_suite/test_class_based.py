"""E2E: class-based task — Stack with push/pop/peek.

Task: Create stack.py with a Stack class supporting push, pop, peek, and is_empty.
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_class_stack():
    """Class-based task — tests the designer's ability to write tests for
    stateful objects with methods, not just pure functions."""
    skip_if_not_enabled()
    root = _e2e_dir("class_stack")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create stack.py with a class Stack that has: push(item) to add an item, "
        "pop() to remove and return the top item (raise IndexError if empty), "
        "peek() to return the top item without removing it (raise IndexError if empty), "
        "and is_empty() returning True if the stack has no items.",
        root, "stun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"class task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "st_e2e")
    s = mod.Stack()
    assert s.is_empty()
    s.push(1)
    s.push(2)
    assert not s.is_empty()
    assert s.peek() == 2
    assert s.pop() == 2
    assert s.peek() == 1
    assert s.pop() == 1
    assert s.is_empty()
    try:
        s.pop()
        assert False, "pop on empty stack should raise IndexError"
    except IndexError:
        pass
    print(f"E2E OK: class_stack — COMPLETE, Stack works correctly")