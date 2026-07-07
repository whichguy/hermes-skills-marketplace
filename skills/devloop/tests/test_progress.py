"""Tests for the progress output system: progress.jsonl, DEVLOOP_PROGRESS levels,
planning announcements, per-criterion judge verdicts, evidence detail, and
HUMAN_REVIEW compact-bypass.

These tests run against loop.run_v1 and runner.run_task with injected fake
dispatchers — no LLM, no network, real subprocess evidence.
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import loop          # noqa: E402

_YES = (lambda t, c: True)
_DESIGN = (lambda c: {"t_c1": "c1"})
_GREEN_SUITE = ["true"]


def _charter(blocking=False, n_criteria=1):
    dod = [{"id": f"c{i+1}", "criterion": f"crit {i+1}", "verify_intent": f"v{i+1}",
            "kind": "shown", "tier": "unit"} for i in range(n_criteria)]
    return {
        "interpreted_intent": "make the script exit 0", "purpose": "demo",
        "dod": dod,
        "assumptions": [{"text": "python is available", "confidence": 0.9}],
        "open_questions": [{"text": "q", "blocking": True}] if blocking else [],
        "happy_path": "write the script", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _progress_events(run_dir):
    """Read progress.jsonl from a run dir."""
    p = os.path.join(run_dir, "progress.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


# ── Stage 1: progress.jsonl + DEVLOOP_PROGRESS levels ─────────────────────

def test_progress_jsonl_exists_after_run():
    """progress.jsonl is created in the run_dir during a loop run."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t1")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        assert len(events) > 0, "progress.jsonl should have events"
        steps = [e["step"] for e in events]
        assert "charter" in steps
        assert "complete" in steps


def test_progress_jsonl_has_timestamps():
    """Each progress event has a ts field for timing analysis."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t2")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        assert all("ts" in e for e in events), "every event needs ts"


def test_progress_quiet_suppresses_stderr():
    """DEVLOOP_PROGRESS=quiet suppresses all stderr output but progress.jsonl is still written."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t3")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None
        old = os.environ.get("DEVLOOP_PROGRESS")
        os.environ["DEVLOOP_PROGRESS"] = "quiet"
        try:
            def implement(charter, attempt, last_failure):
                open(script, "w").write("import sys; sys.exit(0)\n")

            res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                             judge_a=_YES, judge_b=_YES,
                             verify_cmd_for=lambda cid: [sys.executable, script],
                             run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
            assert res["terminal"] == "COMPLETE"
            events = _progress_events(run_dir)
            assert len(events) > 0, "progress.jsonl written even when stderr is quiet"
        finally:
            if old is not None:
                os.environ["DEVLOOP_PROGRESS"] = old
            else:
                os.environ.pop("DEVLOOP_PROGRESS", None)


