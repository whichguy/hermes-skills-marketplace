#!/usr/bin/env python3
"""Narrated, self-checking walkthrough of a durable agentic codebase investigation.

Drives examples/investigate_repo through the REAL run/resume CLI (fixture backend) and
narrates how a long "triage a failing test" session survives the things that actually
derail one:

    ACT 1  the expensive repo scan is memoized; a broken environment blocks `reproduce`,
           gets fixed out of band, and resume re-runs ONLY that step (scan is not redone)
    ACT 2  an ambiguous failure -> a human decides which suspect file to open
    ACT 3  approval before mutating; the edit is killed mid-write -> in-doubt, then resolved
    ACT 4  re-running the finished investigation is free and re-edits nothing
    ACT 5  the same investigation, but the human declines the fix -> report-only branch

For each command it shows the exit code, status, observer trace (scanned vs. replayed),
and the journal delta. Every stage asserts its exit code + invariants, so this doubles
as a regression demo.

    python3 examples/walkthrough_investigate.py                # Python engine (default)
    python3 examples/walkthrough_investigate.py --engine js
    python3 examples/walkthrough_investigate.py --engine both
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
FLOW_PY = os.path.join(HERE, "investigate_repo.py")
FLOW_JS = os.path.join(ROOT, "extras", "js-mirror", "examples", "investigate_repo.js")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "investigation", "tools.json")


def invoke(engine, cmd, state_dir, *, trace=None, dep_down=False, crash_apply=False,
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
    env["INVESTIGATE_MODE"] = "fixture"
    env["INVESTIGATE_FIXTURE"] = FIXTURE
    if trace:
        env["INVESTIGATE_TRACE"] = trace
        open(trace, "w").close()
    else:
        env.pop("INVESTIGATE_TRACE", None)
    if dep_down:
        env["INVESTIGATE_DEP_DOWN"] = "1"
    else:
        env.pop("INVESTIGATE_DEP_DOWN", None)
    if crash_apply:
        env["INVESTIGATE_CRASH_APPLY"] = "1"
    else:
        env.pop("INVESTIGATE_CRASH_APPLY", None)

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


def count_started(state_dir, key):
    return sum(1 for r in read_journal(state_dir)
               if r.get("type") == "step_started" and r.get("key") == key)


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
    return "    %-18s %s%s" % (t, key, detail)


def banner(text):
    print("\n" + "=" * 78)
    print("  " + text)
    print("=" * 78)


def say(text):
    for line in text.split("\n"):
        print("  " + line)


class Story:
    def __init__(self, engine, state_dir, trace):
        self.engine = engine
        self.state_dir = state_dir
        self.trace = trace
        self._shown = 0
        self.problems = []

    def cmd(self, label, cmd, **kw):
        code, payload, err, tr = invoke(self.engine, cmd, self.state_dir, trace=self.trace, **kw)
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
    tmp = tempfile.mkdtemp(prefix="walkinv-%s-" % engine)
    try:
        sd = os.path.join(tmp, "investigation")
        trace = os.path.join(tmp, "trace.txt")
        s = Story(engine, sd, trace)
        goal = '{"goal":"test_verify"}'

        banner("ACT 1 — memoized scan; a broken environment blocks reproduce  [%s]" % engine)
        say("Start the investigation with INVESTIGATE_DEP_DOWN=1: the repo scan succeeds, but a\n"
            "missing dependency stops us from even reproducing the failure. The `reproduce` step\n"
            "fails cleanly (exit 1) — the scan work is already safe on disk.")
        code, _, _ = s.cmd("engine run --input %s   (DEP_DOWN=1)" % goal, "run",
                           inp=goal, dep_down=True)
        s.check(code == 1, "reproduce failed on the broken environment (exit 1)")
        s.check(count_started(sd, "map") == 1, "the repo was scanned once")

        say("\nThe engineer installs the missing dep out of band and resumes. `map` is served from\n"
            "the journal (trace: 'replay map') — the expensive scan is NOT redone — and only\n"
            "`reproduce` runs again, this time capturing the real assertion failure.")
        code, payload, tr = s.cmd("engine run --input %s   (dep restored)" % goal, "run", inp=goal)
        s.check(code == 10, "recovered; suspended at the focus decision gate (exit 10)")
        s.check(count_started(sd, "map") == 1, "map was NOT re-scanned across the resume (still 1)")
        s.check("replay map" in tr and "before reproduce" in tr,
                "map replayed from journal; reproduce re-attempted")
        s.check(bool(payload) and payload.get("pending", {}).get("key") == "focus",
                "now waiting on the human to pick a suspect")

        banner("ACT 2 — the human decides which suspect to open  [%s]" % engine)
        prompt = (payload or {}).get("pending", {}).get("question", {}).get("prompt", "")
        say("The gate offers the located suspects (typed to that exact set):\n  " + prompt)
        say("The agent opens that file, then proposes a fix (a memoized `propose` step — the\n"
            "analysis is never redone on resume) and stops at the approval gate before mutating.")
        code, payload, _ = s.cmd("engine resume --answer '\"src/auth.py\"'", "resume",
                                 answer='"src/auth.py"')
        s.check(code == 10, "inspected + proposed a fix; suspended at the approval gate (exit 10)")
        s.check(bool(payload) and payload.get("pending", {}).get("key") == "approve-fix",
                "now waiting for approval before any mutation")

        banner("ACT 3 — approval, then a crash mid-edit -> in-doubt -> resolve  [%s]" % engine)
        say("We approve the fix, but INVESTIGATE_CRASH_APPLY=1 kills the process INSIDE apply-fix,\n"
            "after the edit is written but before completion is journaled.")
        code, _, _ = s.cmd("engine resume --answer true   (CRASH_APPLY=1)", "resume",
                           answer="true", crash_apply=True)
        s.check(code == 137, "process was killed mid-edit (exit 137)")

        say("\nRe-run. apply-fix started-but-never-finished, and it is non-idempotent, so the engine\n"
            "REFUSES to blindly re-edit the file — it escalates.")
        code, payload, _ = s.cmd("engine run --input %s" % goal, "run", inp=goal)
        s.check(code == 11, "escalated to in-doubt (exit 11)")
        s.check(bool(payload) and payload.get("pending", {}).get("key") == "apply-fix",
                "the in-doubt step is apply-fix")

        say("\nThe engineer confirms the edit landed (git diff shows it) and resolves 'completed';\n"
            "the flow runs verify and finishes.")
        code, payload, _ = s.cmd("engine resume --resolve completed --resolve-value '{\"patched\":\"src/auth.py\"}'",
                                 "resume", resolve="completed",
                                 resolve_value='{"patched":"src/auth.py"}')
        s.check(code == 0, "resolved; investigation completed (exit 0)")
        res = (payload or {}).get("result", {})
        s.check(res.get("status") == "fixed" and res.get("suspect") == "src/auth.py"
                and res.get("fix_applied") is True,
                "result: fixed src/auth.py, verified")

        banner("ACT 4 — re-running a finished investigation is free  [%s]" % engine)
        say("Run the same command again. Every step — including apply-fix — is served from the\n"
            "journal; nothing re-executes; the file is not edited a second time.")
        code, payload, tr = s.cmd("engine run --input %s   (again)" % goal, "run", inp=goal)
        s.check(code == 0, "re-run completed (exit 0)")
        s.check(all(ln.startswith("replay") for ln in tr) and bool(tr),
                "trace is ALL 'replay' — nothing executed")
        s.check(count_started(sd, "apply-fix") == 1, "apply-fix ran exactly once, ever")

        banner("ACT 5 — the report-only branch (human declines the fix)  [%s]" % engine)
        say("Fresh investigation, healthy environment. This time the human declines the fix at the\n"
            "approval gate — the agent reports the finding without mutating anything.")
        sd2 = os.path.join(tmp, "report-only")
        s2 = Story(engine, sd2, trace)
        code, payload, _ = s2.cmd("engine run --input %s" % goal, "run", inp=goal)
        s2.check(code == 10, "suspended at the focus gate (exit 10)")
        code, payload, _ = s2.cmd("engine resume --answer '\"src/auth.py\"'", "resume",
                                  answer='"src/auth.py"')
        s2.check(code == 10, "inspected; suspended at the approval gate (exit 10)")
        code, payload, tr = s2.cmd("engine resume --answer false", "resume", answer="false")
        s2.check(code == 0, "declined; completed (exit 0)")
        res = (payload or {}).get("result", {})
        s2.check(res.get("status") == "reported" and res.get("fix_applied") is False,
                 "result: reported, NO fix applied")
        s2.check(count_started(sd2, "apply-fix") == 0, "apply-fix never ran on the report-only path")

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
    say("All checks passed. A durable investigation survived a broken environment, a human\n"
        "decision, a crash mid-edit, and a re-run — never re-scanning or re-editing, in %s."
        % (" + ".join(engines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
