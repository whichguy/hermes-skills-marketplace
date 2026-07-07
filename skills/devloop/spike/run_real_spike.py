#!/usr/bin/env python3
"""devloop REAL-engine spike harness — the proof that gates retiring legacy v5/v6.

The step-0 spike (run_spike.py) tested a *throwaway prose* loop to decide whether to bet on a
prose orchestrator vs a code-owned sequencer. That bet is SETTLED: we built the code-owned engine
(loop.run_v1 owns phase ordering in code + the trust kernel). So the proof that now matters is the
REAL engine over real tasks: does runner.run_task, driven by real models, produce the CORRECT
terminal on >=5 real tasks, >=2 runs each — COMPLETE on satisfiable work, HUMAN_REVIEW on
ambiguous/unsatisfiable work — and NEVER a false COMPLETE?

Unlike run_spike.py there is no marker-parsing: run_task returns a structured terminal, which IS
the signal. analyze()/evaluate_bar() are pure + unit-tested; run_one() is the only impure part
(injectable as run_task=... for deterministic tests).

Reuses the same tasks.jsonl format + bar constants as run_spike.py (decision 1):
  {"id","repo","request","touches":[...],"expect_human_review":bool}

Run inside the hermes container (real models; structured spec design is the only designer):
  tiers.py spike       — QUICK 2-case go-check (spike/tasks_quick.jsonl, ~5 min)
  tiers.py spike-full  — COMPREHENSIVE 12x3 suite (spike/tasks_extended.jsonl; detached, hours)
Exit 0 == GO; non-zero == NO-GO (safety bar: 0 false-completes).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# devloop kernel dir on sys.path so flat-module imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import runner  # noqa: E402
import worktree  # noqa: E402
from run_spike import load_tasks  # noqa: E402  (reuse the exact same task-file parser)

_TRACES_DIR = Path(".devloop/spike-traces")   # durable per-run traces (the debuggability artifact)


def run_one(task: dict, root: str, run_idx: int, *, run_task=runner.run_task, **run_task_kwargs) -> dict:
    """Drive ONE real run_task for `task` and capture its terminal. The only impure function here;
    injectable run_task keeps analyze/evaluate_bar testable without an LLM. A missing/placeholder
    repo or a raised dispatch error is recorded as a non-completing run (fails the bar, but is NOT a
    false-complete — the fail-closed invariant is about never COMPLETING wrongly, not never erroring).
    """
    base = {"task_id": task.get("id"), "run_idx": run_idx,
            "expect_human_review": bool(task.get("expect_human_review", False))}
    repo = task.get("repo", "")
    if "CHANGE_ME" in repo or not os.path.isdir(repo):
        return {**base, "terminal": "CONFIG_ERROR", "reason": f"repo not found / placeholder: {repo}"}
    name = f"{task['id']}-r{run_idx}"
    # Defensive PRE-CLEAN (idempotent reruns): a prior aborted/killed spike can leave this run's
    # worktree path, its git registration, or its devloop/<name> branch behind — `git worktree
    # add -b` fails on ANY of the three (exit 255; exactly how the first extended-spike launch
    # died on debris from the previous session). All three purges are spike-owned names.
    wt_path = os.path.join(root, name)
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt_path],
                   capture_output=True, text=True)
    shutil.rmtree(wt_path, ignore_errors=True)
    subprocess.run(["git", "-C", repo, "worktree", "prune"], capture_output=True, text=True)
    subprocess.run(["git", "-C", repo, "branch", "-D", f"devloop/{name}"],
                   capture_output=True, text=True)
    try:
        res = run_task(repo, task.get("request", ""), root, name, **run_task_kwargs)
    except Exception as e:   # noqa: BLE001 — a harness-level error is a failing (non-completing) run
        return {**base, "terminal": "ERROR", "reason": f"{type(e).__name__}: {e}"}
    result = res.get("result") or {}
    wt = res.get("worktree") or {}
    run = {**base, "terminal": result.get("terminal"), "reason": result.get("reason", "") or ""}

    # Preserve the trace BEFORE cleanup — spike JSONs used to keep only a ~120-char reason, so a
    # miss was undebuggable once the transient worktree was gone (deep review 2026-07-01).
    tp = result.get("trace_path")
    if tp and os.path.isfile(str(tp)):
        try:
            _TRACES_DIR.mkdir(parents=True, exist_ok=True)
            dest = _TRACES_DIR / f"{name}.trace.jsonl"
            shutil.copyfile(str(tp), dest)
            run["trace"] = str(dest)
        except OSError:
            pass

    # INDEPENDENT existing-suite check: a COMPLETE that breaks the repo's PRE-EXISTING tests is
    # shipped-wrong-code — analyze() counts it as a false_complete. This is the harness-side
    # belt-and-suspenders on the runtime regression gate (if that gate is absent/broken, THIS
    # catches it — the two must never share an implementation).
    suite = task.get("existing_suite") or []
    if run["terminal"] == "COMPLETE" and suite and wt.get("path"):
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", *suite],
                               cwd=wt["path"], capture_output=True, text=True, timeout=600)
            run["regression_red"] = r.returncode != 0
        except Exception:   # noqa: BLE001 — an unrunnable check FAILS CLOSED (counts as red)
            run["regression_red"] = True

    # Cleanup: spike worktrees/branches are noise (traces + the results JSON are the artifacts).
    if wt.get("path"):
        try:
            worktree.remove_worktree(wt.get("repo") or repo, wt["path"])
            if wt.get("branch"):
                subprocess.run(["git", "-C", wt.get("repo") or repo, "branch", "-D", wt["branch"]],
                               capture_output=True, text=True)
        except Exception:   # noqa: BLE001 — cleanup is best-effort
            pass
    return run


def analyze(run: dict) -> dict:
    """Score one real run against the bar. Pure over a captured run dict.

    correct := expect_human_review ? (HUMAN_REVIEW and not COMPLETE) : COMPLETE.
    false_complete := an expect_human_review task that reported COMPLETE — the CARDINAL fail-closed
    violation (a weak/ambiguous spec was falsely declared done). A false_complete always fails and
    always vetoes GO, independently of the per-run verdict.
    """
    terminal = run.get("terminal")
    expect_hr = bool(run.get("expect_human_review"))
    completed = terminal == "COMPLETE"
    human_review = terminal == "HUMAN_REVIEW"
    # BOTH false-complete shapes veto: an ambiguous task declared done, AND a COMPLETE that broke
    # the repo's pre-existing suite (regression_red — shipped wrong code).
    false_complete = (expect_hr and completed) or (completed and bool(run.get("regression_red")))
    correct = (human_review and not completed) if expect_hr else (completed and not run.get("regression_red"))
    return {
        **{k: run.get(k) for k in ("task_id", "run_idx", "expect_human_review", "terminal", "reason",
                                   "regression_red", "trace")},
        "false_complete": false_complete,
        "verdict": "pass" if (correct and not false_complete) else "fail",
    }


def evaluate_bar(results: list[dict], n_tasks: int,
                 min_tasks: int | None = None, min_runs: int | None = None) -> dict:
    """SAFETY-ONLY bar (user decision): GO iff ZERO false-completes (the correctness veto) AND the
    minimum spike coverage (defaults: >=SPIKE_MIN_TASKS tasks, >=SPIKE_RUNS_PER_TASK runs each;
    overridable so the QUICK 2-task suite gates on its own coverage). The autonomous-
    solve rate is reported INFORMATIONALLY, not gated — a satisfiable task that safely routes to
    HUMAN_REVIEW is not a correctness failure (no wrong code shipped), only a lower auto-solve rate."""
    min_tasks = config.SPIKE_MIN_TASKS if min_tasks is None else min_tasks
    min_runs = config.SPIKE_RUNS_PER_TASK if min_runs is None else min_runs
    runs_pass = bool(results) and all(r["verdict"] == "pass" for r in results)   # 100% auto-solve (info)
    no_false_completes = not any(r.get("false_complete") for r in results)       # the hard safety veto
    enough_tasks = n_tasks >= min_tasks
    runs_per_task: dict[str, int] = {}
    for r in results:
        runs_per_task[r["task_id"]] = runs_per_task.get(r["task_id"], 0) + 1
    enough_runs = bool(runs_per_task) and all(v >= min_runs for v in runs_per_task.values())
    # informational: how often a SATISFIABLE task auto-solved (COMPLETEd) vs safely routing to a human
    solvable = [r for r in results if not r.get("expect_human_review")]
    auto_solved = [r for r in solvable if r.get("terminal") == "COMPLETE"]
    auto_solve_rate = round(len(auto_solved) / len(solvable), 2) if solvable else None
    go = no_false_completes and enough_tasks and enough_runs
    return {
        "go": go,
        "decision": "PROCEED — retire legacy (safety bar: 0 false-completes)" if go else "DO NOT retire legacy yet",
        "n_tasks": n_tasks,
        "min_tasks": min_tasks,
        "runs_per_task": runs_per_task,
        "min_runs_per_task": min_runs,
        "no_false_completes": no_false_completes,       # the GO gate
        "auto_solve_rate": auto_solve_rate,             # informational
        "all_runs_pass": runs_pass,                     # informational (100% auto-solve)
        "false_completes": [r for r in results if r.get("false_complete")],
        "regression_reds": [(r.get("task_id"), r.get("run_idx")) for r in results
                            if r.get("regression_red")],   # informational (already inside the veto)
        "human_review_on_solvable": [(r.get("task_id"), r.get("run_idx")) for r in solvable
                                     if r.get("terminal") != "COMPLETE"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="devloop REAL-engine spike harness")
    ap.add_argument("--tasks", required=True, help="path to tasks.jsonl")
    ap.add_argument("--runs", type=int, default=config.SPIKE_RUNS_PER_TASK)
    ap.add_argument("--root", default=".devloop/spike-wts", help="worktree root for run_task")
    ap.add_argument("--out", default=".devloop/real_results.json")
    ap.add_argument("--min-tasks", type=int, default=None, help="coverage floor override (quick suite)")
    ap.add_argument("--min-runs", type=int, default=None, help="runs-per-task floor override (quick suite)")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    Path(args.root).mkdir(parents=True, exist_ok=True)
    results = []
    for task in tasks:
        for run_idx in range(args.runs):
            run = run_one(task, args.root, run_idx)
            results.append(analyze(run))
            print(json.dumps({k: results[-1].get(k) for k in ("task_id", "run_idx", "terminal", "verdict")}))

    verdict = evaluate_bar(results, n_tasks=len(tasks), min_tasks=args.min_tasks, min_runs=args.min_runs)
    out = {"results": results, "verdict": verdict}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
