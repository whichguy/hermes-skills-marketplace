"""Deterministic tests for render.py + testgen.collect_spec_map — structured test design. NO LLM.

Proves: a structured spec renders to canonical pytest that COLLECTS (before the impl exists) and is
credited ONLY when it really collects (collect_spec_map intersects with real `pytest --collect-only`,
so the renderer can't fabricate coverage); malformed entries are SKIPPED (fail-closed); the rendered
assertion really exercises the criterion (fails vs a wrong impl); raises-cases really assert; and the
oracle:"raw" escape hatch is name-pinned. Fail-closed invariants here are mutation-covered.
"""
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import render    # noqa: E402
import testgen   # noqa: E402


def _has_pytest():
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "--version"],
                              capture_output=True, timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


_HAS_PYTEST = _has_pytest()


def _pytest_rc(d, *nodes):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *nodes],
                          cwd=d, capture_output=True, text=True).returncode


# --- render_spec validation (no collection needed) -----------------------------------
def test_render_skips_malformed_entry_failclosed():
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f"},                                   # no cases
            {"criterion_id": "c2", "module": "m", "call": "f",
             "cases": [{"args": [1], "expected": 1, "raises": "ValueError"}]},                    # both -> ambiguous
            {"criterion_id": "c3", "module": "m", "call": "f", "cases": [{"args": [1], "raises": "MyError"}]},  # exc not allow-listed
            {"criterion_id": "c4", "module": "1bad", "call": "f", "cases": [{"args": [1], "expected": 1}]},     # bad module regex
            {"criterion_id": "ok", "module": "m", "call": "f", "cases": [{"args": [1], "expected": 1}]}]}       # valid
        assert render.render_spec(spec, d) == {"test_devloop_dod.py::test_ok": "ok"}


def test_render_raw_enforces_name():
    with tempfile.TemporaryDirectory() as d:
        bad = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "oracle": "raw", "raw_test": "def test_wrong():\n    assert True\n"}]}
        assert render.render_spec(bad, d) == {}                  # fn name != test_c1 -> not rendered (fail-closed)
        good = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "oracle": "raw", "raw_test": "def test_c1():\n    assert True\n"}]}
        assert render.render_spec(good, d) == {"test_devloop_dod.py::test_c1": "c1"}


def test_render_empty_or_bad_spec_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        assert render.render_spec({}, d) == {}
        assert render.render_spec({"schema_version": 2, "tests": []}, d) == {}      # wrong version
        assert render.render_spec({"schema_version": 1, "tests": "nope"}, d) == {}
        assert render.render_spec("not a dict", d) == {}


# --- collect_spec_map: the legitimacy intersection -----------------------------------
def test_render_structured_entry_collects_and_credits():
    if not _HAS_PYTEST:
        print("SKIP test_render_structured_entry (no pytest)"); return
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "calc", "call": "add", "cases": [{"args": [2, 3], "expected": 5}]},
            {"criterion_id": "c2", "module": "calc", "call": "sub", "cases": [{"args": [5, 3], "expected": 2}]}]}
        planned = render.render_spec(spec, d)
        # collects BEFORE calc.py exists (import-inside-fn), and is credited
        assert testgen.collect_spec_map(d, planned) == {
            "test_devloop_dod.py::test_c1": "c1", "test_devloop_dod.py::test_c2": "c2"}


def test_render_drops_uncollectable_planned_node():
    # a raw entry that PASSES name validation (planned) but does NOT collect (module-level bad import)
    # must be dropped by the real-collection intersection -> coverage fails closed, never fabricated.
    if not _HAS_PYTEST:
        print("SKIP test_render_drops_uncollectable (no pytest)"); return
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "oracle": "raw",
             "raw_test": "import nope_missing_xyz\ndef test_c1():\n    assert True\n"}]}
        planned = render.render_spec(spec, d)
        assert planned == {"test_devloop_dod.py::test_c1": "c1"}     # renderer planned it
        assert testgen.collect_spec_map(d, planned) == {}           # but it can't collect -> dropped


def test_render_emits_real_assertion():
    # the rendered assertion must really exercise the criterion: RED vs a wrong impl, GREEN vs right.
    if not _HAS_PYTEST:
        print("SKIP test_render_emits_real_assertion (no pytest)"); return
    with tempfile.TemporaryDirectory() as d:
        render.render_spec({"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f", "cases": [{"args": [2, 3], "expected": 5}]}]}, d)
        node = "test_devloop_dod.py::test_c1"
        open(os.path.join(d, "m.py"), "w").write("def f(a, b):\n    return 500\n")          # wrong
        assert _pytest_rc(d, node) != 0
        open(os.path.join(d, "m.py"), "w").write("def f(a, b):\n    return a + b\n")         # right
        assert _pytest_rc(d, node) == 0


def test_render_raises_case():
    if not _HAS_PYTEST:
        print("SKIP test_render_raises_case (no pytest)"); return
    with tempfile.TemporaryDirectory() as d:
        render.render_spec({"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f", "cases": [{"args": ["x"], "raises": "TypeError"}]}]}, d)
        node = "test_devloop_dod.py::test_c1"
        open(os.path.join(d, "m.py"), "w").write("def f(a):\n    return a\n")                 # does NOT raise -> RED
        assert _pytest_rc(d, node) != 0
        open(os.path.join(d, "m.py"), "w").write("def f(a):\n    raise TypeError('x')\n")     # raises -> GREEN
        assert _pytest_rc(d, node) == 0


def test_render_mocks_and_approx():
    if not _HAS_PYTEST:
        print("SKIP test_render_mocks_and_approx (no pytest)"); return
    with tempfile.TemporaryDirectory() as d:
        render.render_spec({"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "g", "cases": [{"args": [], "expected": 42}],
             "mocks": [{"target": "m.now", "return_value": 42}]},
            {"criterion_id": "c2", "module": "m", "call": "h",
             "cases": [{"args": [0.1, 0.2], "expected": 0.3, "approx": True}]}]}, d)
        open(os.path.join(d, "m.py"), "w").write(
            "def now():\n    return 0\ndef g():\n    return now()\ndef h(a, b):\n    return a + b\n")
        assert _pytest_rc(d, "test_devloop_dod.py::test_c1", "test_devloop_dod.py::test_c2") == 0


def test_designer_spec_via_ask_renders_and_collects():
    # the structured designer: mock the model to return a SPEC -> WE render + return the REAL map.
    if not _HAS_PYTEST:
        print("SKIP test_designer_spec_via_ask (no pytest)"); return
    import dispatch
    with tempfile.TemporaryDirectory() as d:
        spec = ('{"schema_version":1,"tests":[{"criterion_id":"c1","module":"calc","call":"add",'
                '"cases":[{"args":[2,3],"expected":5}]}]}')
        orig = dispatch._chat
        dispatch._chat = lambda p, m, **k: (spec, 0)
        try:
            charter = {"dod": [{"id": "c1", "criterion": "add returns sum", "verify_intent": "add(2,3)==5"}]}
            m = dispatch.designer_spec_via_ask(d)(charter)
            # C2: the oracle filename is PER-RUN (derived from the target dir's basename), so
            # re-runs accumulate protection and concurrent runs never collide on the file.
            fname = render.canonical_file(os.path.basename(os.path.realpath(d)))
            assert m == {f"{fname}::test_c1": "c1"}
            assert os.path.exists(os.path.join(d, fname))
        finally:
            dispatch._chat = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} render tests passed")
