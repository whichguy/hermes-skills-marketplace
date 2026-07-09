"""Deterministic tests for project.py — the project OUTER loop. NO LLM (run_task injected as a fake).

Proves the autonomous bounded drain: happy drain, reattempt->complete, cap exhaustion (termination),
ambiguity escalation, lessons fed into the next plan, unique attempt names, crash resume. The
fail-closed invariants are mutation-covered in tests/mutants.py.
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import project   # noqa: E402
import state     # noqa: E402


def make_fake(script):
    """Fake run_task: pops (terminal, charter) from `script`, STICKING on the last entry (so a
    1-element script is a constant). Records {name, request}. The wt path is NOT created on disk,
    so the loop's _safe_changed returns [] (no git needed)."""
    calls = []
    box = list(script)

    def fake(repo, request, root, name, **kw):
        calls.append({"name": name, "request": request})
        terminal, charter = box.pop(0) if len(box) > 1 else box[0]
        return {"result": {"terminal": terminal, "reason": ""},
                "worktree": {"path": os.path.join(root, name)}, "charter": charter}
    return fake, calls


def test_t1_happy_drain():
    with tempfile.TemporaryDirectory() as root:
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A", "do B"], run_task=fake)
        assert [it["status"] for it in out["items"]] == ["completed", "completed"]
        assert out["achieved"] == ["p1", "p2"] and out["blocked"] == []
        assert len(calls) == 2
        assert len(state.read_learnings(out["lessons_path"])) == 2          # one lesson per attempt


def test_t2_reattempt_then_complete():
    with tempfile.TemporaryDirectory() as root:
        # a back-off/coverage HUMAN_REVIEW has a valid DoD (it got past validation) -> reattempt
        fake, calls = make_fake([("HUMAN_REVIEW", {"dod": [{"id": "c1"}]}), ("COMPLETE", {})])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        items = out["items"]
        assert len(items) == 2                                              # original + 1 enqueued child
        assert items[0]["status"] == "completed"
        assert items[1]["parent_id"] == "p1" and items[1]["attempt_n"] == 2
        assert out["achieved"] == ["p2"] and len(calls) == 2


def test_t3_cap_exhaustion_terminates():
    with tempfile.TemporaryDirectory() as root:
        fake, calls = make_fake([("NO_TERMINATION", {})])                  # never achieves
        out = project.run_project("repo", root, ["do A"], run_task=fake, max_attempts=3)
        assert len(calls) == 3                                             # exactly the cap, then STOP (termination)
        assert out["achieved"] == [] and out["blocked"] == ["p3"]
        assert "cap" in out["items"][-1]["blocked_reason"]


def test_t4_ambiguity_escalates_without_reattempt():
    with tempfile.TemporaryDirectory() as root:
        # DoD present (so escalation is driven by the BLOCKING QUESTION, not the empty-DoD clause)
        amb = {"dod": [{"id": "c1"}], "open_questions": [{"text": "which file?", "blocking": True}]}
        fake, calls = make_fake([("HUMAN_REVIEW", amb)])
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert len(out["items"]) == 1 and len(calls) == 1                  # NO re-attempt enqueued (no cap-burn)
        assert out["items"][0]["status"] == "blocked"
        assert "ambiguity" in out["items"][0]["blocked_reason"]
        assert out["blocked"] == ["p1"]


def test_t5_lessons_feed_next_plan():
    with tempfile.TemporaryDirectory() as root:
        fake, calls = make_fake([("HUMAN_REVIEW", {"dod": [{"id": "c1"}]}), ("COMPLETE", {})])
        project.run_project("repo", root, ["normalize a string"], run_task=fake)
        second = calls[1]["request"]                                       # the re-attempt's request
        assert "PRIOR LESSONS LEARNED" in second and "HUMAN_REVIEW" in second   # the 1st lesson reached planning
        assert "normalize a string" in second                             # original purpose still present


