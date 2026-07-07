"""Mutation-killing tests for gate.py — close confirmed coverage gaps (surviving mutants).

Each test pins CURRENT correct behavior in a direction the existing suite never exercises,
so the deliberate old->new mutant would FAIL it. Deterministic, no LLM: the gates here are
pure functions / take an injected dispatcher lambda.

Run: cd ~/.hermes/skills/software-development/devloop && python3 -m pytest tests/test_gate.py -q
(or: python3 tests/test_gate.py for a dependency-free run)
"""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config          # noqa: E402
import gate            # noqa: E402


def _charter(min_conf=0.9, blocking=False, assumptions=None, open_questions=None):
    # Local copy of the smoke-suite helper (do NOT import across test files).
    return {
        "interpreted_intent": "x", "purpose": "y",
        "dod": [{"id": "c1", "criterion": "returns 200", "verify_intent": "status==200", "kind": "shown"}],
        "assumptions": [{"text": "a", "confidence": min_conf}] if assumptions is None else assumptions,
        "open_questions": [{"text": "q", "blocking": blocking}] if open_questions is None else open_questions,
        "happy_path": "do it", "blast_radius": {"files": ["a.py"], "order": ["a.py"]},
        "backoff_map": [{"trigger": "x", "directional_response": "y"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


# --- (a) ambiguity_gate: floor applies to the WEAKEST assumption (min, not max) ----
def test_ambiguity_gate_routes_human_on_weakest_assumption_not_strongest():
    # CONFIDENCE_FLOOR=0.7. One assumption far above floor, one load-bearing one well below.
    # The decision-2 invariant is min(assumption.confidence) >= floor, so the WEAK one governs.
    ch = _charter(assumptions=[{"text": "trivial", "confidence": 0.95},
                               {"text": "load-bearing", "confidence": 0.3}])
    # min(0.95,0.3)=0.3 < 0.7 -> HUMAN_REVIEW. The `max(confs)` mutant sees 0.95 >= 0.7 -> PROCEED.
    assert gate.ambiguity_gate(ch)[0] == config.DECISION_ROUTE_HUMAN_REVIEW
    # CONTROL (both above floor must still PROCEED): blocks a constant ROUTE_HUMAN_REVIEW from
    # passing trivially — under min() AND max() this is PROCEED, so it pins the non-mutant axis.
    ch2 = _charter(assumptions=[{"text": "a", "confidence": 0.95}, {"text": "b", "confidence": 0.8}])
    assert gate.ambiguity_gate(ch2)[0] == config.DECISION_PROCEED


# --- (b) council_gate: a seatless verdict must NOT pad the distinct-seat COUNT ------
def test_council_gate_seatless_verdict_cannot_pad_seat_count():
    crit = [{"id": "c1"}]
    verdicts = [{"seat": "a", "affirm": True, "missing": []},
                {"seat": "b", "affirm": True, "missing": []},
                {"seat": None, "affirm": True, "missing": []}]   # seatless filler
    # Only 2 DISTINCT real seats < COUNCIL_SIZE(3); the `if v.get("seat")` filter drops None.
    ok, reason = gate.council_gate(crit, "i", lambda c, i: verdicts)
    # Mutant `{v.get("seat") for v in verdicts}` -> {a,b,None} len 3 passes the size gate, then
    # affirm_seats {a,b}=quorum, no missing -> AFFIRMED. So correct code must FAIL-CLOSE here.
    assert ok is False and "seats present" in reason
    # CONTROL (3 real distinct affirming seats must AFFIRM): guards against a constant-False
    # regression masking the kill above; this path is True under both the gate and the mutant.
    real = [{"seat": s, "affirm": True, "missing": []} for s in "abc"]
    assert gate.council_gate(crit, "i", lambda c, i: real)[0] is True


# --- (b) council_gate: affirm_seats is a SET — duplicate affirms from one seat count once --
def test_council_gate_duplicate_affirming_seat_is_not_quorum():
    crit = [{"id": "c1"}]
    # 3 DISTINCT seats present (passes the COUNCIL_SIZE gate), but only seat 'a' affirms — twice;
    # b and c reject. A distinct-seat quorum dedupes 'a' to a single affirming seat.
    verdicts = [{"seat": "a", "affirm": True, "missing": []},
                {"seat": "a", "affirm": True, "missing": []},
                {"seat": "b", "affirm": False, "missing": []},
                {"seat": "c", "affirm": False, "missing": []}]
    ok, reason = gate.council_gate(crit, "i", lambda c, i: verdicts)
    # 1 DISTINCT affirming seat < COUNCIL_QUORUM(2). The list-mutant counts [a,a]=2 -> AFFIRMS.
    assert ok is False and "quorum" in reason
    # CONTROL (2 DISTINCT seats affirming = quorum -> AFFIRM): pins the non-mutant axis; True
    # under both set and list, so a constant-False test couldn't satisfy both assertions.
    two = [{"seat": "a", "affirm": True, "missing": []},
           {"seat": "b", "affirm": True, "missing": []},
           {"seat": "c", "affirm": False, "missing": []}]
    assert gate.council_gate(crit, "i", lambda c, i: two)[0] is True


# --- (c) council_gate: malformed (non-dict) verdicts must FAIL-CLOSE, not crash (gate.py fix) --
def test_council_gate_fail_closed_on_malformed_nondict_verdicts():
    crit = [{"id": "c1"}]
    # a weak advisors wrapper returns a non-empty, non-dict payload (strings, not {seat,...} dicts).
    # Verdict-shape parsing sits inside a guard, so str.get raising AttributeError must ROUTE-not-
    # CRASH per the docstring's fail-closed contract. (Before the fix this raised into the loop.)
    ok, reason = gate.council_gate(crit, "i", lambda c, i: ["a", "b", "c"])
    assert ok is False and "malformed" in reason
    # CONTROL: a well-formed affirming council still AFFIRMS (the guard didn't swallow the happy path).
    real = [{"seat": s, "affirm": True, "missing": []} for s in "abc"]
    assert gate.council_gate(crit, "i", lambda c, i: real)[0] is True


# --- vague_goal_gate: code-enforced unmeasurable-goal screen -----------------------
def test_vague_goal_gate_routes_markered_request_with_no_target():
    # 'Make the app faster.' + a digit-free self-referential charter must ROUTE — this is the
    # exact spike_recal false-complete shape the prompt-only guard let through twice.
    # Mutants killed: `if not hits:` -> `if True:` (gate disabled -> PROCEED) and
    # `if not req_nums:` -> `if False:` (no-target branch skipped; digit-free charter -> PROCEED).
    ch = _charter()
    ch["dod"] = [{"id": "c1", "criterion": "new impl is faster than baseline",
                  "verify_intent": "impl faster than before", "kind": "shown"}]
    decision, reason = gate.vague_goal_gate("Make the app faster.", ch)
    assert decision == config.DECISION_ROUTE_HUMAN_REVIEW
    assert "no measurable target" in reason


def test_vague_goal_gate_ignores_concrete_requests():
    # Control: no marker -> PROCEED even though the criterion invents example numbers
    # (add(2,3)==5) — an unconditional fabricated-number check would nuke every normal task.
    ch = _charter()
    ch["dod"] = [{"id": "c1", "criterion": "add returns the sum",
                  "verify_intent": "add(2,3)==5", "kind": "shown"}]
    decision, _ = gate.vague_goal_gate("Add subtract(a, b) to calc.py", ch)
    assert decision == config.DECISION_PROCEED


def test_vague_goal_gate_flags_fabricated_benchmark_number():
    # Marker + request numbers: a criterion quoting a number the request never stated is a
    # fabricated benchmark -> ROUTE. Quoting only request numbers (float-compare: '2' == '2.0')
    # -> PROCEED. Mutant killed: `if fabricated:` -> `if False:`.
    req = "make the tokenizer faster: 1000 lines must parse in under 2 seconds"
    ch = _charter()
    ch["dod"] = [{"id": "c1", "criterion": "parses 1000 lines in under 2.0 seconds",
                  "verify_intent": "1000 lines parse < 2.0s", "kind": "shown"}]
    decision, _ = gate.vague_goal_gate(req, ch)
    assert decision == config.DECISION_PROCEED          # 1000 + 2.0 both stated in the request
    ch["dod"][0] = {"id": "c1", "criterion": "parses 1000 lines in under 200 ms",
                    "verify_intent": "1000 lines parse < 200ms", "kind": "shown"}
    decision, reason = gate.vague_goal_gate(req, ch)
    assert decision == config.DECISION_ROUTE_HUMAN_REVIEW   # 200 was never stated -> fabricated
    assert "200" in reason and "fabricated" in reason


def test_vague_goal_gate_edge_pins():
    # Edge-input pins (2026-07-02 audit): this gate exists because the prompt-only version
    # false-completed twice, so its edges are pinned explicitly. All routes here are the
    # accepted-conservative direction: over-matching costs a human look, never a false COMPLETE.
    hr, ok = config.DECISION_ROUTE_HUMAN_REVIEW, config.DECISION_PROCEED
    # multiple markers, no number anywhere -> HR (no-target branch)
    d, _ = gate.vague_goal_gate("make it faster and cleaner and more robust", {"dod": []})
    assert d == hr
    # %-style target stated in the request and echoed by the criterion -> PROCEED
    req = "optimize the endpoint: p95 improves by 20 percent"
    d, _ = gate.vague_goal_gate(req, {"dod": [{"id": "c1", "criterion": "p95 latency improves by 20",
                                               "verify_intent": "measure"}]})
    assert d == ok
    # ...but a criterion quoting a number the request never stated -> HR (fabricated)
    d, r = gate.vague_goal_gate(req, {"dod": [{"id": "c1", "criterion": "latency under 25",
                                               "verify_intent": "measure"}]})
    assert d == hr and "25" in r
    # marker only in the DoD, never in the request -> PROCEED (the gate is request-scoped by
    # design: a concrete request stays concrete even if the planner phrased a criterion loosely)
    d, _ = gate.vague_goal_gate("add a Sum function",
                                {"dod": [{"id": "c1", "criterion": "faster than 100 ms", "verify_intent": ""}]})
    assert d == ok
    # UNIT MISMATCH pinned as accepted-conservative: request says 200 (ms), criterion says the
    # same target as 0.2 (seconds) -> HR. The gate float-compares raw literals, it does NOT
    # normalize units; a unit conversion reads as a fabricated number and costs a human look.
    d, r = gate.vague_goal_gate("speed up parsing: respond within 200 ms",
                                {"dod": [{"id": "c1", "criterion": "responds in 0.2 seconds",
                                          "verify_intent": ""}]})
    assert d == hr and "0.2" in r
    # non-ASCII digits: \d is Unicode and float() normalizes, so '٥' in the request MATCHES a
    # criterion's '5' (no crash, no spurious fabricated-number route)
    d, _ = gate.vague_goal_gate("make it faster: finish in ٥ seconds",
                                {"dod": [{"id": "c1", "criterion": "runs in 5 seconds", "verify_intent": ""}]})
    assert d == ok


def test_ambiguity_gate_empty_assumptions_routes_human_by_design():
    # E5 pin (2026-07-02 audit): an EMPTY assumptions list -> confs=[] -> low=0.0 < floor ->
    # HUMAN_REVIEW, even for a crisp fully-specified request. KEPT deliberately: treating "no
    # declared uncertainty" as confidence would WEAKEN the gate; the planner prompt requires >=1
    # calibrated assumption instead. Fail-closed over-route — costs a human look, never a false
    # COMPLETE. (The `empty assumptions fail OPEN` mutant pins the same direction.)
    ch = _charter(assumptions=[])
    d, reason = gate.ambiguity_gate(ch)
    assert d == config.DECISION_ROUTE_HUMAN_REVIEW and "confidence" in reason


# --- regression_gate: whole-suite green required for COMPLETE ----------------------
def _ev(exit_code):
    import evidence
    return evidence.Evidence(criterion_id="__suite__", cmd=("pytest",),
                             exit_code=exit_code, passed=(exit_code == 0))


def test_regression_gate_exit_code_matrix():
    # green (0) and vacuous (pytest exit 5 = no tests collected) pass; ANY other exit fails
    # closed, incl. exit 1 (test failures) and None (timeout/OSError Evidence).
    # Mutant killed: `if code in (0, 5):` -> `in (0, 1, 5)` (red suite reads as pass).
    assert gate.regression_gate(_ev(0)) == (True, "whole-suite green")
    ok5, r5 = gate.regression_gate(_ev(5))
    assert ok5 and "nothing to regress" in r5
    ok1, r1 = gate.regression_gate(_ev(1))
    assert not ok1 and "regression red" in r1
    okt, _ = gate.regression_gate(_ev(None))
    assert not okt                                       # timeout Evidence (exit_code None)


def test_regression_gate_fail_closed_on_missing_or_shapeless_evidence():
    # None -> fail-closed with the explicit no-evidence reason (kills `if ev is None:` -> `if False:`
    # which would fall through to the generic red message). A shapeless object (no exit_code attr)
    # must also fail closed (kills getattr default 0 = fail-open).
    ok, reason = gate.regression_gate(None)
    assert not ok and "no regression evidence" in reason
    ok2, _ = gate.regression_gate(object())              # no exit_code attr -> None -> red
    assert not ok2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
