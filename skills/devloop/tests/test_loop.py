"""Real end-to-end tests of the loop spine (loop.run_v1) — NO LLM.

Fake dispatchers write REAL files; `evidence.run` executes a REAL subprocess; the loop must
genuinely iterate red->green, terminate on persistent red, and route to HUMAN_REVIEW on an
ambiguous Charter — and produce a correct, inspectable trace (the kernel-call audit).
(Ported from the v0 `loop.run` 2026-07-02 when v0 was deleted: its evidence-only COMPLETE was a
latent fail-open entry point. Injected always-True judges + a green regression_cmd keep these
tests pinned on the SPINE mechanics; the gate semantics have their own suites.)
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config        # noqa: E402
import loop          # noqa: E402
import trace_view    # noqa: E402

_YES = (lambda t, c: True)
_DESIGN = (lambda c: {"t_c1": "c1"})      # one test covering the single criterion
_GREEN_SUITE = ["true"]                   # regression stand-in: whole suite green


def _charter(blocking=False):
    return {
        "interpreted_intent": "make the script exit 0", "purpose": "demo",
        "dod": [{"id": "c1", "criterion": "script exits 0", "verify_intent": "exit==0", "kind": "shown"}],
        "assumptions": [{"text": "python is available", "confidence": 0.9}],
        "open_questions": [{"text": "q", "blocking": blocking}] if blocking else [],
        "happy_path": "write the script", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _events(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def test_loop_iterates_red_then_green():
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t1")

        def implement(charter, attempt, last_failure):
            # attempt 0 writes a FAILING script; attempt>=1 writes a PASSING one (the "fix")
            open(script, "w").write(f"import sys; sys.exit(0 if {attempt} >= 1 else 1)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: [sys.executable, script], run_dir=run_dir,
                          cwd=d, regression_cmd=_GREEN_SUITE)

        assert res["terminal"] == "COMPLETE"
        assert res["state"]["rebuild_count"] == 1          # exactly one red retry before green
        ev = _events(res["trace_path"])
        steps = [e["step"] for e in ev]
        assert "ambiguity_gate" in steps                    # the gate was genuinely CALLED
        assert steps.count("evidence") == 2                 # one real red + one real green
        assert any(e["step"] == "evidence" and not e["passed"] for e in ev)   # a REAL failing subprocess
        assert any(e["step"] == "evidence" and e["passed"] for e in ev)       # a REAL passing subprocess
        assert ev[-1]["terminal"] == "COMPLETE"
        # the inspector renders without error and shows the terminal
        rendered = trace_view.render(res["trace_path"])
        assert "COMPLETE" in rendered and "IMPLEMENT" in rendered


def test_loop_routes_human_on_ambiguous_charter():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, ".devloop", "runs", "t2")
        calls = []

        def implement(*a):
            calls.append(1)

        res = loop.run_v1(_charter(blocking=True), design=lambda c: calls.append("design"),
                          implement=implement, judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: ["true"], run_dir=run_dir, cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert calls == []                                  # never designed, implemented, or verified
        steps = [e["step"] for e in _events(res["trace_path"])]
        assert "evidence" not in steps and "implement" not in steps


def test_loop_terminates_on_persistent_red():
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t3")

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(1)\n")     # always fails

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: [sys.executable, script], run_dir=run_dir,
                          cwd=d, max_passes=64)
        assert res["terminal"] == "HUMAN_REVIEW"             # back-off, not infinite loop
        assert res["terminal"] != "NO_TERMINATION"
        assert res["state"]["replan_count"] == config.MAX_REPLANS
        ev = _events(res["trace_path"])
        n_evidence = sum(1 for e in ev if e["step"] == "evidence")
        assert n_evidence == config.MAX_LOCAL_REBUILDS * config.MAX_REPLANS  # 9; capped, not runaway


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} loop-spine tests passed")
