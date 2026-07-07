#!/usr/bin/env python3
"""devloop_pipeline_cli — the SCOUT -> BUILD pipeline entrypoint.

    devloop_pipeline_cli.py "<goal>" --repo PATH [--scout-only] [--fresh]
                            [--max-cycles N] [--wallclock SECS] [--plan-timeout SECS]
                            [--task-timeout SECS] [--json]

relentless-solve scouts the happy path READ-ONLY (cheap, resumable, information-producing)
and returns ordered steps with success criteria; each step then runs through the verified
devloop (charter -> oracle tests -> judges -> implement -> evidence -> audits -> merge).
See scout.py's module docstring for the architecture verdict this encodes.

Exit-code contract (a correctness guarantee, mutant-pinned): 0 means the outcome you asked
for HAPPENED — every scouted step built AND merged, or a clean informational stop
(--scout-only, or an honest concluded "no viable path"). 1 = the build fell short (blocked/
pending steps, or the scout couldn't conclude — its partial finding is in the report).
2 = usage / scout failure (nothing trustworthy produced).

Invocation (in-container): python3 ${HERMES_HOME}/skills/software-development/devloop/scripts/devloop_pipeline_cli.py ...
"""
from __future__ import annotations

import argparse
import json as _json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEVLOOP_DIR = os.path.dirname(_THIS_DIR)


def _mods():
    if _DEVLOOP_DIR not in sys.path:
        sys.path.insert(0, _DEVLOOP_DIR)
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    import devloop_bridge
    import devloop_cli
    import scout
    return scout, devloop_cli, devloop_bridge


def main(argv=None, *, pipeline=None, validate=None, write_safe=None) -> int:
    ap = argparse.ArgumentParser(
        prog="devloop-pipeline",
        description="Scout the happy path with relentless-solve, then build each step "
                    "through the verified devloop.")
    ap.add_argument("request", help="the goal (plain English; the scout turns it into steps)")
    ap.add_argument("--repo", required=True,
                    help="target git repo to scout and MODIFY (required — a scout needs "
                         "something to investigate)")
    ap.add_argument("--scout-only", action="store_true",
                    help="stop after the scout: print the step list, build nothing")
    ap.add_argument("--fresh", action="store_true",
                    help="discard the prior scout AND drain state for this request (default: "
                         "an identical request against the same repo RESUMES both)")
    ap.add_argument("--max-cycles", type=int, default=None, help="scout clarify/plan cycles")
    ap.add_argument("--wallclock", type=int, default=None,
                    help="RAISE-only scout wall-clock budget in seconds")
    ap.add_argument("--plan-timeout", type=int, default=None,
                    help="RAISE-only per-plan-call ceiling passed through to the scout")
    ap.add_argument("--task-timeout", type=int, default=None,
                    help="RAISE-only per-task ceiling passed through to the scout")
    ap.add_argument("--json", action="store_true", help="print the raw result dict as JSON")
    args = ap.parse_args(argv)

    if pipeline is None or validate is None or write_safe is None:
        scout_mod, cli_mod, bridge_mod = _mods()
        pipeline = pipeline or scout_mod.run_pipeline
        validate = validate or cli_mod._validate_repo
        write_safe = write_safe or bridge_mod._WRITE_SAFE
        defaults = (scout_mod.DEFAULT_MAX_CYCLES, scout_mod.DEFAULT_WALLCLOCK_S)
    else:
        defaults = (3, 1800)

    repo, refusal = validate(args.repo, write_safe)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    # `is not None`, not `or`: an explicit 0 is the user's value, never "unset"
    res = pipeline(repo, args.request, scout_only=args.scout_only, fresh=args.fresh,
                   max_cycles=args.max_cycles if args.max_cycles is not None else defaults[0],
                   wallclock=args.wallclock if args.wallclock is not None else defaults[1],
                   plan_timeout=args.plan_timeout, task_timeout=args.task_timeout)

    if args.json:
        print(_json.dumps(res, indent=2, default=str))
    else:
        print(res.get("report") or "(no report)")

    # Exit-code contract (see module docstring). "Drained clean" = no blocked items and no
    # pending leftovers — with project.py's bounded-drain guarantee that means every scouted
    # step's lineage ended in a verified, MERGED devloop COMPLETE.
    sc = res.get("scout") or {}
    if not sc.get("ok"):
        return 2
    if not res.get("built"):
        # informational stops: --scout-only and a CONCLUDED no-path are the asked-for
        # outcome (0); an unconcluded scout is not — its finding needs a human (1)
        return 1 if sc.get("unconcluded") else 0
    proj = res.get("project") or {}
    items = proj.get("items") or []
    drained = bool(items) and not proj.get("blocked") and all(it.get("status") == "completed" for it in items)
    return 0 if drained else 1


if __name__ == "__main__":
    raise SystemExit(main())
