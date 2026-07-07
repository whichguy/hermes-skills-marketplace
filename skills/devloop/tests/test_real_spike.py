"""Deterministic tests for the REAL-engine spike harness (spike/run_real_spike.py).

The pure scorers (analyze, evaluate_bar) + the impure run_one with an INJECTED fake run_task — no
LLM, no git. The cardinal property under test: an expect_human_review task that reports COMPLETE is
a `false_complete` that fails its run AND vetoes GO (fail-closed), independent of every other run.
"""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "spike"))

import config        # noqa: E402
import run_real_spike as rs   # noqa: E402


def _runs(*specs):
    """specs: (expect_hr, terminal) -> analyzed run dicts across distinct task_ids."""
    return [rs.analyze({"task_id": f"t{i}", "run_idx": 0,
                        "expect_human_review": ehr, "terminal": term, "reason": ""})
            for i, (ehr, term) in enumerate(specs, 1)]


def test_analyze_complete_task_passes_on_complete():
    a = rs.analyze({"task_id": "t1", "run_idx": 0, "expect_human_review": False, "terminal": "COMPLETE"})
    assert a["verdict"] == "pass" and a["false_complete"] is False


def test_analyze_complete_task_fails_on_human_review():
    a = rs.analyze({"task_id": "t1", "run_idx": 0, "expect_human_review": False, "terminal": "HUMAN_REVIEW"})
    assert a["verdict"] == "fail"          # a satisfiable task that didn't complete is a fail
    assert a["false_complete"] is False    # but NOT a false-complete (it didn't wrongly claim done)


def test_analyze_ambiguous_task_passes_on_human_review():
    a = rs.analyze({"task_id": "t4", "run_idx": 0, "expect_human_review": True, "terminal": "HUMAN_REVIEW"})
    assert a["verdict"] == "pass" and a["false_complete"] is False


def test_analyze_ambiguous_task_false_complete_is_cardinal_fail():
    a = rs.analyze({"task_id": "t4", "run_idx": 0, "expect_human_review": True, "terminal": "COMPLETE"})
    assert a["verdict"] == "fail" and a["false_complete"] is True   # the fail-closed violation


def test_evaluate_bar_go_on_clean_full_run():
    # 5 tasks x 2 runs, all correct (4 satisfiable COMPLETE + 1 ambiguous HUMAN_REVIEW)
    specs = [(False, "COMPLETE")] * 4 + [(True, "HUMAN_REVIEW")]
    results = []
    for ehr, term in specs:
        results += _runs((ehr, term), (ehr, term))      # 2 runs each, distinct task_ids per pair
    # give each pair a shared task_id so the runs-per-task check sees 2 each
    for i in range(0, len(results), 2):
        results[i]["task_id"] = results[i + 1]["task_id"] = f"task{i}"
    bar = rs.evaluate_bar(results, n_tasks=5)
    assert bar["go"] is True and bar["no_false_completes"] is True


def test_evaluate_bar_false_complete_vetoes_go():
    results = _runs((False, "COMPLETE"), (True, "COMPLETE"))   # second is a false-complete
    # even pretend the counts are fine:
    results[0]["task_id"] = "a"; results[1]["task_id"] = "b"
    bar = rs.evaluate_bar(results + _runs((False, "COMPLETE"), (True, "COMPLETE")), n_tasks=5)
    assert bar["no_false_completes"] is False and bar["go"] is False


def test_evaluate_bar_no_go_on_too_few_tasks():
    specs = [(False, "COMPLETE")]
    results = _runs(*specs, *specs)
    results[0]["task_id"] = results[1]["task_id"] = "only"
    bar = rs.evaluate_bar(results, n_tasks=1)              # < SPIKE_MIN_TASKS
    assert bar["go"] is False


def test_evaluate_bar_no_go_on_too_few_runs():
    # 5 tasks but only 1 run each (< SPIKE_RUNS_PER_TASK)
    results = _runs(*[(False, "COMPLETE")] * 5)
    bar = rs.evaluate_bar(results, n_tasks=5)
    assert bar["go"] is False                              # enough_runs fails


def test_run_one_placeholder_repo_is_config_error_not_crash():
    out = rs.run_one({"id": "t1", "repo": "/opt/data/projects/CHANGE_ME", "request": "x"}, "/tmp/wts", 0)
    assert out["terminal"] == "CONFIG_ERROR" and "placeholder" in out["reason"]
    assert rs.analyze(out)["verdict"] == "fail" and rs.analyze(out)["false_complete"] is False


def test_run_one_uses_injected_run_task_and_reads_terminal():
    captured = {}

    def fake_run_task(repo, request, root, name, **kw):
        captured.update(repo=repo, request=request, name=name)
        return {"result": {"terminal": "COMPLETE", "reason": "ok"}, "worktree": {}, "charter": {}}

    out = rs.run_one({"id": "t9", "repo": _DIR, "request": "do x", "expect_human_review": False},
                     "/tmp/wts", 1, run_task=fake_run_task)
    assert out["terminal"] == "COMPLETE" and captured["name"] == "t9-r1" and captured["request"] == "do x"


