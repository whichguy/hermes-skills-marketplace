"""More deterministic tests for lint.py — closing confirmed coverage gaps (surviving mutants). NO LLM.

Each test below pins behaviour the existing test_lint.py suite leaves unexercised, in a way that
the hypothetical mutant (old->new) would FAIL:
  - the spawn-failure except branch fail-CLOSES (ok=False) and surfaces the un-spawnable entry;
  - failures() classifies error/None entries AND never flags skipped (tool-absent) entries;
  - extension lookup is case-insensitive (.PY behaves like .py on case-insensitive filesystems);
  - discover().covered honestly reflects bool(runnable), not a hardcoded True;
  - the .js argv builder really runs `node --check <file>` end-to-end (not a vacuous `node --version`).
All real-subprocess paths use stdlib linters / node; the spawn-failure path monkeypatches
lint.subprocess.run (restored in finally) so no real process is ever spawned for that case.
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import lint  # noqa: E402

_BROKEN = "def f(:\n    return 1\n"      # SyntaxError
_CLEAN = "def f():\n    return 1\n"


def _raise_oserror(*a, **k):
    # stand-in for subprocess.run that passes available() but cannot exec (OOM/EMFILE/exec-format)
    raise OSError("exec format error")


# --- gap 1: spawn-failure except branch must set ok=False (fail-CLOSED), never ok=True --------
def test_lint_paths_spawn_failure_fails_closed():
    orig = lint.subprocess.run
    lint.subprocess.run = _raise_oserror
    try:
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.py"); open(good, "w").write(_CLEAN)  # syntactically CLEAN
            ok, res = lint.lint_paths([good])
            # good.py is clean, so the ONLY route to ok=False is the spawn-failure except branch.
            assert ok is False                                          # mutant `ok = True` -> this fails
            errs = [r for r in res if r.get("error")]
            assert len(errs) >= 1                                       # the un-spawnable entr(ies) (.py runs py-syntax + ruff)
            assert all(e["exit_code"] is None for e in errs)           # recorded as un-spawnable, not green
    finally:
        lint.subprocess.run = orig


# --- gap 2: failures() must SURFACE the un-spawnable (error/None) entry -----------------------
def test_failures_flags_unspawnable_error_entry():
    orig = lint.subprocess.run
    lint.subprocess.run = _raise_oserror
    try:
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.py"); open(good, "w").write(_CLEAN)
            _, res = lint.lint_paths([good])
            f = lint.failures(res)
            # the entries have exit_code=None (None in (0,None)) so ONLY the `r.get('error') or` clause
            # flags them; the mutant drops that clause -> failures() == [] -> this assertion fails.
            assert len(f) >= 1                                          # .py runs py-syntax + ruff -> both un-spawnable
            assert all(e.get("error") and e.get("exit_code") is None for e in f)
    finally:
        lint.subprocess.run = orig


# --- gap 3: extension lookup must be case-insensitive (.PY -> .py) ----------------------------
def test_lint_paths_uppercase_extension_is_linted():
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "Bad.PY"); open(bad, "w").write(_BROKEN)   # SyntaxError, UPPERCASE ext
        ok, res = lint.lint_paths([bad])
        # with .lower() dropped, LINTERS.get('.PY') is None -> recorded as skipped -> ok stays True.
        assert ok is False and lint.failures(res)                       # py-syntax (stdlib) caught it
        # control: a CLEAN uppercase-ext file still maps to the linter and passes (ok True), proving
        # the gate isn't just constant-failing on the extension.
        good = os.path.join(d, "Good.PY"); open(good, "w").write(_CLEAN)
        assert lint.lint_paths([good])[0] is True


# --- gap 4: skipped (tool-absent / unmapped) results must NEVER count as failures ------------
def test_failures_never_flags_skipped_results():
    skips = [
        {"path": "x.md", "skipped": "no linter for this file type"},
        {"path": "y.css", "linter": "stylelint", "skipped": "tool not installed"},
    ]
    # exit_code absent -> .get('exit_code') is None -> must classify as NOT a failure.
    assert lint.failures(skips) == []                                   # mutant `not in (0,)` -> non-empty
    # control: a genuine nonzero-exit entry is STILL flagged (guards against a vacuous test).
    assert lint.failures([{"path": "z.py", "linter": "py-syntax", "exit_code": 1, "output": "err"}]) != []


# --- gap 5: discover().covered must reflect bool(runnable), not a hardcoded True --------------
def test_discover_covered_reflects_runtime_availability():
    rep = lint.discover()
    by_ext = {tuple(r["extensions"]): r for r in rep}
    # web-stack tools are absent here -> covered must be False; the mutant forces covered=True.
    assert by_ext[(".css", ".scss", ".less")]["covered"] == lint._on_path("stylelint")
    assert by_ext[(".html", ".htm")]["covered"] == lint._on_path("htmlhint")
    # control: a stdlib-backed language is genuinely covered (True == True), so the equality test
    # above is pinning real availability, not comparing two constant Falses.
    assert by_ext[(".py",)]["covered"] is True


# --- gap 6: the .js builder runs `node --check <file>` end-to-end, not a vacuous argv ---------
def test_lint_paths_js_check_runs_against_the_file():
    if not lint._on_path("node"):
        return                                                          # node absent -> not the path under test
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.js"); open(bad, "w").write("function (\n")   # JS SyntaxError
        ok, res = lint.lint_paths([bad])
        # mutant `['node','--version']` ignores the file and exits 0 -> ok True -> this fails.
        assert ok is False and lint.failures(res)
        good = os.path.join(d, "ok.js"); open(good, "w").write("const x = 1;\n")
        assert lint.lint_paths([good])[0] is True                       # valid JS passes the same builder


# --- gap 7: stdlib-only linters for TOML, XML, Shell, C (P1 additions 2026-07-08) -------------
def test_lint_paths_toml_valid_and_invalid():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.toml"); open(good, "w").write('[section]\nkey = "value"\n')
        bad = os.path.join(d, "bad.toml"); open(bad, "w").write('[section\nkey = value\n')
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)


def test_lint_paths_xml_valid_and_invalid():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.xml"); open(good, "w").write("<root><child/></root>\n")
        bad = os.path.join(d, "bad.xml"); open(bad, "w").write("<root><child></root>\n")
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)


def test_lint_paths_shell_valid_and_invalid():
    if not lint._on_path("bash"):
        return
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.sh"); open(good, "w").write("#!/bin/bash\necho hello\n")
        bad = os.path.join(d, "bad.sh"); open(bad, "w").write("if then fi\n")
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)


def test_lint_paths_c_valid_and_invalid():
    if not lint._on_path("gcc"):
        return
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.c"); open(good, "w").write("int main(void) { return 0; }\n")
        bad = os.path.join(d, "bad.c"); open(bad, "w").write("int main(void { return 0; }\n")
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)


def test_lint_paths_makefile_valid():
    if not lint._on_path("make"):
        return
    with tempfile.TemporaryDirectory() as d:
        mk = os.path.join(d, "Makefile"); open(mk, "w").write("all:\n\techo hello\n")
        assert lint.lint_paths([mk])[0] is True


def test_ruff_finds_undefined_name():
    """Ruff (F821) catches undefined names that py-syntax (compile) misses."""
    if not lint._on_path("ruff"):
        return
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.py"); open(bad, "w").write("undefined_name_var\n")
        ok, res = lint.lint_paths([bad])
        ruff_results = [r for r in res if r.get("linter") == "ruff"]
        assert ruff_results, "ruff should have been run"
        assert ruff_results[0]["exit_code"] != 0, "ruff should flag F821"


def test_file_key_handles_extensionless_files():
    """_file_key returns basename for extensionless files like Makefile."""
    assert lint._file_key("Makefile") == "makefile"
    assert lint._file_key("/path/to/Makefile") == "makefile"
    assert lint._file_key("script.sh") == ".sh"
    assert lint._file_key("config.TOML") == ".toml"


def test_lint_paths_yaml_valid_and_invalid():
    """YAML linter (PyYAML) catches invalid YAML."""
    if not lint._has_module("yaml"):
        return
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.yaml"); open(good, "w").write("key: value\nlist:\n  - a\n  - b\n")
        bad = os.path.join(d, "bad.yaml"); open(bad, "w").write("key: [unclosed\n")
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)


def test_lint_paths_sql_valid():
    """SQL linter (sqlparse) parses valid SQL without error."""
    if not lint._has_module("sqlparse"):
        return
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.sql"); open(good, "w").write("SELECT * FROM users WHERE id = 1;\n")
        assert lint.lint_paths([good])[0] is True


# --- P0: _resolve_exe finds venv-installed tools (prevents wired-but-never-functional) --------
# The ruff venv-bin bug: _on_path() used only shutil.which (PATH), which doesn't
# include /opt/data/.venv/bin. Ruff was wired in _LANGUAGES but silently skipped
# on every run since devloop's inception. These tests prevent that pattern.

def test_resolve_exe_returns_path_for_known_tool():
    """_resolve_exe('ruff') must return a real path (not just 'ruff') when ruff is
    installed in the venv. If it returns the bare name, subprocess.run will fail
    to find it (the wired-but-never-functional pattern)."""
    ruff_path = lint._resolve_exe("ruff")
    # Must be an absolute path, not the bare exe name
    assert ruff_path != "ruff", (
        "_resolve_exe('ruff') returned the bare name 'ruff' — the venv-bin bug. "
        "ruff is installed at /opt/data/.venv/bin/ruff but _resolve_exe can't find it. "
        "Check sys.prefix/bin, dirname(sys.executable), and /opt/data/.venv/bin."
    )
    assert os.path.isfile(ruff_path), f"resolve_exe returned {ruff_path} but file doesn't exist"
    assert os.access(ruff_path, os.X_OK), f"resolve_exe returned {ruff_path} but not executable"


def test_resolve_exe_fallback_for_missing_tool():
    """_resolve_exe('nonexistent_tool_xyz') returns the bare name (lets subprocess try PATH).
    This is the correct fallback behavior — not None, not empty, just the name."""
    result = lint._resolve_exe("nonexistent_tool_xyz_12345")
    assert result == "nonexistent_tool_xyz_12345", (
        f"Expected bare name fallback, got {result!r}"
    )


def test_on_path_finds_venv_tools():
    """_on_path('ruff') must return True when ruff is installed in the venv.
    This is the function _LANGUAGES builders use for available() checks —
    if it returns False, the linter is silently skipped."""
    assert lint._on_path("ruff") is True, (
        "_on_path('ruff') returned False — the venv-bin bug. "
        "Ruff is wired in _LANGUAGES but _on_path can't discover it. "
        "Check that _on_path checks sys.prefix/bin and /opt/data/.venv/bin, not just PATH."
    )


def test_on_path_returns_false_for_missing():
    """_on_path returns False for a tool that genuinely doesn't exist."""
    assert lint._on_path("nonexistent_tool_xyz_12345") is False


