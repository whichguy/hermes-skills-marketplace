"""End-to-end composition tests for the devloop kernel.

The production loop is PROSE in SKILL.md executed by the native Hermes runtime, so there is
no Python orchestrator to test directly. This file defines a TEST-ONLY reference
mini-orchestrator (`_drive_loop`) that composes ONLY real kernel calls in the documented
SKILL.md order, with injected dispatchers. It proves the kernel's central guarantees that NO
single-unit test can: a forged/vacuous test never COMPLETEs, a malformed/low-confidence
Charter never reaches BUILD, and a persistently-red loop always terminates via the backstop.

Plus an OPT-IN real-runtime spike smoke (approach b), double-gated so a default/laptop run
neither false-passes nor errors.

Run: cd <devloop> && python3 tests/test_e2e.py   (or: python3 -m pytest tests/test_e2e.py -q)
"""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "spike"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config        # noqa: E402
import state         # noqa: E402
import evidence      # noqa: E402
import gate          # noqa: E402
import dod_oracle    # noqa: E402
import run_spike     # noqa: E402
from test_smoke import _charter, _good_oracle  # noqa: E402

NO_TERMINATION = "NO_TERMINATION"

# affirming 3-seat council; an empty council (lambda c, i: []) fail-closes.
AFFIRM_3 = lambda c, i: [{"seat": s, "affirm": True, "missing": []} for s in "abc"]  # noqa: E731
GREEN = lambda cid: ["true"]   # noqa: E731
RED = lambda cid: ["false"]    # noqa: E731
YES = lambda t, c: True        # noqa: E731
NO = lambda t, c: False        # noqa: E731


def _drive_loop(charter, *, dispatch_advisors, judge_a, judge_b, test_to_criterion,
                evidence_cmd_for, run_dir=None, max_passes=64):
    """Compose the real kernel gates in SKILL.md loop order. Asserts nothing itself.
    Returns {terminal, entered_build, state, evidence_calls}. terminal is one of
    'HUMAN_REVIEW' | 'DoD-SATISFIED' | NO_TERMINATION (the last is a bug sentinel every
    test asserts is NEVER returned, proving the backstop — not max_passes — terminated)."""
    calls = []

    def _spy(cid):
        calls.append(cid)
        return evidence_cmd_for(cid)

    decision, _ = gate.ambiguity_gate(charter)
    if decision != config.DECISION_PROCEED:
        return {"terminal": "HUMAN_REVIEW", "entered_build": False, "state": None, "evidence_calls": calls}

    st = state.new_run_state(charter)
    by_id = {c["id"]: c for c in charter["dod"]}
    for _ in range(max_passes):
        action, _ = gate.backoff_exhausted(st)
        if action == "HUMAN_REVIEW":
            return {"terminal": "HUMAN_REVIEW", "entered_build": True, "state": st, "evidence_calls": calls}
        if action == "REPLAN":
            state.on_replan(st)
            continue
        ledger = {cid: evidence.run(cid, _spy(cid)) for cid in by_id}
        cov_ok, _ = dod_oracle.check_structural_coverage(charter["dod"], test_to_criterion)
        tests = [{"test_id": f"t_{cid}", "criterion_id": cid} for cid in by_id]
        jv = dod_oracle.judge_assertions(tests, by_id, judge_a, judge_b)
        st["evidence_ledger"] = ledger
        if run_dir:
            state.save_checkpoint(run_dir, st)
        ok, _ = gate.stop_condition(charter, ledger, cov_ok, jv)
        if ok:
            return {"terminal": "DoD-SATISFIED", "entered_build": True, "state": st, "evidence_calls": calls}
        state.on_rebuild_fail(st)
    return {"terminal": NO_TERMINATION, "entered_build": True, "state": st, "evidence_calls": calls}


def test_e2e_happy_path_reaches_dod_satisfied():
    r = _drive_loop(_charter(min_conf=0.9), dispatch_advisors=AFFIRM_3, judge_a=YES, judge_b=YES,
                    test_to_criterion={"t_c1": "c1"}, evidence_cmd_for=GREEN)
    assert r["terminal"] == "DoD-SATISFIED" and r["terminal"] != NO_TERMINATION
    assert r["entered_build"] is True
    assert r["state"]["rebuild_count"] == 0 and r["state"]["replan_count"] == 0  # first pass, untouched
    assert r["state"]["evidence_ledger"]["c1"].passed is True


