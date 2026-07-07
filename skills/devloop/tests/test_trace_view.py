"""trace_view must render EVERY event type; an unknown event falls through to a compact-JSON
line, never silently dropped (deep review 2026-07-01 — the old renderer dropped judge/coverage/
stop_check/attribution/lint, i.e. every v1 verification step was invisible in the human view).

Run: python3 -m pytest tests/test_trace_view.py -q  (or python3 tests/test_trace_view.py)
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import trace_view  # noqa: E402

_EVENTS = [
    {"ts": 100.0, "step": "charter", "intent": "build x", "n_criteria": 1,
     "dod": [{"id": "c1", "criterion": "crit-text", "verify_intent": "v"}],
     "assumptions": [], "open_questions": [{"text": "blocker-q", "blocking": True}]},
    {"ts": 101.0, "step": "ambiguity_gate", "decision": "PROCEED", "reason": "ok"},
    {"ts": 102.0, "step": "coverage", "ok": True, "uncovered": []},
    {"ts": 103.0, "step": "judge", "verdicts": [
        {"criterion": "c1", "encodes": True, "escalate": False, "judge_a": True, "judge_b": True}]},
    {"ts": 104.0, "step": "attribution", "fault": "test", "criteria": ["c1"]},
    {"ts": 105.0, "step": "lint_discovery", "coverage": {"py": True}},
    {"ts": 106.0, "step": "lint", "attempt": 0, "ok": False, "checked": 1, "skipped": 0,
     "failures": [{"path": "a.py", "linter": "ruff", "out": "E999"}]},
    {"ts": 107.0, "step": "backoff", "action": "CONTINUE", "rebuild": 0, "replan": 0, "reason": "ok"},
    {"ts": 108.0, "step": "replan", "replan": 1},
    {"ts": 109.0, "step": "implement", "attempt": 0, "dur_s": 1.5, "summary": "wrote a.py"},
    {"ts": 110.0, "step": "evidence", "criterion": "c1", "cmd": ["true"], "exit": 0,
     "passed": True, "stderr_tail": ""},
    {"ts": 111.0, "step": "stop_check", "complete": True, "reason": "DoD-SATISFIED"},
    {"ts": 112.0, "step": "regression", "exit": 0, "passed": True, "reason": "whole-suite green"},
    {"ts": 113.0, "step": "rebuild_fail", "rebuild": 1, "cause": "regression"},
    {"ts": 114.0, "step": "dispatch_error", "reason": "coder exploded"},
    {"ts": 115.0, "step": "some_future_event", "detail": "novel-payload"},
    # frozen_tests has no dedicated branch — it must surface via the compact-JSON fallback (the
    # forensic trace is the only artifact left after worktree cleanup; a dropped gate event would
    # make a forged-green diagnosis impossible post-hoc).
    {"ts": 115.5, "step": "frozen_tests", "ok": False, "reason": "changed=[test_x.py]",
     "restored": ["test_x.py"]},
    {"ts": 116.0, "step": "terminal", "terminal": "COMPLETE"},
]


def _render_all():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "trace.jsonl")
        open(p, "w").write("\n".join(json.dumps(e) for e in _EVENTS) + "\n")
        return trace_view.render(p)


def test_every_event_type_renders():
    out = _render_all()
    for marker in ("CHARTER", "crit-text", "BLOCKING: blocker-q",       # charter carries the DoD text
                   "ambiguity_gate -> PROCEED", "coverage -> ok",
                   "judge c1: trusted a=True b=True",                    # per-judge votes visible
                   "ATTRIBUTION: test fault",
                   "lint discovery", "lint attempt=0: FAIL",
                   "backoff_exhausted -> CONTINUE", "RE-PLAN",
                   "IMPLEMENT  attempt=0 dur=1.5s",
                   "evidence.run c1: exit=0 [PASS]",
                   "stop_condition -> COMPLETE-able",
                   "REGRESSION (whole suite): exit=0 [PASS]",
                   "rebuild_count=1 cause=regression",
                   "DISPATCH ERROR: coder exploded",
                   "== COMPLETE =="):
        assert marker in out, f"missing render for: {marker}"
    assert "+" in out                                                   # elapsed prefixes present


def test_unknown_event_never_silently_dropped():
    # Mutant killed: default branch -> pass (a novel event type vanishes from the human view).
    out = _render_all()
    assert "some_future_event" in out and "novel-payload" in out
    assert "frozen_tests" in out and "test_x.py" in out    # the frozen-gate event surfaces too


def test_chain_view_pivots_by_criterion():
    """C7: --chain renders the per-criterion TDD chain (promise -> intention -> judges ->
    tests -> evidence -> terminal) and NEVER drops a criterion — one that never ran evidence
    still gets a block. Mutant killed: criterion loop dropped."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "trace.jsonl")
        evs = [
            {"step": "charter", "dod": [
                {"id": "c1", "criterion": "does X", "verify_intent": "X happens"},
                {"id": "c2", "criterion": "does Y", "verify_intent": "Y happens"}]},
            {"step": "judge", "verdicts": [
                {"criterion": "c1", "encodes": True, "judge_a": True, "judge_b": True}]},
            {"step": "evidence", "criterion": "c1", "exit": 0, "passed": True},
            {"step": "grounding", "criteria": [{"criterion_id": "c1", "tests": ["t.py::test_c1"]}]},
            {"step": "terminal", "terminal": "COMPLETE"},
        ]
        open(p, "w").write("\n".join(json.dumps(e) for e in evs) + "\n")
        out = trace_view.chain(p)
        assert "does X" in out and "X happens" in out           # promise + intention
        assert "[unit]" in out                                  # tier marker (default unit)
        assert "a=True b=True" in out and "trusted" in out
        assert "t.py::test_c1" in out
        assert "PASS" in out and "COMPLETE" in out
        assert "does Y" in out and "(never ran)" in out         # NO criterion dropped


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} trace_view tests passed")
