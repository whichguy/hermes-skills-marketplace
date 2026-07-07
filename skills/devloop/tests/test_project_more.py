"""More deterministic tests for project.py — the project OUTER loop. NO LLM (run_task injected).

Each test KILLS a confirmed surviving mutant the base suite (tests/test_project.py) misses:
  1. _safe_changed's broad `except Exception` (a git CalledProcessError is NOT OSError) — telemetry
     diff errors must never abort the bounded drain.
  2. crash-recovery resets ONLY in_progress (a human-escalated `blocked` purpose must NOT revive).
  3/4. _render_report's undrained-pending warning and all-clear branches (operator completion view).
  5. _summarize's empty-attempts guard (an enqueued-but-unrun child must not IndexError the report).

Mirrors tests/test_project.py: flat-import header, a local make_fake, real state, the __main__ runner.
"""
import json
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import project   # noqa: E402
import state     # noqa: E402


def make_fake(script):
    """Fake run_task: pops (terminal, charter) from `script`, STICKING on the last entry (so a
    1-element script is a constant). Records {name, request}. The wt path is NOT created on disk,
    so the loop's _safe_changed returns [] (no git needed). Mirrors test_project.make_fake."""
    calls = []
    box = list(script)

    def fake(repo, request, root, name, **kw):
        calls.append({"name": name, "request": request})
        terminal, charter = box.pop(0) if len(box) > 1 else box[0]
        return {"result": {"terminal": terminal, "reason": ""},
                "worktree": {"path": os.path.join(root, name)}, "charter": charter}
    return fake, calls


def test_safe_changed_prefers_bridge_reported_files():
    """Pipeline steps arrive with the worktree finalized/REMOVED — the path diff is always
    empty, so lessons claimed "changed 0 file(s)" (information loss, review 2026-07-03).
    devloop_result.changed_files, when present, is the ground truth and must win.
    Mutant killed: bridge preference dropped."""
    with tempfile.TemporaryDirectory() as root:
        def fake(repo, request, root_, name, **kw):
            return {"result": {"terminal": "COMPLETE", "reason": ""},
                    "worktree": {},                       # already finalized/removed
                    "charter": {},
                    "devloop_result": {"changed_files": ["calc.py", "test_calc.py"]}}
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert out["items"][0]["attempts"][-1]["changed_files"] == ["calc.py", "test_calc.py"]
        assert "2 file(s): calc.py, test_calc.py" in out["report"]


def test_safe_changed_swallows_git_error_not_just_oserror():
    # _safe_changed wraps worktree.changed_files in a BROAD `except Exception` because git runs via
    # subprocess.run(check=True), which raises CalledProcessError (an Exception, NOT an OSError) on a
    # non-git/odd path. A per-task diff is telemetry — it must never abort the whole project drain.
    with tempfile.TemporaryDirectory() as root:
        def fake(repo, request, root_, name, **kw):
            # create a REAL dir so _safe_changed's os.path.isdir() passes -> it ENTERS the try block
            os.makedirs(os.path.join(root_, name), exist_ok=True)
            return {"result": {"terminal": "COMPLETE", "reason": ""},
                    "worktree": {"path": os.path.join(root_, name)}, "charter": {}}
        orig = project.worktree.changed_files
        project.worktree.changed_files = lambda p: (_ for _ in ()).throw(
            subprocess.CalledProcessError(128, "git"))           # NOT an OSError
        try:
            out = project.run_project("repo", root, ["do A"], run_task=fake)   # MUST NOT raise
        finally:
            project.worktree.changed_files = orig
        # the drain completed normally and the diff degraded to [] instead of crashing the loop
        assert out["achieved"] == ["p1"]
        assert out["items"][0]["attempts"][-1]["changed_files"] == []
        # under the `except OSError:` mutant the CalledProcessError escapes _safe_changed ->
        # run_project raises mid-drain -> this test errors out -> mutant killed.


def test_resume_does_not_revive_blocked_purpose():
    # crash-recovery resets ONLY in_progress (a half-run attempt) back to pending. A `blocked`
    # purpose was escalated to a human (ambiguity / cap exhaustion); re-running reproduces the block
    # and burns the cap, so resume must leave it blocked and NEVER re-attempt it.
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".devloop"))
        plan = {"schema_version": 1, "items": [
            {"id": "p1", "purpose": "amb", "status": "blocked", "attempt_n": 1, "parent_id": None,
             "blocked_reason": "ambiguity — which file?",
             "attempts": [{"name": "p1-a1", "terminal": "HUMAN_REVIEW", "changed_files": []}]}]}
        with open(os.path.join(root, ".devloop", "PLAN.json"), "w") as f:
            json.dump(plan, f)
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["amb"], run_task=fake)
        assert len(calls) == 0                              # blocked purpose NOT re-run (no cap burn)
        assert out["items"][0]["status"] == "blocked"
        assert out["blocked"] == ["p1"] and out["achieved"] == []
        # under the `!= "completed"` mutant: recovery resets blocked->pending -> _next_pending picks
        # it -> the fake runs (len(calls)==1) and the COMPLETE flips status to 'completed' -> killed.


def _write_plan(root, plan):
    os.makedirs(os.path.join(root, ".devloop"), exist_ok=True)
    with open(os.path.join(root, ".devloop", "PLAN.json"), "w") as f:
        json.dump(plan, f)


