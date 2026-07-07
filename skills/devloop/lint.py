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
    return shutil.which(exe) is not None


# --- builders: zero-arg -> {name, available, argv}. Ordered per language, syntax-first. ------
def _py_syntax():
    # stdlib, ALWAYS present; pure syntax via compile() — writes no .pyc, never imports the module.
    return {"name": "py-syntax", "available": lambda: True,
            "argv": lambda p: [sys.executable, "-c",
                               "import sys; q=sys.argv[1]; compile(open(q, encoding='utf-8').read(), q, 'exec')", p]}


def _ruff():
    # ERROR rules only (E9 syntax, F82x undefined/used-before), NEVER style -> no false rebuilds.
    return {"name": "ruff", "available": lambda: _on_path("ruff"),
            "argv": lambda p: ["ruff", "check", "--quiet", "--select", "E9,F821,F822,F823", p]}


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


# extension(s) -> ordered builders. Add new languages here; discovery + the gate both read this.
_LANGUAGES = [
    ((".py",), [_py_syntax, _ruff]),
    ((".json",), [_json_syntax]),
    ((".yaml", ".yml"), [_yaml_syntax]),
    ((".js", ".jsx", ".mjs", ".cjs"), [_node_check]),
    ((".ts", ".tsx"), [_tsc]),
    ((".css", ".scss", ".less"), [_stylelint]),
    ((".html", ".htm"), [_htmlhint]),
]
LINTERS = {ext: builders for exts, builders in _LANGUAGES for ext in exts}


def discover():
    """Per-language report of what's WIRED vs actually runnable HERE. The loop logs this once per
    run so coverage gaps (e.g. '.css present but stylelint not installed') are visible, never
    silent — `covered` is False when a language has no runnable linter in this environment."""
    report = []
    for exts, builders in _LANGUAGES:
        specs = [b() for b in builders]
        runnable = [s["name"] for s in specs if s["available"]()]
        report.append({"extensions": list(exts), "linters": [s["name"] for s in specs],
                       "available": runnable, "covered": bool(runnable)})
    return report


def lint_paths(paths, cwd=None, timeout=120):
    """Run the mapped linters on each path. Returns (ok, results). ok is False iff some linter
    EXITED NONZERO (or could not be spawned). Deleted files, unmapped extensions, and unavailable
    tools are skipped and recorded with a "skipped" key — never a failure."""
    results = []
    ok = True
    for p in paths:
        if not os.path.isfile(p):                      # deleted/moved -> nothing to lint
            continue
        builders = LINTERS.get(os.path.splitext(p)[1].lower())
        if not builders:
            results.append({"path": p, "skipped": "no linter for this file type"})
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
