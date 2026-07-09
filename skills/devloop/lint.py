"""lint.py — post-IMPLEMENT syntactic gate + linter discovery.

After the coder writes files, run language-appropriate linters on EXACTLY the files it changed
(real subprocess exit codes, like evidence.py) to catch syntax / obvious errors early — before the
per-criterion tests, and covering files no test imports. A CONFIRMED linter failure feeds the
errors back to the coder and forces a rebuild; it can never let the loop COMPLETE. An unmapped file
type, an uninstalled linter, or a missing file is SKIPPED (recorded, not failed), so a tool not
being installed can never fail-close an otherwise correct build.

Two choices keep this from manufacturing false-negatives (we learned strict gates do):
  - linters are SYNTAX / ERROR-scoped, NOT style — an unconventional-but-valid file isn't punished;
  - anything not runnable HERE is skipped, and `discover()` reports the gaps so they're never silent.

Extending (the web stack is wired but most tools aren't installed yet): add a `(extensions,
[builders])` row to `_LANGUAGES`. A builder is a zero-arg fn returning
`{name, available()->bool, argv(path)->list}`; return `available()=False` when its tool/module is
absent so the gate skips instead of failing.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys


def _has_module(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def _on_path(exe):
    """True iff `exe` is executable on PATH OR in the active venv bin (ruff lives there
    but isn't on the default PATH in subprocess contexts). Also checks sys.prefix/bin
    so `uv run`-installed tools are discoverable."""
    if shutil.which(exe) is not None:
        return True
    # Check the active venv bin directory (ruff, mypy, etc. live here under uv)
    for bindir in (
        os.path.join(sys.prefix, "bin"),
        os.path.join(os.path.dirname(sys.executable), ""),
        "/opt/data/.venv/bin",
    ):
        candidate = os.path.join(bindir, exe)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


def _resolve_exe(exe):
    """Return the full path to `exe` if findable, else `exe` (let subprocess try PATH)."""
    p = shutil.which(exe)
    if p:
        return p
    for bindir in (
        os.path.join(sys.prefix, "bin"),
        os.path.join(os.path.dirname(sys.executable), ""),
        "/opt/data/.venv/bin",
    ):
        candidate = os.path.join(bindir, exe)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return exe


# --- builders: zero-arg -> {name, available, argv}. Ordered per language, syntax-first. ------
def _py_syntax():
    # stdlib, ALWAYS present; pure syntax via compile() — writes no .pyc, never imports the module.
    return {"name": "py-syntax", "available": lambda: True,
            "argv": lambda p: [sys.executable, "-c",
                               "import sys; q=sys.argv[1]; compile(open(q, encoding='utf-8').read(), q, 'exec')", p]}


def _ruff():
    # ERROR rules only (E9 syntax, F82x undefined/used-before), NEVER style -> no false rebuilds.
    ruff = _resolve_exe("ruff")
    return {"name": "ruff", "available": lambda: _on_path("ruff"),
            "argv": lambda p: [ruff, "check", "--quiet", "--select", "E9,F821,F822,F823", p]}


def _mypy():
    # mypy: type-error scope only. --no-error-summary for clean output. Only runs when
    # mypy is installed (via uv). Skipped otherwise (available()=False). We use
    # --ignore-missing-imports to avoid false errors from untyped deps, and
    # --no-namespace-packages to avoid scanning unrelated packages.
    mypy = _resolve_exe("mypy")
    return {"name": "mypy", "available": lambda: _on_path("mypy"),
            "argv": lambda p: [mypy, "--ignore-missing-imports", "--no-error-summary",
                               "--no-namespace-packages", "--no-color-output", p]}


def _json_syntax():
    # stdlib; `python -m json.tool` exits nonzero on invalid JSON.
    return {"name": "json.tool", "available": lambda: True,
            "argv": lambda p: [sys.executable, "-m", "json.tool", p]}


def _yaml_syntax():
    # PyYAML if importable; safe_load_all parses every doc (raises -> nonzero), executes no tags.
    return {"name": "pyyaml", "available": lambda: _has_module("yaml"),
            "argv": lambda p: [sys.executable, "-c",
                               "import sys, yaml; list(yaml.safe_load_all(open(sys.argv[1], encoding='utf-8')))", p]}


def _node_check():
    # pure JS SYNTAX parse — no config, no style, no false positives (the right syntactic check).
    return {"name": "node --check", "available": lambda: _on_path("node"),
            "argv": lambda p: ["node", "--check", p]}


def _tsc():
    # TypeScript: tsc when installed (also type-checks -> stricter); skipped when absent (the usual
    # case). --skipLibCheck keeps it from dragging in library typings.
    return {"name": "tsc --noEmit", "available": lambda: _on_path("tsc"),
            "argv": lambda p: ["tsc", "--noEmit", "--skipLibCheck", "--allowJs", p]}


def _stylelint():
    return {"name": "stylelint", "available": lambda: _on_path("stylelint"),
            "argv": lambda p: ["stylelint", p]}


def _htmlhint():
    return {"name": "htmlhint", "available": lambda: _on_path("htmlhint"),
            "argv": lambda p: ["htmlhint", p]}


def _toml_syntax():
    # stdlib tomllib (Python 3.11+); parse TOML validity, executes no code.
    return {"name": "tomllib", "available": lambda: _has_module("tomllib"),
            "argv": lambda p: [sys.executable, "-c",
                               "import sys, tomllib; tomllib.load(open(sys.argv[1], 'rb'))", p]}


def _xml_syntax():
    # stdlib xml.etree.ElementTree; parse XML validity (no external DTD/entity expansion).
    return {"name": "xml.etree", "available": lambda: True,
            "argv": lambda p: [sys.executable, "-c",
                               "import sys; import xml.etree.ElementTree as ET; ET.parse(sys.argv[1])", p]}


def _ini_syntax():
    # stdlib configparser; parse INI/CFG file validity.
    return {"name": "configparser", "available": lambda: _has_module("configparser"),
            "argv": lambda p: [sys.executable, "-c",
                               "import sys, configparser; cp=configparser.ConfigParser(); cp.read(sys.argv[1])", p]}


def _bash_syntax():
    # bash -n: pure syntax check, no execution, no style. bash is typically present.
    return {"name": "bash -n", "available": lambda: _on_path("bash"),
            "argv": lambda p: ["bash", "-n", p]}


def _make_syntax():
    # make -n: dry-run parse of the Makefile (no commands executed). make is typically present.
    return {"name": "make -n", "available": lambda: _on_path("make"),
            "argv": lambda p: ["make", "-n", "-f", p]}


def _gcc_syntax():
    # gcc -fsyntax-only: parse C without generating output. gcc is present in this env.
    gcc = _resolve_exe("gcc")
    return {"name": "gcc -fsyntax-only", "available": lambda: _on_path("gcc"),
            "argv": lambda p: [gcc, "-fsyntax-only", "-Wall", p]}


def _gpp_syntax():
    # g++ -fsyntax-only: parse C++ without generating output. g++ is present in this env.
    gpp = _resolve_exe("g++")
    return {"name": "g++ -fsyntax-only", "available": lambda: _on_path("g++"),
            "argv": lambda p: [gpp, "-fsyntax-only", "-Wall", p]}


def _pyflakes():
    # pyflakes: catches undefined names, unused imports, and other static issues.
    # Installed in the venv alongside ruff; serves as a cross-check on ruff's narrow rule set.
    pyflakes = _resolve_exe("pyflakes")
    return {"name": "pyflakes", "available": lambda: _on_path("pyflakes"),
            "argv": lambda p: [pyflakes, p]}


def _sql_syntax():
    # sqlparse: parse SQL validity. Very permissive (tokenizes, doesn't validate against a schema),
    # but catches gross syntax errors like unterminated statements.
    return {"name": "sqlparse", "available": lambda: _has_module("sqlparse"),
            "argv": lambda p: [sys.executable, "-c",
                               "import sys, sqlparse; sqlparse.parse(open(sys.argv[1], encoding='utf-8').read())", p]}


def _dockerfile_syntax():
    # docker build --check: dry-run Dockerfile parse (no actual build). docker is available
    # in this env. Runs in the Dockerfile's directory with a dummy context.
    docker = _resolve_exe("docker")
    def _argv(p):
        d = os.path.dirname(p) or "."
        return [docker, "build", "--check", "--no-cache", "-f", p, d]
    return {"name": "docker --check", "available": lambda: _on_path("docker"),
            "argv": _argv}


# extension(s) -> ordered builders. Add new languages here; discovery + the gate both read this.
_LANGUAGES = [
    ((".py",), [_py_syntax, _pyflakes, _ruff, _mypy]),
    ((".json",), [_json_syntax]),
    ((".yaml", ".yml"), [_yaml_syntax]),
    ((".js", ".jsx", ".mjs", ".cjs"), [_node_check]),
    ((".ts", ".tsx"), [_tsc]),
    ((".css", ".scss", ".less"), [_stylelint]),
    ((".html", ".htm"), [_htmlhint]),
    # ── stdlib-only linters (P1 additions 2026-07-08) ──
    ((".toml",), [_toml_syntax]),
    ((".xml",), [_xml_syntax]),
    ((".ini", ".cfg", ".conf"), [_ini_syntax]),
    ((".sh", ".bash"), [_bash_syntax]),
    (("Makefile", ".mk"), [_make_syntax]),
    ((".c", ".h"), [_gcc_syntax]),
    ((".cpp", ".hpp"), [_gpp_syntax]),
    ((".sql",), [_sql_syntax]),
    (("Dockerfile",), [_dockerfile_syntax]),
]
LINTERS = {ext: builders for exts, builders in _LANGUAGES for ext in exts}


def discover(paths=None):
    """Per-language report of what's WIRED vs actually runnable HERE. The loop logs this once per
    run so coverage gaps (e.g. '.css present but stylelint not installed') are visible, never
    silent — `covered` is False when a language has no runnable linter in this environment.

    If `paths` is given, only checks languages for the file types actually present —
    fast path: skips availability probes for irrelevant linters."""
    # Build the set of file keys we actually need to check
    if paths is not None:
        needed = {_file_key(p) for p in paths if os.path.isfile(p)}
    else:
        needed = None  # check all
    report = []
    for exts, builders in _LANGUAGES:
        if needed is not None:
            # Skip this language if none of its extensions are in the needed set
            if not any(ext in needed for ext in exts):
                continue
        specs = [b() for b in builders]
        runnable = [s["name"] for s in specs if s["available"]()]
        report.append({"extensions": list(exts), "linters": [s["name"] for s in specs],
                       "available": runnable, "covered": bool(runnable)})
    # Report uncovered file types (no wired linter at all) — research candidates
    if needed is not None:
        covered_exts = {ext for r in report for ext in r["extensions"] if r["covered"]}
        uncovered = [ext for ext in needed if ext not in covered_exts]
        if uncovered:
            report.append({"extensions": uncovered, "linters": [], "available": [],
                           "covered": False, "research": True})
    return report


def _file_key(path):
    """Lookup key for LINTERS: extension if present, else basename (for extensionless
    files like Makefile/Dockerfile). Always lowercased for case-insensitive matching."""
    ext = os.path.splitext(path)[1].lower()
    if ext:
        return ext
    return os.path.basename(path).lower()


def lint_paths(paths, cwd=None, timeout=120):
    """Run the mapped linters on each path. Returns (ok, results). ok is False iff some linter
    EXITED NONZERO (or could not be spawned). Deleted files, unmapped extensions, and unavailable
    tools are skipped and recorded with a "skipped" key — never a failure."""
    results = []
    ok = True
    for p in paths:
        if not os.path.isfile(p):                      # deleted/moved -> nothing to lint
            continue
        builders = LINTERS.get(_file_key(p))
        if not builders:
            results.append({"path": p, "skipped": "no linter for this file type",
                            "research": True})  # flag for linter research
            continue
        for build in builders:
            spec = build()
            if not spec["available"]():
                results.append({"path": p, "linter": spec["name"], "skipped": "tool not installed"})
                continue
            argv = spec["argv"](p)
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
            except (OSError, subprocess.SubprocessError) as e:   # could not spawn the linter
                results.append({"path": p, "linter": spec["name"], "exit_code": None, "error": str(e)[:300]})
                ok = False
                continue
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            results.append({"path": p, "linter": spec["name"], "exit_code": r.returncode, "output": out[-800:]})
            if r.returncode != 0:
                ok = False
    return ok, results


def failures(results):
    """The subset of results that are real failures (nonzero exit or un-spawnable)."""
    return [r for r in results if r.get("error") or r.get("exit_code") not in (0, None)]
