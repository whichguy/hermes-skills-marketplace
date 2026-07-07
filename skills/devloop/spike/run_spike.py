#!/usr/bin/env python3
"""devloop step-0 spike harness.

Drives a throwaway prose CHARTER->PLAN->BUILD->VERIFY loop on the native Hermes runtime
across real multi-file tasks, captures a phase trace per run, and evaluates the locked
acceptance bar (see spike/README.md). Emits a go/no-go verdict for the deletion path.

The ONLY thing to wire (step 0) is `run_one()` -> a real `hermes chat -q` call. Everything
else (trace analysis, bar evaluation, reporting) is implemented and testable now.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# devloop kernel dir on sys.path so `import config` works (flat-module convention)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

CANONICAL_PHASES = ["CHARTER", "PLAN", "BUILD", "VERIFY"]

# In-container hermes binary (same default as productivity/ask model_utils). Override with HERMES_BIN.
HERMES_BIN = os.environ.get("HERMES_BIN", "/opt/hermes/bin/hermes")
# Orchestration model for the spike (the loop-driver). Override with DEVLOOP_SPIKE_MODEL.
SPIKE_MODEL = os.environ.get("DEVLOOP_SPIKE_MODEL", "glm-5.2:cloud")
_SPIKE_SKILL = Path(__file__).resolve().parent / "spike_skill.md"
_MARK = r"\[DEVLOOP-SPIKE\]"


def load_tasks(path: str) -> list[dict]:
    tasks = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tasks.append(json.loads(line))
    return tasks


def build_spike_prompt(task: dict) -> str:
    """The throwaway spike skill prose + the task request."""
    skill = _SPIKE_SKILL.read_text()
    req = task.get("request", "")
    touches = task.get("touches") or []
    repo = task.get("repo", "")
    suffix = f"\nRepo: {repo}\nLikely files: {', '.join(touches) if touches else '(unspecified)'}\nRequest: {req}\n"
    return skill + suffix


def parse_spike_output(stdout: str) -> dict:
    """Parse the [DEVLOOP-SPIKE] markers into the run schema. Deterministic + unit-tested.
    Fail-closed: evidence_all_green is True only on an explicit `evidence_green=true` STOP."""
    phase_trace: list[str] = []
    reported_complete = False
    evidence_green = False
    entered_hr = False
    for line in (stdout or "").splitlines():
        line = line.strip()
        m = re.search(_MARK + r"\s*PHASE=(\w+)", line)
        if m:
            phase_trace.append(m.group(1).upper())
            continue
        if re.search(_MARK + r"\s*(HUMAN_REVIEW|DECISION=ROUTE_HUMAN_REVIEW)", line):
            entered_hr = True
            continue
        if re.search(_MARK + r"\s*STOP=COMPLETE\b", line):
            reported_complete = True
            if re.search(r"evidence_green\s*=\s*true", line, re.IGNORECASE):
                evidence_green = True
    return {
        "phase_trace": phase_trace,
        "reported_complete": reported_complete,
        "evidence_all_green": evidence_green,
        "entered_human_review": entered_hr,
    }


def run_one(task: dict, model: str = SPIKE_MODEL, timeout: int = 1800,
            dry_run: bool = False) -> dict:
    """Drive ONE spike run of the prose loop on the native Hermes runtime, then parse its
    emitted phase markers. Runs the throwaway spike skill with a STUBBED evidence gate.

    Must run where HERMES_BIN exists (inside the hermes container, or set HERMES_BIN).
    """
    prompt = build_spike_prompt(task)
    cmd = [HERMES_BIN, "chat", "-q", prompt, "-m", model, "-Q", "--yolo", "-t", "file,terminal"]
    if dry_run:
        return {"_dry_run": True, "cmd": cmd[:2] + ["-m", model, "<prompt:%d chars>" % len(prompt)]}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
    except FileNotFoundError:
        raise SystemExit(
            f"hermes binary not found at {HERMES_BIN}. Run inside the hermes container or set HERMES_BIN.")
    except subprocess.TimeoutExpired:
        # Timeout = the loop did not terminate; record as a non-completing run (will fail the bar).
        return {"phase_trace": [], "reported_complete": False, "evidence_all_green": False,
                "entered_human_review": False, "notes": f"timeout after {timeout}s", "raw": ""}
    parsed = parse_spike_output(out)
    parsed["notes"] = f"exit={r.returncode}"
    parsed["raw"] = out  # full transcript for iterative review (analyze() ignores it)
    return parsed


def analyze(run: dict) -> dict:
    """Evaluate one run against the acceptance bar. Pure function over a captured trace."""
    trace = run.get("phase_trace", [])
    seen = [p for p in trace if p in CANONICAL_PHASES]
    expected = [p for p in CANONICAL_PHASES if p in seen]
    # wandering = any out-of-order visit (first-occurrence order != canonical order).
    # Non-consecutive repeats (legit re-BUILD/re-VERIFY iterations) are NOT wandering.
    wandered = _first_occurrence_order(seen) != expected

    reported_complete = bool(run.get("reported_complete"))
    evidence_green = bool(run.get("evidence_all_green"))
    entered_hr = bool(run.get("entered_human_review"))

    # gated stop honored: never COMPLETE without all evidence green.
    gated_stop_ok = (not reported_complete) or evidence_green
    # if the task expected HUMAN_REVIEW, it must have entered it and NOT reported complete.
    hr_ok = (not run.get("expect_human_review")) or (entered_hr and not reported_complete)

    # A legitimate early HUMAN_REVIEW exit (e.g. after CHARTER) is NOT a phase-skip: require
    # the full 4-phase walk only for runs that did NOT correctly route to human review.
    early_human_exit = entered_hr and hr_ok and not reported_complete
    skips = [] if early_human_exit else [p for p in CANONICAL_PHASES if p not in seen]

    passed = (len(skips) <= config.SPIKE_MAX_PHASE_SKIPS) and (not wandered) and gated_stop_ok and hr_ok
    return {
        **{k: run.get(k) for k in ("task_id", "run_idx")},
        "phase_skips": skips,
        "wandered": wandered,
        "gated_stop_ok": gated_stop_ok,
        "human_review_ok": hr_ok,
        "early_human_exit": early_human_exit,
        "verdict": "pass" if passed else "fail",
    }


def _first_occurrence_order(xs: list[str]) -> list[str]:
    seen: list[str] = []
    for x in xs:
        if x not in seen:
            seen.append(x)
    return seen


def evaluate_bar(results: list[dict], n_tasks: int) -> dict:
    """Apply locked decision 1: >=5 tasks, >=2 runs each, 0 phase-skips/wandering, gated stop."""
    runs_pass = all(r["verdict"] == "pass" for r in results)
    enough_tasks = n_tasks >= config.SPIKE_MIN_TASKS
    runs_per_task: dict[str, int] = {}
    for r in results:
        runs_per_task[r["task_id"]] = runs_per_task.get(r["task_id"], 0) + 1
    enough_runs = all(v >= config.SPIKE_RUNS_PER_TASK for v in runs_per_task.values()) and bool(runs_per_task)
    go = runs_pass and enough_tasks and enough_runs
    return {
        "go": go,
        "decision": "PROCEED with deletion path" if go else "FALL BACK to thin ~300-LOC sequencer",
        "n_tasks": n_tasks,
        "min_tasks": config.SPIKE_MIN_TASKS,
        "runs_per_task": runs_per_task,
        "min_runs_per_task": config.SPIKE_RUNS_PER_TASK,
        "all_runs_pass": runs_pass,
        "failing_runs": [r for r in results if r["verdict"] != "pass"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="devloop step-0 spike harness")
    ap.add_argument("--tasks", required=True, help="path to tasks.jsonl")
    ap.add_argument("--runs", type=int, default=config.SPIKE_RUNS_PER_TASK)
    ap.add_argument("--model", default=SPIKE_MODEL, help="orchestration model for the spike loop")
    ap.add_argument("--out", default=".devloop/results.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the hermes command for each task without executing")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    if args.dry_run:
        for task in tasks:
            print(json.dumps(run_one(task, model=args.model, dry_run=True)))
        return 0

    results = []
    for task in tasks:
        for run_idx in range(args.runs):
            run = run_one(task, model=args.model)
            run.setdefault("task_id", task.get("id"))
            run.setdefault("run_idx", run_idx)
            run.setdefault("expect_human_review", task.get("expect_human_review", False))
            results.append(analyze(run))

    verdict = evaluate_bar(results, n_tasks=len(tasks))
    out = {"results": results, "verdict": verdict}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
