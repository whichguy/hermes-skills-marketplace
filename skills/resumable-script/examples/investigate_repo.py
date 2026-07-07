#!/usr/bin/env python3
"""Agentic investigation flow — a durable, resumable "triage a failing test" session.

This is what the engine is FOR: a long codebase investigation you don't want to redo.
The expensive scan is memoized, a broken environment is recovered by resuming, an
ambiguous failure routes through a human decision, a mutating edit is gated on approval
and survives a mid-edit crash. See examples/walkthrough_investigate.py for a narrated
run, and examples/investigate_tools.py for the swappable fixture/real tool backend.

    python3 examples/investigate_repo.py run    --state-dir /tmp/i --input '{"goal":"test_verify"}'
    python3 examples/investigate_repo.py resume --state-dir /tmp/i --answer '"src/auth.py"'

The steps (each a real investigation moment mapped to an engine mechanism):

    map          idempotent   scan the repo layout            <- memoized across resumes
    reproduce    step         run the tests to reproduce      <- env failure -> fix -> resume
    locate       idempotent   grep the failing symbol
    focus        human gate   pick which suspect to open
    inspect      idempotent   read the suspect file
    approve-fix  human gate   sign off before mutating
    apply-fix    NON-idem     edit the file                   <- crash here -> in-doubt
    verify       step         re-run the tests
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
from engine import flow, run_cli          # noqa: E402
import investigate_tools as tools         # noqa: E402

observer = tools.observer                 # module-level name the engine looks for
MAX_FLAKY = 2                             # bounded retries before escalating a flaky failure


@flow(id="investigate-repo", version=1)
def investigate(ctx, inp):
    goal = (inp or {}).get("goal", "the failing test")

    # 1. Map the repo. Expensive -> memoized; resuming an investigation never re-scans.
    modules = ctx.step("map", tools.map_repo, desc="scan the repo layout")

    # 2. Reproduce. A broken ENVIRONMENT (missing dep) fails this step; fix it out of
    #    band and resume -> only this step re-runs (map stays memoized).
    rep = ctx.step("reproduce", lambda: tools.run_tests("reproduce"),
                   desc="run the tests to reproduce %s" % goal)
    kind = tools.classify(rep["out"])

    # 3. Flaky failures: retry a bounded number of times; if it never stabilizes, ask a
    #    human whether to dig in anyway or abandon (the transient-vs-real decision).
    if kind == "flaky":
        for i in range(MAX_FLAKY):
            rep = ctx.step("reproduce-retry#%d" % i, lambda: tools.run_tests("reproduce"),
                           desc="retry the flaky reproduce (#%d)" % i)
            kind = tools.classify(rep["out"])
            if kind != "flaky":
                break
        if kind == "flaky":
            decision = ctx.ask(
                "flaky-decision",
                {"prompt": "Still flaky after %d retries. Proceed anyway or abandon?" % MAX_FLAKY},
                {"type": "string", "enum": ["proceed", "abandon"]},
                desc="decide on a persistently flaky failure")
            if decision == "abandon":
                return {"status": "abandoned-flaky", "kind": "flaky", "modules": modules}

    if rep["code"] == 0:
        return {"status": "no-repro", "modules": modules}

    # 4. Locate suspects via the symbol in the failure output.
    symbol = tools.extract_symbol(rep["out"])
    suspects = ctx.step("locate", lambda: tools.grep(symbol),
                        desc="grep for %s" % symbol)
    suspect_paths = sorted({m["path"] for m in suspects})

    # 5. Human decides which suspect to open first (routing by a typed choice).
    choice = ctx.ask(
        "focus",
        {"prompt": "Failure kind=%s in %s. Suspects: %s. Open which first?"
                   % (kind, symbol, suspect_paths)},
        {"type": "string", "enum": suspect_paths} if suspect_paths else None,
        desc="pick the file to inspect")

    # 6. Inspect the chosen file.
    ctx.step("inspect", lambda: tools.read_region(choice), desc="read %s" % choice)

    # 7. Propose a fix — memoized (a real agent's analysis is expensive; never redo it on
    #    resume), then gate on human approval BEFORE any mutation.
    edit = ctx.step("propose", tools.propose_fix, desc="propose a fix for %s" % choice)
    approved = ctx.ask(
        "approve-fix",
        {"prompt": "Apply proposed fix (%s -> %s) to %s?"
                   % (edit.get("find", "?"), edit.get("replace", "?"), choice)},
        {"type": "boolean"},
        desc="approve the mutation")
    if not approved:
        return {"status": "reported", "kind": kind, "suspect": choice, "fix_applied": False}

    # 7. Apply the fix — NON-idempotent. A crash here escalates to in-doubt rather than
    #    silently re-editing the file.
    ctx.step("apply-fix", lambda idem: tools.apply_fix(choice, edit, idem),
             idempotent=False, desc="edit %s" % choice)

    # 8. Verify the fix.
    ver = ctx.step("verify", lambda: tools.run_tests("verify"), desc="re-run the tests")
    return {"status": "fixed" if ver["code"] == 0 else "fix-failed",
            "kind": kind, "suspect": choice, "fix_applied": True, "verify": ver}


if __name__ == "__main__":
    sys.exit(run_cli(investigate, observer=observer))
