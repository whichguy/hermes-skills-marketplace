"""Core-pipeline integration test (P2 from advisor review).

Exercises the implement → lint → evidence → gate path with mocked LLM calls
in a real git worktree. This is NOT an E2E test (no real models) — it's an
integration test that verifies the deterministic parts of the pipeline work
together across module boundaries.

The advisor review noted: "Audit integration coverage of the critical path;
if gaps found, add a core-pipeline integration test with mocked LLM responses
and a temp git worktree (not a ratio-padding test)."

Run: cd /opt/data/skills/software-development/devloop && python3 -m pytest tests/test_integration_pipeline.py -q
(or: python3 tests/test_integration_pipeline.py)
"""
import os
import sys
import tempfile
import subprocess

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import gate          # noqa: E402
import lint          # noqa: E402
import evidence      # noqa: E402
import state         # noqa: E402
import config        # noqa: E402
import loop          # noqa: E402


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], check=check,
                          capture_output=True, text=True)


def _init_repo(repo):
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "x")


def _charter():
    return {
        "interpreted_intent": "create calc.py",
        "purpose": "a calculator module",
        "dod": [{"id": "c1", "criterion": "add(a,b) returns a+b",
                 "verify_intent": "add(2,3)==5", "kind": "unit"}],
        "assumptions": [{"text": "standard arithmetic", "confidence": 0.9}],
        "open_questions": [],
        "happy_path": "call add(2,3)",
        "blast_radius": {"files": ["calc.py"], "order": ["calc.py"]},
        "backoff_map": [],
        "advisors_verdict": "ok",
        "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def test_lint_gate_on_implemented_file():
    """Lint gate runs on a file the coder created — verifies lint.py + loop._lint_gate."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        # Coder created calc.py
        calc_path = os.path.join(repo, "calc.py")
        with open(calc_path, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        # Lint gate
        ok, feedback = loop._lint_gate([calc_path], cwd=repo, run_dir=root, attempt=0)
        assert ok is True
        assert feedback is None


def test_lint_gate_catches_syntax_error():
    """Lint gate catches a syntax error in the implemented file."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        bad_path = os.path.join(repo, "calc.py")
        with open(bad_path, "w") as f:
            f.write("def add(a, b)\n    return a +\n")  # syntax error
        ok, feedback = loop._lint_gate([bad_path], cwd=repo, run_dir=root, attempt=0)
        assert ok is False
        assert feedback is not None
        assert "calc.py" in feedback


def test_evidence_run_on_real_subprocess():
    """Evidence.run executes a real subprocess and returns a structured Evidence."""
    with tempfile.TemporaryDirectory() as root:
        ev = evidence.run("c1", [sys.executable, "-c", "print('hello')"], cwd=root)
        assert ev.criterion_id == "c1"
        assert ev.exit_code == 0
        assert ev.passed is True
        assert "hello" in (ev.stdout_tail or "")


def test_evidence_run_failing_subprocess():
    """Evidence.run captures a failing subprocess."""
    with tempfile.TemporaryDirectory() as root:
        ev = evidence.run("c1", [sys.executable, "-c", "import sys; sys.exit(1)"], cwd=root)
        assert ev.exit_code == 1
        assert ev.passed is False


def test_gate_stop_condition_after_evidence():
    """Integration: stop_condition reads evidence ledger from evidence.run."""
    with tempfile.TemporaryDirectory() as root:
        # Run a real evidence command
        ev = evidence.run("c1", [sys.executable, "-c", "print('ok')"], cwd=root)
        ledger = {"c1": ev}
        charter = _charter()
        verdicts = [{"criterion_id": "c1", "encodes": True, "escalate": False,
                     "judge_a": True, "judge_b": True,
                     "judge_a_reason": "", "judge_b_reason": ""}]
        ok, reason = gate.stop_condition(charter, ledger, True, verdicts)
        assert ok is True
        assert "DoD-SATISFIED" in reason


def test_gate_stop_condition_after_failing_evidence():
    """Integration: stop_condition fails when evidence shows a failure."""
    with tempfile.TemporaryDirectory() as root:
        ev = evidence.run("c1", [sys.executable, "-c", "import sys; sys.exit(1)"], cwd=root)
        ledger = {"c1": ev}
        charter = _charter()
        verdicts = [{"criterion_id": "c1", "encodes": True, "escalate": False,
                     "judge_a": True, "judge_b": True,
                     "judge_a_reason": "", "judge_b_reason": ""}]
        ok, reason = gate.stop_condition(charter, ledger, True, verdicts)
        assert ok is False
        assert "c1" in reason


def test_do_implement_then_lint_gate_pipeline():
    """Integration: _do_implement returns paths, _lint_gate uses those paths."""
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "repo")
        _init_repo(repo)
        # Fake implement that creates a file
        def fake_implement(charter, attempt, last_failure):
            calc_path = os.path.join(repo, "calc.py")
            with open(calc_path, "w") as f:
                f.write("def add(a, b):\n    return a + b\n")
            return {"exit_code": 0, "files_changed": 1, "summary": "created calc.py",
                    "changed_paths": [calc_path]}
        ec, fc, paths = loop._do_implement(fake_implement, _charter(), 0, None, root)
        assert ec == 0
        assert paths == [os.path.join(repo, "calc.py")]
        # Now run lint gate on those paths
        ok, _ = loop._lint_gate(paths, cwd=repo, run_dir=root, attempt=0)
        assert ok is True


def test_state_run_lifecycle():
    """Integration: state.new_run_state → save_checkpoint → load_checkpoint round-trip."""
    charter = _charter()
    st = state.new_run_state(charter)
    assert st["rebuild_count"] == 0
    assert st["replan_count"] == 0
    # Modify state
    state.on_rebuild_fail(st)
    assert st["rebuild_count"] == 1
    state.on_repair(st)
    assert st["rebuild_count"] == 0  # on_repair resets the rebuild count
    # Save and load round-trip
    with tempfile.TemporaryDirectory() as rd:
        state.save_checkpoint(rd, st)
        loaded = state.load_checkpoint(rd)
        assert loaded is not None
        assert loaded["rebuild_count"] == 0  # on_repair reset was persisted


def test_lint_discover_finds_available_linters():
    """Integration: lint.discover probes available linters for the file types present."""
    with tempfile.TemporaryDirectory() as root:
        # Create a .py file
        py_file = os.path.join(root, "test_file.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")
        coverage = lint.discover([py_file])
        assert isinstance(coverage, list)
        assert len(coverage) > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} integration tests passed")