def _resume_item(purpose="do A", status="completed"):
    terminal = "COMPLETE" if status == "completed" else "in_progress"
    return {"id": "p1", "purpose": purpose, "status": status, "attempt_n": 1,
            "parent_id": None,
            "attempts": [{"name": "p1-a1", "terminal": terminal, "changed_files": []}]}


def test_resume_refuses_wrong_schema_version():
    with tempfile.TemporaryDirectory() as root:
        _write_plan(root, {"schema_version": 999, "items": [_resume_item()]})
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert calls == [] and out["blocked"] and out["achieved"] == []


def test_resume_refuses_bool_schema_version():
    with tempfile.TemporaryDirectory() as root:
        _write_plan(root, {"schema_version": True, "items": [_resume_item()]})
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert calls == [] and out["blocked"] and out["achieved"] == []


def test_resume_refuses_purpose_mismatch():
    with tempfile.TemporaryDirectory() as root:
        _write_plan(root, {"schema_version": 1, "items": [_resume_item("old purpose")]})
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["new purpose"], run_task=fake)
        assert calls == [] and out["blocked"] and out["achieved"] == []


def test_resume_refuses_empty_items_nonempty_purposes():
    with tempfile.TemporaryDirectory() as root:
        _write_plan(root, {"schema_version": 1, "items": []})
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert calls == [] and out["blocked"] and out["achieved"] == []


def test_resume_refuses_corrupt_file_not_reseed():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".devloop"))
        with open(os.path.join(root, ".devloop", "PLAN.json"), "w") as f:
            f.write("{not valid json")
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert calls == [] and out["blocked"] and out["achieved"] == []


def test_resume_still_works_on_purpose_match():
    with tempfile.TemporaryDirectory() as root:
        _write_plan(root, {"schema_version": 1,
                           "items": [_resume_item(status="in_progress")]})
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert len(calls) == 1 and calls[0]["name"].startswith("p1-")
        assert out["items"][0]["status"] == "completed" and out["achieved"] == ["p1"]


def test_render_report_warns_on_undrained_pending():
    # The report is the operator's only at-a-glance completion view (task #21). A partial/aborted
    # drain that still has pending purposes MUST surface the 'did not fully drain' warning, never
    # read as a clean run.
    rep = project._render_report(
        items=[{"id": "p1", "purpose": "x", "status": "pending", "attempts": []}],
        achieved=[], blocked=[], lessons=[])
    assert "did not fully drain" in rep
    assert "1 purpose(s) still pending" in rep              # under `if False:` neither line is emitted
    # CONTROL: a fully-drained report (no pending) must NOT carry the warning, proving the line is
    # gated on `pending`, not unconditional.
    rep2 = project._render_report(
        items=[{"id": "p1", "purpose": "x", "status": "completed",
                "attempts": [{"terminal": "COMPLETE", "changed_files": []}]}],
        achieved=[{"id": "p1", "purpose": "x",
                   "attempts": [{"terminal": "COMPLETE", "changed_files": []}]}],
        blocked=[], lessons=[])
    assert "did not fully drain" not in rep2


def test_render_report_all_clear_only_when_nothing_outstanding():
    # 'all purposes resolved; nothing outstanding' is a completion all-clear; emitting it while a
    # purpose is blocked is a fail-OPEN signal to the operator, contradicting the loop's fail-closed
    # posture.
    blk = [{"id": "p1", "purpose": "x", "status": "blocked", "blocked_reason": "cap",
            "attempts": [{"terminal": "NO_TERMINATION", "changed_files": []}]}]
    rep = project._render_report(items=blk, achieved=[], blocked=blk, lessons=[])
    assert "all purposes resolved" not in rep              # under `if True:` it is wrongly appended
    assert "BLOCKED" in rep                                # the blocked purpose IS reported
    # CONTROL: with nothing blocked/pending the all-clear line MUST appear (guards a constant test).
    rep2 = project._render_report(
        items=[{"id": "p1", "purpose": "x", "status": "completed",
                "attempts": [{"terminal": "COMPLETE", "changed_files": []}]}],
        achieved=[{"id": "p1", "purpose": "x",
                   "attempts": [{"terminal": "COMPLETE", "changed_files": []}]}],
        blocked=[], lessons=[])
    assert "all purposes resolved" in rep2


def test_summarize_tolerates_item_with_no_attempts():
    # The `it["attempts"] and` short-circuit in the achieved computation defends the end-of-project
    # summary against an enqueued-but-unrun re-attempt child (created with attempts=[]). Dropping it
    # makes it["attempts"][-1] IndexError and crash _summarize.
    with tempfile.TemporaryDirectory() as root:
        plan = {"schema_version": 1, "items": [
            {"id": "p1", "purpose": "x", "status": "completed", "attempt_n": 1, "parent_id": None,
             "attempts": [{"name": "p1-a1", "terminal": "COMPLETE", "changed_files": []}]},
            {"id": "p2", "parent_id": "p1", "purpose": "retry", "status": "pending",
             "attempt_n": 2, "attempts": []}]}                 # <-- no attempts yet
        out = project._summarize(plan, root, os.path.join(root, ".devloop", "LESSONS.jsonl"), 20)
        assert out["achieved"] == ["p1"]                       # p1 counted, p2 (empty) skipped safely
        assert out["blocked"] == []
        # under the dropped-guard mutant, p2's it["attempts"][-1] raises IndexError -> killed.


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} project tests passed")