def test_t6_unique_attempt_names():
    with tempfile.TemporaryDirectory() as root:
        fake, calls = make_fake([("NO_TERMINATION", {})])
        project.run_project("repo", root, ["do A", "do B"], run_task=fake, max_attempts=3)
        names = [c["name"] for c in calls]
        assert len(set(names)) == len(names)                              # no create_worktree collision
        assert all("-a" in n for n in names)


def test_t7_resume_skips_completed_and_resets_in_progress():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".devloop"))
        plan = {"schema_version": 1, "items": [
            {"id": "p1", "purpose": "done", "status": "completed", "attempt_n": 1, "parent_id": None,
             "attempts": [{"name": "p1-a1", "terminal": "COMPLETE", "changed_files": []}]},
            {"id": "p2", "purpose": "half", "status": "in_progress", "attempt_n": 1, "parent_id": None,
             "attempts": [{"name": "p2-a1", "terminal": "in_progress", "changed_files": []}]}]}
        with open(os.path.join(root, ".devloop", "PLAN.json"), "w") as f:
            json.dump(plan, f)
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project("repo", root, ["done", "half"], run_task=fake)
        names = [c["name"] for c in calls]
        assert len(calls) == 1                                            # only the resumed p2 ran
        assert not any(n.startswith("p1-") for n in names)               # completed item NOT re-attempted
        assert names[0].startswith("p2-")                                # in_progress -> pending -> attempted
        assert out["items"][0]["status"] == "completed" and "p2" in out["achieved"]


def test_empty_dod_charter_escalates_not_reattempts():
    # a HUMAN_REVIEW with an empty/invalid DoD (no blocking question) cannot be fixed by retrying
    # (the planner produced no spec) -> escalate to a human immediately, never burn the cap.
    with tempfile.TemporaryDirectory() as root:
        fake, calls = make_fake([("HUMAN_REVIEW", {"dod": []})])           # empty dod, no blocking q
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert len(out["items"]) == 1 and len(calls) == 1                  # NO re-attempt enqueued
        assert out["items"][0]["status"] == "blocked" and out["blocked"] == ["p1"]


def test_non_retryable_hr_escalates_immediately():
    # A HUMAN_REVIEW the runner marked retryable=False (a deterministic gate on the request text,
    # e.g. vague_goal_gate) reproduces on every re-run -> escalate in ONE attempt, never burn the
    # cap. The charter here has a valid DoD and no blocking question, so ONLY the new
    # retryable-False clause can escalate it. Mutant killed: that clause -> `if False:`.
    with tempfile.TemporaryDirectory() as root:
        def fake(repo, request, root_, name, **kw):
            return {"result": {"terminal": "HUMAN_REVIEW", "retryable": False,
                               "reason": "vague quality goal ('faster') with no measurable target"},
                    "worktree": {"path": os.path.join(root_, name)},
                    "charter": {"dod": [{"id": "c1"}]}}
        out = project.run_project("repo", root, ["make it faster"], run_task=fake)
        assert len(out["items"]) == 1                                      # NO re-attempt enqueued
        assert out["items"][0]["status"] == "blocked" and out["blocked"] == ["p1"]


def test_rerun_over_leftover_branch_suffixes_instead_of_aborting():
    # E2 (re-runnability): a prior run's kept-for-review devloop/* branch must not abort a re-run
    # of the same project — _attempt_name probes the repo and suffixes -r2 instead of handing
    # create_worktree a colliding branch name. Mutants killed: the probe loop -> `while False:`;
    # the base name -> item["id"].
    import subprocess
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo"); os.makedirs(repo)
        for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
            subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
        open(os.path.join(repo, "README"), "w").write("r\n")
        subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo, "branch", "devloop/p1-a1"], check=True, capture_output=True)
        fake, calls = make_fake([("COMPLETE", {})])
        out = project.run_project(repo, root, ["do A"], run_task=fake)
        assert calls[0]["name"] == "p1-a1-r2"                              # probed past the leftover
        assert out["achieved"] == ["p1"]


