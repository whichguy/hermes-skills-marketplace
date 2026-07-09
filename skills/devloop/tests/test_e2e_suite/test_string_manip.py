"""E2E: string manipulation with edge cases.

Task: Create strings.py with a function reverse_words(s) that reverses the order
of words in a string. Handle empty string, single word, multiple spaces.
Expected: COMPLETE, reverse_words("hello world")=="world hello"
"""

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, _e2e_dir, _git_repo, _import_fresh, _run_devloop,
    _find_produced_file,
)


def test_string_reverse_words():
    """String manipulation with edge cases — tests the designer's ability to write
    tests covering empty strings, single words, and multi-word inputs."""
    skip_if_not_enabled()
    root = _e2e_dir("string_reverse")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create strings.py with a function reverse_words(s) that takes a string "
        "and returns the words in reverse order, joined by single spaces. "
        "Empty string returns empty string.",
        root, "strun")
    res = out["result"]
    assert res["terminal"] == "COMPLETE", f"string task should COMPLETE: {res['terminal']}"
    produced = _find_produced_file(out["worktree"]["path"])
    mod = _import_fresh(produced, "str_e2e")
    assert mod.reverse_words("hello world") == "world hello"
    assert mod.reverse_words("one") == "one"
    assert mod.reverse_words("") == ""
    assert mod.reverse_words("a b c") == "c b a"
    print(f"E2E OK: string_reverse_words — COMPLETE")