"""Deterministic failure-path tests for devloop core gates and dispatch.

No LLM calls. Each test exercises a single fail-closed or crash-handling seam using
injected fakes and real temporary files where possible.

Run: cd /opt/data/skills/software-development/devloop &&
     uv run --with pytest --with pyyaml --with sqlparse --with mypy python3 -m pytest tests/test_failure_paths.py -v
"""
import json
import os
import sys
import tempfile
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config        # noqa: E402
import dispatch      # noqa: E402
import gate          # noqa: E402
import lint          # noqa: E402
import loop          # noqa: E402


def _charter(*, blocking=False, assumptions=None, confidence=0.9):
    return {
        "interpreted_intent": "make the script exit 0", "purpose": "demo",
        "dod": [{"id": "c1", "criterion": "script exits 0", "verify_intent": "exit==0", "kind": "shown"}],
        "assumptions": assumptions if assumptions is not None else [{"text": "python is available", "confidence": confidence}],
        "open_questions": [{"text": "which script?", "blocking": True}] if blocking else [],
        "happy_path": "write the script", "blast_radius": {"files": ["m.py"], "order": ["m.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


# (1) gate.ambiguity_gate rejection — blocking open question -> ROUTE_HUMAN_REVIEW
def test_ambiguity_gate_rejects_blocking_question():
    ch = _charter(blocking=True, confidence=0.95)  # confidence is fine, question blocks
    decision, reason = gate.ambiguity_gate(ch)
    assert decision == config.DECISION_ROUTE_HUMAN_REVIEW
    assert "blocking" in reason.lower()


# (2) gate.stop_condition — ALL criteria UNTRUSTED -> False, reason names the untrusted criterion
def test_stop_condition_all_untrusted_names_criteria():
    # _judges_ok short-circuits at the first untrusted criterion, so use a single-criterion
    # charter to keep the assertion crisp: the one-and-only criterion is untrusted.
    ch = {
        "interpreted_intent": "demo",
        "dod": [
            {"id": "c1", "criterion": "a", "verify_intent": "a", "kind": "shown"},
        ],
    }
    ledger = {}
    verdicts = [
        {"criterion_id": "c1", "encodes": False, "escalate": False,
         "judge_a": False, "judge_b": False},
    ]
    ok, reason = gate.stop_condition(ch, ledger, coverage_ok=True, judge_verdicts=verdicts)
    assert ok is False
    assert "c1" in reason and ("trusted" in reason.lower() or "verdict" in reason.lower())

    # Multi-criterion: still returns False (short-circuits at first untrusted id).
    ch["dod"].append({"id": "c2", "criterion": "b", "verify_intent": "b", "kind": "shown"})
    verdicts.append({"criterion_id": "c2", "encodes": False, "escalate": True,
                     "judge_a": True, "judge_b": True})
    ok2, _ = gate.stop_condition(ch, ledger, coverage_ok=True, judge_verdicts=verdicts)
    assert ok2 is False


# (3) loop._do_implement — implement that raises -> crash marker is emitted
def test_do_implement_exception_emits_crash_marker():
    with tempfile.TemporaryDirectory() as d:
        run_dir = os.path.join(d, "run")

        def boom(*a, **k):
            raise RuntimeError("coder exploded")

        with mock.patch.object(loop, "_progress_crash") as crash:
            ec, fc, paths = loop._do_implement(boom, _charter(), 0, None, run_dir)

        crash.assert_called_once()
        args, kwargs = crash.call_args
        assert args[1] == "implement"
        assert isinstance(args[2], RuntimeError)
        assert os.path.exists(os.path.join(run_dir, "trace.jsonl"))


# (4) dispatch._chat — model returns a refusal -> fail-closed behavior (bad result returned)
def test_chat_refusal_fail_closed_returns_bad_result():
    def always_refuse(prompt, model, **k):
        return ("I cannot assist with that request.", 0)
    orig_raw, orig_sleep = dispatch._chat_raw, dispatch._sleep
    dispatch._chat_raw = always_refuse
    dispatch._sleep = lambda *_: None
    try:
        out, code = dispatch._chat("p", "m", retries=1)
        # Fail-closed means the LAST bad result is handed back, not a fabricated success.
        assert "cannot assist" in out.lower()
        assert code == 0  # process exit was fine; content is unusable
    finally:
        dispatch._chat_raw, dispatch._sleep = orig_raw, orig_sleep


# (5) lint gate — non-zero linter exit -> ok=False, feedback names the file
def test_lint_gate_nonzero_exit_names_file():
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.py")
        open(bad, "w").write("def f(:\n    return 1\n")
        ok, results = lint.lint_paths([bad], cwd=d)
        assert ok is False
        fails = lint.failures(results)
        assert any(os.path.basename(bad) in (r.get("path") or "") for r in fails)
        # Loop-level wiring: feedback contains the file name
        with tempfile.TemporaryDirectory() as run_d:
            lint_ok, fb = loop._lint_gate([bad], d, os.path.join(run_d, "run"), 0)
            assert lint_ok is False
            assert any("bad.py" in k for k in (fb or {}))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} failure-path tests passed")
