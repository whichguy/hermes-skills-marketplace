"""Dispatch-error short-circuit tests (the learning-3 fix) — deterministic, no LLM.

A model/dispatch ERROR (coder process errored, or made NO file change) must route to
HUMAN_REVIEW FAST — without burning the rebuild/replan budget that a genuine code red would.
Still fail-closed: a broken coder routes to a human, never to COMPLETE. The one subtlety: a
zero-diff that is already GREEN is "already satisfied" -> COMPLETE, not an error.
(Ported to run_v1 2026-07-02 when the v0 `loop.run` was deleted.)
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import loop  # noqa: E402

_YES = (lambda t, c: True)
_GREEN_SUITE = ["true"]                   # regression stand-in: whole suite green


def _design_for(n):
    return lambda c: {f"t_c{i}": f"c{i}" for i in range(1, n + 1)}


def _charter(n=1):
    dod = [{"id": f"c{i}", "criterion": f"crit {i}", "verify_intent": f"v{i}", "kind": "shown"}
           for i in range(1, n + 1)]
    return {
        "interpreted_intent": "demo", "purpose": "demo", "dod": dod,
        "assumptions": [{"text": "a", "confidence": 0.9}], "open_questions": [],
        "happy_path": "implement, verify", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _events(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def _count(ev, step):
    return sum(1 for e in ev if e["step"] == step)


def test_errored_coder_short_circuits_without_running_tests():
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(), design=_design_for(1),
                          implement=lambda c, a, lf: {"exit_code": 1, "files_changed": 0, "summary": "ctx exceeded"},
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: ["false"], run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        ev = _events(res["trace_path"])
        assert any(e["step"] == "dispatch_error" for e in ev)
        assert _count(ev, "evidence") == 0        # never even ran the tests
        assert res["state"]["rebuild_count"] == 0  # NOT the 9-run/3-replan grind a code-red would burn


def test_noop_coder_with_red_routes_human_fast():
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(), design=_design_for(1),
                          implement=lambda c, a, lf: {"exit_code": 0, "files_changed": 0, "summary": "did nothing"},
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: ["false"], run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        ev = _events(res["trace_path"])
        assert any(e["step"] == "dispatch_error" for e in ev)
        assert _count(ev, "evidence") == 1        # ran ONCE (zero-diff check), not 9
        assert res["state"]["rebuild_count"] == 0


def test_noop_but_already_satisfied_completes():
    # zero-diff is NOT always an error: if the tests are already GREEN, the task is satisfied.
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(), design=_design_for(1),
                          implement=lambda c, a, lf: {"exit_code": 0, "files_changed": 0, "summary": "already done"},
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: ["true"], run_dir=os.path.join(d, "run"),
                          cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"


def test_healthy_dict_implement_still_iterates_red_to_green():
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")

        def impl(c, a, lf):
            open(script, "w").write(f"import sys; sys.exit(0 if {a} >= 1 else 1)\n")
            return {"exit_code": 0, "files_changed": 1, "summary": "wrote m.py"}

        res = loop.run_v1(_charter(), design=_design_for(1), implement=impl,
                          judge_a=_YES, judge_b=_YES,
                          verify_cmd_for=lambda cid: [sys.executable, script],
                          run_dir=os.path.join(d, "run"), cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE" and res["state"]["rebuild_count"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} dispatch-error tests passed")