def test_e2e_forged_green_test_never_completes():
    # All three: GREEN evidence + affirming council, so only the ORACLE surface is wrong.
    scenarios = [
        dict(judge_a=YES, judge_b=NO, test_to_criterion={"t_c1": "c1"}),   # (a) escalate
        dict(judge_a=NO, judge_b=NO, test_to_criterion={"t_c1": "c1"}),    # (b) no trusted test
        dict(judge_a=YES, judge_b=YES, test_to_criterion={}),             # (c) coverage gap
    ]
    for sc in scenarios:
        r = _drive_loop(_charter(min_conf=0.9), dispatch_advisors=AFFIRM_3,
                        evidence_cmd_for=GREEN, **sc)
        assert r["terminal"] != "DoD-SATISFIED", sc          # forged test must NOT complete
        assert r["terminal"] != NO_TERMINATION, sc           # and must still terminate
        assert r["terminal"] == "HUMAN_REVIEW", sc
        assert r["state"]["evidence_ledger"]["c1"].passed is True, sc  # rejection from oracle, not red evidence


def test_e2e_low_confidence_or_malformed_charter_routes_human_without_building():
    bad_charters = [_charter(min_conf=0.5), _charter_with_empty_dod(), _charter(blocking=True)]
    for ch in bad_charters:
        r = _drive_loop(ch, dispatch_advisors=AFFIRM_3, judge_a=YES, judge_b=YES,
                        test_to_criterion={"t_c1": "c1"}, evidence_cmd_for=GREEN)
        assert r["terminal"] == "HUMAN_REVIEW"
        assert r["entered_build"] is False        # never created run state
        assert r["state"] is None
        assert r["evidence_calls"] == []          # NOT ONE subprocess ran -> ordering proven


def test_e2e_persistent_red_terminates_via_backoff_to_human_review():
    r = _drive_loop(_charter(min_conf=0.9), dispatch_advisors=AFFIRM_3, judge_a=YES, judge_b=YES,
                    test_to_criterion={"t_c1": "c1"}, evidence_cmd_for=RED, max_passes=64)
    assert r["terminal"] == "HUMAN_REVIEW" and r["terminal"] != NO_TERMINATION
    assert r["state"]["replan_count"] == config.MAX_REPLANS
    # one criterion -> one evidence call per CONTINUE pass; backstop caps total work.
    assert len(r["evidence_calls"]) == config.MAX_LOCAL_REBUILDS * config.MAX_REPLANS
    assert len(r["evidence_calls"]) < 64          # backstop, not the safety cap, terminated


def test_e2e_checkpoint_resume_preserves_counters_and_ledger():
    st = state.new_run_state(_charter())
    state.on_rebuild_fail(st); state.on_rebuild_fail(st)   # rebuild 2
    state.on_replan(st)                                    # rebuild 0, replan 1
    state.on_rebuild_fail(st)                              # rebuild 1
    st["evidence_ledger"] = {"c1": evidence.run("c1", ["true"])}
    with tempfile.TemporaryDirectory() as d:
        state.save_checkpoint(d, st)
        loaded = state.load_checkpoint(d)
    assert loaded["rebuild_count"] == 1 and loaded["replan_count"] == 1   # survived exactly
    assert isinstance(loaded["evidence_ledger"]["c1"], evidence.Evidence)
    assert loaded["evidence_ledger"]["c1"].passed is True
    assert gate.backoff_exhausted(loaded)[0] == "CONTINUE"               # resumed counters still gate


# council_gate's own fail-closed behavior is covered in test_smoke.py + test_gate.py; it is not part
# of stop_condition (council is not wired into the live stop — see gate.stop_condition).


# --- opt-in real-runtime spike (approach b), double-gated ---------------------
def test_real_spike_smoke_optin():
    if os.environ.get("DEVLOOP_RUN_REAL_SPIKE") != "1" or not os.path.exists(run_spike.HERMES_BIN):
        print("SKIP test_real_spike_smoke_optin (set DEVLOOP_RUN_REAL_SPIKE=1 inside the container)")
        return
    out = run_spike.run_one({"id": "smoke", "request": "add a shared helper used by two files",
                             "touches": ["a.py", "b.py"]})
    v = run_spike.analyze({**out, "task_id": "smoke", "run_idx": 0, "expect_human_review": False})
    assert v["gated_stop_ok"] and v["phase_skips"] == [] and v["verdict"] == "pass", out


def _charter_with_empty_dod():
    ch = _charter()
    ch["dod"] = []
    return ch


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} e2e tests passed")
