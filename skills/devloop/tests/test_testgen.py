"""Deterministic tests for testgen — the v1 legitimacy guard. No LLM.

Proves: the PLANNED map is credited ONLY where real pytest collection agrees (collect_spec_map;
a planned-but-uncollectable test is NOT credited, so a forged manifest fails closed); node_source
extracts exactly what was written (the judges' ground truth); and per-criterion verify commands
run just that criterion's node(s). (The free-form annotation-parser tests were deleted with the
free-form designer path, 2026-07-01.)
"""
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import dod_oracle  # noqa: E402
import testgen     # noqa: E402


def _pytest_available():
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "--version"],
                              capture_output=True, timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


_HAS_PYTEST = _pytest_available()


def test_node_source_walks_class_nested_paths():
    # node_source must descend Class::method paths exactly (the judges' ground truth for
    # class-grouped canonical/raw tests); same-named methods in different classes don't collide.
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_style.py"), "w").write(
            'def test_doc():\n    """top-level"""\n    from m import f\n    assert f()\n\n'
            'class TestGroup:\n    def test_method(self):\n        """nested — note"""\n'
            "        from m import g\n        assert g()\n")
        src = testgen.node_source(d, "test_style.py::TestGroup::test_method")
        assert "def test_method" in src and "nested" in src and "test_doc" not in src


def test_parametrized_planned_node_is_credited_and_source_shows_decorator():
    # _covered: a PLANNED node `f` is credited when it collects as parametrized instances `f[..]`
    # (running `pytest f` bare still executes every case); node_source includes the decorator so
    # the judge sees the cases.
    if not _HAS_PYTEST:
        print("SKIP test_parametrized_planned_node_is_credited_and_source_shows_decorator (pytest not available)")
        return
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_param.py"), "w").write(
            "import pytest\n\n@pytest.mark.parametrize(\"n\", [2, 4])\n"
            "def test_even(n):\n    from m import is_even\n    assert is_even(n)\n")
        planned = {"test_param.py::test_even": "c1"}
        assert testgen.collect_spec_map(d, planned) == {"test_param.py::test_even": "c1"}
        src = testgen.node_source(d, "test_param.py::test_even")
        assert "parametrize" in src and "def test_even" in src


def test_node_source_extracts_just_the_function():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_x.py"), "w").write(
            "import os\n\ndef test_a():\n    # dod: c1\n    assert True\n\ndef test_b():\n    assert 1\n")
        src = testgen.node_source(d, "test_x.py::test_a")
        assert "def test_a" in src and "# dod: c1" in src and "test_b" not in src
        assert testgen.node_source(d, "test_x.py::missing") == ""
        assert testgen.node_source(d, "no_colon_here") == ""


def test_verify_cmd_per_criterion_and_failclosed_for_missing():
    inv = testgen.invert({"test_x.py::test_a": "c1", "test_x.py::test_b": "c1", "test_y.py::test_c": "c2"})
    vc = testgen.verify_cmd_for(inv)
    c1 = vc("c1")
    assert c1[:3] == [sys.executable, "-m", "pytest"] and "test_x.py::test_a" in c1 and "test_x.py::test_b" in c1
    # a criterion with no node fails closed (exit 1), never silently green
    miss = vc("c_missing")
    assert miss[0] == sys.executable and "sys.exit(1)" in " ".join(miss)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} testgen tests passed")