def test_progress_verbose_shows_judge_detail(capsys):
    """DEVLOOP_PROGRESS=verbose shows per-criterion judge verdicts on stderr."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t4")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None
        old = os.environ.get("DEVLOOP_PROGRESS")
        os.environ["DEVLOOP_PROGRESS"] = "verbose"
        try:
            def implement(charter, attempt, last_failure):
                open(script, "w").write("import sys; sys.exit(0)\n")

            design_map = {"t_c1": "c1", "t_c2": "c2"}
            res = loop.run_v1(_charter(n_criteria=2), design=lambda c: design_map,
                             implement=implement, judge_a=_YES, judge_b=_YES,
                             verify_cmd_for=lambda cid: [sys.executable, script],
                             run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
            assert res["terminal"] == "COMPLETE"
            captured = capsys.readouterr()
            assert "judge" in captured.err.lower()
        finally:
            if old is not None:
                os.environ["DEVLOOP_PROGRESS"] = old
            else:
                os.environ.pop("DEVLOOP_PROGRESS", None)


def test_progress_jsonl_judge_verdicts_per_criterion():
    """progress.jsonl contains per-criterion judge verdicts with judge names and reasons."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t5")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        def judge_a(t, c):
            return (True, "test encodes criterion")
        def judge_b(t, c):
            return (True, "test matches intent")

        design_map = {"t_c1": "c1", "t_c2": "c2"}

        res = loop.run_v1(_charter(n_criteria=2), design=lambda c: design_map,
                         implement=implement, judge_a=judge_a, judge_b=judge_b,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        judge_events = [e for e in events if e["step"] == "judge"]
        assert len(judge_events) >= 1
        je = judge_events[-1]
        assert "verdicts" in je or "trusted" in je, f"judge event missing verdicts: {je}"


# ── Stage 2: evidence pass/fail during rebuild loops ────────────────────────

def test_progress_evidence_red_then_green():
    """progress.jsonl records evidence events with per-criterion pass/fail across rebuilds."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t6")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write(f"import sys; sys.exit(0 if {attempt} >= 1 else 1)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        evidence_events = [e for e in events if e["step"] == "evidence"]
        assert len(evidence_events) >= 2
        assert any(not e.get("passed", True) for e in evidence_events), "first evidence should be RED"
        assert evidence_events[-1].get("passed"), "last evidence should be GREEN"


def test_progress_evidence_shows_attempt_number():
    """Evidence events in progress.jsonl include the attempt number for rebuild tracking."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t7")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write(f"import sys; sys.exit(0 if {attempt} >= 1 else 1)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        evidence_events = [e for e in events if e["step"] == "evidence"]
        attempts = [e.get("attempt") for e in evidence_events if e.get("attempt") is not None]
        assert len(attempts) >= 2, f"evidence events should have attempt numbers: {evidence_events}"


# ── Stage 3: terminal results + learnings ─────────────────────────────────

def test_progress_terminal_complete_has_grounding():
    """progress.jsonl terminal event for COMPLETE includes grounding summary."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t8")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        terminal_events = [e for e in events if e["step"] == "terminal"]
        assert len(terminal_events) >= 1
        te = terminal_events[-1]
        assert te.get("terminal") == "COMPLETE"


def test_progress_terminal_human_review_has_reason():
    """progress.jsonl terminal event for HUMAN_REVIEW includes the reason."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, ".devloop", "runs", "t9")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        res = loop.run_v1(_charter(blocking=True), design=lambda c: {"t_c1": "c1"},
                         implement=lambda *a: None, judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: ["true"], run_dir=run_dir, cwd=d)
        assert res["terminal"] == "HUMAN_REVIEW"
        events = _progress_events(run_dir)
        terminal_events = [e for e in events if e["step"] == "terminal"]
        assert len(terminal_events) >= 1
        te = terminal_events[-1]
        assert te.get("terminal") == "HUMAN_REVIEW"
        assert "reason" in te


# ── Stage 4: HUMAN_REVIEW bypasses compact mode ─────────────────────────────

def test_progress_human_review_bypasses_compact(capsys):
    """HUMAN_REVIEW blocking questions are visible even in compact mode."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, ".devloop", "runs", "t10")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None
        old = os.environ.get("DEVLOOP_PROGRESS")
        os.environ["DEVLOOP_PROGRESS"] = "compact"
        try:
            res = loop.run_v1(_charter(blocking=True), design=lambda c: {"t_c1": "c1"},
                             implement=lambda *a: None, judge_a=_YES, judge_b=_YES,
                             verify_cmd_for=lambda cid: ["true"], run_dir=run_dir, cwd=d)
            assert res["terminal"] == "HUMAN_REVIEW"
            captured = capsys.readouterr()
            assert "HUMAN_REVIEW" in captured.err or "blocking" in captured.err.lower() \
                or "ambiguous" in captured.err.lower(), \
                f"HUMAN_REVIEW must bypass compact: {captured.err!r}"
        finally:
            if old is not None:
                os.environ["DEVLOOP_PROGRESS"] = old
            else:
                os.environ.pop("DEVLOOP_PROGRESS", None)


# ── Stage 1b: planning announcements + design ──────────────────────────────

def test_progress_design_announcement():
    """progress.jsonl has a design event with test count and coverage info."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t11")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        design_map = {"t_c1": "c1", "t_c2": "c2"}
        res = loop.run_v1(_charter(n_criteria=2), design=lambda c: design_map,
                         implement=implement, judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        design_events = [e for e in events if e["step"] == "design"]
        assert len(design_events) >= 1, "should have a design progress event"
        de = design_events[-1]
        assert "n_tests" in de or "n_criteria" in de, f"design event should have counts: {de}"


def test_progress_roadmap_emitted():
    """progress.jsonl includes a roadmap event at the start of the run."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "t12")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            open(script, "w").write("import sys; sys.exit(0)\n")

        res = loop.run_v1(_charter(), design=_DESIGN, implement=implement,
                         judge_a=_YES, judge_b=_YES,
                         verify_cmd_for=lambda cid: [sys.executable, script],
                         run_dir=run_dir, cwd=d, regression_cmd=_GREEN_SUITE)
        assert res["terminal"] == "COMPLETE"
        events = _progress_events(run_dir)
        first_steps = [e["step"] for e in events[:3]]
        assert "roadmap" in first_steps, f"roadmap should be early: {first_steps}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
