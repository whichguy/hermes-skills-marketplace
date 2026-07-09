#!/usr/bin/env python3
"""Test suite for devloop_digest.py — validates schema parsing, edge cases, and output format.

Run: python3 -m pytest tests/test_devloop_digest.py -q
Or:  python3 tests/test_devloop_digest.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Ensure the script is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import devloop_digest as dd


# ── Fixtures

# Use a helper to mint timestamps relative to NOW so the fixtures never go stale.
import time as _time
_NOW = _time.time()
def _ts(seconds_ago=0):
    """Timestamp N seconds ago from now (default 0 = right now)."""
    return round(_NOW - seconds_ago, 3)

PROGRESS_COMPLETE = [
    {"ts": _ts(225), "step": "charter_result", "n_criteria": 3, "n_assumptions": 5, "n_blocking": 0},
    {"ts": _ts(225), "step": "roadmap", "phases": ["charter", "design", "judge", "evidence", "complete"]},
    {"ts": _ts(225), "step": "charter", "ok": None, "detail": "decomposing request..."},
    {"ts": _ts(225), "step": "coverage", "ok": True, "detail": "3 tests covering 3 criteria", "n_criteria": 3},
    {"ts": _ts(149), "step": "judge", "ok": True, "trusted": 3, "total": 3,
     "verdicts": [
         {"criterion": "c1", "encodes": True, "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
         {"criterion": "c2", "encodes": True, "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
         {"criterion": "c3", "encodes": False, "judge_a": False, "judge_b": True, "judge_a_reason": "test doesn't assert return type", "judge_b_reason": ""},
     ]},
    {"ts": _ts(149), "step": "implement", "ok": None, "detail": "coder attempt 0..."},
    {"ts": _ts(109), "step": "evidence", "ok": True, "attempt": 0, "passed": 3, "total": 3, "red": [], "per_criterion": {"c1": True, "c2": True, "c3": True}},
    {"ts": _ts(109), "step": "stop_check", "ok": True, "detail": "DoD-SATISFIED"},
    {"ts": _ts(108), "step": "regression", "ok": True, "detail": "whole-suite"},
    {"ts": _ts(33), "step": "overfit_audit", "ok": True, "detail": "3 criteria x 2 auditors"},
    {"ts": _ts(0), "step": "complete", "ok": None, "detail": "all gates passed, merging..."},
    {"ts": _ts(0), "step": "terminal", "terminal": "COMPLETE"},
]

PROGRESS_HUMAN_REVIEW = [
    {"ts": _ts(2600), "step": "charter_result", "n_criteria": 2, "n_assumptions": 3, "n_blocking": 1},
    {"ts": _ts(2600), "step": "charter", "ok": None, "detail": "decomposing..."},
    {"ts": _ts(2550), "step": "judge", "ok": False, "trusted": 1, "total": 2,
     "verdicts": [
         {"criterion": "c1", "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
         {"criterion": "c2", "judge_a": False, "judge_b": False, "judge_a_reason": "bad test", "judge_b_reason": "bad test"},
     ]},
    {"ts": _ts(2500), "step": "terminal", "terminal": "HUMAN_REVIEW", "reason": "test fault: criteria [c2] have no judge-trusted test"},
]

PROGRESS_INTERRUPTED = [
    {"ts": _ts(3600), "step": "charter_result", "n_criteria": 1, "n_assumptions": 2, "n_blocking": 0},
    {"ts": _ts(3600), "step": "charter", "ok": None, "detail": "decomposing..."},
    {"ts": _ts(3550), "step": "design", "ok": None, "detail": "generating tests..."},
]

PROGRESS_WITH_REBUILDS = [
    {"ts": _ts(4600), "step": "charter_result", "n_criteria": 2, "n_assumptions": 1, "n_blocking": 0},
    {"ts": _ts(4600), "step": "judge", "ok": True, "trusted": 2, "total": 2,
     "verdicts": [
         {"criterion": "c1", "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
         {"criterion": "c2", "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
     ]},
    {"ts": _ts(4500), "step": "evidence", "ok": False, "attempt": 0, "passed": 1, "total": 2, "red": ["c2"], "per_criterion": {"c1": True, "c2": False}},
    {"ts": _ts(4500), "step": "rebuild_fail", "rebuild": 1, "cause": "frozen_tests"},
    {"ts": _ts(4400), "step": "evidence", "ok": True, "attempt": 1, "passed": 2, "total": 2, "red": [], "per_criterion": {"c1": True, "c2": True}},
    {"ts": _ts(4400), "step": "terminal", "terminal": "COMPLETE"},
]

PROGRESS_OLD_FORMAT = [
    {"ts": _ts(2400), "step": "charter", "detail": "decomposing...", "ok": None, "elapsed_s": 0.0},
    {"ts": _ts(2351), "step": "judge", "detail": "1/1 trusted", "ok": True, "elapsed_s": 48.9},
    {"ts": _ts(2308), "step": "evidence", "detail": "1/1 passed", "ok": True, "elapsed_s": 91.2},
    {"ts": _ts(2239), "step": "complete", "detail": "merging...", "ok": None, "elapsed_s": 161.0},
]


def _write_progress(tmpdir: Path, events: list[dict]) -> Path:
    """Write a progress.jsonl file into tmpdir and return the path."""
    p = tmpdir / "progress.jsonl"
    with open(p, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return p


# ── Tests: _parse_progress

class TestParseProgress:
    """Test the _parse_progress function with various progress.jsonl shapes."""

    def test_complete_run(self, tmp_path):
        """A complete run with all fields populated."""
        p = _write_progress(tmp_path, PROGRESS_COMPLETE)
        result = dd._parse_progress(p)
        assert result is not None
        assert result["terminal"] == "COMPLETE"
        assert result["n_criteria"] == 3
        assert result["rebuilds"] == 0
        assert result["duration_s"] == round(_ts(0) - _ts(225), 1)
        assert result["judge_verdicts"] is not None
        assert len(result["judge_verdicts"]) == 3
        # c3 should show judge_a rejected
        c3 = result["judge_verdicts"][2]
        assert c3["judge_a"] is False
        assert "return type" in c3["judge_a_reason"]
        # Evidence
        assert len(result["evidence_results"]) == 1
        assert result["evidence_results"][0]["passed"] == 3
        assert result["evidence_results"][0]["total"] == 3
        assert result["evidence_results"][0]["red"] == []

    def test_human_review_run(self, tmp_path):
        """A HUMAN_REVIEW terminal with a blocking question."""
        p = _write_progress(tmp_path, PROGRESS_HUMAN_REVIEW)
        result = dd._parse_progress(p)
        assert result is not None
        assert result["terminal"] == "HUMAN_REVIEW"
        assert "test fault" in result["reason"]
        assert result["n_criteria"] == 2
        assert result["judge_verdicts"] is not None
        # c2 should be untrusted
        c2 = result["judge_verdicts"][1]
        assert c2["judge_a"] is False
        assert c2["judge_b"] is False

    def test_interrupted_run(self, tmp_path):
        """A run with no terminal event — should be INTERRUPTED."""
        p = _write_progress(tmp_path, PROGRESS_INTERRUPTED)
        result = dd._parse_progress(p)
        assert result is not None
        assert result["terminal"] == "INTERRUPTED"
        assert result["n_criteria"] == 1

    def test_run_with_rebuilds(self, tmp_path):
        """A run that had rebuild failures before passing."""
        p = _write_progress(tmp_path, PROGRESS_WITH_REBUILDS)
        result = dd._parse_progress(p)
        assert result is not None
        assert result["terminal"] == "COMPLETE"
        assert result["rebuilds"] == 1
        assert len(result["evidence_results"]) == 2
        # First evidence had c2 RED
        assert "c2" in result["evidence_results"][0]["red"]
        # Second evidence all green
        assert result["evidence_results"][1]["red"] == []

    def test_old_format_no_charter_result(self, tmp_path):
        """Old progress.jsonl without charter_result step."""
        p = _write_progress(tmp_path, PROGRESS_OLD_FORMAT)
        result = dd._parse_progress(p)
        assert result is not None
        # No charter_result → n_criteria stays 0 (fallback to coverage step)
        assert result["n_criteria"] == 0
        # But terminal should still be COMPLETE (from "complete" step fallback)
        assert result["terminal"] == "COMPLETE"
        # Duration from elapsed_s fallback
        assert result["duration_s"] is not None

    def test_empty_file(self, tmp_path):
        """Empty progress.jsonl returns None."""
        p = tmp_path / "progress.jsonl"
        p.write_text("")
        assert dd._parse_progress(p) is None

    def test_nonexistent_file(self, tmp_path):
        """Nonexistent file returns None."""
        p = tmp_path / "nonexistent.jsonl"
        assert dd._parse_progress(p) is None

    def test_corrupt_json(self, tmp_path):
        """Corrupt JSON lines are handled gracefully."""
        p = tmp_path / "progress.jsonl"
        p.write_text('{"ts": 1.0, "step": "charter"}\n{corrupt\n{"ts": 2.0, "step": "terminal", "terminal": "COMPLETE"}\n')
        # Should return None because json.JSONDecodeError is caught
        result = dd._parse_progress(p)
        # Corrupt file returns None (the whole parse fails)
        assert result is None

    def test_run_dt_from_ts(self, tmp_path):
        """run_dt is correctly parsed from the first ts."""
        events = [
            {"ts": _ts(225), "step": "charter", "ok": None},
            {"ts": _ts(0), "step": "terminal", "terminal": "COMPLETE"},
        ]
        p = _write_progress(tmp_path, events)
        result = dd._parse_progress(p)
        assert result is not None
        assert result["run_dt"] is not None
        assert result["run_dt"].timestamp() == _ts(225)


# ── Tests: _scan_traces

class TestScanTraces:
    """Test the _scan_traces function."""

    def test_no_traces_dir(self, tmp_path):
        """Nonexistent traces directory returns empty list."""
        result = dd._scan_traces(tmp_path / "nonexistent", 24, datetime.now(timezone.utc))
        assert result == []

    def test_empty_traces_dir(self, tmp_path):
        """Empty traces directory returns empty list."""
        result = dd._scan_traces(tmp_path, 24, datetime.now(timezone.utc))
        assert result == []

    def test_finds_runs_in_window(self, tmp_path):
        """Runs within the time window are found."""
        # Create a trace dir with a recent progress.jsonl
        run_dir = tmp_path / "build-test-001"
        run_dir.mkdir()
        _write_progress(run_dir, PROGRESS_COMPLETE)
        
        now = datetime.now(timezone.utc)
        runs = dd._scan_traces(tmp_path, 24, now)
        assert len(runs) == 1
        assert runs[0]["terminal"] == "COMPLETE"

    def test_filters_old_runs(self, tmp_path):
        """Runs outside the time window are filtered out."""
        run_dir = tmp_path / "build-old-001"
        run_dir.mkdir()
        # Write a progress.jsonl with old timestamp
        old_events = [
            {"ts": 1000.0, "step": "charter_result", "n_criteria": 1},
            {"ts": 1000.0, "step": "terminal", "terminal": "COMPLETE"},
        ]
        _write_progress(run_dir, old_events)
        
        now = datetime.now(timezone.utc)
        runs = dd._scan_traces(tmp_path, 24, now)
        assert len(runs) == 0  # filtered out (ts=1000 is 1970)

    def test_falls_back_to_trace_jsonl(self, tmp_path):
        """When progress.jsonl doesn't exist, falls back to trace.jsonl."""
        run_dir = tmp_path / "build-trace-only"
        run_dir.mkdir()
        trace_path = run_dir / "trace.jsonl"
        with open(trace_path, "w") as f:
            f.write(json.dumps({"ts": _ts(225), "step": "charter", "intent": "test intent", "n_criteria": 2}) + "\n")
            f.write(json.dumps({"ts": _ts(0), "step": "terminal", "terminal": "COMPLETE", "reason": ""}) + "\n")
        
        now = datetime.now(timezone.utc)
        runs = dd._scan_traces(tmp_path, 24, now)
        assert len(runs) == 1
        assert runs[0]["terminal"] == "COMPLETE"
        assert runs[0]["intent"] == "test intent"


