"""Real tests for lint.py — no mocks, real temp files.

Covers discover() and lint_paths() contracts:
  1. discover() on a .py file returns linter info (covered=True, py-syntax available)
  2. discover() on an unknown extension returns no coverage (covered=False)
  3. discover() on an empty list returns an empty report
  4. lint_paths() on a clean .py file passes
  5. lint_paths() on a .py file with a syntax error fails
  6. lint_paths() on an empty list passes (vacuous)
  7. lint_paths() returns per-file results with 'skipped' for unknown extensions
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import lint  # noqa: E402

_BROKEN_PY = "def f(:\n    return 1\n"   # SyntaxError
_CLEAN_PY = "def f():\n    return 1\n"


def test_discover_py_file_returns_linter_info():
    with tempfile.TemporaryDirectory() as d:
        py_path = os.path.join(d, "module.py")
        with open(py_path, "w", encoding="utf-8") as f:
            f.write(_CLEAN_PY)

        report = lint.discover([py_path])
        assert isinstance(report, list)
        py_reports = [r for r in report if ".py" in r.get("extensions", [])]
        assert len(py_reports) == 1, f"expected one .py report, got {py_reports!r}"
        entry = py_reports[0]
        assert entry["covered"] is True
        assert "py-syntax" in entry["linters"]
        assert "py-syntax" in entry["available"]
        assert entry["extensions"] == [".py"]


def test_discover_unknown_extension_returns_no_coverage():
    with tempfile.TemporaryDirectory() as d:
        weird_path = os.path.join(d, "notes.xyz")
        with open(weird_path, "w", encoding="utf-8") as f:
            f.write("stuff\n")

        report = lint.discover([weird_path])
        assert isinstance(report, list)
        assert len(report) == 1
        entry = report[0]
        assert entry["extensions"] == [".xyz"]
        assert entry["linters"] == []
        assert entry["available"] == []
        assert entry["covered"] is False
        assert entry.get("research") is True


def test_discover_empty_list_returns_empty():
    report = lint.discover([])
    assert report == []


def test_lint_paths_clean_py_passes():
    with tempfile.TemporaryDirectory() as d:
        clean_path = os.path.join(d, "clean.py")
        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(_CLEAN_PY)

        ok, results = lint.lint_paths([clean_path])
        assert ok is True
        assert isinstance(results, list)
        assert any(r["path"] == clean_path and r.get("linter") == "py-syntax" for r in results)


def test_lint_paths_broken_py_fails():
    with tempfile.TemporaryDirectory() as d:
        bad_path = os.path.join(d, "bad.py")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write(_BROKEN_PY)

        ok, results = lint.lint_paths([bad_path])
        assert ok is False
        assert lint.failures(results)
        assert any(r["path"] == bad_path and r.get("linter") == "py-syntax" and r.get("exit_code") != 0 for r in results)


def test_lint_paths_empty_list_passes():
    ok, results = lint.lint_paths([])
    assert ok is True
    assert results == []


def test_lint_paths_unknown_extension_is_skipped():
    with tempfile.TemporaryDirectory() as d:
        weird_path = os.path.join(d, "notes.xyz")
        with open(weird_path, "w", encoding="utf-8") as f:
            f.write("stuff\n")

        ok, results = lint.lint_paths([weird_path])
        assert ok is True
        assert len(results) == 1
        entry = results[0]
        assert entry["path"] == weird_path
        assert "skipped" in entry
        assert "no linter for this file type" in entry["skipped"]
        assert entry.get("research") is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} lint tests passed")
