#!/usr/bin/env python3
"""Backend-swappable investigation tools, shared by examples/investigate_repo.py.

The investigation flow is written ONCE against these tools; the backend is chosen at
runtime so the same flow drives both the hermetic ladder and the real-repo integration:

    INVESTIGATE_MODE=fixture   (default) canned, sorted, stable outputs from
                               $INVESTIGATE_FIXTURE (a JSON file) — fully deterministic.
    INVESTIGATE_MODE=real      operate on a real repo under $INVESTIGATE_ROOT
                               (glob / file-read / subprocess).

Env knobs honored by BOTH backends, so a scenario scripts identically at either fidelity:

    INVESTIGATE_DEP_DOWN=1     run_tests('reproduce') reports an ENVIRONMENT failure
                               (missing dep) -> the reproduce step fails; clear it and
                               resume to recover (command-fails -> fix -> resume).
    INVESTIGATE_CRASH_APPLY=1  apply_fix hard-exits AFTER writing, before returning ->
                               a mid-mutation crash; re-run escalates to in-doubt.
    INVESTIGATE_TRACE=path     append "(phase key)" per step for the walkthrough narrator.
"""
import json
import os
import re
import subprocess
import sys


def _real():
    return os.environ.get("INVESTIGATE_MODE") == "real"


def _fixture():
    with open(os.environ["INVESTIGATE_FIXTURE"]) as f:
        return json.load(f)


def _root():
    return os.environ["INVESTIGATE_ROOT"]


def observer(event):
    # Out-of-band narration hook (picked up by the engine as `observer`); runs on every
    # pass incl. replay, try-guarded in-engine so it can never affect the flow.
    p = os.environ.get("INVESTIGATE_TRACE")
    if not p:
        return
    with open(p, "a") as f:
        f.write("%s %s\n" % (event.get("phase"), event.get("key")))


def map_repo():
    """Return a SORTED list of source module paths — the expensive scan we memoize."""
    if _real():
        root = _root()
        out = []
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.endswith((".py", ".js", ".json", ".txt", ".md")):
                    out.append(os.path.relpath(os.path.join(dirpath, fn), root))
        return sorted(out)
    return sorted(_fixture()["map"])


def run_tests(phase="reproduce"):
    """Run the project's tests; return {code, out}. An ENVIRONMENT failure (missing dep)
    on the reproduce phase RAISES, so the calling step fails and can be recovered."""
    dep_down = os.environ.get("INVESTIGATE_DEP_DOWN") == "1" and phase == "reproduce"
    if _real():
        env = dict(os.environ)
        if dep_down:
            env["DEP_DOWN"] = "1"
        else:
            env.pop("DEP_DOWN", None)
        p = subprocess.run([sys.executable, "run_tests.py"], cwd=_root(), env=env,
                           capture_output=True, text=True)
        out = (p.stdout + p.stderr).strip()
        if "ModuleNotFoundError" in out or "ImportError" in out:
            raise RuntimeError("environment not ready: %s" % out.splitlines()[-1])
        return {"code": p.returncode, "out": out}
    fx = _fixture()
    if dep_down:
        raise RuntimeError("environment not ready: %s" % fx["reproduce_depdown"])
    r = fx[phase]                      # "reproduce" -> failing; "verify" -> passing
    return {"code": r["code"], "out": r["out"]}


def grep(symbol):
    """Find a symbol across the sources; return SORTED [{path, line, text}]."""
    if _real():
        root = _root()
        hits = []
        for path in map_repo():
            full = os.path.join(root, path)
            try:
                lines = open(full, encoding="utf-8").read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, ln in enumerate(lines, 1):
                if symbol in ln:
                    hits.append({"path": path, "line": i, "text": ln.strip()})
        return sorted(hits, key=lambda m: (m["path"], m["line"]))
    return _fixture()["grep"].get(symbol, [])


def read_region(path):
    """Return the text of a suspect file (small fixture/source files)."""
    if _real():
        try:
            return open(os.path.join(_root(), path), encoding="utf-8").read()
        except OSError as e:
            return "<<unreadable: %s>>" % e
    return _fixture()["read"].get(path, "")


def apply_fix(path, edit, idem):
    """NON-idempotent mutation. Real: apply edit['find']->edit['replace'] in the file.
    Fixture: just record it. `idem` (run_id:apply-fix) is what a real editing API would
    dedupe on. A crash here (INVESTIGATE_CRASH_APPLY) models a death mid-write."""
    if _real():
        full = os.path.join(_root(), path)
        text = open(full, encoding="utf-8").read()
        if edit.get("find") and edit["find"] in text:
            text = text.replace(edit["find"], edit.get("replace", ""), 1)
            open(full, "w", encoding="utf-8").write(text)
    # crash-window: die AFTER the write lands but before the engine journals completion.
    if os.environ.get("INVESTIGATE_CRASH_APPLY") == "1":
        os._exit(137)
    return {"patched": path}


def propose_fix():
    """Return the proposed edit {find, replace}. Fixture: the JSON `edit` field. Real:
    the repo's proposed_fix.json (what a real agent would synthesize). Wrapping this in a
    memoized `propose` step means the (expensive) analysis is never redone on resume."""
    if _real():
        with open(os.path.join(_root(), "proposed_fix.json"), encoding="utf-8") as f:
            return json.load(f)
    return _fixture().get("edit", {})


# Pure analysis helpers (run in the flow body, no side effects -> deterministic).

def classify(out):
    low = out.lower()
    if "flaky" in low or "timeout" in low or "connection reset" in low:
        return "flaky"
    if "ModuleNotFoundError" in out or "ImportError" in out:
        return "missing_dep"
    if "SyntaxError" in out:
        return "compile_error"
    if "AssertionError" in out:
        return "assertion_fail"
    return "unknown"


def extract_symbol(out):
    m = re.search(r"\bin (\w+)", out)
    return m.group(1) if m else "main"
