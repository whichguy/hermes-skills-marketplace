"""E2E: conditional logic (fizzbuzz).

Task: Create fizzbuzz.py with a function fizzbuzz(n) that returns a list of
strings for numbers 1 to n, where "Fizz" for multiples of 3, "Buzz" for 5,
"FizzBuzz" for both, else the number as a string.
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_fizzbuzz():
    """Conditional logic with multiple branches — tests the designer's ability
    to write tests covering all branches and edge cases."""
    skip_if_not_enabled()
    root = _e2e_dir("fizzbuzz")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create fizzbuzz.py with a function fizzbuzz(n) that returns a list of "
        "strings for numbers 1 to n. For each number: if divisible by both 3 and 5, "
        "use 'FizzBuzz'; if divisible by 3, use 'Fizz'; if divisible by 5, use 'Buzz'; "
        "otherwise use the number as a string.",
        root, "fbun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"fizzbuzz task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "fb_e2e")
    result = mod.fizzbuzz(15)
    assert result[0] == "1"        # 1
    assert result[2] == "Fizz"    # 3
    assert result[4] == "Buzz"    # 5
    assert result[14] == "FizzBuzz"  # 15
    assert len(result) == 15
    print(f"E2E OK: fizzbuzz — COMPLETE, all branches verified")