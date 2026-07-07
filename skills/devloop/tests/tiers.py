#!/usr/bin/env python3
"""tiers.py — the staged test-tier dispatcher: ONE entry point for validation, fastest first.

No new framework. Reuses the existing suites/scripts + env-gates — the real-model tests already
self-skip unless DEVLOOP_RUN_REAL is set, so `fast` excludes them for free
(no pytest markers needed). Run in-container under uv (so pytest is importable):

  uv run --with pytest python3 tests/tiers.py fast      # ~10s  no LLM  deterministic logic + composition (THE general suite)
  uv run --with pytest python3 tests/tiers.py smoke     # ~1-2m 1 real  one tiny add(a,b) build end-to-end + corroborate
  uv run --with pytest python3 tests/tiers.py mutants   # ~25m  no LLM  OPTIONAL mutation guard (on demand; run detached)
  uv run --with pytest python3 tests/tiers.py spike     # ~5m   real    QUICK go-check (2 tasks x1: 1 modify + 1 vague)
  uv run --with pytest python3 tests/tiers.py spike-full # ~2-3h real   COMPREHENSIVE suite (12 tasks x3; on demand, detached)
  uv run --with pytest python3 tests/tiers.py all        # fast -> smoke (the general ladder; the rest stays opt-in)
  uv run --with pytest python3 tests/tiers.py full       # fast -> FULL mutation guard (the complete seal)
  uv run --with pytest python3 tests/tiers.py suite            # list the named validation groups
  uv run --with pytest python3 tests/tiers.py suite loop-spine # run ONE named group
  uv run --with pytest python3 tests/tiers.py suite loop-spine full # group tests + scoped mutants

Tiers escalate: cost + signal both grow. `fast` is the GENERAL suite (every change, pre-commit);
`smoke` is a quick "does the whole loop still work end-to-end" gut-check; `mutants` is an OPTIONAL
deep-verification tier run ON DEMAND (user decision 2026-07-01 — routine commits do NOT gate on it;
still REGISTER a killing mutant for every new fail-closed guard so an on-demand run can verify it);
`spike` is the QUICK real-engine go-check (user decision 2026-07-01: 1-2 cases, minutes);
`spike-full` is the comprehensive 12x3 suite — on demand, run DETACHED.

`suite <name>` slices `fast` into the named validation groups below (the test-suite INDEX);
append `full` to run that group's tests plus only its owned mutants. See TESTING.md for each
group's input -> expected-output contract.
"""
import os
import subprocess
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the devloop skill dir
_PYTEST = [sys.executable, "-m", "pytest", "-q"]
# the existing tiny single-task real e2e is the smoke (production v1 path: charter->...->judge->COMPLETE)
_SMOKE_TEST = "tests/test_e2e_real.py::test_e2e_real_v1_simple_task_completes"


def _run(cmd, env=None):
    full = dict(os.environ, **(env or {}))
    print(f"\n=== running: {' '.join(cmd)} {('(' + ','.join(env) + ')') if env else ''} ===", flush=True)
    return subprocess.run(cmd, cwd=_DIR, env=full).returncode


# Named validation groups (the test-suite INDEX): name -> (one-line description, test files).
# THE single source of truth for the group->file mapping — TESTING.md documents each group's
# input -> expected-output rows but deliberately repeats no file lists (no dual registry).
# test_smoke.py pins that these groups partition mutants.TEST_FILES exactly (drift guard).
SUITES = {
    "fail-closed-kernel": ("gates + DoD oracle + GO-bar: every refusal path that guards COMPLETE",
                           ("tests/test_smoke.py", "tests/test_gate.py", "tests/test_dod_oracle.py",
                            "tests/test_real_spike.py", "tests/test_mutants_registry.py")),
    "evidence-state":     ("real exit codes + state persistence honesty",
                           ("tests/test_evidence.py", "tests/test_state.py")),
    "design-oracle":      ("structured spec -> rendered pytest + real collection intersection",
                           ("tests/test_render.py", "tests/test_render_more.py",
                            "tests/test_testgen.py", "tests/test_testgen_more.py")),
    "loop-spine":         ("run_v1 mechanics: lint / frozen-tests / dispatch-error / back-off / trace",
                           ("tests/test_loop.py", "tests/test_loop_v1.py", "tests/test_loop_more.py",
                            "tests/test_loop_dispatch_error.py", "tests/test_lint.py",
                            "tests/test_lint_more.py", "tests/test_trace_view.py")),
    "runner-pipeline":    ("the per-task pipeline: charter -> gates -> design -> loop -> crash-finalize",
                           ("tests/test_runner.py", "tests/test_runner_more.py", "tests/test_e2e.py")),
    "worktree-merge":     ("branch isolation, finalize keep/remove semantics, fail-safe auto-merge",
                           ("tests/test_worktree.py", "tests/test_worktree_more.py")),
    "bridge-cli":         ("the pipeline seam + CLI: scratch-by-default, exit codes, fail-closed guard",
                           ("tests/test_bridge.py", "tests/test_cli.py")),
    "dispatch-seam":      ("the hermes-chat model boundary: argv contract, parse fail-close, majorities",
                           ("tests/test_dispatch.py", "tests/test_dispatch_more.py")),
    "outer-loop":         ("the project drain: bounded re-attempts, escalation, lessons, re-runnability",
                           ("tests/test_project.py", "tests/test_project_more.py")),
    "scout-pipeline":     ("relentless-solve as pathfinder: gated findings, discipline gates, exit contract",
                           ("tests/test_scout.py",)),
}

