"""Smoke + regression tests for the devloop trust kernel.

Covers the deterministic cores AND the fixes from the 2026-06-29 adversarial review
(fail-closed gates, ledger round-trip, charter validation, backstop, spike).

Run: cd ~/.hermes/skills/software-development/devloop && python3 -m pytest tests/ -q
(or: python3 tests/test_smoke.py for a dependency-free run)
"""
import json
import os
import shutil
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "spike"))

import config          # noqa: E402
import state           # noqa: E402
import evidence        # noqa: E402
import gate            # noqa: E402
import dod_oracle      # noqa: E402
import run_spike       # noqa: E402


def _charter(min_conf=0.9, blocking=False, assumptions=None, open_questions=None):
    return {
        "interpreted_intent": "x", "purpose": "y",
        "dod": [{"id": "c1", "criterion": "returns 200", "verify_intent": "status==200", "kind": "shown"}],
        "assumptions": [{"text": "a", "confidence": min_conf}] if assumptions is None else assumptions,
        "open_questions": [{"text": "q", "blocking": blocking}] if open_questions is None else open_questions,
        "happy_path": "do it", "blast_radius": {"files": ["a.py"], "order": ["a.py"]},
        "backoff_map": [{"trigger": "x", "directional_response": "y"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _good_oracle(charter):
    """Coverage + judge verdicts that should let a green ledger COMPLETE."""
    ids = [c.get("id") for c in charter["dod"] if c.get("id")]
    verdicts = [{"test_id": f"t_{i}", "criterion_id": cid, "encodes": True, "escalate": False}
                for i, cid in enumerate(ids)]
    return True, verdicts


# --- state / charter ----------------------------------------------------------
def test_charter_validation():
    assert state.validate_charter(_charter()) == []
    bad = _charter(); del bad["dod"]
    assert any("dod" in e for e in state.validate_charter(bad))


def test_charter_empty_lists_are_valid():
    # empty assumptions/open_questions == "none", must NOT be rejected (review S5)
    assert state.validate_charter(_charter(assumptions=[], open_questions=[])) == []


def test_atomic_checkpoint_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        st = state.new_run_state(_charter())
        state.save_checkpoint(d, st)
        loaded = state.load_checkpoint(d)
        assert loaded["charter"]["interpreted_intent"] == "x"
        assert loaded["rebuild_count"] == 0 and loaded["replan_count"] == 0
    assert state.load_checkpoint(tempfile.gettempdir() + "/devloop-nope-xyz") is None


def test_load_checkpoint_rejects_garbage():
    # wrong-type / partial JSON must not resume (review S1)
    with tempfile.TemporaryDirectory() as d:
        for bad in ("null", "[]", "123", '{"no_charter": 1}'):
            p = os.path.join(d, "ITERATION_STATE.json")
            with open(p, "w") as f:
                f.write(bad)
            assert state.load_checkpoint(d) is None


def test_evidence_ledger_survives_roundtrip():
    # review M3: Evidence must serialize and rehydrate, and stop_condition still pass
    ch = _charter()
    st = state.new_run_state(ch)
    st["evidence_ledger"] = {"c1": evidence.run("c1", ["true"])}
    with tempfile.TemporaryDirectory() as d:
        state.save_checkpoint(d, st)
        loaded = state.load_checkpoint(d)
    led = loaded["evidence_ledger"]
    assert isinstance(led["c1"], evidence.Evidence) and led["c1"].passed
    cov, jv = _good_oracle(ch)
    assert gate.stop_condition(ch, led, cov, jv)[0] is True


# --- evidence -----------------------------------------------------------------
def test_evidence_fail_closed():
    assert evidence.run("c1", ["true"]).passed
    assert not evidence.run("c1", ["false"]).passed
    assert not evidence.run("c1", ["this-binary-does-not-exist-xyz"]).passed
    assert not evidence.run("c1", []).passed


def test_all_passing_empty_is_false():
    assert evidence.all_passing({}, []) is False          # review S4: vacuous pass closed
    assert evidence.all_passing({"c1": evidence.run("c1", ["true"])}, ["c1"]) is True


# --- ambiguity gate -----------------------------------------------------------
def test_ambiguity_gate():
    assert gate.ambiguity_gate(_charter(min_conf=0.9))[0] == config.DECISION_PROCEED
    assert gate.ambiguity_gate(_charter(min_conf=0.5))[0] == config.DECISION_ROUTE_HUMAN_REVIEW
    assert gate.ambiguity_gate(_charter(blocking=True))[0] == config.DECISION_ROUTE_HUMAN_REVIEW


def test_ambiguity_gate_empty_and_null_confidence():
    # review M5: empty assumptions must NOT auto-PROCEED; null confidence must not crash
    assert gate.ambiguity_gate(_charter(assumptions=[]))[0] == config.DECISION_ROUTE_HUMAN_REVIEW
    assert gate.ambiguity_gate(_charter(assumptions=[{"text": "a", "confidence": None}]))[0] \
        == config.DECISION_ROUTE_HUMAN_REVIEW


def test_ambiguity_gate_nan_inf_confidence_fail_closed():
    # verification follow-up: NaN/Inf (json.loads accepts bare NaN) must NOT auto-PROCEED
    for bad in (float("nan"), float("inf"), float("-inf"), "high", True):
        assert gate.ambiguity_gate(_charter(assumptions=[{"text": "a", "confidence": bad}]))[0] \
            == config.DECISION_ROUTE_HUMAN_REVIEW, f"confidence={bad!r} should route to human"


def test_ambiguity_gate_invalid_charter_routes_human():
    bad = _charter(); bad["dod"] = []
    assert gate.ambiguity_gate(bad)[0] == config.DECISION_ROUTE_HUMAN_REVIEW  # review S2


# --- stop condition -----------------------------------------------------------
def test_stop_condition():
    ch = _charter()
    cov, jv = _good_oracle(ch)
    green = {"c1": evidence.run("c1", ["true"])}
    red = {"c1": evidence.run("c1", ["false"])}
    assert gate.stop_condition(ch, green, cov, jv)[0] is True
    assert gate.stop_condition(ch, red, cov, jv)[0] is False       # evidence red
    assert gate.stop_condition(ch, {}, cov, jv)[0] is False        # missing evidence


def test_stop_condition_requires_oracle():
    ch = _charter()
    green = {"c1": evidence.run("c1", ["true"])}
    _, jv = _good_oracle(ch)
    assert gate.stop_condition(ch, green, False, jv)[0] is False             # coverage failed (M2)
    assert gate.stop_condition(ch, green, True, [])[0] is False              # no judge verdict (M2)
    bad_jv = [{"criterion_id": "c1", "encodes": True, "escalate": True}]
    assert gate.stop_condition(ch, green, True, bad_jv)[0] is False          # escalated judge (M2)


def test_stop_condition_idless_criterion_fail_closed():
    # review M1: a mix of id'd + un-id'd criteria must NOT COMPLETE
    ch = _charter()
    ch["dod"].append({"criterion": "no id", "verify_intent": "x"})
    green = {"c1": evidence.run("c1", ["true"])}
    cov, jv = _good_oracle(ch)
    assert gate.stop_condition(ch, green, cov, jv)[0] is False


# --- council gate -------------------------------------------------------------
def _seats(*names, missing=()):
    return [{"seat": n, "affirm": True, "missing": list(missing) if n == names[0] else []} for n in names]


def test_council_gate():
    crit = [{"id": "c1"}]
    assert gate.council_gate(crit, "i", lambda c, i: [])[0] is False                       # no verdicts
    assert gate.council_gate(crit, "i", lambda c, i: (_ for _ in ()).throw(RuntimeError()))[0] is False
    assert gate.council_gate(crit, "i", lambda c, i: _seats("a", "b"))[0] is False          # <3 seats (S3)
    assert gate.council_gate(crit, "i", lambda c, i: _seats("a", "a", "b"))[0] is False     # dup seat (S3)
    assert gate.council_gate(crit, "i", lambda c, i: _seats("a", "b", "c"))[0] is True
    assert gate.council_gate(crit, "i", lambda c, i: _seats("a", "b", "c", missing=["c2"]))[0] is False


# --- dod oracle ---------------------------------------------------------------
def test_structural_coverage_and_judge_agreement():
    crits = [{"id": "c1", "verify_intent": "x"}, {"id": "c2", "verify_intent": "y"}]
    ok, uncovered = dod_oracle.check_structural_coverage(crits, {"t1": "c1"})
    assert not ok and uncovered == ["c2"]
    assert dod_oracle.check_structural_coverage(crits, {"t1": "c1", "t2": "c2"})[0]
    by_id = {c["id"]: c for c in crits}
    tests = [{"test_id": "t1", "criterion_id": "c1"}]
    agree = dod_oracle.judge_assertions(tests, by_id, lambda t, c: True, lambda t, c: True)
    assert agree[0]["encodes"] and not agree[0]["escalate"]
    disagree = dod_oracle.judge_assertions(tests, by_id, lambda t, c: True, lambda t, c: False)
    assert not disagree[0]["encodes"] and disagree[0]["escalate"]


# --- termination backstop -----------------------------------------------------
def test_backoff_exhausted():
    assert gate.backoff_exhausted({"rebuild_count": 0, "replan_count": 0})[0] == "CONTINUE"
    assert gate.backoff_exhausted({"rebuild_count": config.MAX_LOCAL_REBUILDS, "replan_count": 0})[0] == "REPLAN"
    assert gate.backoff_exhausted({"rebuild_count": 0, "replan_count": config.MAX_REPLANS})[0] == "HUMAN_REVIEW"


def test_run_counters():
    st = state.new_run_state(_charter())
    state.on_rebuild_fail(st); state.on_rebuild_fail(st)
    assert st["rebuild_count"] == 2
    state.on_replan(st)
    assert st["replan_count"] == 1 and st["rebuild_count"] == 0  # rebuilds reset on replan


# --- spike harness ------------------------------------------------------------
def test_spike_analyze_human_review_not_a_skip():
    # review S8: a legit early HUMAN_REVIEW exit must PASS, not fail on phase-skips
    run = {"task_id": "t", "run_idx": 0, "phase_trace": ["CHARTER"],
           "entered_human_review": True, "reported_complete": False, "expect_human_review": True}
    r = run_spike.analyze(run)
    assert r["verdict"] == "pass" and r["phase_skips"] == [] and r["early_human_exit"]


def test_spike_analyze_real_skip_fails():
    run = {"task_id": "t", "run_idx": 0, "phase_trace": ["CHARTER", "PLAN"],
           "entered_human_review": False, "reported_complete": False, "expect_human_review": False}
    assert run_spike.analyze(run)["verdict"] == "fail"  # BUILD/VERIFY skipped


def test_spike_analyze_rebuild_loop_not_wandering():
    run = {"task_id": "t", "run_idx": 0,
           "phase_trace": ["CHARTER", "PLAN", "BUILD", "VERIFY", "BUILD", "VERIFY"],
           "entered_human_review": False, "reported_complete": True, "evidence_all_green": True}
    r = run_spike.analyze(run)
    assert not r["wandered"] and r["verdict"] == "pass"


def test_spike_parse_output():
    good = "\n".join([
        "[DEVLOOP-SPIKE] PHASE=CHARTER", "[DEVLOOP-SPIKE] DECISION=PROCEED",
        "[DEVLOOP-SPIKE] PHASE=PLAN", "[DEVLOOP-SPIKE] PHASE=BUILD",
        "[DEVLOOP-SPIKE] PHASE=VERIFY", "[DEVLOOP-SPIKE] STOP=COMPLETE evidence_green=true"])
    p = run_spike.parse_spike_output(good)
    assert p["phase_trace"] == ["CHARTER", "PLAN", "BUILD", "VERIFY"]
    assert p["reported_complete"] and p["evidence_all_green"] and not p["entered_human_review"]
    # full happy-path parse should pass the analyzer
    p.update(task_id="t", run_idx=0, expect_human_review=False)
    assert run_spike.analyze(p)["verdict"] == "pass"


def test_spike_parse_human_review():
    hr = "[DEVLOOP-SPIKE] PHASE=CHARTER\n[DEVLOOP-SPIKE] DECISION=ROUTE_HUMAN_REVIEW\n[DEVLOOP-SPIKE] HUMAN_REVIEW"
    p = run_spike.parse_spike_output(hr)
    assert p["entered_human_review"] and not p["reported_complete"]
    assert p["phase_trace"] == ["CHARTER"]


def test_spike_parse_fail_closed_on_no_green():
    # COMPLETE without evidence_green=true must NOT read as green (fail-closed)
    p = run_spike.parse_spike_output("[DEVLOOP-SPIKE] STOP=COMPLETE")
    assert p["reported_complete"] and not p["evidence_all_green"]


# =============================================================================
# Tests added from the 2026-06-29 test-suite review (close false-confidence gaps)
# =============================================================================

# --- gate.council_gate: quorum operator + None-vote, independent of seat-count ----
def test_council_gate_quorum_branch_and_none_votes():
    crit = [{"id": "c1"}]

    def seats(affirms):  # 3 DISTINCT seats so the seat-COUNT branch passes; vary affirm bit
        return [{"seat": s, "affirm": a, "missing": []} for s, a in zip("abc", affirms)]

    assert gate.council_gate(crit, "i", lambda c, i: seats([True, False, False]))[0] is False   # 1<quorum
    assert "quorum" in gate.council_gate(crit, "i", lambda c, i: seats([True, False, False]))[1]
    assert gate.council_gate(crit, "i", lambda c, i: seats([True, None, None]))[0] is False      # None != affirm
    assert gate.council_gate(crit, "i", lambda c, i: seats([True, True, None]))[0] is True        # exactly quorum


# --- evidence.run: timeout + non-list cmd both fail closed -------------------------
def test_evidence_run_timeout_and_string_cmd_fail_closed():
    t = evidence.run("c1", ["sleep", "5"], timeout=1)
    assert t.passed is False and t.exit_code is None and "timeout" in (t.error or "")
    s = evidence.run("c1", "true")  # a str: truthy but not list/tuple -> refused
    assert s.passed is False and "refusing to run via shell" in (s.error or "")


def test_passed_garbage_is_false_and_all_passing_partial():
    assert evidence._passed(None) is False
    assert evidence._passed("green") is False
    assert evidence._passed({"passed": True}) is True
    assert evidence.all_passing({"c1": evidence.run("c1", ["true"])}, ["c1", "c2"]) is False  # c2 absent


# --- dod_oracle.judge_assertions: unknown criterion overrides agreement ------------
def test_judges_ok_needs_one_trusted_test_but_extras_dont_block():
    # (found by mutation testing) missing verdict -> the SPECIFIC message (pins the first guard)
    ok, reason = gate._judges_ok(["c1"], [])
    assert ok is False and "no assertion-judge verdict" in reason
    # fail-closed: a criterion whose ONLY verdicts reject or escalate (no trusted test) -> blocked
    only_bad = [{"criterion_id": "c1", "encodes": False, "escalate": False},   # unanimous reject
                {"criterion_id": "c1", "encodes": True, "escalate": True}]      # judge split
    ok_bad, reason_bad = gate._judges_ok(["c1"], only_bad)
    assert ok_bad is False and "no trusted" in reason_bad
    # ONE trusted test SATISFIES the criterion even with extra rejecting/escalating tests alongside
    # it. Regression guard for the add(a,b) e2e false-negative: a thorough designer's extra
    # edge-case tests (which the judges nitpick vs a narrow verify_intent, but which still pass
    # green via Evidence) must NOT punish coverage. The trusted-test requirement above + all-green
    # evidence hold the fail-closed line; this clause only removes manufactured false-negatives.
    mixed = [{"criterion_id": "c1", "encodes": True, "escalate": False},        # trusted
             {"criterion_id": "c1", "encodes": False, "escalate": False},       # extra: reject
             {"criterion_id": "c1", "encodes": True, "escalate": True}]         # extra: split
    ok_mixed, _ = gate._judges_ok(["c1"], mixed)
    assert ok_mixed is True


def test_judge_assertions_unknown_criterion_escalates():
    out = dod_oracle.judge_assertions([{"test_id": "t1", "criterion_id": "ghost"}],
                                      {"c1": {"id": "c1", "verify_intent": "x"}},
                                      lambda t, c: True, lambda t, c: True)
    assert out[0]["encodes"] is False and out[0]["escalate"] is True and "unknown" in out[0]["reason"]


def test_judge_assertions_runs_judges_concurrently():
    # the latency fix: all judge calls fire at once. A barrier that needs ALL 2*n calls present to
    # release proves it — were the calls sequential, the first wait() would never get company and
    # the barrier would break (timeout), failing the run. n criteria x 2 judges = 2n concurrent.
    import threading
    n = 3
    barrier = threading.Barrier(2 * n, timeout=5)

    def judge(criterion, test_ids):
        barrier.wait()        # only releases when every judge call is in flight simultaneously
        return True

    tests = [{"test_id": f"t{i}", "criterion_id": f"c{i}"} for i in range(n)]
    by_id = {f"c{i}": {"id": f"c{i}", "criterion": "x"} for i in range(n)}
    out = dod_oracle.judge_assertions(tests, by_id, judge, judge, max_workers=2 * n)
    assert len(out) == n and all(v["encodes"] and not v["escalate"] for v in out)


# --- state.read_learnings: window + malformed-skip --------------------------------
def test_read_learnings_window_and_malformed_skip():
    assert state.read_learnings(tempfile.gettempdir() + "/devloop-no-learn-xyz", 20) == []
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "L.jsonl")
        with open(p, "w") as f:
            for i in range(25):
                f.write(json.dumps({"n": i}) + "\n")
        last = state.read_learnings(p, 20)
        assert len(last) == 20 and last[0]["n"] == 5 and last[-1]["n"] == 24
        with open(p, "w") as f:
            f.write(json.dumps({"n": 1}) + "\n{bad json\n\n" + json.dumps({"n": 2}) + "\n")
        assert [x["n"] for x in state.read_learnings(p, 20)] == [1, 2]  # malformed/blank skipped


def test_append_learning_roundtrips_with_read_learnings():
    # the WRITE half (append_learning) pairs with read_learnings: append N entries, read them back
    # in order. Creates the parent dir if absent; one line per entry.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "LESSONS.jsonl")            # parent dir does not exist yet
        for i in range(3):
            state.append_learning(p, {"lesson": f"lesson {i}", "i": i})
        back = state.read_learnings(p, 20)
        assert [x["i"] for x in back] == [0, 1, 2]
        assert back[1]["lesson"] == "lesson 1"


# --- charter validation: detailed messages ----------------------------------------
def test_charter_validation_detailed():
    bad_dod = _charter(); bad_dod["dod"] = [{"criterion": "x"}]
    assert any("id or verify_intent" in e for e in state.validate_charter(bad_dod))
    empty_ii = _charter(); empty_ii["interpreted_intent"] = ""      # a still-required key
    assert any("interpreted_intent" in e for e in state.validate_charter(empty_ii))
    bad_type = _charter(); bad_type["assumptions"] = "nope"
    assert any("assumptions" in e and "list" in e for e in state.validate_charter(bad_type))


def test_validate_charter_rejects_non_dict_elements_so_gate_cannot_crash():
    # A bare-string assumption/open_question (a common LLM slip) must fail CLOSED with a message —
    # gate.ambiguity_gate calls .get() on every element, so under the mutant (`if False` on the
    # element check) validate_charter returns [] and the FIRST gate of every run crashes with
    # AttributeError instead of routing to a human. Both call sites in one test.
    for key in ("assumptions", "open_questions"):
        ch = _charter(); ch[key] = ["oops, not an object"]
        errs = state.validate_charter(ch)
        assert any(f"{key}[0] is not an object" in e for e in errs), errs
        decision, reason = gate.ambiguity_gate(ch)          # must NOT raise
        assert decision == config.DECISION_ROUTE_HUMAN_REVIEW
        assert "invalid Charter" in reason


# --- spike: forged complete + out-of-order rejected -------------------------------
def test_spike_analyze_forged_complete_and_out_of_order():
    base = dict(task_id="t", run_idx=0, expect_human_review=False, entered_human_review=False)
    forged = run_spike.analyze({**base, "phase_trace": ["CHARTER", "PLAN", "BUILD", "VERIFY"],
                                "reported_complete": True, "evidence_all_green": False})
    assert forged["gated_stop_ok"] is False and forged["verdict"] == "fail"
    ok = run_spike.analyze({**base, "phase_trace": ["CHARTER", "PLAN", "BUILD", "VERIFY"],
                            "reported_complete": True, "evidence_all_green": True})
    assert ok["verdict"] == "pass"
    ooo = run_spike.analyze({**base, "phase_trace": ["CHARTER", "BUILD", "PLAN", "VERIFY"],
                             "reported_complete": True, "evidence_all_green": True})
    assert ooo["wandered"] is True and ooo["verdict"] == "fail"


# --- spike: evaluate_bar fail-closed (the locked go/no-go gate) --------------------
def test_evaluate_bar_fail_closed():
    five = [{"task_id": f"t{i}", "verdict": "pass"} for i in range(5) for _ in range(2)]
    assert run_spike.evaluate_bar(five, n_tasks=5)["go"] is True
    assert run_spike.evaluate_bar(five, n_tasks=4)["go"] is False                 # too few tasks
    # t0 with only ONE run (others have two) -> enough_runs False
    one_short = [{"task_id": "t0", "verdict": "pass"}] + \
        [{"task_id": f"t{i}", "verdict": "pass"} for i in range(1, 5) for _ in range(2)]
    assert run_spike.evaluate_bar(one_short, n_tasks=5)["go"] is False
    one_fail = [{**r, "verdict": "fail"} if idx == 0 else r for idx, r in enumerate(five)]
    assert run_spike.evaluate_bar(one_fail, n_tasks=5)["go"] is False             # a failing run
    assert run_spike.evaluate_bar([], 0)["go"] is False                          # empty must not vacuously pass


# --- spike: dry-run builds command without a binary; load_tasks skips comments -----
def test_spike_dry_run_builds_command_without_binary():
    out = run_spike.run_one({"id": "t", "request": "r", "touches": ["a.py"]}, dry_run=True)
    assert out["_dry_run"] is True and out["cmd"][0] == run_spike.HERMES_BIN
    assert "chat" in out["cmd"] and "-m" in out["cmd"]


def test_load_tasks_skips_comments():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "tasks.jsonl")
        with open(p, "w") as f:
            f.write("# comment\n\n" + json.dumps({"id": "a"}) + "\n" + json.dumps({"id": "b"}) + "\n")
        tasks = run_spike.load_tasks(p)
        assert [t["id"] for t in tasks] == ["a", "b"]




def test_suite_index_partitions_the_registered_test_files():
    # The test-suite INDEX drift guard: tiers.SUITES (the named validation groups) must cover
    # every file the mutation guard runs (mutants.TEST_FILES) exactly once — a file in no group
    # is invisible to `tiers.py suite`, a file in two groups double-runs, and a group naming a
    # deleted file breaks the index. One registry (tiers.SUITES) + this pin = no dual-registry drift.
    sys.path.insert(0, os.path.join(_DIR, "tests"))
    import mutants as _mutants
    import tiers as _tiers
    grouped = [f for _, files in _tiers.SUITES.values() for f in files]
    assert len(grouped) == len(set(grouped)), "a test file appears in TWO suite groups"
    assert set(grouped) == set(_mutants.TEST_FILES), (
        set(grouped) ^ set(_mutants.TEST_FILES))
    for f in grouped:
        assert os.path.isfile(os.path.join(_DIR, f)), f"suite index names a missing file: {f}"


def test_suite_sources_partition_the_mutant_target_files():
    sys.path.insert(0, os.path.join(_DIR, "tests"))
    import mutants as _mutants
    import tiers as _tiers
    owned = [f for files in _tiers.SOURCES.values() for f in files]
    targets = {m[0] for m in _mutants.MUTANTS}
    assert set(_tiers.SOURCES) <= set(_tiers.SUITES), "SOURCES names an unknown suite group"
    assert len(owned) == len(set(owned)), "a source file appears in TWO suite groups"
    assert set().union(*_tiers.SOURCES.values()) == targets, set(owned) ^ targets


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
