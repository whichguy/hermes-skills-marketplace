"""Deterministic tests for quality_lint.py — NO LLM.

Pins each pattern the pre-judge gate rejects and verifies the feedback text is actionable.
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import quality_lint as ql    # noqa: E402


def _find(src: str) -> list[dict]:
    return [f.as_dict() for f in ql._collect_findings("test_devloop_dod.py", src)]


def test_gate_flags_module_level_patch():
    src = """\
def test_c1():
    from unittest import mock
    with mock.patch('mod.dep'):
        from mod import func
        func()
"""
    f = _find(src)
    assert len(f) == 1
    assert f[0]["category"] == "module_level_patch"
    assert "dependency injection" in f[0]["message"]


def test_gate_allows_dependency_injection_raw_hatch():
    src = """\
def test_c1():
    from unittest.mock import MagicMock
    from mod import func
    fake = MagicMock()
    func(dep=fake)
    assert fake.call_args[0][0] == 'expected'
    fake.assert_called_once()
"""
    assert _find(src) == []


def test_gate_flags_mock_without_call_inspection():
    src = """\
def test_c1():
    from unittest.mock import Mock
    from mod import func
    m = Mock(return_value=42)
    assert func(dep=m) == 42
"""
    f = _find(src)
    assert len(f) == 1
    assert f[0]["category"] == "mock_without_call_inspection"
    assert "call_args" in f[0]["message"]


def test_gate_allows_mock_with_assert_called():
    src = """\
def test_c1():
    from unittest.mock import Mock
    from mod import func
    m = Mock(return_value=42)
    assert func(dep=m) == 42
    m.assert_called_once()
"""
    assert _find(src) == []


def test_gate_flags_datetime_string_literal():
    src = """\
def test_c1():
    from mod import parse
    result = parse('tomorrow')
    assert result == 'datetime(2026,7,6)'
"""
    f = _find(src)
    assert len(f) == 1
    assert f[0]["category"] == "datetime_string_literal"
    assert "real datetime" in f[0]["message"]


def test_gate_allows_real_datetime_object():
    src = """\
from datetime import datetime
def test_c1():
    from mod import parse
    result = parse('tomorrow')
    assert result == datetime(2026, 7, 6)
"""
    assert _find(src) == []


def test_lint_rendered_tests_honors_filename_filter():
    with tempfile.TemporaryDirectory() as d:
        # oracle file should be scanned
        open(os.path.join(d, "test_devloop_dod.py"), "w").write(
            "def test_c1():\n    assert 1 == 'datetime(2026,7,6)'\n")
        # non-oracle file should be ignored
        open(os.path.join(d, "other.py"), "w").write(
            "def test_c1():\n    assert 1 == 'datetime(2026,7,6)'\n")
        ok, findings = ql.lint_rendered_tests(d)
        assert not ok
        assert len(findings) == 1
        assert findings[0]["path"] == os.path.join(d, "test_devloop_dod.py")


def test_feedback_for_redesigner_includes_category_and_fix_hint():
    findings = [{"path": "x.py", "line": 5, "category": "datetime_string_literal",
                 "message": "use real datetime"}]
    fb = ql.feedback_for_redesigner(findings)
    assert "QUALITY GATE rejected" in fb
    assert "datetime_string_literal" in fb
    assert "x.py:5" in fb
    assert "use real datetime" in fb


def test_gate_flags_weak_substring_command_assertion():
    src = """\
def test_c1():
    from unittest.mock import MagicMock
    from mod import run_cli
    m = MagicMock()
    run_cli(args=['--today'], gws_runner=m)
    assert 'events create' in m.call_args[0][0]
"""
    f = _find(src)
    assert len(f) == 1
    assert f[0]["category"] == "weak_substring_command_assertion"
    assert "only checked with 'in' assertions" in f[0]["message"]


def test_gate_allows_structured_command_assertion():
    src = """\
def test_c1():
    from unittest.mock import MagicMock
    from mod import run_cli
    m = MagicMock()
    run_cli(args=['--today'], gws_runner=m)
    cmd = m.call_args[0][0].split()
    assert cmd[0] == 'gws'
    assert 'events' in cmd
"""
    assert _find(src) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} quality-lint tests passed")
