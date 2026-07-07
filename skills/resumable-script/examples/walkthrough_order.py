#!/usr/bin/env python3
"""Walkthrough flow — one order that touches every mechanism the engine offers.

Read this together with examples/walkthrough.py, the narrated driver that runs this
flow through a crash, an in-doubt resolution, and both sides of a human decision gate:

    python3 examples/walkthrough.py                # narrate on the Python engine
    python3 examples/walkthrough.py --engine js    # ... on the Node engine
    python3 examples/walkthrough.py --engine both  # both, back to back

You can also drive it by hand — it is an ordinary CLI flow:

    python3 examples/walkthrough_order.py run    --state-dir /tmp/w --input '{"sku":"widget-1","qty":1}'
    python3 examples/walkthrough_order.py resume --state-dir /tmp/w --answer '"approve"'

The steps, in order:

    validate       (idempotent)      normalize the incoming order
    reserve-stock  (idempotent)      hold inventory
    charge-card    (NON-idempotent)  move money   <- the step that can crash mid-flight
    ship-approval  (human gate)      approve | hold
    ship / hold    (NON-idempotent)  the branch chosen at the gate

Environment knobs the driver toggles to script the story (all optional):
    WALK_CRASH=1     hard-exit inside charge-card AFTER the effect lands, BEFORE the
                     engine can journal completion — a real mid-step process death.
    WALK_LEDGER=path append the idempotency key when the card is charged, so the driver
                     can PROVE the card is charged exactly once across every resume.
    WALK_TRACE=path  append "(phase key)" for every step as it runs — incl. replay — so
                     the driver can show what actually executed vs. what came from the journal.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from engine import flow, run_cli  # noqa: E402


def _trace(event):
    """Out-of-band narration hook, picked up by the engine's flow loader as `observer`.

    Runs on EVERY pass (including replay) and is try-guarded inside the engine, so it can
    never affect the flow. We just append (phase, key) to $WALK_TRACE if it is set.
    """
    path = os.environ.get("WALK_TRACE")
    if not path:
        return
    with open(path, "a") as f:
        f.write("%s %s\n" % (event.get("phase"), event.get("key")))


observer = _trace  # module-level name the engine looks for


def validate(inp):
    order = inp or {}
    return {"sku": order.get("sku", "widget-1"),
            "qty": int(order.get("qty", 1)),
            "region": order.get("region", "us")}


def reserve(order):
    return {"reserved": order["qty"], "sku": order["sku"]}


def charge(order, idem):
    # The money move. `idem` (= "<run_id>:charge-card") is what you would forward to the
    # payment API as its idempotency key, so a re-attempt after a crash dedupes there too.
    # Here we append it to a "ledger" file to make the exactly-once guarantee observable.
    ledger = os.environ.get("WALK_LEDGER")
    if ledger:
        seen = set()
        if os.path.exists(ledger):
            seen = set(x for x in open(ledger).read().split("\n") if x)
        if idem not in seen:
            with open(ledger, "a") as f:
                f.write(idem + "\n")
    # Simulate a process death AFTER the side effect lands but BEFORE the engine journals
    # completion -> on resume the step is "in doubt" (exit 11), not blindly retried.
    if os.environ.get("WALK_CRASH") == "1":
        os._exit(137)
    return {"charged": order["qty"] * 10, "currency": "USD"}


def ship(order, idem):
    return {"shipped_to": order["region"], "sku": order["sku"]}


def hold(order, idem):
    return {"held": True, "sku": order["sku"]}


@flow(id="walkthrough-order", version=1)
def order_flow(ctx, inp):
    order = ctx.step("validate", lambda: validate(inp),
                     desc="normalize the order")
    ctx.step("reserve-stock", lambda: reserve(order),
             desc="hold inventory")
    charged = ctx.step("charge-card", lambda idem: charge(order, idem),
                       idempotent=False, desc="charge the card (non-idempotent)")
    decision = ctx.ask(
        "ship-approval",
        {"prompt": "Charged %s %s for %s. Ship to %s?"
                   % (charged["charged"], charged["currency"], order["sku"], order["region"])},
        {"type": "string", "enum": ["approve", "hold"]},
        desc="human approval to ship")
    if decision == "approve":
        outcome = ctx.step("ship", lambda idem: ship(order, idem),
                           idempotent=False, desc="ship the order")
    else:
        outcome = ctx.step("hold", lambda idem: hold(order, idem),
                           idempotent=False, desc="queue the order on hold")
    return {"decision": decision, "order": order, "charge": charged, "outcome": outcome}


if __name__ == "__main__":
    sys.exit(run_cli(order_flow, observer=observer))