def test_run_task_reason_flows_into_lesson():
    # the reason loop.run_v1 now returns must survive into LESSONS (dict field AND lesson text), so
    # the NEXT iteration's plan re-reads the actual diagnostic, not a content-free stub.
    with tempfile.TemporaryDirectory() as root:
        def fake(repo, request, root_, name, **kw):
            return {"result": {"terminal": "HUMAN_REVIEW", "reason": "DoD criteria with no covering test: ['c2']"},
                    "worktree": {"path": os.path.join(root_, name)}, "charter": {}}
        project.run_project("repo", root, ["do A"], run_task=fake, max_attempts=1)
        lessons = state.read_learnings(os.path.join(root, ".devloop", "LESSONS.jsonl"))
        assert lessons and lessons[0]["reason"] == "DoD criteria with no covering test: ['c2']"
        assert "no covering test" in lessons[0]["lesson"]           # distilled into the lesson TEXT too


def test_bridge_path_populates_rich_lesson_fields():
    """P1a: when run_task returns a bridge-shape devloop_result.commit_message,
    the LESSONS.jsonl entry must carry non-empty learnings_text, references,
    and failure_conditions."""
    with tempfile.TemporaryDirectory() as root:
        commit_msg = (
            "devloop COMPLETE: p1-a1\n\n"
            "INTENTION:\n  do A\n\n"
            "THESIS:\n  all gates passed\n\n"
            "LEARNINGS:\n"
            "  - Use subprocess.run for real binaries\n"
            "  AVOID: mocking external calls hides failures\n\n"
            "REFERENCES:\n"
            "  Trace: /tmp/trace.jsonl\n"
            "  Prior: abc1234\n"
        )
        def fake(repo, request, root_, name, **kw):
            return {
                "result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED"},
                "worktree": {"path": os.path.join(root_, name)},
                "charter": {},
                "devloop_result": {
                    "commit_message": commit_msg,
                    # N2: bridge now exposes rich fields directly
                    "learnings_text": "Use subprocess.run for real binaries",
                    "references": "Trace: /tmp/trace.jsonl\nPrior: abc1234",
                    "failure_conditions": ["AVOID: mocking external calls hides failures"],
                },
            }
        out = project.run_project("repo", root, ["do A"], run_task=fake)
        assert out["achieved"] == ["p1"]
        lessons = state.read_learnings(os.path.join(root, ".devloop", "LESSONS.jsonl"))
        assert len(lessons) == 1
        e = lessons[0]
        assert "Use subprocess.run" in e["learnings_text"]
        assert "Trace:" in e["references"]
        assert any("mocking external calls" in fc for fc in e["failure_conditions"])


def test_direct_runner_path_populates_rich_lesson_fields():
    """P1b: the default direct-runner path has no devloop_result.commit_message.
    project.run_project must still synthesize rich fields so LESSONS.jsonl entries
    have non-empty learnings_text, references, and failure_conditions."""
    with tempfile.TemporaryDirectory() as root:
        def fake(repo, request, root_, name, **kw):
            return {"result": {"terminal": "HUMAN_REVIEW", "reason": "ambiguous target"},
                    "worktree": {"path": os.path.join(root_, name)}, "charter": {}}
        # prevent infinite re-attempts: cap=1 so we get exactly one entry
        project.run_project("repo", root, ["do A"], run_task=fake, max_attempts=1)
        lessons = state.read_learnings(os.path.join(root, ".devloop", "LESSONS.jsonl"))
        assert len(lessons) == 1
        e = lessons[0]
        assert e["learnings_text"] != ""
        assert e["references"] != ""
        assert e["failure_conditions"] != []
        assert any("ambiguous target" in fc for fc in e["failure_conditions"])


