#!/usr/bin/env python3
"""Narrated, self-checking walkthrough of NESTED flows + portable state (ctx.call +
run_flow/resume_flow — see references/nested-flows.md).

Unlike examples/walkthrough.py (which drives the run/resume CLI against an on-disk
--state-dir), this one uses the LIBRARY API: no state directory, no lock, no subprocess —
the entire resumable run travels as ONE self-contained JSON value.

    ACT 1  a parent flow calls an independent CHILD flow; the child hits a human gate,
           and the suspend bubbles up with a hoisted key ("payment/confirm_charge")
    ACT 2  the returned state IS the whole run — records, the embedded child sub-journal,
           inlined blobs — proven by round-tripping it through json.dumps/loads
    ACT 3  resume with the answer (passing back pending.key verbatim); the child's charge
           step is NOT re-run (a module counter proves exactly-once), the run completes
    ACT 4  resume the ACT-1 state AGAIN with a different answer — an independent fork
           reaching a different completion (why your own store should compare
           state["version"] before accepting a write-back)

Every act asserts its exit code and invariants — exits non-zero on any surprise.

    python3 examples/walkthrough_nested.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from engine import EXIT_OK, EXIT_SUSPENDED, flow, resume_flow, run_flow  # noqa: E402

CHARGES = []          # the "payment rail": every ctx.step("charge") execution lands here


@flow(id="payment")
def payment_flow(ctx, inp):
    # An independent, reusable child flow — its own Flow object, callable from any parent.
    decision = ctx.ask("confirm_charge",
                       {"prompt": "Charge %s to card ending %s?" % (inp["amount"], inp["card"]),
                        "options": ["yes", "no"]})
    if decision != "yes":
        return {"charged": False, "reason": decision}
    receipt = ctx.step("charge", lambda: (CHARGES.append(inp["amount"]) or
                                          {"receipt": "rcpt-%d" % len(CHARGES)}))
    return {"charged": True, "receipt": receipt["receipt"]}


@flow(id="fulfil_order")
def fulfil_order(ctx, inp):
    sku = ctx.step("reserve_stock", lambda: {"sku": inp["sku"], "reserved": True})
    pay = ctx.call("payment", payment_flow, {"amount": inp["amount"], "card": inp["card"]})
    return {"stock": sku, "payment": pay}


def say(txt):
    print(txt)


def check(cond, msg):
    if not cond:
        print("\nWALKTHROUGH SURPRISED: %s" % msg)
        sys.exit(1)


def main():
    order = {"sku": "widget-9", "amount": "$49.00", "card": "4242"}

    say("=" * 78)
    say("ACT 1 — run: the parent calls the child; the child's gate suspends the WHOLE chain")
    say("=" * 78)
    payload, code = run_flow(fulfil_order, order)
    say("  exit=%d status=%s" % (code, payload["status"]))
    say("  pending.key   = %r   <- hoisted: <call key>/<child's gate key>" % payload["pending"]["key"])
    say("  pending.chain = %r" % payload["pending"]["chain"])
    say("  question      = %r" % payload["pending"]["question"]["prompt"])
    check(code == EXIT_SUSPENDED, "expected suspend, got %d" % code)
    check(payload["pending"]["key"] == "payment/confirm_charge", "hoisted key wrong")
    check(CHARGES == [], "nothing should be charged yet")

    say("")
    say("=" * 78)
    say("ACT 2 — the returned state IS the whole run: one self-contained JSON value")
    say("=" * 78)
    state = payload["state"]
    call_recs = [r for r in state["records"] if r["type"] == "call_suspended"]
    say("  top-level records: %d  (%s)" % (len(state["records"]),
                                           ", ".join(r["type"] for r in state["records"])))
    say("  the call_suspended record EMBEDS the child's entire sub-journal:")
    for r in call_recs[0]["child_state"]["records"]:
        say("      child record: %s %s" % (r["type"], r.get("key", "")))
    say("  version token (for YOUR store's optimistic concurrency): %d" % state["version"])
    blob = json.dumps(state)
    say("  json.dumps round-trip: %d bytes — hand this to any process, any machine" % len(blob))
    state = json.loads(blob)   # from here on we only use the round-tripped copy
    check(len(call_recs) == 1, "expected exactly one embedded call")

    say("")
    say("=" * 78)
    say("ACT 3 — resume with the answer; the memoized prefix replays, nothing re-runs")
    say("=" * 78)
    payload2, code2 = resume_flow(fulfil_order, state, answer='"yes"',
                                  key="payment/confirm_charge")   # pending.key round-trips verbatim
    say("  exit=%d status=%s" % (code2, payload2["status"]))
    say("  result: %s" % json.dumps(payload2["result"], sort_keys=True))
    say("  charges actually fired: %r  <- exactly once" % CHARGES)
    check(code2 == EXIT_OK, "expected completion, got %d" % code2)
    check(payload2["result"]["payment"] == {"charged": True, "receipt": "rcpt-1"}, "payment wrong")
    check(CHARGES == ["$49.00"], "the charge must fire exactly once")

    say("")
    say("=" * 78)
    say("ACT 4 — the OLD state is still a valid run: forking is possible, so guard writes")
    say("=" * 78)
    fork = json.loads(blob)                       # the ACT-1 snapshot, answered differently
    payload3, code3 = resume_flow(fulfil_order, fork, answer='"no"')
    say("  exit=%d status=%s result=%s" % (code3, payload3["status"],
                                           json.dumps(payload3["result"], sort_keys=True)))
    say("  charges after the fork: %r  <- the 'no' branch never charges" % CHARGES)
    say("  -> two DIFFERENT completions now exist from one history point. The engine cannot")
    say("     see your storage; compare state['version'] in your own store before accepting")
    say("     a written-back blob (references/nested-flows.md, trade-off #2).")
    check(code3 == EXIT_OK, "fork should complete")
    check(payload3["result"]["payment"] == {"charged": False, "reason": "no"}, "fork branch wrong")
    check(CHARGES == ["$49.00"], "the fork's 'no' branch must not charge")

    say("")
    say("walkthrough_nested: ALL GOOD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
