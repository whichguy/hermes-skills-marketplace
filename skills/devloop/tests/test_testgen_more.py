"""Deterministic tests for testgen — closing confirmed coverage gaps. No LLM.

Pins three currently-uncovered legitimacy guards:
  - collect_spec_map MUST RAISE when pytest is unavailable (never return planned -> fail-OPEN),
  - _covered's `nid + "["` parametrize boundary blocks a same-prefix sibling from false-crediting
    a criterion it never exercises.

The pytest-unavailable branches are driven by swapping the module global `testgen.pytest_available`
(restored in finally) — exactly as the suite swaps dispatch._chat — so NO real pytest run is needed.
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import testgen  # noqa: E402


def test_collect_spec_map_raises_when_pytest_unavailable():
    # collect_spec_map feeds the structured-designer path: if a missing-pytest runtime returned
    # `planned` instead of raising, EVERY renderer-claimed node would be credited with ZERO real
    # collection -> fail-OPEN false COMPLETE. The raise is the v1 legitimacy guard.
    orig = testgen.pytest_available
    testgen.pytest_available = lambda: False
    try:
        with tempfile.TemporaryDirectory() as d:
            planned = {"test_x.py::test_a": "c1"}   # non-empty -> skips the early `if not planned`
            raised = False
            try:
                testgen.collect_spec_map(d, planned)
            except RuntimeError:
                raised = True
            assert raised, "collect_spec_map must RAISE when pytest is unavailable"
            # control: empty planned hits the early `if not planned: return {}` BEFORE the pytest
            # check -> {} with no raise (the `return planned` mutant would also return {} here), so
            # the raise is bound to the non-empty path — not a function that always raises.
            assert testgen.collect_spec_map(d, {}) == {}
    finally:
        testgen.pytest_available = orig


def test_covered_parametrize_boundary():
    # The `nid + "["` boundary credits a node by EXACT match or as parametrized instances f[..],
    # but must NOT credit a same-prefix sibling (test_abc) for a criterion annotated on test_a.
    # The `c.startswith(nid)` mutant drops the `[` and false-credits the sibling -> fail-OPEN.
    assert testgen._covered("test_x.py::test_a", {"test_x.py::test_abc"}) is False   # prefix collision must NOT credit
    assert testgen._covered("test_x.py::test_a", {"test_x.py::test_a[1]"}) is True   # real parametrized instance IS credited
    assert testgen._covered("test_x.py::test_a", {"test_x.py::test_a"}) is True      # exact match still credited


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} testgen_more tests passed")
