"""More deterministic tests for render.py — close confirmed mutation-coverage gaps. NO LLM.

Each test pins a fail-closed / injection-barrier guard in render_spec that the existing
test_render.py suite leaves unexercised: every one drives a malformed designer spec and asserts
the entry is SKIPPED (empty manifest), with a CONTROL asserting the well-formed twin still credits
(so a constant `{}`-return could not pass both halves). Pure render_spec validation — no real pytest
collection needed, no model call.
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import render    # noqa: E402

_NODE = "test_devloop_dod.py::test_c1"


# --- _render_case: kwargs-key identifier guard (render.py:49) -------------------------
def test_render_skips_bad_kwarg_key_failclosed():
    # each kwarg key flows UNESCAPED into f"{k}={_lit(v)}"; the _IDENT guard is the only
    # injection barrier. A non-identifier key must drop the whole entry (fail-closed).
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "kwargs": {"x=1) bad": 1}, "expected": 1}]}]}
        assert render.render_spec(spec, d) == {}
        # CONTROL: a valid kwarg key DOES render & credit -> distinguishes from a constant {}.
        ok = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "kwargs": {"x": 1}, "expected": 1}]}]}
        assert render.render_spec(ok, d) == {_NODE: "c1"}


# --- _render_entry: call-name identifier guard (render.py:112) ------------------------
def test_render_skips_bad_call_regex_failclosed():
    # `call` is inserted UNESCAPED into `from {module} import {call}` and `assert {call}(...)`;
    # the module half is covered (c4 in test_render) but the call half is not. Mirror it.
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "1bad",
             "cases": [{"args": [1], "expected": 1}]}]}
        assert render.render_spec(spec, d) == {}
        # CONTROL: same entry with a valid call symbol renders & credits.
        ok = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [1], "expected": 1}]}]}
        assert render.render_spec(ok, d) == {_NODE: "c1"}


# --- _mock_with: side_effect allowlist guard (render.py:76) ---------------------------
def test_render_skips_nonallowlisted_side_effect_failclosed():
    # side_effect is emitted UNESCAPED as `side_effect={m['side_effect']}` (NOT repr) — the
    # _ALLOWED_EXC allowlist is the sole defense against arbitrary code reaching the file.
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "g",
             "cases": [{"args": [], "expected": 42}],
             "mocks": [{"target": "m.now", "side_effect": "NotAllowed"}]}]}
        assert render.render_spec(spec, d) == {}
        # CONTROL: an allow-listed exception name DOES render & credit.
        ok = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "g",
             "cases": [{"args": [], "expected": 42}],
             "mocks": [{"target": "m.now", "side_effect": "ValueError"}]}]}
        assert render.render_spec(ok, d) == {_NODE: "c1"}


# --- render_spec: duplicate criterion_id dedup (render.py:149) ------------------------
def test_render_dedup_keeps_first_def():
    # Two `def test_c1():` in one module means the LAST shadows the first at import while the
    # node stays credited — a false-complete path. The return MAP is identical with/without the
    # `if cid in seen` guard, so the kill MUST inspect file content (one def, no lax body).
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f", "cases": [{"args": [1], "expected": 1}]},
            {"criterion_id": "c1", "module": "m", "call": "f", "cases": [{"args": [1], "expected": 999}]}]}
        manifest = render.render_spec(spec, d)
        assert manifest == {_NODE: "c1"}                              # map equal either way
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert content.count("def test_c1(") == 1                    # mutant emits two defs
        assert "999" not in content                                  # lax shadowing body must be absent


# --- _render_case: args/kwargs container-type guard (render.py:47) --------------------
def test_render_skips_nonlist_args_or_nondict_kwargs_failclosed():
    # Malformed case shape (non-list args / non-dict kwargs) must fail closed rather than render a
    # meaningless test that fabricates DoD coverage (a str arg would iterate into per-char args).
    with tempfile.TemporaryDirectory() as d:
        bad_args = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": "notalist", "expected": 1}]}]}
        assert render.render_spec(bad_args, d) == {}
        bad_kwargs = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "kwargs": "notadict", "expected": 1}]}]}
        assert render.render_spec(bad_kwargs, d) == {}
        # CONTROL: proper list args + dict kwargs render & credit.
        ok = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [1], "expected": 1}]}]}
        assert render.render_spec(ok, d) == {_NODE: "c1"}


# --- _valid_raw: top-level-class rejection (render.py:93, `and not classes`) ----------
def test_render_raw_rejects_toplevel_class_failclosed():
    # The raw escape hatch is legit only because it's exactly one top-level fn named fn and NO
    # top-level class (node-id predictability). An accepted top-level class adds extra auto-collected
    # uncredited nodes + import side effects, defeating the name-pinning invariant.
    with tempfile.TemporaryDirectory() as d:
        raw = "def test_c1():\n    assert True\nclass TestExtra:\n    def test_x(self):\n        assert True\n"
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "oracle": "raw", "raw_test": raw}]}
        assert render.render_spec(spec, d) == {}
        # CONTROL: same raw WITHOUT the top-level class renders & credits.
        ok = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "oracle": "raw", "raw_test": "def test_c1():\n    assert True\n"}]}
        assert render.render_spec(ok, d) == {_NODE: "c1"}


# --- C2: per-run oracle filenames (repeat/concurrent runs must not clobber each other) -
def test_canonical_file_is_per_run_and_sanitized():
    # No run_name -> the bare canonical default (fixtures/greenfield unchanged).
    assert render.canonical_file() == render.CANONICAL_FILE
    assert render.canonical_file("") == render.CANONICAL_FILE
    # A real worktree basename -> a distinct, deterministic, identifier-safe filename.
    a = render.canonical_file("build-9442-1783085220539703889")
    assert a == "test_devloop_dod_build_9442_1783085220539703889.py"
    assert a != render.canonical_file("build-9443-x")           # distinct runs -> distinct files
    # sanitize-not-trust: the slug lands in a filesystem path + pytest node ids.
    evil = render.canonical_file("../..//weird name!;rm -rf")
    assert "/" not in evil and " " not in evil and ";" not in evil and ".." not in evil[:-3]
    assert evil.startswith("test_devloop_dod_") and evil.endswith(".py")


def test_render_spec_run_names_accumulate_not_clobber():
    """Two runs against the SAME tree write two oracle files; run 2 never erases run 1's DoD
    protection (the whole-suite regression gate keeps enforcing run 1's criteria)."""
    spec = {"schema_version": 1, "tests": [
        {"criterion_id": "c1", "oracle": "raw", "raw_test": "def test_c1():\n    assert True\n"}]}
    with tempfile.TemporaryDirectory() as d:
        m1 = render.render_spec(spec, d, run_name="build-1-aa")
        m2 = render.render_spec(spec, d, run_name="build-2-bb")
        f1, f2 = render.canonical_file("build-1-aa"), render.canonical_file("build-2-bb")
        assert list(m1) == [f"{f1}::test_c1"] and list(m2) == [f"{f2}::test_c1"]
        assert os.path.exists(os.path.join(d, f1)) and os.path.exists(os.path.join(d, f2))


# --- C6: the oracle ships INTO the target repo — import only what it references ---------
def test_render_header_imports_only_whats_used():
    """Unused imports (F401) fail strict-lint target repos; a MISSING import when mocks/raises
    are rendered would NameError the whole oracle."""
    with tempfile.TemporaryDirectory() as d:
        plain = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [1], "expected": 2}]}]}
        assert render.render_spec(plain, d)
        src = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "import pytest" not in src and "mock" not in src   # nothing referenced -> no imports
        compile(src, "oracle.py", "exec")                         # still valid python
        rich = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "raises": "ValueError"}],
             "mocks": [{"target": "m.dep", "return_value": 1}]}]}
        assert render.render_spec(rich, d, run_name="r2")
        src2 = open(os.path.join(d, render.canonical_file("r2"))).read()
        assert "import pytest" in src2 and "from unittest import mock" in src2
        compile(src2, "oracle2.py", "exec")