# ── Tests: generate_digest

class TestGenerateDigest:
    """Test the generate_digest function."""

    def test_empty_runs_and_learnings(self):
        """Empty runs + empty learnings = empty string (silent on empty)."""
        result = dd.generate_digest([], [], 24)
        assert result == ""

    def test_complete_run_digest(self):
        """A COMPLETE run produces a valid digest."""
        runs = [{
            "terminal": "COMPLETE",
            "reason": "",
            "intent": "Create slug.py",
            "n_criteria": 3,
            "duration_s": 212.0,
            "rebuilds": 0,
            "overfit_suspects": [],
            "judge_verdicts": [
                {"criterion": "c1", "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
            ],
            "evidence_results": [{"passed": 3, "total": 3, "red": []}],
            "run_dt": datetime.now(timezone.utc),
            "_schema_mismatch": False,
            "trace_dir": "build-001",
        }]
        result = dd.generate_digest(runs, [], 24)
        assert "devloop digest" in result
        assert "COMPLETE" in result
        assert "slug.py" in result
        assert "✅" in result

    def test_human_review_shows_reason(self):
        """A HUMAN_REVIEW run shows the failure reason."""
        runs = [{
            "terminal": "HUMAN_REVIEW",
            "reason": "test fault: criteria [c2] have no judge-trusted test",
            "intent": "Build something",
            "n_criteria": 2,
            "duration_s": 100.0,
            "rebuilds": 1,
            "overfit_suspects": [],
            "judge_verdicts": None,
            "evidence_results": [],
            "run_dt": datetime.now(timezone.utc),
            "_schema_mismatch": False,
            "trace_dir": "build-002",
        }]
        result = dd.generate_digest(runs, [], 24)
        assert "HUMAN_REVIEW" in result
        assert "test fault" in result
        assert "Failure modes" in result

    def test_untrusted_judge_shown(self):
        """Untrusted judge verdicts appear in per-run details."""
        runs = [{
            "terminal": "COMPLETE",
            "reason": "",
            "intent": "test",
            "n_criteria": 2,
            "duration_s": 100.0,
            "rebuilds": 0,
            "overfit_suspects": [],
            "judge_verdicts": [
                {"criterion": "c1", "judge_a": True, "judge_b": True, "judge_a_reason": "", "judge_b_reason": ""},
                {"criterion": "c2", "judge_a": False, "judge_b": True, "judge_a_reason": "bad assertion", "judge_b_reason": ""},
            ],
            "evidence_results": [{"passed": 2, "total": 2, "red": []}],
            "run_dt": datetime.now(timezone.utc),
            "_schema_mismatch": False,
            "trace_dir": "build-003",
        }]
        result = dd.generate_digest(runs, [], 24)
        assert "c2" in result
        assert "judge_a ✗" in result
        assert "bad assertion" in result


# ── Tests: main / silent-on-empty

class TestMain:
    """Test the main function's CLI behavior."""

    def test_silent_on_empty_traces_dir(self, tmp_path):
        """No runs → empty stdout, exit 0."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(dd.__file__).parent / "devloop_digest.py"),
             "--traces-dir", str(tmp_path), "--hours", "24"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_json_output(self, tmp_path):
        """JSON output mode produces valid JSON."""
        run_dir = tmp_path / "build-json-001"
        run_dir.mkdir()
        _write_progress(run_dir, PROGRESS_COMPLETE)
        
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(dd.__file__).parent / "devloop_digest.py"),
             "--traces-dir", str(tmp_path), "--hours", "24", "--json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert data["runs"][0]["terminal"] == "COMPLETE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])