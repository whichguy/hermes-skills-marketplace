"""Deterministic tests for the post-IMPLEMENT lint gate (lint.py + its wiring in loop.py). NO LLM.

Proves: the syntactic linter runs on the coder's changed files via REAL subprocesses; a syntax
error blocks the pass (feeds back + rebuilds) BEFORE tests run; an unmapped type / missing tool /
missing file is skipped (never a false red); and at the loop level a persistently broken file
fail-closes to HUMAN_REVIEW even when the test evidence would be green (the gate can never let
syntactically-broken code COMPLETE).
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config    # noqa: E402
import loop      # noqa: E402
import lint      # noqa: E402
import dispatch  # noqa: E402

_BROKEN = "def f(:\n    return 1\n"      # SyntaxError
_CLEAN = "def f():\n    return 1\n"


def _charter():
    return {
        "interpreted_intent": "make the script exit 0", "purpose": "demo",
        "dod": [{"id": "c1", "criterion": "script exits 0", "verify_intent": "exit==0", "kind": "shown"}],
        "assumptions": [{"text": "python is available", "confidence": 0.9}], "open_questions": [],
        "happy_path": "write the script", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _events(path):
    return [json.loads(l) for l in open(path) if l.strip()]


# --- lint.lint_paths unit behaviour -------------------------------------------------
def test_lint_paths_clean_broken_and_skips():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.py"); open(good, "w").write("x = 1\n\n\ndef f():\n    return x\n")
        bad = os.path.join(d, "bad.py"); open(bad, "w").write(_BROKEN)
        md = os.path.join(d, "notes.md"); open(md, "w").write("# title\n")

        ok, _ = lint.lint_paths([good])
        assert ok is True                                              # clean python passes
        ok2, res2 = lint.lint_paths([bad])
        assert ok2 is False and lint.failures(res2)                    # syntax error is a real failure
        ok3, res3 = lint.lint_paths([md])
        assert ok3 is True and res3 and res3[0].get("skipped")         # unmapped type -> skipped, not failed
        ok4, res4 = lint.lint_paths([os.path.join(d, "gone.py")])
        assert ok4 is True and res4 == []                             # missing file -> silently skipped
        ok5, _ = lint.lint_paths([good, bad])
        assert ok5 is False                                           # one bad file poisons the batch


def test_changed_paths_detects_created_and_modified():
    before = {"/a": (1, 10), "/b": (1, 20)}
    after = {"/a": (1, 10), "/b": (2, 25), "/c": (3, 5)}              # a same, b modified, c created
    assert set(dispatch._changed_paths(before, after)) == {"/b", "/c"}


# --- loop-level wiring: catch -> feed back -> recover -------------------------------
def test_lint_gate_catches_syntax_error_then_recovers():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.py")
        evid = []

        def implement(charter, attempt, last_failure):
            open(path, "w").write(_BROKEN if attempt == 0 else _CLEAN)
            return {"exit_code": 0, "files_changed": 1, "changed_paths": [path]}

        def verify_cmd_for(cid):
            evid.append(cid)
            return [sys.executable, "-c", ""]                         # always green WHEN reached

        res = loop.run_v1(_charter(), design=lambda c: {"t_c1": "c1"}, implement=implement,
                          judge_a=lambda t, c: True, judge_b=lambda t, c: True,
                          verify_cmd_for=verify_cmd_for, regression_cmd=["true"],
                          run_dir=os.path.join(d, ".devloop", "runs", "lt1"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        assert evid == ["c1"]                                         # evidence ran ONLY on the clean pass
        ev = _events(res["trace_path"])
        lints = [e for e in ev if e["step"] == "lint"]
        assert lints[0]["ok"] is False and lints[-1]["ok"] is True    # broke first, clean after the fix
        assert any(e["step"] == "rebuild_fail" and e.get("cause") == "lint" for e in ev)  # lint forced the rebuild


# --- loop-level fail-closed: persistent syntax error never COMPLETEs ----------------
def test_lint_gate_failclosed_on_persistent_syntax_error():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.py")
        evid = []

        def implement(charter, attempt, last_failure):
            open(path, "w").write(_BROKEN)                            # ALWAYS broken
            return {"exit_code": 0, "files_changed": 1, "changed_paths": [path]}

        def verify_cmd_for(cid):
            evid.append(cid)
            return [sys.executable, "-c", ""]                         # would be green IF ever reached

        res = loop.run_v1(_charter(), design=lambda c: {"t_c1": "c1"}, implement=implement,
                          judge_a=lambda t, c: True, judge_b=lambda t, c: True,
                          verify_cmd_for=verify_cmd_for,
                          run_dir=os.path.join(d, ".devloop", "runs", "lt2"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"                      # never COMPLETE despite green verify
        assert evid == []                                            # evidence NEVER ran — lint blocked every pass
        ev = _events(res["trace_path"])
        assert [e for e in ev if e["step"] == "lint"] and all(
            e["ok"] is False for e in ev if e["step"] == "lint")     # every pass got a lint failure


# --- discovery + expanded language coverage -----------------------------------------
def test_discover_reports_languages_and_runtime_gaps():
    rep = lint.discover()
    by_ext = {tuple(r["extensions"]): r for r in rep}
    # python + json have stdlib linters -> ALWAYS covered, regardless of what's installed
    assert by_ext[(".py",)]["covered"] is True and "py-syntax" in by_ext[(".py",)]["available"]
    assert by_ext[(".json",)]["covered"] is True
    # the web stack is WIRED (present in the report) even when its tools aren't installed here;
    # `covered` honestly reflects availability so a gap is visible, not silent.
    assert (".css", ".scss", ".less") in by_ext and (".html", ".htm") in by_ext
    js = by_ext[(".js", ".jsx", ".mjs", ".cjs")]
    assert "node --check" in js["linters"]
    assert js["covered"] == (lint._on_path("node"))     # covered iff node is actually on PATH


def test_lint_paths_validates_json():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "ok.json"); open(good, "w").write('{"a": 1, "b": [2, 3]}\n')
        bad = os.path.join(d, "bad.json"); open(bad, "w").write('{"a": 1, oops}\n')
        assert lint.lint_paths([good])[0] is True
        ok, res = lint.lint_paths([bad])
        assert ok is False and lint.failures(res)                    # invalid JSON is a real failure


def test_lint_paths_skips_web_linter_when_absent():
    # a .css file when stylelint isn't installed -> SKIPPED (graceful), never a false red
    if lint._on_path("stylelint"):
        return                                                       # tool present -> not the path under test
    with tempfile.TemporaryDirectory() as d:
        css = os.path.join(d, "x.css"); open(css, "w").write("body { color: red; }\n")
        ok, res = lint.lint_paths([css])
        assert ok is True and res and res[0].get("skipped")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} lint tests passed")