# ── Semantic correctness: rendered output uses the RIGHT patterns ────────────────────
# (Advisor DeepSeek P2: regression tests that verify render output quality, not just
# injection-barrier rejection. These pin the _lit() datetime fix and mock assertion
# rendering so they can't silently regress.)


def test_render_datetime_expected_produces_real_object():
    """_lit() must emit `datetime(2026, 7, 6)` not `'datetime(2026, 7, 6)'` —
    string-literal datetime comparisons are the #1 judge-rejected pattern."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": dt.datetime(2026, 7, 6, 12, 0)}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "datetime(2026, 7, 6, 12, 0)" in content, f"real datetime object not found in:\n{content}"
        assert "'datetime(" not in content, "string-literal datetime leaked into rendered test"
        assert '"datetime(' not in content, "string-literal datetime leaked into rendered test"


def test_render_datetime_in_args_produces_real_object():
    """Datetime args must also render as real objects (call_args comparison, not string ==)."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [dt.datetime(2026, 7, 6, 9, 30)], "expected": True}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "datetime(2026, 7, 6, 9, 30)" in content
        assert "'datetime(" not in content


def test_render_date_object_not_string():
    """date() objects must render as real date() calls, not repr strings."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": dt.date(2026, 7, 6)}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "date(2026, 7, 6)" in content
        assert "datetime.date(" not in content  # repr() would produce datetime.date(...)


def test_render_datetime_in_list_renders_recursively():
    """Datetime inside a list arg must also get the real-object treatment (recursive _lit)."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [[dt.datetime(2026, 7, 6, 12, 0), dt.datetime(2026, 7, 7, 9, 0)]],
                        "expected": 2}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "datetime(2026, 7, 6, 12, 0)" in content
        assert "datetime(2026, 7, 7, 9, 0)" in content
        assert "'datetime(" not in content


