#!/usr/bin/env python3
"""Visualize how the devloop INNER loop iterates within a SINGLE task — deterministic, no LLM.

The live spike never iterates (its evidence gate is always-green, so the first VERIFY
completes). Real iteration = when VERIFY is RED the loop backs off and retries, governed by
code-enforced counters (gate.backoff_exhausted + state counters) until it either COMPLETEs or
routes to HUMAN_REVIEW. This prints that loop pass-by-pass using the REAL kernel functions.

Run: python3 spike/loop_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config      # noqa: E402
import state       # noqa: E402
import evidence    # noqa: E402
import gate        # noqa: E402

JV = [{"criterion_id": "c1", "encodes": True, "escalate": False}]  # a trusted judge verdict


def _charter():
    return {"interpreted_intent": "demo", "purpose": "demo",
            "dod": [{"id": "c1", "criterion": "x", "verify_intent": "x", "kind": "shown"}],
            "assumptions": [{"text": "a", "confidence": 0.9}], "open_questions": [],
            "happy_path": "do", "blast_radius": {"files": ["a.py"], "order": ["a.py"]},
            "backoff_map": [{"trigger": "t", "directional_response": "r"}],
            "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"}}


def demo(label, verify_results):
    """verify_results: per BUILD->VERIFY attempt, 'green' or 'red' (last value repeats)."""
    ch = _charter()
    st = state.new_run_state(ch)
    print(f"\n=== {label} ===")
    print(f"caps: MAX_LOCAL_REBUILDS={config.MAX_LOCAL_REBUILDS}  MAX_REPLANS={config.MAX_REPLANS}")
    print(f"{'pass':>4}  {'action':<13} {'rebuild':>7} {'replan':>6}  {'VERIFY':>6}  result")
    attempt = 0
    for _ in range(100):  # safety cap; the backstop terminates well before this
        action, _ = gate.backoff_exhausted(st)
        if action == "HUMAN_REVIEW":
            print(f"{'':>4}  {'HUMAN_REVIEW':<13} {st['rebuild_count']:>7} {st['replan_count']:>6}"
                  f"          back-off exhausted -> ask the human")
            return
        if action == "REPLAN":
            state.on_replan(st)
            print(f"{'':>4}  {'RE-PLAN':<13} {st['rebuild_count']:>7} {st['replan_count']:>6}"
                  f"          structural retry (rebuilds reset)")
            continue
        # CONTINUE -> one BUILD then VERIFY
        res = verify_results[min(attempt, len(verify_results) - 1)]
        attempt += 1
        ledger = {"c1": evidence.run("c1", ["true"] if res == "green" else ["false"])}
        ok, _ = gate.stop_condition(ch, ledger, council_affirmed=True, coverage_ok=True, judge_verdicts=JV)
        if ok:
            print(f"{attempt:>4}  {'BUILD+VERIFY':<13} {st['rebuild_count']:>7} {st['replan_count']:>6}"
                  f"  {res:>6}  COMPLETE (DoD-SATISFIED)")
            return
        state.on_rebuild_fail(st)
        print(f"{attempt:>4}  {'BUILD+VERIFY':<13} {st['rebuild_count']:>7} {st['replan_count']:>6}"
              f"  {res:>6}  red -> local re-BUILD")


if __name__ == "__main__":
    demo("A) fixed on the 3rd try  (red, red, green)", ["red", "red", "green"])
    demo("B) never fixed -> terminates at HUMAN_REVIEW  (always red)", ["red"])
    print("\nTakeaway: the loop ITERATES BUILD->VERIFY; a code gate (not the model) decides "
          "re-BUILD vs RE-PLAN vs HUMAN_REVIEW; DoD-SATISFIED or the back-off cap always ends it.")