def test_py_linters_all_available_and_runnable():
    """All four Python linters (py-syntax, pyflakes, ruff, mypy) must be available AND produce
    the correct exit code on a clean file. This is the integration check — available()
    returning True but the linter failing to spawn is the wired-but-never-functional
    pattern in its most dangerous form."""
    with tempfile.TemporaryDirectory() as d:
        clean = os.path.join(d, "clean.py")
        open(clean, "w").write("def add(a, b):\n    return a + b\n")
        ok, results = lint.lint_paths([clean])
        # All four must have run (not skipped)
        skipped = [r for r in results if "skipped" in r]
        assert not skipped, f"Expected 0 skipped, got {len(skipped)}: {skipped}"
        # All must pass (exit_code 0)
        failed = lint.failures(results)
        assert not failed, f"Clean .py file should pass all linters: {failed}"


def test_lint_paths_cpp_valid_and_invalid():
    """g++ -fsyntax-only must accept valid C++ and reject invalid C++."""
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.cpp")
        bad = os.path.join(d, "bad.cpp")
        open(good, "w").write("#include \u003cvector\u003e\nint main() { std::vector\u003cint\u003e v; return 0; }\n")
        open(bad, "w").write("int main() { std::vector\u003cint\u003e v; return 0; }\n")  # missing include
        ok, results = lint.lint_paths([good])
        assert ok, f"Valid C++ should lint clean: {results}"
        ok, results = lint.lint_paths([bad])
        assert not ok, f"Invalid C++ should fail lint: {results}"


def test_lint_paths_pyflakes_catches_undefined_name():
    """pyflakes must catch an undefined name that ruff may also catch, but the test pins
    the builder is wired and executable."""
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.py")
        open(bad, "w").write("print(undefined_var)\n")
        ok, results = lint.lint_paths([bad])
        pyflakes_results = [r for r in results if r.get("linter") == "pyflakes"]
        assert pyflakes_results, "pyflakes did not run on .py file"
        assert pyflakes_results[0].get("exit_code") != 0, "pyflakes should flag undefined name"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} lint tests passed")