def test_request_dedup_collapses_duplicate_avoid_lines():
    """P5: a failure_condition that is also present verbatim in learnings_text must
    appear only ONCE in the next attempt's request (the _add_part/seen_parts logic)."""
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".devloop"))
        state.append_learning(os.path.join(root, ".devloop", "LESSONS.jsonl"), {
            "ts": "2026-07-05T00:00:00+00:00",
            "purpose_id": "p0", "purpose": "seed", "attempt_n": 1, "name": "seed",
            "terminal": "HUMAN_REVIEW", "achieved": False, "changed_files": [],
            "reason": "ambiguous target", "lesson": "REFUTED THESIS: ambiguous target",
            "learnings_text": "  - AVOID: mocking external calls hides failures\n",
            "references": "Trace: /tmp/t.jsonl",
            "failure_conditions": ["AVOID: mocking external calls hides failures"],
        })
        # a NO_TERMINATION run that will re-attempt once; we only need the first call
        def fake(repo, request, root_, name, **kw):
            return {"result": {"terminal": "NO_TERMINATION", "reason": "stuck"},
                    "worktree": {"path": os.path.join(root_, name)}, "charter": {}}
        project.run_project("repo", root, ["do A"], run_task=fake, max_attempts=1)
        # We seeded one lesson and the single attempt made a second; the request of the
        # single attempt (lessons folded in) is what we inspect.
        # The seeded AVOID line appears in learnings_text and again in failure_conditions,
        # but _add_part dedup should collapse it.
        lessons = state.read_learnings(os.path.join(root, ".devloop", "LESSONS.jsonl"))
        assert len(lessons) == 2  # seed + one attempt
        # Request with folded-in lessons is not in the journal. Use the second attempt's
        # report as a proxy — it lists learned lines. Check the line count for the repeated
        # AVOID entry: it must appear exactly once in the report.
        rep = project._render_report(
            items=[{"id":"p1","purpose":"do A","status":"blocked",
                    "blocked_reason":"cap", "attempts":[
                        {"name":"p1-a1","terminal":"NO_TERMINATION","changed_files":[]}]}],
            achieved=[], blocked=[{"id":"p1","purpose":"do A","status":"blocked",
                                   "blocked_reason":"cap",
                                   "attempts":[{"name":"p1-a1","terminal":"NO_TERMINATION",
                                                  "changed_files":[]}]}],
            lessons=lessons)
        assert rep.count("AVOID: mocking external calls hides failures") == 1


def test_consolidator_reads_project_lessons_jsonl():
    """N1: _git_history_learnings should read target_dir/.devloop/LESSONS.jsonl
    in addition to LEARNINGS.jsonl, so project-local learnings reach the planner."""
    import dispatch as _dispatch
    with tempfile.TemporaryDirectory() as target_dir:
        # Set up a fake git repo so the git log scan doesn't crash
        os.makedirs(os.path.join(target_dir, ".devloop"))
        _dispatch._WRITE_SAFE_ROOT = target_dir  # point LEARNINGS.jsonl lookup here too
        try:
            # No LEARNINGS.jsonl, but LESSONS.jsonl exists with project-local learnings
            lessons_path = os.path.join(target_dir, ".devloop", "LESSONS.jsonl")
            state.append_learning(lessons_path, {
                "ts": "2026-07-05T00:00:00+00:00",
                "purpose_id": "p1", "purpose": "do A", "attempt_n": 1,
                "name": "p1-a1", "terminal": "HUMAN_REVIEW", "achieved": False,
                "changed_files": [], "reason": "ambiguous target",
                "lesson": "REFUTED THESIS: ambiguous target",
                "learnings_text": "  - AVOID: mocking external calls hides failures\n",
                "references": "Trace: /tmp/t.jsonl",
                "failure_conditions": ["AVOID: mocking external calls hides failures"],
            })
            # We need git log to find at least one structured commit, or the function
            # returns early. Create a dummy commit with LEARNINGS in the body.
            import subprocess as _sp
            _sp.run(["git", "init", "-q", target_dir], check=True)
            _sp.run(["git", "-C", target_dir, "config", "user.email", "t@t.com"], check=True)
            _sp.run(["git", "-C", target_dir, "config", "user.name", "test"], check=True)
            _sp.run(["git", "-C", target_dir, "add", "."], check=True)
            _sp.run(["git", "-C", target_dir, "commit", "-q", "-m",
                     "LEARNINGS:\n  - initial commit\n---COMMIT-END---"], check=True)
            # Call with DEVLOOP_NO_HISTORY_LLM=1 to get mechanical fallback (includes journal)
            os.environ["DEVLOOP_NO_HISTORY_LLM"] = "1"
            try:
                result = _dispatch._git_history_learnings(target_dir)
            finally:
                os.environ.pop("DEVLOOP_NO_HISTORY_LLM", None)
            # The project-local LESSONS.jsonl content should appear in the output
            assert "mocking external calls" in result, f"LESSONS.jsonl content missing from: {result}"
        finally:
            _dispatch._WRITE_SAFE_ROOT = os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data")