def test_render_timedelta_renders_as_real_object():
    """timedelta must render as timedelta(...) not as string repr."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": dt.timedelta(minutes=30)}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "timedelta(" in content
        assert "datetime.timedelta(" not in content  # repr would produce datetime.timedelta(...)


def test_render_mock_assert_called_with_renders_correctly():
    """Mock with assert_called_with must produce `.assert_called_with(...)` in output."""
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": ["input"], "expected": 42}],
             "mocks": [{"target": "m.dep", "return_value": 99,
                        "assert_called_with": [["input"], {}]}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert ".assert_called_with(" in content, f"assert_called_with not in:\n{content}"
        assert "'input'" in content  # the expected arg


def test_render_mock_assert_call_arg_renders_correctly():
    """Mock with assert_call_arg must produce `call_args[N][key] == expected` in output."""
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": True}],
             "mocks": [{"target": "m.dep", "return_value": None,
                        "assert_call_arg": [0, "field", "expected_value"]}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert ".call_args[" in content, f"call_args inspection not in:\n{content}"
        assert "'field'" in content
        assert "'expected_value'" in content


def test_render_mock_assert_called_once_renders():
    """Mock with assert_called_once must produce `.assert_called_once()` in output."""
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": 42}],
             "mocks": [{"target": "m.dep", "return_value": 42,
                        "assert_called_once": True}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert ".assert_called_once()" in content


def test_render_datetime_header_auto_imported():
    """When datetime objects are used, `from datetime import ...` must be auto-imported."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as d:
        spec = {"schema_version": 1, "tests": [
            {"criterion_id": "c1", "module": "m", "call": "f",
             "cases": [{"args": [], "expected": dt.datetime(2026, 7, 6)}]}]}
        assert render.render_spec(spec, d)
        content = open(os.path.join(d, render.CANONICAL_FILE)).read()
        assert "from datetime import" in content, f"datetime import missing from:\n{content}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} render_more tests passed")
