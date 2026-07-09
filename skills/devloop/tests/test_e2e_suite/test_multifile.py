"""E2E: multi-file with cross-module import (quarantined — judge non-determinism).

Task: Create mathutils.py (is_even, is_prime) + filters.py (evens, primes) with
filters.py importing from mathutils.py.

QUARANTINED: fails ~50% due to judge non-determinism. The tiebreaker judge
(added 2026-07-09) should reduce this. Run with DEVLOOP_RUN_MULTIFILE=1.
"""
import importlib
import os
import sys

from tests.test_e2e_suite.conftest import (
    skip_if_not_enabled, skip_if_quarantined, _e2e_dir, _git_repo, _run_devloop,
)


def test_multifile():
    """Multi-file with cross-module import — the hardest scenario. Quarantined
    due to judge non-determinism; the tiebreaker should help."""
    skip_if_not_enabled()
    skip_if_quarantined("multifile")
    root = _e2e_dir("multifile_suite")
    repo = _git_repo(root)
    out = _run_devloop(
        repo,
        "Create two modules in the repo. mathutils.py with is_even(n) returning True iff n is even, "
        "and is_prime(n) returning True iff n is a prime number (n < 2 is not prime). filters.py with "
        "evens(nums) returning the even numbers from the list nums in their original order, and "
        "primes(nums) returning the prime numbers from nums in order. filters.py MUST import and use "
        "the functions from mathutils.py.",
        root, "mfrun")
    res = out["result"]
    wt = out["worktree"]["path"]
    assert res["terminal"] == "COMPLETE", f"multi-file task should COMPLETE: {res['terminal']}"
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
    print(f"E2E OK: multifile — COMPLETE, mathutils+filters work across modules")