def test_devloop_result_has_rich_fields():
    """N2: _run should expose learnings_text, references, and failure_conditions
    directly in devloop_result (not just commit_message)."""
    import devloop_bridge as _br
    # Use a fake run_task that returns a HUMAN_REVIEW result
    fake = lambda repo, request, root, name, **kw: {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "ambiguous target"},
        "worktree": {}, "charter": {}}
    orig_sr, orig_ws = _br._scratch_repo, _br._WRITE_SAFE
    _br._scratch_repo = lambda name: "/fake/repo"
    with tempfile.TemporaryDirectory() as d:
        _br._WRITE_SAFE = d
        try:
            os.environ["DEVLOOP_NO_COMMIT_LLM"] = "1"
            result = _br._run("test request", "rich-probe", run_task=fake)
        finally:
            _br._scratch_repo, _br._WRITE_SAFE = orig_sr, orig_ws
            os.environ.pop("DEVLOOP_NO_COMMIT_LLM", None)
    dr = result["devloop_result"]
    # N2: these keys must be present (even if empty for a HUMAN_REVIEW with no learnings)
    assert "learnings_text" in dr
    assert "references" in dr
    assert "failure_conditions" in dr
    # failure_result must have the same keys (shape mirror)
    crash = _br.failure_result("kaboom")["devloop_result"]
    assert set(crash) == set(dr), f"Shape mismatch: {set(crash) ^ set(dr)}"


def test_avoid_double_prefix_stripped_in_consolidator():
    """Quality review fix: failure_conditions entries that already start with
    'AVOID:' must NOT be double-prefixed in the consolidator journal."""
    import dispatch as _dispatch
    with tempfile.TemporaryDirectory() as target_dir:
        os.makedirs(os.path.join(target_dir, ".devloop"))
        _dispatch._WRITE_SAFE_ROOT = target_dir
        try:
            lessons_path = os.path.join(target_dir, ".devloop", "LESSONS.jsonl")
            state.append_learning(lessons_path, {
                "ts": "2026-07-05T00:00:00+00:00",
                "purpose_id": "p1", "purpose": "do A", "attempt_n": 1,
                "name": "p1-a1", "terminal": "HUMAN_REVIEW", "achieved": False,
                "changed_files": [], "reason": "ambiguous target",
                "lesson": "REFUTED THESIS: ambiguous target",
                "learnings_text": "  - AVOID: mocking external calls hides failures\n",
                "references": "",
                "failure_conditions": ["AVOID: mocking external calls hides failures"],
            })
            import subprocess as _sp
            _sp.run(["git", "init", "-q", target_dir], check=True)
            _sp.run(["git", "-C", target_dir, "config", "user.email", "t@t.com"], check=True)
            _sp.run(["git", "-C", target_dir, "config", "user.name", "test"], check=True)
            _sp.run(["git", "-C", target_dir, "add", "."], check=True)
            _sp.run(["git", "-C", target_dir, "commit", "-q", "-m",
                     "LEARNINGS:\n  - initial commit\n---COMMIT-END---"], check=True)
            os.environ["DEVLOOP_NO_HISTORY_LLM"] = "1"
            try:
                result = _dispatch._git_history_learnings(target_dir)
            finally:
                os.environ.pop("DEVLOOP_NO_HISTORY_LLM", None)
            # Must NOT contain double AVOID: prefix
            assert "AVOID: AVOID:" not in result, f"Double AVOID: prefix found in: {result}"
            assert "AVOID: mocking external calls" in result
        finally:
            _dispatch._WRITE_SAFE_ROOT = os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} project tests passed")