# Source files whose mutation guards belong to each validation group. test_smoke.py pins that
# these values partition the target-file column of mutants.MUTANTS exactly.
SOURCES: dict[str, tuple[str, ...]] = {
    "worktree-merge":    ("worktree.py",),
    "scout-pipeline":    ("scout.py", "scripts/devloop_pipeline_cli.py"),
    "bridge-cli":        ("devloop_bridge.py", "scripts/devloop_cli.py"),
    "dispatch-seam":     ("dispatch.py",),
    "loop-spine":        ("loop.py", "lint.py", "trace_view.py"),
    "fail-closed-kernel": ("gate.py", "dod_oracle.py", "spike/run_real_spike.py",
                           "spike/run_spike.py"),
    "evidence-state":    ("evidence.py", "state.py"),
    "design-oracle":     ("render.py", "testgen.py"),
    "runner-pipeline":   ("runner.py",),
    "outer-loop":        ("project.py",),
}


TIERS = {
    # deterministic logic + composition; the env-gated real tests self-skip with no DEVLOOP_RUN_REAL
    "fast":    lambda: _run([*_PYTEST, "tests/"]),
    # one tiny real build, end-to-end, independently corroborated
    "smoke":   lambda: _run([*_PYTEST, "-s", _SMOKE_TEST], env={"DEVLOOP_RUN_REAL": "1"}),
    # OPTIONAL mutation guard (on demand, run detached): every registered mutant must be KILLED
    "mutants": lambda: _run([sys.executable, "tests/mutants.py"]),
    # QUICK real-engine go-check: 1 modify task (full spine incl. frozen-tests + regression +
    # independent suite check) + 1 vague task (the safety side), 1 run each (~3-5 min)
    "spike":   lambda: _run([sys.executable, "spike/run_real_spike.py", "--tasks", "spike/tasks_quick.jsonl",
                             "--runs", "1", "--root", "/opt/data/devloop-spike-wts",
                             "--out", ".devloop/spike_quick.json", "--min-tasks", "2", "--min-runs", "1"]),
    # COMPREHENSIVE suite (on demand, run DETACHED — hours): 12 tasks x3 over the extended set
    "spike-full": lambda: _run([sys.executable, "spike/run_real_spike.py", "--tasks", "spike/tasks_extended.jsonl",
                                "--runs", "3", "--root", "/opt/data/devloop-spike-wts",
                                "--out", ".devloop/spike_ext.json"]),
}


def main(argv):
    tier = argv[1] if len(argv) > 1 else ""
    if tier == "suite":   # the test-suite index: list the groups, or run one by name
        name = argv[2] if len(argv) > 2 else ""
        if name in SUITES:
            tests_rc = _run([*_PYTEST, *SUITES[name][1]])
            if len(argv) > 3 and argv[3] == "full":
                sources = SOURCES.get(name, ())
                if not sources:
                    print(f"no scoped mutants for {name}")
                    return tests_rc
                mutants_rc = _run([sys.executable, "tests/mutants.py", "--files", *sources])
                return 1 if tests_rc != 0 or mutants_rc != 0 else 0
            return tests_rc
        print("validation groups (each supports smoke/default or full depth; contracts in TESTING.md):")
        for n, (desc, files) in SUITES.items():
            print(f"  {n:20} {desc}  [{len(files)} file(s)]")
        if name:
            print(f"\nunknown group {name!r}")
            return 2
        return 0
    if tier == "all":   # the general ladder (mutants + full stay opt-in / on demand)
        for t in ("fast", "smoke"):
            if TIERS[t]() != 0:
                print(f"\nTIER FAILED: {t}")
                return 1
        print("\nfast + smoke: all green")
        return 0
    if tier == "full":   # the complete deterministic seal
        if TIERS["fast"]() != 0:
            print("\nTIER FAILED: fast")
            return 1
        if TIERS["mutants"]() != 0:
            print("\nTIER FAILED: mutants")
            return 1
        print("\nfast + full mutation guard: all green")
        return 0
    if tier not in TIERS:
        print(f"usage: tiers.py [fast|smoke|mutants|spike|spike-full|all|full|suite [<group> [full]]]  (got {tier!r})")
        return 2
    return TIERS[tier]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
