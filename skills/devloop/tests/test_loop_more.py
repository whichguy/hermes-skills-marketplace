"""Deterministic tests closing loop.py coverage gaps (surviving mutants) — NO LLM.

Each test pins the CURRENT correct behavior of loop.run_v1 (the v0 `loop.run` was deleted
2026-07-02) against a specific surviving mutant:

  1. run_v1 post-IMPLEMENT lint gate `if not lint_ok` -> `if False:`
  2. (deleted 2026-07-01) v0 checkpoint resume — loop-level resume was removed entirely;
       the fresh-start contract is pinned in test_loop_v1.test_v1_ignores_planted_checkpoint_fresh_budget
  3. run_v1 noop-coder fast route `if files_changed == 0` -> `if False:`
  4. run_v1 max_passes exhaustion -> the NO_TERMINATION bug sentinel (producer side)

Fakes write REAL files; evidence/lint run REAL subprocesses; the oracle (coverage + 2-model
assertion judge) gates the stop — exactly like test_loop_v1.py, whose module header, sys.path
setup, and local helpers (_charter / _events / YES / NO) this file mirrors.
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

# Source fixtures for the lint gate: a SyntaxError file (py-syntax linter is stdlib -> always
# available, so it deterministically exits nonzero) and its clean counterpart.
_BROKEN = "def f(:\n    return 1\n"
_CLEAN = "def f():\n    return 1\n"


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


def test_run_v1_lint_gate_blocks_broken_then_lets_clean_through():
    # Survivor 1 — loop.py:222 `if not lint_ok` (the v1 copy, "skip the test/judge passes").
    # Mutate to `if False:` and syntactically broken source sails past the syntactic gate straight
    # into the evidence/judge passes -> a FALSE COMPLETE on a green-but-uncompilable build. We pin
    # BOTH directions so a constant-return can't pass: broken-forever NEVER completes (evidence
    # never even runs); clean code DOES complete after exactly one lint-driven rebuild (control).

    # (b) PERSISTENT broken: the gate blocks every pass -> HUMAN_REVIEW, evidence NEVER runs.
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")
        mpath = os.path.join(d, "m.py")
        evid = []                                              # records each evidence.run via verify_cmd_for

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")   # ALWAYS green IF ever reached
            return {"t_c1": "c1"}

        def implement(charter, attempt, last_failure):            # every attempt writes BROKEN source
            open(mpath, "w").write(_BROKEN)
            return {"exit_code": 0, "files_changed": 1, "changed_paths": [mpath]}

        def verify_cmd_for(cid):
            evid.append(cid)                                      # only appended if evidence actually runs
            return [sys.executable, check]

        res = loop.run_v1(_charter(1), design=design, implement=implement, judge_a=YES, judge_b=YES,
                          verify_cmd_for=verify_cmd_for, run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"                  # KILL: the mutant COMPLETEs broken source
        assert evid == []                                         # KILL: lint blocked -> evidence never ran (mutant runs it)
        lint_events = [e for e in _events(res["trace_path"]) if e["step"] == "lint"]
        assert lint_events and all(e["ok"] is False for e in lint_events)   # every pass: lint really WAS red

    # (a) RECOVERY control: BROKEN on attempt 0, CLEAN after -> COMPLETE with ONE lint rebuild.
    with tempfile.TemporaryDirectory() as d:
        check = os.path.join(d, "check.py")
        mpath = os.path.join(d, "m.py")

        def design(charter):
            open(check, "w").write("import sys\nsys.exit(0)\n")
            return {"t_c1": "c1"}

        def implement(charter, attempt, last_failure):
            open(mpath, "w").write(_CLEAN if attempt >= 1 else _BROKEN)
            return {"exit_code": 0, "files_changed": 1, "changed_paths": [mpath]}

        res = loop.run_v1(_charter(1), design=design, implement=implement, judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: [sys.executable, check],
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "COMPLETE"
        assert res["state"]["rebuild_count"] == 1                 # KILL: the mutant skips the gate -> COMPLETE at 0
        ev = _events(res["trace_path"])
        assert any(e["step"] == "rebuild_fail" and e.get("cause") == "lint" for e in ev)   # KILL: no lint rebuild under mutant


def test_run_v1_noop_coder_with_red_evidence_routes_human_fast():
    # Survivor 3 — loop.py:249 `if files_changed == 0` (the v1 copy, "...AND not complete...").
    # A coder reporting files_changed==0 while evidence is RED is a no-progress dispatch: route
    # straight to HUMAN_REVIEW FAST (learning-3) instead of grinding the whole rebuild/replan budget.
    # Mutate to `if False:` and (judges trusted, so #18 attribution is empty) the loop falls through
    # to the rebuild grind: evidence re-runs 9x and exits via backoff with a useless reason.
    with tempfile.TemporaryDirectory() as d:
        res = loop.run_v1(_charter(1),
                          design=lambda c: {"t_c1": "c1"},                 # c1 covered -> coverage ok
                          implement=lambda c, a, lf: {"exit_code": 0, "files_changed": 0, "summary": "noop"},
                          judge_a=YES, judge_b=YES,                        # tests TRUSTED -> NOT a #18 test fault
                          verify_cmd_for=lambda cid: ["false"],            # evidence RED every run
                          run_dir=os.path.join(d, "run"), cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"                          # (both paths reach human; the rest discriminates)
        assert "no file change" in res.get("reason", "")                  # KILL: mutant exits with the backoff reason instead
        ev = _events(res["trace_path"])
        assert any(e["step"] == "dispatch_error" for e in ev)             # KILL: mutant never emits the fast-route event
        assert len([e for e in ev if e["step"] == "evidence"]) == 1       # KILL: fast route -> evidence ran ONCE, not 9x
        assert res["state"]["rebuild_count"] == 0                         # FAST route burned no rebuild budget


def test_run_v1_max_passes_exhaustion_emits_no_termination():
    # The bug-sentinel PRODUCER (T5, 2026-07-02 audit): exhausting max_passes without a terminal
    # decision must return NO_TERMINATION — with the exhaustion reason and the trace terminal —
    # NEVER COMPLETE. In production the back-off caps fire long before max_passes=64, so this
    # pins the sentinel with max_passes=1: one pass of red evidence + real file progress ends the
    # loop body without a decision. Mutant killed: the final terminal "NO_TERMINATION" -> "COMPLETE"
    # (the worst possible surviving mutant: an undecided run reads as success).
    with tempfile.TemporaryDirectory() as d:
        mpath = os.path.join(d, "m.py")

        def implement(charter, attempt, last_failure):
            open(mpath, "w").write("x = 1\n")
            return {"exit_code": 0, "files_changed": 1, "summary": "wrote m.py"}

        res = loop.run_v1(_charter(1), design=lambda c: {"t_c1": "c1"},
                          implement=implement, judge_a=YES, judge_b=YES,
                          verify_cmd_for=lambda cid: ["false"],           # red every pass
                          run_dir=os.path.join(d, "run"), cwd=d, max_passes=1)
        assert res["terminal"] == "NO_TERMINATION", res
        assert "max_passes exhausted" in res["reason"]
        ev = _events(res["trace_path"])
        assert ev[-1]["step"] == "terminal" and ev[-1]["terminal"] == "NO_TERMINATION"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} loop coverage-gap tests passed")
