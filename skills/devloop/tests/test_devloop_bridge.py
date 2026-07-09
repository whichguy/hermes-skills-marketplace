"""Tests for devloop_bridge.py — the sync/merge safety net (P1 from advisor review).

_regression_check is a thin wrapper around evidence.run + gate.regression_gate.
It does lazy imports inside the function, so we mock by injecting the modules
into sys.modules before calling.

Run: cd /opt/data/skills/software-development/devloop && python3 -m pytest tests/test_devloop_bridge.py -q
(or: python3 tests/test_devloop_bridge.py for a dependency-free run)
"""
import os
import sys
import tempfile
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)


def _setup_mocks(exit_code=0, passed=True, gate_ok=True, gate_reason="green"):
    """Set up mock evidence and gate modules in sys.modules so lazy imports see them.
    Returns (mock_ev, mock_gate, originals) — caller MUST restore originals in cleanup."""
    from evidence import Evidence

    ev = Evidence(criterion_id="__sync__", cmd=("python3", "-m", "pytest"),
                  exit_code=exit_code, passed=passed)
    mock_ev = mock.MagicMock()
    mock_ev.run.return_value = ev
    mock_gate = mock.MagicMock()
    mock_gate.regression_gate.return_value = (gate_ok, gate_reason)
    # Save originals so we can restore
    orig_ev = sys.modules.get("evidence")
    orig_gate = sys.modules.get("gate")
    sys.modules["evidence"] = mock_ev
    sys.modules["gate"] = mock_gate
    return mock_ev, mock_gate, (orig_ev, orig_gate)


def _restore_mocks(originals):
    """Restore original evidence and gate modules after mocking."""
    orig_ev, orig_gate = originals
    if orig_ev is not None:
        sys.modules["evidence"] = orig_ev
    else:
        sys.modules.pop("evidence", None)
    if orig_gate is not None:
        sys.modules["gate"] = orig_gate
    else:
        sys.modules.pop("gate", None)


def test_regression_check_pass_exit_zero():
    """Regression check with pytest exit 0 → (True, 'whole-suite green')."""
    _orig = _setup_mocks(exit_code=0, passed=True, gate_ok=True, gate_reason="whole-suite green")
    try:
        import devloop_bridge
        ok, reason = devloop_bridge._regression_check("/fake/cwd")
        assert ok is True
        assert "green" in reason
    finally:
        _restore_mocks(_orig[2])


def test_regression_check_fail_exit_nonzero():
    """Regression check with pytest exit 1 → (False, reason)."""
    _orig = _setup_mocks(exit_code=1, passed=False, gate_ok=False, gate_reason="whole-suite RED")
    try:
        import devloop_bridge
        ok, reason = devloop_bridge._regression_check("/fake/cwd")
        assert ok is False
        assert "RED" in reason
    finally:
        _restore_mocks(_orig[2])


def test_regression_check_vacuous_pass_exit_five():
    """Regression check with pytest exit 5 (no tests collected) → vacuous pass."""
    _orig = _setup_mocks(exit_code=5, passed=False, gate_ok=True, gate_reason="whole-suite green (vacuous)")
    try:
        import devloop_bridge
        ok, reason = devloop_bridge._regression_check("/fake/cwd")
        assert ok is True
        assert "vacuous" in reason
    finally:
        _restore_mocks(_orig[2])


def test_regression_check_calls_evidence_run_with_correct_args():
    """_regression_check calls evidence.run with __sync__ id and pytest command."""
    _orig = _setup_mocks(exit_code=0, passed=True, gate_ok=True, gate_reason="green")
    try:
        import devloop_bridge
        devloop_bridge._regression_check("/some/path")
        _orig[0].run.assert_called_once()
        call_args = _orig[0].run.call_args
        assert call_args[0][0] == "__sync__"
        cmd = call_args[0][1]
        assert "pytest" in " ".join(cmd) or "-m" in cmd
    finally:
        _restore_mocks(_orig[2])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} devloop_bridge tests passed")