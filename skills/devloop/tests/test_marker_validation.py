"""Validation tests for progress.jsonl marker integrity.

These tests parse the JSONL written by loop._progress_event and verify:
- every begin marker (ok=None / ⏳) has a matching end marker (ok=True/False / ✅/❌)
- no step ends without first beginning (except instant steps)
- every record has a run_id
- crash markers include a traceback

Run: cd /opt/data/skills/software-development/devloop && python3 -m pytest tests/test_marker_validation.py -q
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import gate  # noqa: E402
import loop  # noqa: E402


def _make_progress_jsonl(run_dir, records):
    """Write a fake progress.jsonl from a list of (step, ok, detail) tuples.

    ok values:
        None  -> begin marker (⏳)
        True  -> passing end marker (✅)
        False -> failing end marker (❌)
    """
    p = os.path.join(run_dir, "progress.jsonl")
    os.makedirs(run_dir, exist_ok=True)
    run_id = "test-run-1234"
    with open(p, "w") as f:
        for step, ok, detail in records:
            rec = {
                "ts": 0.0,
                "step": step,
                "run_id": run_id,
                "ok": ok,
                "detail": detail,
            }
            f.write(json.dumps(rec) + "\n")
    return p


def _parse_progress_jsonl(path):
    """Parse a progress.jsonl file into a list of dicts."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _validate_markers(records, instant_steps=None, terminal_steps=None):
    """Validate marker integrity over parsed progress records.

    Returns (ok: bool, reason: str).
    """
    instant_steps = set(instant_steps or [])
    terminal_steps = set(terminal_steps or [])

    # 1. every record has a run_id
    for i, rec in enumerate(records):
        if not rec.get("run_id"):
            return False, f"record {i} missing run_id"

    # 2. crash markers include a traceback
    for i, rec in enumerate(records):
        if rec.get("step") == "crash":
            if "traceback" not in rec:
                return False, f"crash record {i} missing traceback"

    # Build per-step state machine
    began = set()       # steps that have seen a begin marker
    ended = set()       # steps that have seen an end marker

    for i, rec in enumerate(records):
        step = rec.get("step")
        ok = rec.get("ok")
        if ok is None:
            # begin marker
            if step in began:
                return False, f"step {step!r} began again at record {i}"
            began.add(step)
        elif ok in (True, False):
            # end marker (pass/fail)
            if step not in began and step not in instant_steps:
                return False, f"step {step!r} ended at record {i} without a begin"
            ended.add(step)
        else:
            return False, f"record {i} has invalid ok value {ok!r}"

    # 3. every begin must have a matching end, except instant/terminal steps
    for step in began:
        if step in instant_steps or step in terminal_steps:
            continue
        if step not in ended:
            return False, f"step {step!r} began but never ended"

    return True, "markers valid"


# ── Helper / marker tests ──────────────────────────────────────────────


def test_helper_builds_valid_progress_jsonl():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("charter", None, "starting"),
            ("charter", True, "done"),
        ]
        p = _make_progress_jsonl(run_dir, records)
        parsed = _parse_progress_jsonl(p)
        assert len(parsed) == 2
        assert parsed[0]["ok"] is None
        assert parsed[1]["ok"] is True


def test_validate_markers_accepts_valid_run():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("charter", None, "starting"),
            ("charter", True, "done"),
            ("design", None, "starting"),
            ("design", True, "done"),
            ("implement", None, "starting"),
            ("implement", False, "failed"),
        ]
        _make_progress_jsonl(run_dir, records)
        ok, reason = _validate_markers(_parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl")))
        assert ok, reason


def test_validate_markers_rejects_begin_without_end():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("charter", None, "starting"),
        ]
        _make_progress_jsonl(run_dir, records)
        ok, reason = _validate_markers(_parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl")))
        assert not ok
        assert "began but never ended" in reason


def test_validate_markers_rejects_end_without_begin():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("charter", True, "done"),
        ]
        _make_progress_jsonl(run_dir, records)
        ok, reason = _validate_markers(_parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl")))
        assert not ok
        assert "ended" in reason and "without a begin" in reason


def test_validate_markers_allows_instant_steps():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("charter", None, "starting"),
            ("charter", True, "done"),
            ("announce", True, "instant message"),
        ]
        _make_progress_jsonl(run_dir, records)
        ok, reason = _validate_markers(
            _parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl")),
            instant_steps={"announce"},
        )
        assert ok, reason


def test_validate_markers_checks_run_id():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        p = os.path.join(run_dir, "progress.jsonl")
        os.makedirs(run_dir, exist_ok=True)
        with open(p, "w") as f:
            f.write(json.dumps({"ts": 0.0, "step": "charter", "ok": True, "detail": ""}) + "\n")
        ok, reason = _validate_markers(_parse_progress_jsonl(p))
        assert not ok
        assert "run_id" in reason


def test_validate_markers_checks_crash_traceback():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")
        records = [
            ("implement", None, "starting"),
            ("crash", False, "boom"),
        ]
        _make_progress_jsonl(run_dir, records)
        parsed = _parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl"))
        # strip traceback so we can assert it's required
        parsed[1].pop("traceback", None)
        ok, reason = _validate_markers(parsed, instant_steps={"crash"})
        assert not ok
        assert "traceback" in reason


# ── Integration: validation on a real loop run ───────────────────────


def test_real_loop_run_has_valid_markers():
    """End-to-end: a real loop.run_v1 emits markers that pass our validator."""
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "m.py")
        run_dir = os.path.join(d, ".devloop", "runs", "mv1")
        loop._PROGRESS_START = None
        loop._PROGRESS_RUN_DIR = None

        def implement(charter, attempt, last_failure):
            with open(script, "w") as f:
                f.write("import sys; sys.exit(0)\n")

        res = loop.run_v1(
            {
                "interpreted_intent": "make the script exit 0",
                "purpose": "demo",
                "dod": [{"id": "c1", "criterion": "script exits 0", "verify_intent": "exit 0", "kind": "shown", "tier": "unit"}],
                "assumptions": [{"text": "python is available", "confidence": 0.9}],
                "open_questions": [],
                "happy_path": "write the script",
                "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
                "backoff_map": [{"trigger": "t", "directional_response": "r"}],
                "advisors_verdict": "ok",
                "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
            },
            design=(lambda c: {"t_c1": "c1"}),
            implement=implement,
            judge_a=(lambda t, c: True),
            judge_b=(lambda t, c: True),
            verify_cmd_for=lambda cid: [sys.executable, script],
            run_dir=run_dir,
            cwd=d,
            regression_cmd=["true"],
        )
        assert res["terminal"] == "COMPLETE"
        records = _parse_progress_jsonl(os.path.join(run_dir, "progress.jsonl"))
        instant_steps = {
            "roadmap", "announce", "pre_clarify",
            "ambiguity_gate", "coverage", "quality_lint", "lint_discovery",
            "stop_check", "overfit_audit", "commit_scope", "rebuild", "redesign",
        }
        ok, reason = _validate_markers(
            records,
            instant_steps=instant_steps,
            terminal_steps={"terminal"},
        )
        assert ok, reason


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
