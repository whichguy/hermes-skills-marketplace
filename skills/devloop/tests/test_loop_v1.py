"""Deterministic tests of the v1 loop (loop.run_v1) — the DoD oracle, NO LLM.

Fakes write REAL files; evidence runs REAL subprocesses; the oracle (coverage + 2-model
assertion judge) gates the stop via gate.stop_condition. Proves the central v1 guarantee at
the LOOP level: a forged-green test (real passing subprocess that the judge rejects) NEVER
completes; an uncovered DoD criterion routes to HUMAN_REVIEW before any code is trusted.
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config  # noqa: E402
import loop    # noqa: E402
import state   # noqa: E402

YES = lambda t, c: True   # noqa: E731
NO = lambda t, c: False   # noqa: E731


def _charter(n=1, blocking=False):
    dod = [{"id": f"c{i}", "criterion": f"crit {i}", "verify_intent": f"v{i}", "kind": "shown"}
           for i in range(1, n + 1)]
    return {
        "interpreted_intent": "demo", "purpose": "demo", "dod": dod,
        "assumptions": [{"text": "a", "confidence": 0.9}],
        "open_questions": [{"text": "q", "blocking": blocking}] if blocking else [],
        "happy_path": "design, implement, verify", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _events(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def test_v1_happy_path_with_oracle():
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")
        sentinel = os.path.join(d, "impl_ok.txt")

        def design(charter):  # the test (checks the sentinel; no import -> no stale-pyc flakiness)
            open(check, "w").write(f"import os, sys\nsys.exit(0 if os.path.exists({sentinel!r}) else 1)\n")
            return {"t_c1": "c1"}

        def implement(charter, attempt, last_failure):  # "fixes" it on the 2nd attempt
            if attempt >= 1:
                open(sentinel, "w").write("ok")

        res = loop.run_v1(_charter(1), design=design, implement=implement, judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        assert res.get("reason")                                    # COMPLETE carries the stop reason
        assert res["state"]["rebuild_count"] == 1
        steps = [e["step"] for e in _events(res["trace_path"])]
        assert "coverage" in steps and "judge" in steps and "stop_check" in steps


def test_v1_uncovered_criterion_routes_human_before_building():
    with tempfile.TemporaryDirectory() as d:
        calls = []
        res = loop.run_v1(_charter(2),
                          design=lambda charter: {"t_c1": "c1"},   # c2 has NO test -> coverage fails
                          implement=lambda *a: calls.append(1),
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert "no covering test" in res.get("reason", "") and "c2" in res["reason"]   # the WHY reaches the lesson
        assert calls == []                                          # never implemented
        assert any(e["step"] == "coverage" and not e["ok"] for e in _events(res["trace_path"]))


def test_v1_forged_green_blocked_by_judge():
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")    # ALWAYS green (forged/vacuous)
            return {"t_c1": "c1"}

        res = loop.run_v1(_charter(1), design=design,
                          implement=lambda *a: open(os.path.join(d, "m.py"), "w").write("ok=True\n"),
                          judge_a=YES, judge_b=NO,                  # judges DISAGREE -> escalate -> not trusted
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d, max_passes=64)
        assert res["terminal"] == "HUMAN_REVIEW"                    # green evidence, but the oracle blocks
        assert res["terminal"] != "COMPLETE"
        # #18 ATTRIBUTION + JUDGE-ONCE: the tests are judged ONCE up-front, so an untrusted test
        # (judges disagree -> escalate) is caught a TEST fault BEFORE any code is built or evidence is
        # run — re-IMPLEMENT can't fix a test the judges distrust, and a forged-green check can't sneak
        # past because the gate never even reaches (forge-able) evidence.
        assert res["state"]["rebuild_count"] == 0                          # routed before any rebuild
        assert "test fault" in res.get("reason", "")
        ev = _events(res["trace_path"])
        assert not os.path.exists(os.path.join(d, "m.py"))                 # implement never ran
        assert not any(e["step"] == "evidence" for e in ev)               # blocked BEFORE (forge-able) evidence
        assert any(e["step"] == "attribution" and e.get("fault") == "test" for e in ev)


def test_v1_ignores_planted_checkpoint_fresh_budget():
    # Loop-level resume was DELETED (2026-07-01 deep review): it was production-dead (both real
    # entrypoints mint a unique run_dir per call, so load_checkpoint never fired) and incoherent
    # if it ever had (runner re-drafts the charter each call -> resumed counters would bind to a
    # DIFFERENT DoD's criterion ids). Contract now: a pre-existing checkpoint with an EXHAUSTED
    # budget is IGNORED — the run starts fresh and COMPLETEs on green. Mutant re-adding
    # `state.load_checkpoint(run_dir) or` makes the planted budget force HUMAN_REVIEW -> FAIL.
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        ch = _charter(1)
        seed = state.new_run_state(ch)
        seed["replan_count"] = config.MAX_REPLANS                   # poisoned checkpoint on disk
        state.save_checkpoint(run_dir, seed)
        res = loop.run_v1(ch, design=lambda c: {"t_c1": "c1"},
                          implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=run_dir, cwd=d)
        assert res["terminal"] == "COMPLETE"                        # checkpoint IGNORED -> fresh run on green
        assert res["state"]["replan_count"] == 0                    # fresh counters, not the planted ones


def test_v1_regression_gate_blocks_complete_when_existing_suite_red():
    # NEW (2026-07-01): a would-be-COMPLETE must ALSO leave the repo's whole suite green — the
    # per-criterion commands run only the DoD's own nodes, so without this gate a modify task
    # could break PRE-EXISTING tests and still COMPLETE (regression-blind). Seed cwd with a
    # failing pre-existing test: per-criterion evidence is green and stop_condition says
    # complete, but the regression gate turns every pass red -> back-off -> HUMAN_REVIEW.
    # Mutant killed: loop.py `if not reg_ok:` -> `if False:` (regression-blind COMPLETE).
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_existing.py"), "w").write(
            "def test_pre_existing_contract():\n    assert False, 'regression'\n")
        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"},
                          implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"                    # never COMPLETE on a red suite
        ev = _events(res["trace_path"])
        regs = [e for e in ev if e["step"] == "regression"]
        assert regs and all(e["passed"] is False for e in regs)     # gate evaluated, and red
        assert any(e.get("cause") == "regression" for e in ev if e["step"] == "rebuild_fail")
        assert not any(e.get("terminal") == "COMPLETE" for e in ev)


def test_v1_regression_gate_green_suite_still_completes():
    # Green control: a PASSING pre-existing suite must not block COMPLETE. (The vacuous exit-5
    # path — empty cwd, no tests collected — is what every other COMPLETE test in this file
    # already exercises.) Kills exit-set widening in the paired gate unit test's direction.
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_existing.py"), "w").write(
            "def test_pre_existing_contract():\n    assert True\n")
        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"},
                          implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        ev = _events(res["trace_path"])
        assert any(e["step"] == "regression" and e["passed"] for e in ev)


def test_v1_trace_carries_dod_judge_votes_and_ts():
    # The trace must be sufficient to diagnose a false-complete post-hoc: full DoD text +
    # assumptions/open_questions on the charter event, per-judge votes on the judge event,
    # a ts on every event. Mutant killed: _charter_event dod -> [] (the DoD text vanishes).
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"}, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        ev = _events(res["trace_path"])
        ch = next(e for e in ev if e["step"] == "charter")
        assert ch["dod"] and ch["dod"][0]["id"] == "c1" and ch["dod"][0]["criterion"]
        assert "assumptions" in ch and "open_questions" in ch
        jd = next(e for e in ev if e["step"] == "judge")
        assert jd["verdicts"][0]["judge_a"] is True and jd["verdicts"][0]["judge_b"] is True
        assert all("ts" in e for e in ev)                              # every event timestamped


def test_v1_frozen_tests_gate_blocks_complete_when_test_file_deleted():
    # FROZEN-TESTS invariant (caught LIVE by the extended spike, t3-validate-r0): deleting a
    # pre-existing test would turn the whole-suite regression gate green — so a missing frozen
    # test file must block COMPLETE outright. Mutants killed: `if viol:` -> `if False:` and
    # `missing = [...]` -> `missing = []`.
    with tempfile.TemporaryDirectory() as d:
        tf = os.path.join(d, "test_existing.py")
        open(tf, "w").write("def test_pre():\n    assert True\n")

        def implement(c, a, lf):
            if os.path.exists(tf):
                os.unlink(tf)                                   # the coder "helpfully" removes it

        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"}, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"                # never COMPLETE on a violated freeze
        assert "frozen test files violated" in res.get("reason", "")
        ev = _events(res["trace_path"])
        assert any(e["step"] == "frozen_tests" and e.get("ok") is False for e in ev)
        assert any(e.get("cause") == "frozen_tests" for e in ev if e["step"] == "rebuild_fail")
        assert not any(e.get("terminal") == "COMPLETE" for e in ev)


def test_v1_frozen_tests_gate_blocks_complete_when_test_file_rewritten():
    # The forged-green shape judge-once opened: rewrite the (already-judged) test file to a
    # vacuous assert and pass evidence against it. A content change to a frozen test must block.
    # Mutant killed: `changed = [...]` -> `changed = []`.
    with tempfile.TemporaryDirectory() as d:
        tf = os.path.join(d, "test_existing.py")
        open(tf, "w").write("def test_pre():\n    assert 1 + 1 == 2\n")

        def implement(c, a, lf):
            open(tf, "w").write("def test_pre():\n    assert True  # gutted\n")

        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"}, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert "changed=" in res.get("reason", "") and "test_existing.py" in res.get("reason", "")


def test_v1_frozen_tests_self_heal_recovers_to_complete():
    # SELF-HEAL (q1 spike finding): the coder deleted the DoD test file and could never restore
    # it (it never saw the content) -> the run ground exit-4 evidence to a wasted HUMAN_REVIEW.
    # Now the LOOP restores the originals; a transient violation costs one rebuild, not the run.
    # Mutant killed: `restored = _frozen_restore(...)` -> `restored = []` (no heal -> the deleted
    # file stays gone -> generic red grind -> HUMAN_REVIEW instead of COMPLETE).
    with tempfile.TemporaryDirectory() as d:
        tf = os.path.join(d, "test_existing.py")
        original = "def test_pre():\n    assert 1 + 1 == 2\n"
        open(tf, "w").write(original)
        calls = []

        def implement(c, a, lf):
            calls.append(1)
            if len(calls) == 1 and os.path.exists(tf):
                os.unlink(tf)                                   # misbehaves ONCE, then behaves

        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"}, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"                    # healed -> recovered, not wasted
        assert open(tf).read() == original                      # the oracle is byte-identical
        ev = _events(res["trace_path"])
        heal = next(e for e in ev if e["step"] == "frozen_tests" and e.get("ok") is False)
        assert heal["restored"] == ["test_existing.py"]         # the loop did the restoring
        assert any(e.get("cause") == "frozen_tests" for e in ev if e["step"] == "rebuild_fail")


def test_frozen_snapshot_and_violation_helpers():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_a.py"), "w").write("def test_a():\n    assert True\n")
        open(os.path.join(d, "b_test.py"), "w").write("def test_b():\n    assert True\n")
        open(os.path.join(d, "code.py"), "w").write("x = 1\n")             # not a test -> not pinned
        os.makedirs(os.path.join(d, "__pycache__"))
        open(os.path.join(d, "__pycache__", "test_junk.py"), "w").write("j")  # junk dir skipped
        snap = loop._test_snapshot(d)
        assert set(snap) == {"test_a.py", "b_test.py"}
        assert loop._frozen_violation(d, snap) is None                     # intact -> no violation
        open(os.path.join(d, "test_new.py"), "w").write("def test_n():\n    assert True\n")
        assert loop._frozen_violation(d, snap) is None                     # NEW files are fine
        open(os.path.join(d, "code.py"), "w").write("x = 2\n")
        assert loop._frozen_violation(d, snap) is None                     # non-test edits are fine


# --- judged mid-run TEST REPAIR (user decision 2026-07-02) --------------------------------------
import gate    # noqa: E402

WRONG = lambda c, tids, tail: True    # noqa: E731  auditor: the test IS wrong
RIGHT = lambda c, tids, tail: False   # noqa: E731  auditor: the test is fine


def _red_oracle(d):
    """A DESIGN whose check NEVER passes (the 'wrong expected output' shape) + an implement
    that writes correct-looking code every pass. Returns (design, implement, verify, sentinel)."""
    check = os.path.join(d, "check.py")
    sentinel = os.path.join(d, "impl_ok.txt")

    def design(charter):
        open(check, "w").write("import sys\nsys.exit(1)\n")     # asserts an impossible output
        return {"t_c1": "c1"}

    def implement(charter, attempt, last_failure):
        open(sentinel, "w").write("ok")                          # the code was 'right' all along

    return design, implement, (lambda cid: [sys.executable, check]), sentinel


def test_v1_test_repair_replaces_wrong_oracle_and_completes():
    # THE repair contract: exhaustion + unanimous audit -> the designer (never the coder)
    # regenerates the oracle, coverage+judges re-gate it, the loop continues and COMPLETEs.
    # Mutants killed: repair trigger dropped; on_repair budget reset dropped.
    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, sentinel = _red_oracle(d)
        check2 = os.path.join(d, "check2.py")
        failures = []

        def implement2(charter, attempt, last_failure):
            failures.append(last_failure)
            implement(charter, attempt, last_failure)

        def redesign(charter, wrong, details):
            assert wrong == ["c1"] and details[0]["wrong"] is True
            open(check2, "w").write(
                f"import os, sys\nsys.exit(0 if os.path.exists({sentinel!r}) else 1)\n")
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check2])

        res = loop.run_v1(_charter(1), design=design, implement=implement2,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "COMPLETE"
        assert res["state"]["repair_used"] is True
        ev = _events(res["trace_path"])
        assert any(e["step"] == "test_audit" and e["wrong"] == ["c1"] for e in ev)
        assert any(e["step"] == "test_repair" and e.get("ok") is True for e in ev)
        assert any(e["step"] == "coverage" and e.get("repair") for e in ev)   # re-gated
        assert any(e["step"] == "judge" and e.get("repair") for e in ev)      # re-judged
        # the post-repair coder was TOLD the oracle changed
        assert any(lf and "test_repair" in lf for lf in failures)


def test_v1_audit_dissent_keeps_the_oracle_and_routes_human():
    # ONE auditor saying 'test wrong' is not enough — the oracle keeps the benefit of the doubt,
    # the run exits to a human, and the audit verdict reaches the terminal reason.
    # Mutant killed: unanimity weakened to any-vote.
    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, _ = _red_oracle(d)
        called = []
        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=lambda *a: called.append(1) or ({}, None),
                          audit_a=WRONG, audit_b=RIGHT)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert called == []                                     # dissent -> redesign NEVER runs
        assert "test audit: 0/1 red criteria judged test-wrong" in res.get("reason", "")


def test_v1_repair_runs_at_most_once():
    # A repaired oracle that is STILL wrong must not repair again: the second exhaustion goes to
    # a human. Mutant killed: repair_used guard dropped (endless repair loop).
    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, _ = _red_oracle(d)
        redesigns = []

        def redesign(charter, wrong, details):
            redesigns.append(1)
            check2 = os.path.join(d, f"check2_{len(redesigns)}.py")
            open(check2, "w").write("import sys\nsys.exit(1)\n")   # STILL wrong
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check2])

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert redesigns == [1]                                 # exactly ONE repair, ever
        ev = _events(res["trace_path"])
        assert sum(1 for e in ev if e["step"] == "test_repair" and e.get("ok")) == 1


def test_v1_repair_regate_failures_fall_back_to_human():
    # The repaired tests go through the SAME trust machinery: broken coverage or judge-rejected
    # repairs never continue the loop. Mutant killed: repair coverage/judge re-gate skipped.
    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, _ = _red_oracle(d)
        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=lambda c, w, dt: ({}, None),   # repaired map covers NOTHING
                          audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "HUMAN_REVIEW"
        ev = _events(res["trace_path"])
        assert any(e["step"] == "test_repair" and e.get("ok") is False
                   and "uncovered" in e.get("reason", "") for e in ev)

    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, _ = _red_oracle(d)
        b_calls = []

        def judge_b(criterion, test_ids):                        # trusts the ORIGINAL design only
            b_calls.append(1)
            return len(b_calls) <= 1

        def redesign(charter, wrong, details):
            check2 = os.path.join(d, "check2.py")
            open(check2, "w").write("import sys\nsys.exit(0)\n")
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check2])

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=judge_b, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "HUMAN_REVIEW"
        ev = _events(res["trace_path"])
        assert any(e["step"] == "test_repair" and e.get("ok") is False
                   and "not judge-trusted" in e.get("reason", "") for e in ev)


def test_v1_repair_repins_the_frozen_snapshot():
    # The repaired oracle must be RE-FROZEN: without the re-pin, the loop's own self-heal would
    # 'restore' the OLD wrong test over the repaired one and grind to HUMAN_REVIEW.
    # Mutant killed: `frozen_tests = rep["frozen"]` dropped.
    with tempfile.TemporaryDirectory() as d:
        tf = os.path.join(d, "test_oracle.py")

        def design(charter):
            open(tf, "w").write("def test_o():\n    assert 1 == 2  # wrong expected output\n")
            return {"t_c1": "c1"}

        check = os.path.join(d, "check.py")
        open(check, "w").write("import sys\nsys.exit(1)\n")      # red evidence -> exhaustion

        def redesign(charter, wrong, details):
            open(tf, "w").write("def test_o():\n    assert 1 == 1\n")   # the REPAIRED oracle
            return {"t2_c1": "c1"}, (lambda cid: ["true"])

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "COMPLETE"
        assert "assert 1 == 1" in open(tf).read()                # repaired oracle survived


def test_v1_upfront_judge_distrust_spends_the_one_redesign_then_completes():
    # UP-FRONT ORACLE RETRY (live quick-spike catch 2026-07-02): one flaky judge dissent used to
    # waste the whole run as a test fault. With a redesign seam available, the run spends its ONE
    # oracle regeneration, re-gates, and proceeds. Mutant killed: up-front retry dropped.
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        b_calls = []

        def judge_b(criterion, test_ids):                 # dissents ONCE (the flaky round)
            b_calls.append(1)
            return len(b_calls) > 1

        redesigns = []

        def redesign(charter, wrong, details):
            redesigns.append(wrong)
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check])

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=judge_b,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "COMPLETE"
        assert redesigns == [["c1"]]                      # the one regeneration, spent up-front
        assert res["state"]["repair_used"] is True
        ev = _events(res["trace_path"])
        assert any(e["step"] == "test_redesign" and e["cause"] == "judge_distrust" for e in ev)


def test_v1_upfront_distrust_still_untrusted_routes_human_once():
    # A regeneration that the judges STILL distrust goes to a human — and only one regeneration
    # ever happens (the bound is shared with the mid-run repair).
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        redesigns = []

        def redesign(charter, wrong, details):
            redesigns.append(1)
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check])

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=NO,                    # distrust is persistent
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert "test fault" in res.get("reason", "")
        assert redesigns == [1]                           # bounded: exactly one attempt


def test_v1_complete_ships_grounding_proof_chain():
    # END-OF-RUN GROUNDING (user ask 2026-07-02): a COMPLETE returns the promise->proof chain —
    # every criterion with the tests that encode it, both judge votes, and passing evidence —
    # in the result AND the trace. Mutant killed: grounding report dropped from the COMPLETE.
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(2), design=lambda c: {"t_c1": "c1", "t_c2": "c2"},
                          implement=lambda *a: None,
                          judge_a=YES, judge_b=YES, verify_cmd_for=lambda cid: ["true"],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        g = res["grounding"]
        assert g["grounded"] is True and g["intent"] == "demo"
        assert [i["criterion_id"] for i in g["criteria"]] == ["c1", "c2"]
        assert g["criteria"][0]["tests"] == ["t_c1"]                 # promise -> its proving tests
        assert g["criteria"][0]["judges"] == {"a": True, "b": True}  # -> judge votes
        assert all(i["evidence_passed"] for i in g["criteria"])      # -> green evidence
        ev = _events(res["trace_path"])
        gev = next(e for e in ev if e["step"] == "grounding")
        assert gev["grounded"] is True and len(gev["criteria"]) == 2


def test_audit_tests_green_or_missing_evidence_never_audited():
    # gate.audit_tests unit contract: green tests are working oracles — only RED criteria are
    # auditable; a crashed auditor never indicts. Mutants killed: green-skip dropped;
    # crash-counts-as-wrong.
    ch = _charter(2)
    # dict-shaped records (the checkpoint-rehydrated form evidence._passed supports; an unknown
    # shape fail-closes to not-passed, which is the AUDITABLE direction)
    green = {"passed": True, "stderr_tail": ""}
    red = {"passed": False, "stderr_tail": "AssertionError: boom"}
    tmap = {"c1": ["t_c1"], "c2": ["t_c2"]}
    wrong, details = gate.audit_tests(ch, {"c1": green, "c2": red}, tmap, WRONG, WRONG)
    assert wrong == ["c2"]                                       # green c1 never audited
    assert [x["criterion_id"] for x in details] == ["c2"]

    def crash(c, tids, tail):
        raise RuntimeError("auditor died")

    wrong, details = gate.audit_tests(ch, {"c2": red}, tmap, crash, WRONG)
    assert wrong == [] and details[0]["wrong"] is False          # crash never indicts the oracle


# --- GREEN-side overfit audit (user decision 2026-07-03, run-3 live specimen) -------------------
def test_v1_green_overfit_unanimous_regenerates_then_completes():
    """A WRONG oracle the coder overfit stays GREEN — the red-side repair can't reach it. At the
    first would-be-COMPLETE, UNANIMOUS overfit indictment spends the one regeneration budget,
    the loop re-implements against the honest oracle, and COMPLETEs honestly.
    Mutants killed: green-audit trigger dropped; budget not spent on indictment."""
    with tempfile.TemporaryDirectory() as d:
        wrong = os.path.join(d, "wrong_check.py")     # the overfit-green oracle
        honest = os.path.join(d, "honest_check.py")   # the regenerated oracle
        fixed = os.path.join(d, "fixed.txt")

        def design(charter):
            open(wrong, "w").write("import sys\nsys.exit(0)\n")            # green, but wrong
            return {"t_c1": "c1"}

        def implement(charter, attempt, last_failure):
            if last_failure and "test_repair" in last_failure:
                open(fixed, "w").write("ok")                               # the HONEST fix

        def redesign(charter, suspects, details):
            assert suspects == ["c1"] and details[0]["overfit"] is True
            open(honest, "w").write(
                f"import os, sys\nsys.exit(0 if os.path.exists({fixed!r}) else 1)\n")
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, honest])

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, wrong],
                          run_dir=os.path.join(d, "run"), cwd=d, redesign=redesign,
                          overfit_a=lambda c, tids: True, overfit_b=lambda c, tids: True)
        assert res["terminal"] == "COMPLETE"
        assert res["state"]["repair_used"] is True                # the shared budget was spent
        assert os.path.exists(fixed)                              # the honest fix actually happened
        ev = _events(res["trace_path"])
        assert any(e["step"] == "overfit_audit" and e.get("suspect") == ["c1"] for e in ev)
        assert any(e["step"] == "test_repair" and e.get("ok") is True for e in ev)
        assert os.path.isfile(os.path.join(d, "run", "overfit_audit.json"))


def test_v1_green_overfit_split_vote_is_advisory_never_blocks():
    """One flaky auditor YES must not block or spend the budget — it becomes a visible
    grounding advisory. Mutants killed: unanimity weakened to any-vote; advisory dropped."""
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=lambda *a: ({}, None),      # would fail re-gate if it ever ran
                          overfit_a=lambda c, tids: True, overfit_b=lambda c, tids: False)
        assert res["terminal"] == "COMPLETE"
        assert res["state"].get("repair_used") is not True        # budget NOT spent on a split vote
        assert res["grounding"]["overfit_advisory"] == ["c1"]     # ...but the flag is visible
        ev = _events(res["trace_path"])
        assert any(e["step"] == "overfit_audit" and e.get("suspect") == [] for e in ev)


def test_v1_green_overfit_indicted_regate_failure_routes_human():
    """A UNANIMOUSLY indicted oracle that cannot be regenerated through the trusted path must
    never COMPLETE (that would be a false-complete on a corrupt proof). Mutant killed:
    HUMAN_REVIEW-on-failed-regate dropped."""
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=lambda *a: ({}, None),      # regeneration fails coverage
                          overfit_a=lambda c, tids: True, overfit_b=lambda c, tids: True)
        assert res["terminal"] == "HUMAN_REVIEW"
        assert "overfit audit indicted" in res["reason"]
        assert res["grounding"]["grounded"] is False              # partial chain ships


def test_v1_overfit_audit_shares_the_one_repair_budget():
    """After a mid-run (red-side) repair spent the budget, the green-side audit must NOT fire —
    ONE regeneration per run, first spender wins (termination unchanged).
    Mutant killed: repair_used guard dropped from the green-audit gate."""
    with tempfile.TemporaryDirectory() as d:
        design, implement, verify, sentinel = _red_oracle(d)
        check2 = os.path.join(d, "check2.py")
        redesigns = []

        def redesign(charter, wrong, details):
            redesigns.append(1)
            open(check2, "w").write(
                f"import os, sys\nsys.exit(0 if os.path.exists({sentinel!r}) else 1)\n")
            return {"t2_c1": "c1"}, (lambda cid: [sys.executable, check2])

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d,
                          redesign=redesign, audit_a=WRONG, audit_b=WRONG,
                          overfit_a=lambda c, tids: True, overfit_b=lambda c, tids: True)
        assert res["terminal"] == "COMPLETE"
        assert redesigns == [1]                                   # exactly ONE regeneration, ever


# --- COMMIT-SCOPE gate (user ask 2026-07-03: only intended items reach the commit) --------------
def _git_cwd(d):
    """A git repo cwd (the scope gate reads worktree.changed_files, which needs git)."""
    import subprocess as sp
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        sp.run(["git", "-C", d, *args], check=True, capture_output=True)
    open(os.path.join(d, "README.md"), "w").write("base\n")
    sp.run(["git", "-C", d, "add", "."], check=True, capture_output=True)
    sp.run(["git", "-C", d, "commit", "-qm", "base"], check=True, capture_output=True)


def test_v1_commit_scope_drops_scratch_keeps_protected_and_reverifies():
    """Scratch is pruned from what finalize will commit; the ORACLE file is PROTECTED no matter
    what the auditor says; the pruned tree is re-verified before being trusted.
    Mutants killed: scope trigger dropped; protected-set guard dropped."""
    with tempfile.TemporaryDirectory() as d:
        _git_cwd(d)
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            open(os.path.join(d, "test_x.py"), "w").write("def test_x():\n    assert True\n")
            return {"test_x.py::test_x": "c1"}

        def implement(charter, attempt, last_failure):
            open(os.path.join(d, "scratch_notes.md"), "w").write("debug scribbles\n")
            open(os.path.join(d, "impl.py"), "w").write("VALUE = 1\n")

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, ".devloop", "runs", "r"), cwd=d,
                          scope_audit=lambda ch, p, head: "scratch"
                          if p in ("scratch_notes.md", "test_x.py") else "deliverable")
        assert res["terminal"] == "COMPLETE"
        assert res["scope_dropped"] == ["scratch_notes.md"]
        assert not os.path.exists(os.path.join(d, "scratch_notes.md"))   # pruned
        assert os.path.exists(os.path.join(d, "impl.py"))                # deliverable kept
        assert os.path.exists(os.path.join(d, "test_x.py"))              # PROTECTED oracle survives
        assert os.path.isfile(os.path.join(d, ".devloop", "runs", "r", "commit_scope.json"))


def test_v1_commit_scope_restores_when_prune_breaks_verification():
    """A wrong 'scratch' call on a needed file is caught by the re-verify: every pruned file is
    RESTORED and everything commits — over-inclusion is cosmetic, lost work never happens.
    Mutants killed: restore-on-red dropped; per-criterion re-verify faked."""
    with tempfile.TemporaryDirectory() as d:
        _git_cwd(d)
        helper = os.path.join(d, "needed_helper.py")
        check = os.path.join(d, "check.py")

        def design(charter):
            open(helper, "w").write("OK = True\n")
            open(check, "w").write(
                f"import sys\nsys.exit(0 if 'OK' in open({helper!r}).read() else 1)\n")
            return {"t_c1": "c1"}

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, ".devloop", "runs", "r"), cwd=d,
                          scope_audit=lambda ch, p, head: "scratch"
                          if p == "needed_helper.py" else "deliverable")
        assert res["terminal"] == "COMPLETE"
        assert res["scope_dropped"] == []                                # nothing was lost
        assert open(helper).read() == "OK = True\n"                      # restored byte-identical
        cs = next(e for e in _events(res["trace_path"]) if e["step"] == "commit_scope")
        assert "restored" in cs.get("note", "")


def test_v1_commit_scope_regression_still_guards_the_pruned_tree():
    """Pruning may leave per-criterion evidence green yet break the SUITE (a pruned module a
    repo test imports) — the whole-suite gate re-runs on the pruned tree and restores on red.
    Mutant killed: post-prune regression re-check faked."""
    with tempfile.TemporaryDirectory() as d:
        _git_cwd(d)
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            open(os.path.join(d, "helper_mod.py"), "w").write("OK = True\n")
            open(os.path.join(d, "test_x.py"), "w").write(
                "def test_x():\n    import helper_mod\n    assert helper_mod.OK\n")
            return {"test_x.py::test_x": "c1"}

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, ".devloop", "runs", "r"), cwd=d,
                          scope_audit=lambda ch, p, head: "scratch"
                          if p == "helper_mod.py" else "deliverable")
        assert res["terminal"] == "COMPLETE"
        assert res["scope_dropped"] == []
        assert os.path.exists(os.path.join(d, "helper_mod.py"))          # the SUITE gate saved it


def test_v1_commit_scope_auditor_crash_fails_closed_to_deliverable():
    """Mutant killed: fail-closed default inverted (a crashed auditor must never classify
    anything as scratch)."""
    with tempfile.TemporaryDirectory() as d:
        _git_cwd(d)
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        def implement(charter, attempt, last_failure):
            open(os.path.join(d, "kept.md"), "w").write("x\n")

        def boom(ch, p, head):
            raise RuntimeError("auditor down")

        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, ".devloop", "runs", "r"), cwd=d,
                          scope_audit=boom)
        assert res["terminal"] == "COMPLETE" and res["scope_dropped"] == []
        assert os.path.exists(os.path.join(d, "kept.md"))
        cs = json.load(open(os.path.join(d, ".devloop", "runs", "r", "commit_scope.json")))
        assert cs["verdicts"] and set(cs["verdicts"].values()) == {"deliverable"}


def test_v1_tdd_order_pinned_tests_before_first_implement():
    """C8 (user ask 2026-07-03): the TDD order is DEMONSTRABLE in every trace — coverage,
    judge, and frozen_tests all strictly precede the first implement (tests gate the code,
    never retrofit). Mutant killed: freeze emit dropped."""
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        res = loop.run_v1(_charter(1), design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        steps = [e["step"] for e in _events(res["trace_path"])]
        first_impl = steps.index("implement")
        for pre in ("coverage", "judge", "frozen_tests"):
            assert steps.index(pre) < first_impl, f"{pre} did not precede the first implement"


def test_v1_human_review_ships_partial_grounding():
    """C8: a FAILED run ships the same per-criterion chain as a COMPLETE (grounded=False) —
    which promises were proven, which weren't, and why. Failed runs used to carry the least
    diagnosis exactly when the most was needed. Mutants killed: partial chain dropped at the
    back-off and test-fault terminals."""
    with tempfile.TemporaryDirectory() as d:
        # (a) back-off exhaustion with red evidence
        design, implement, verify, _ = _red_oracle(d)
        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=YES, judge_b=YES, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        g = res["grounding"]
        assert g["grounded"] is False
        it = g["criteria"][0]
        assert it["criterion_id"] == "c1" and it["evidence_passed"] is False   # the unproven promise, NAMED
        assert it["tests"] == ["t_c1"]                                         # ...with its covering tests
        assert os.path.isfile(os.path.join(d, "run", "grounding.json"))
    with tempfile.TemporaryDirectory() as d:
        # (b) up-front test fault (judge distrust): the chain still ships, evidence never ran
        design, implement, verify, _ = _red_oracle(d)
        res = loop.run_v1(_charter(1), design=design, implement=implement,
                          judge_a=NO, judge_b=NO, verify_cmd_for=verify,
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW" and "test fault" in res["reason"]
        g = res["grounding"]
        assert g["grounded"] is False and g["criteria"][0]["evidence_passed"] is False


def test_v1_persists_inspection_bundle():
    """C7 (user ask 2026-07-03): every loop stage leaves an inspectable artifact in run_dir —
    the bridge copies the whole dir to devloop-traces/<name>/ after the worktree is removed.
    Mutants killed: design_spec / grounding / oracle persist dropped."""
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            open(os.path.join(d, "test_x.py"), "w").write("def test_x():\n    assert True\n")
            return {"test_x.py::test_x": "c1"}

        rd = os.path.join(d, "run")
        ch = _charter(1)
        ch["dod"][0]["tier"] = "integration"        # tier scoping rides the whole chain
        res = loop.run_v1(ch, design=design, implement=lambda *a: None,
                          judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=rd, cwd=d)
        assert res["terminal"] == "COMPLETE"
        arts = {f: json.load(open(os.path.join(rd, f))) for f in
                ("charter.json", "design_spec.json", "rendered_tests.json",
                 "judge_verdicts.json", "grounding.json")}
        assert arts["charter.json"]["dod"][0]["id"] == "c1"
        spec = arts["design_spec.json"]["criteria"][0]
        assert spec["criterion_id"] == "c1" and spec["tests"] == ["test_x.py::test_x"]
        assert spec["verify_intent"] == "v1"                    # the INTENTION is recorded
        assert spec["tier"] == "integration"                    # ...and its validation TIER
        assert arts["grounding.json"]["criteria"][0]["tier"] == "integration"
        assert spec["judges"]["encodes"] is True
        assert "test_x.py" in arts["rendered_tests.json"]       # the oracle exactly as frozen
        assert arts["grounding.json"]["grounded"] is True
        notes = [json.loads(ln) for ln in open(os.path.join(rd, "attempts.jsonl"))]
        assert notes and notes[-1]["gate"] == "evidence" and notes[-1]["ok"] is True


# --- _do_implement: the engine's heart (P1 from advisor review) -----------------

def test_do_implement_dict_result_extracts_fields():
    """A real dispatcher returns a dict with exit_code, files_changed, changed_paths."""
    with tempfile.TemporaryDirectory() as rd:
        def fake_implement(charter, attempt, last_failure):
            return {"exit_code": 0, "files_changed": 2,
                    "summary": "created calc.py and test_calc.py",
                    "changed_paths": ["calc.py", "test_calc.py"]}
        ec, fc, paths = loop._do_implement(fake_implement, {"dod": [{"id": "c1"}]}, 0, None, rd)
        assert ec == 0
        assert fc == 2
        assert paths == ["calc.py", "test_calc.py"]


def test_do_implement_non_dict_result_returns_none():
    """A legacy implement that returns None (not a dict) → ec=None, fc=None, paths=[]."""
    with tempfile.TemporaryDirectory() as rd:
        def legacy_implement(charter, attempt, last_failure):
            return None
        ec, fc, paths = loop._do_implement(legacy_implement, {"dod": [{"id": "c1"}]}, 0, None, rd)
        assert ec is None
        assert fc is None
        assert paths == []


def test_do_implement_non_dict_result_with_string():
    """A legacy implement returning a string → ec=None, fc=None, summary=string."""
    with tempfile.TemporaryDirectory() as rd:
        def legacy_implement(charter, attempt, last_failure):
            return "did some work"
        ec, fc, paths = loop._do_implement(legacy_implement, {"dod": [{"id": "c1"}]}, 0, None, rd)
        assert ec is None
        assert fc is None
        assert paths == []


def test_do_implement_exit_code_nonzero():
    """A failed implementation (exit_code=1) → ok=False in the progress marker."""
    with tempfile.TemporaryDirectory() as rd:
        def fail_implement(charter, attempt, last_failure):
            return {"exit_code": 1, "files_changed": 0, "summary": "error",
                    "changed_paths": []}
        ec, fc, paths = loop._do_implement(fail_implement, {"dod": [{"id": "c1"}]}, 0, None, rd)
        assert ec == 1
        assert fc == 0
        assert paths == []


def test_do_implement_empty_dod():
    """A charter with empty dod → still works, just no criteria count in the marker."""
    with tempfile.TemporaryDirectory() as rd:
        def fake_implement(charter, attempt, last_failure):
            return {"exit_code": 0, "files_changed": 1, "summary": "ok",
                    "changed_paths": ["a.py"]}
        ec, fc, paths = loop._do_implement(fake_implement, {}, 0, None, rd)
        assert ec == 0
        assert fc == 1
        assert paths == ["a.py"]


def test_do_implement_no_changed_paths():
    """A dict result with no changed_paths → paths defaults to []."""
    with tempfile.TemporaryDirectory() as rd:
        def no_paths_implement(charter, attempt, last_failure):
            return {"exit_code": 0, "files_changed": 1, "summary": "ok"}
        ec, fc, paths = loop._do_implement(no_paths_implement, {"dod": [{"id": "c1"}]}, 0, None, rd)
        assert ec == 0
        assert paths == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} v1-loop tests passed")
