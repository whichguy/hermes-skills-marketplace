#!/usr/bin/env python3
"""Narrated, self-checking walkthrough of the resumable-script engine.

Drives examples/walkthrough_order through the REAL run/resume CLI and narrates every
stage of one order's life:

    ACT 1  a non-idempotent step (charge-card) is killed mid-flight
    ACT 2  re-running detects the dangling step and escalates instead of re-charging;
           an operator resolves the doubt and the flow advances
    ACT 3  a human decision gate — a bad answer bounces, "approve" ships
    ACT 4  re-running a finished run is free and never charges the card twice
    ACT 5  the same flow on a clean run, answered "hold" — the other branch

For each command it shows: the exit code, the status payload, the observer trace
(what actually executed vs. what was served from the journal), and the journal delta.
Every stage asserts its exit code and the key invariants, so this is also a
regression demo — it exits non-zero if any stage surprises it.

    python3 examples/walkthrough.py                # Python engine (default)
    python3 examples/walkthrough.py --engine js    # Node engine
    python3 examples/walkthrough.py --engine both   # both, back to back
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE_PY = os.path.join(ROOT, "scripts", "engine.py")
ENGINE_JS = os.path.join(ROOT, "extras", "js-mirror", "scripts", "engine.js")  # quarantined mirror
FLOW_PY = os.path.join(HERE, "walkthrough_order.py")
FLOW_JS = os.path.join(ROOT, "extras", "js-mirror", "examples", "walkthrough_order.js")


# --- CLI invocation + journal reading ------------------------------------------------

def invoke(engine, cmd, state_dir, *, trace=None, ledger=None, crash=False,
           inp=None, answer=None, resolve=None, resolve_value=None):
    if engine == "py":
        argv = [sys.executable, ENGINE_PY, cmd, "--flow", FLOW_PY, "--state-dir", state_dir]
    else:
        argv = ["node", ENGINE_JS, cmd, "--flow", FLOW_JS, "--state-dir", state_dir]
    if inp is not None:
        argv += ["--input", inp]
    if answer is not None:
        argv += ["--answer", answer]
    if resolve is not None:
        argv += ["--resolve", resolve]
    if resolve_value is not None:
        argv += ["--resolve-value", resolve_value]

    env = dict(os.environ)
    if trace:
        env["WALK_TRACE"] = trace
        open(trace, "w").close()          # reset: show only THIS command's activity
    else:
        env.pop("WALK_TRACE", None)
    if ledger:
        env["WALK_LEDGER"] = ledger
    else:
        env.pop("WALK_LEDGER", None)
    if crash:
        env["WALK_CRASH"] = "1"
    else:
        env.pop("WALK_CRASH", None)

    p = subprocess.run(argv, capture_output=True, text=True, env=env)
    payload = None
    body = p.stdout.strip()
    if body:
        try:
            payload = json.loads(body.splitlines()[-1])
        except ValueError:
            payload = None
    trace_lines = []
    if trace and os.path.exists(trace):
        trace_lines = [ln for ln in open(trace).read().splitlines() if ln]
    return p.returncode, payload, p.stderr.strip(), trace_lines


def read_journal(state_dir):
    jp = os.path.join(state_dir, "journal.jsonl")
    if not os.path.exists(jp):
        return []
    out = []
    for ln in open(jp):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def ledger_lines(path):
    if not path or not os.path.exists(path):
        return []
    return [x for x in open(path).read().splitlines() if x]


def fmt_record(r):
    t = r.get("type", "?")
    key = r.get("key") or r.get("pending_key") or ""
    detail = ""
    if t == "step_completed":
        detail = " -> " + json.dumps(r.get("result"))
    elif t == "ask_requested":
        detail = " ? " + (r.get("question") or {}).get("prompt", "")
    elif t == "ask_answered":
        detail = " = " + json.dumps(r.get("answer"))
    elif t == "in_doubt_resolved":
        detail = " [%s]" % r.get("action")
    elif t == "run_started":
        key = "run_id=" + str(r.get("run_id", ""))[:8]
    elif t in ("flow_completed", "flow_failed", "flow_suspended"):
        key = key or ""
    return "    %-18s %s%s" % (t, key, detail)


# --- narration -----------------------------------------------------------------------

def banner(text):
    print("\n" + "=" * 78)
    print("  " + text)
    print("=" * 78)


def say(text):
    for line in text.split("\n"):
        print("  " + line)


class Story:
    """One state dir carried across acts; prints command results + journal deltas."""

    def __init__(self, engine, state_dir, ledger, trace):
        self.engine = engine
        self.state_dir = state_dir
        self.ledger = ledger
        self.trace = trace
        self._shown = 0
        self.problems = []

    def cmd(self, label, cmd, **kw):
        code, payload, err, tr = invoke(self.engine, cmd, self.state_dir,
                                        trace=self.trace, ledger=self.ledger, **kw)
        print("\n  $ %s" % label)
        status = payload.get("status") if payload else "(no JSON — process died)"
        print("    exit %s   status=%s" % (code, status))
        if err:
            print("    stderr: " + err.splitlines()[0])
        if tr:
            print("    trace : " + ", ".join(tr))
        delta = self._journal_delta()
        if delta:
            print("    journal +%d:" % len(delta))
            for r in delta:
                print("  " + fmt_record(r))
        return code, payload, tr

    def _journal_delta(self):
        recs = read_journal(self.state_dir)
        new = recs[self._shown:]
        self._shown = len(recs)
        return new

    def check(self, cond, msg):
        print("      [%s] %s" % ("ok" if cond else "FAIL", msg))
        if not cond:
            self.problems.append("%s: %s" % (self.engine, msg))


def walk(engine):
    tmp = tempfile.mkdtemp(prefix="walk-%s-" % engine)
    try:
        sd = os.path.join(tmp, "crash-story")
        ledger = os.path.join(tmp, "ledger.txt")
        trace = os.path.join(tmp, "trace.txt")
        s = Story(engine, sd, ledger, trace)
        order = '{"sku":"widget-1","qty":1,"region":"us"}'

        banner("ACT 1 — a non-idempotent step is killed mid-flight  [%s]" % engine)
        say("Run the order. WALK_CRASH=1 kills the process INSIDE charge-card, after the\n"
            "money moves (ledger gets an entry) but before the engine can journal that the\n"
            "step finished.")
        code, _, _ = s.cmd("engine run --input %s   (WALK_CRASH=1)" % order, "run",
                           inp=order, crash=True)
        s.check(code == 137, "process was killed mid-charge (exit 137)")
        s.check(len(ledger_lines(ledger)) == 1, "card WAS charged once (ledger has 1 entry)")
        last = read_journal(sd)[-1] if read_journal(sd) else {}
        s.check(last.get("type") == "step_started" and last.get("key") == "charge-card",
                "journal ends at 'step_started charge-card' with no completion -> in doubt")

        banner("ACT 2 — re-run escalates instead of re-charging; operator resolves  [%s]" % engine)
        say("Re-run. The engine replays validate + reserve from the journal (see the trace:\n"
            "'replay'), reaches charge-card, finds it started-but-never-finished, and because\n"
            "it is non-idempotent it REFUSES to blindly re-charge — it escalates.")
        code, payload, _ = s.cmd("engine run --input %s" % order, "run", inp=order)
        s.check(code == 11, "escalated to in-doubt (exit 11)")
        s.check(bool(payload) and payload.get("pending", {}).get("key") == "charge-card",
                "the in-doubt step is charge-card")
        s.check(len(ledger_lines(ledger)) == 1, "still charged only once (no re-charge on the probe)")

        say("\nThe operator checks the payment provider (here: the ledger) out of band, sees the\n"
            "charge landed, and resolves the doubt as 'completed', handing back the known result.")
        code, payload, _ = s.cmd("engine resume --resolve completed --resolve-value '{...}'",
                                 "resume", resolve="completed",
                                 resolve_value='{"charged":10,"currency":"USD"}')
        s.check(code == 10, "doubt resolved; flow advanced to the human gate (exit 10)")
        s.check(bool(payload) and payload.get("pending", {}).get("key") == "ship-approval",
                "now suspended at the ship-approval gate")

        banner("ACT 3 — the human decision gate  [%s]" % engine)
        say("The gate is typed (enum: approve | hold). A bad answer is rejected and the gate\n"
            "stays open for a corrected one.")
        code, _, _ = s.cmd("engine resume --answer '\"maybe\"'", "resume", answer='"maybe"')
        s.check(code == 2, "invalid answer 'maybe' rejected (exit 2); gate stays open")

        say("\nNow a valid answer. 'approve' routes to the ship step — and ONLY ship executes;\n"
            "everything before it is served from the journal (trace shows 'replay').")
        code, payload, tr = s.cmd("engine resume --answer '\"approve\"'", "resume", answer='"approve"')
        s.check(code == 0, "approved; flow completed (exit 0)")
        res = (payload or {}).get("result", {})
        s.check(res.get("decision") == "approve" and res.get("outcome", {}).get("shipped_to") == "us",
                "result routed down the ship branch (shipped_to=us)")
        s.check("before charge-card" not in tr and "before ship" in tr,
                "charge-card was NOT re-executed; only 'ship' ran fresh")

        banner("ACT 4 — resuming a finished run is free and safe  [%s]" % engine)
        say("Run the exact same command again on the same state dir. Every step is served from\n"
            "the journal; nothing re-executes; the card is NOT charged a second time.")
        code, payload, tr = s.cmd("engine run --input %s   (again)" % order, "run", inp=order)
        s.check(code == 0, "re-run completed (exit 0)")
        res = (payload or {}).get("result", {})
        s.check(res.get("outcome", {}).get("shipped_to") == "us", "identical result returned")
        s.check(all(ln.startswith("replay") for ln in tr) and bool(tr),
                "trace is ALL 'replay' — nothing executed")
        s.check(len(ledger_lines(ledger)) == 1, "card STILL charged exactly once (exactly-once proof)")

        banner("ACT 5 — the other decision path, on a clean run  [%s]" % engine)
        say("Fresh state dir, no crash. Same flow, answered 'hold' at the gate — the flow takes\n"
            "the other branch (queue-hold, not ship).")
        sd2 = os.path.join(tmp, "hold-story")
        ledger2 = os.path.join(tmp, "ledger2.txt")
        s2 = Story(engine, sd2, ledger2, trace)
        order2 = '{"sku":"gadget-9","qty":2,"region":"eu"}'
        code, payload, _ = s2.cmd("engine run --input %s" % order2, "run", inp=order2)
        s2.check(code == 10, "clean run suspended at the gate (exit 10)")
        prompt = (payload or {}).get("pending", {}).get("question", {}).get("prompt", "")
        s2.check("Charged 20 USD for gadget-9" in prompt and "Ship to eu" in prompt,
                 "gate prompt reflects this order (charged 20 USD, region eu)")
        s2.check(len(ledger_lines(ledger2)) == 1, "charged once, cleanly")
        code, payload, tr = s2.cmd("engine resume --answer '\"hold\"'", "resume",
                                   answer='"hold"')
        s2.check(code == 0, "held; completed (exit 0)")
        res = (payload or {}).get("result", {})
        s2.check(res.get("decision") == "hold" and res.get("outcome", {}).get("held") is True
                 and "shipped_to" not in res.get("outcome", {}),
                 "result routed down the HOLD branch (ship never ran)")
        s2.check("before ship" not in tr, "the ship step was never executed on this path")

        return s.problems + s2.problems
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["py"], default="py")  # js mirror quarantined
    args = ap.parse_args()
    engines = ["py", "js"] if args.engine == "both" else [args.engine]

    problems = []
    for eng in engines:
        if eng == "js" and not shutil.which("node"):
            print("\n[skip] node not found; cannot run the JS engine.")
            continue
        problems += walk(eng)

    banner("SUMMARY")
    if problems:
        say("%d check(s) FAILED:" % len(problems))
        for p in problems:
            print("    - " + p)
        return 1
    say("All checks passed. The engine crashed, refused to double-charge, was resolved,\n"
        "gated on a human, and replayed for free — deterministically, in %s."
        % (" + ".join(engines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
