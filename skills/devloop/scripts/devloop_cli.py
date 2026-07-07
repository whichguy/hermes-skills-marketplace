#!/usr/bin/env python3
"""devloop_cli — THE prompt-callable entrypoint for the devloop engine.

    devloop_cli.py "<request>" [--repo PATH] [--keep-branch] [--debug-code STR] [--error STR]
                   [--json] [--timeout N]

Runs the WHOLE loop (charter -> gates -> tests -> implement -> judges/evidence/regression) and,
on COMPLETE, AUTO-MERGES the work into the target repo's current branch (user decision
2026-07-01). No --repo = a fresh scratch workspace under the write-safe root is the deliverable.

Correctness properties this thin layer OWNS (mutant-pinned):
  * NEVER implicit cwd: without --repo the bridge gets the SCRATCH sentinel — the legacy
    cwd-if-git fallback (which could target the ~/.hermes DATA repo from an agent session)
    cannot fire from here.
  * Exit code 0 IFF the run really COMPLETEd, error-free, AND the outcome you asked for happened:
    the auto-merge landed the code, or (--keep-branch) the verified branch was actually kept —
    anything else exiting 0 would be a false-complete at the shell boundary. 2 = needs-your-input
    / a validation refusal; 1 = failure (incl. COMPLETE whose merge degraded to branch-for-review).

Invocation: `devloop` (shim on the container PATH) or
`python3 ${HERMES_HOME}/skills/software-development/devloop/scripts/devloop_cli.py ...`.
"""
from __future__ import annotations

import argparse
import json as _json
import os
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEVLOOP_DIR = os.path.dirname(_THIS_DIR)


def _bridge():
    if _DEVLOOP_DIR not in sys.path:
        sys.path.insert(0, _DEVLOOP_DIR)
    import devloop_bridge
    return devloop_bridge


def _validate_repo(path: str, write_safe: str) -> tuple[str | None, str | None]:
    """(realpath, None) for a usable target repo, else (None, refusal-reason). Refuses the
    write-safe root ITSELF (the Hermes data repo); subdirectories are allowed — re-running
    against a prior greenfield workspace is the supported iteration flow."""
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        return None, f"--repo {path}: not a directory"
    if os.path.realpath(write_safe) == real:
        return None, (f"--repo {path}: refusing to target the write-safe root itself "
                      "(the Hermes data repo). Point at a project repo, or omit --repo "
                      "for a fresh scratch workspace.")
    r = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    top = os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    if top is None:
        return None, (f"--repo {path}: not a git repository. Omit --repo to build in a fresh "
                      "scratch workspace, or git-init the target first.")
    if top != real:
        # git's upward walk found an ENCLOSING repo (e.g. a plain dir inside the ~/.hermes data
        # repo) — targeting that would cut devloop branches off the wrong repository.
        return None, (f"--repo {path}: not a git repo itself (it sits inside {top}). "
                      "git-init the target, or pass the actual repo root.")
    return real, None


def _rerun_line(args) -> str:
    """A copy-pasteable continuation for a NEEDS-INPUT outcome: every invoke is fresh by design,
    so 'answering' = re-running with the answers folded into the request."""
    repo = f" --repo {args.repo}" if args.repo else ""
    return f'devloop "{args.request} — ANSWERS: <fill in>"{repo}'


def main(argv=None, *, bridge=None) -> int:
    ap = argparse.ArgumentParser(
        prog="devloop",
        description="Run the devloop autonomous build/debug loop on a request.")
    ap.add_argument("request", help="what to build/fix (plain English; name files/behaviors)")
    ap.add_argument("--repo", default=None,
                    help="target git repo to MODIFY; omit for a fresh scratch workspace")
    ap.add_argument("--debug-code", default=None, help="failing code (switches to the debug form)")
    ap.add_argument("--error", default=None, help="error/failure text (debug form)")
    ap.add_argument("--keep-branch", action="store_true",
                    help="on COMPLETE, keep the verified devloop/<name> branch instead of "
                         "auto-merging (PR-style workflows; the merge command is printed)")
    ap.add_argument("--json", action="store_true", help="print the raw result dict as JSON")
    ap.add_argument("--timeout", type=int, default=None,
                    help="RAISE-only per-model-call ceiling in seconds (never lowers the floor)")
    args = ap.parse_args(argv)

    br = bridge or _bridge()

    if args.repo:
        repo, refusal = _validate_repo(args.repo, br._WRITE_SAFE)
        if refusal:
            print(refusal, file=sys.stderr)
            return 2
    else:
        repo = br.SCRATCH          # NEVER implicit cwd (mutant-pinned)

    if args.debug_code or args.error:
        res = br.call_guarded(br.run_debug, args.request, code=args.debug_code,
                              error_feedback=args.error, timeout=args.timeout, repo=repo,
                              keep_branch=args.keep_branch)
    else:
        res = br.call_guarded(br.run_build, args.request, timeout=args.timeout, repo=repo,
                              keep_branch=args.keep_branch)

    dr = res.get("devloop_result") or {}
    if args.json:
        print(_json.dumps(res, indent=2, default=str))
    else:
        print(res.get("content") or "(no content)")
        if dr.get("needs_human"):
            print("\nanswer + re-run:\n  " + _rerun_line(args))

    # Exit-code contract (a correctness guarantee — see module docstring): 0 means the outcome
    # you asked for HAPPENED — gate-verified COMPLETE and the code either merged (default) or
    # sits on its kept branch (--keep-branch). A COMPLETE whose auto-merge degraded to
    # branch-for-review exits 1 — the branch pointer is in the output. --keep-branch with no
    # branch actually kept (no artifact) is likewise 1, never a hollow 0.
    if res.get("error") is None and dr.get("terminal") == "COMPLETE" and (
            dr.get("merged") or (args.keep_branch and dr.get("kept_branch"))):
        return 0
    if dr.get("needs_human"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