def test_run_one_swallows_dispatch_error_as_failing_run():
    def boom(*a, **k):
        raise RuntimeError("model collision")
    out = rs.run_one({"id": "t1", "repo": _DIR, "request": "x"}, "/tmp/wts", 0, run_task=boom)
    assert out["terminal"] == "ERROR" and "model collision" in out["reason"]
    assert rs.analyze(out)["false_complete"] is False     # an error is never a false-complete


def test_analyze_regression_red_complete_is_false_complete():
    # NEW (deep review 2026-07-01): a COMPLETE that broke the repo's PRE-EXISTING suite is
    # shipped-wrong-code — the second false-complete shape, vetoing GO exactly like an
    # ambiguous-task COMPLETE. Mutant killed: the `or (completed and regression_red)` half dropped.
    red = rs.analyze({"task_id": "t", "run_idx": 0, "expect_human_review": False,
                      "terminal": "COMPLETE", "reason": "", "regression_red": True})
    assert red["false_complete"] is True and red["verdict"] == "fail"
    green = rs.analyze({"task_id": "t", "run_idx": 0, "expect_human_review": False,
                        "terminal": "COMPLETE", "reason": "", "regression_red": False})
    assert green["false_complete"] is False and green["verdict"] == "pass"   # control


def test_evaluate_bar_vetoes_go_on_regression_red():
    # end-to-end through the bar: one regression-red COMPLETE among otherwise-perfect runs -> NO GO.
    runs = _runs(*[(False, "COMPLETE")] * (config.SPIKE_MIN_TASKS * config.SPIKE_RUNS_PER_TASK))
    # rebuild with proper per-task run counts, then poison one run with regression_red
    runs = [rs.analyze({"task_id": f"t{i}", "run_idx": r, "expect_human_review": False,
                        "terminal": "COMPLETE", "reason": ""})
            for i in range(1, config.SPIKE_MIN_TASKS + 1) for r in range(config.SPIKE_RUNS_PER_TASK)]
    poisoned = rs.analyze({"task_id": "t1", "run_idx": 0, "expect_human_review": False,
                           "terminal": "COMPLETE", "reason": "", "regression_red": True})
    runs[0] = poisoned
    verdict = rs.evaluate_bar(runs, n_tasks=config.SPIKE_MIN_TASKS)
    assert verdict["go"] is False
    assert ("t1", 0) in verdict["regression_reds"]



def test_run_one_precleans_stale_worktree_and_branch():
    # Idempotent reruns: a prior aborted spike leaves the run's worktree path/registration/branch
    # behind; run_one must pre-clean all three so `git worktree add -b` succeeds on the rerun.
    import subprocess
    import tempfile
    import worktree as wtmod

    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(repo)
        for a in (["init", "-q"], ["config", "user.email", "x@y"], ["config", "user.name", "x"]):
            subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
        open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)
        root = os.path.join(d, "wts")
        # simulate the debris of an aborted run: a live worktree + branch under this run's name
        wtmod.create_worktree(repo, "tX-r0", root)

        def fake_run_task(repo_, request, root_, name, **kw):
            wt = wtmod.create_worktree(repo_, name, root_)     # raises on ANY leftover collision
            return {"result": {"terminal": "HUMAN_REVIEW", "reason": "ok", "trace_path": None},
                    "worktree": wt, "charter": {}}

        run = rs.run_one({"id": "tX", "repo": repo, "request": "x", "expect_human_review": True},
                         root, 0, run_task=fake_run_task)
        assert run["terminal"] == "HUMAN_REVIEW", run          # NOT ERROR — debris pre-cleaned


def test_evaluate_bar_min_overrides_enable_quick_suite():
    # The QUICK suite (2 tasks x1) gates on ITS OWN coverage floors via the overrides; the
    # config defaults still apply when no override is given (the comprehensive suite's bar).
    runs = [rs.analyze({"task_id": "q1", "run_idx": 0, "expect_human_review": False,
                        "terminal": "COMPLETE", "reason": ""}),
            rs.analyze({"task_id": "q2", "run_idx": 0, "expect_human_review": True,
                        "terminal": "HUMAN_REVIEW", "reason": ""})]
    quick = rs.evaluate_bar(runs, n_tasks=2, min_tasks=2, min_runs=1)
    assert quick["go"] is True and quick["min_tasks"] == 2 and quick["min_runs_per_task"] == 1
    full_bar = rs.evaluate_bar(runs, n_tasks=2)                    # defaults -> config floors
    assert full_bar["go"] is False                                 # 2 tasks x1 < the full bar

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} real-spike tests passed")
