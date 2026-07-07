"""Mutation-killing tests for evidence.py — the trust anchor / verification runner.

Each test closes a CONFIRMED coverage gap (a surviving mutant) recorded in
.devloop/impl_groups.json for src=="evidence.py". Every test asserts the CURRENT
(correct) behavior so the hypothetical old->new mutant would make it FAIL.

Deterministic, no LLM, no network. Uses real subprocess where the module needs it
(signal-kill honesty) and a subprocess.run spy for the timeout-wiring case — mirroring
test_smoke.py's blast_radius.subprocess.run monkeypatch idiom.

Run: cd ~/.hermes/skills/software-development/devloop && python3 -m pytest tests/test_evidence.py -q
(or: python3 tests/test_evidence.py for a dependency-free run)
"""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import evidence  # noqa: E402


# --- run(): signal-killed verification is NOT green --------------------------------
def test_evidence_signal_killed_is_not_green():
    # A command killed by a signal returns returncode = -signum (here -9 for SIGKILL).
    # passed must be exactly (returncode == 0); the `r.returncode <= 0` mutant would read
    # -9 as green -> a FALSE COMPLETE on a crashed/OOM-killed verification.
    ev = evidence.run("c1", [sys.executable, "-c",
                             "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
    assert ev.exit_code is not None and ev.exit_code < 0   # signal death -> negative exit code
    assert ev.passed is False                              # crashed verification must not read green
    # control: a clean exit 0 still reads green (guards against a constant-False passed)
    assert evidence.run("c1", [sys.executable, "-c", "pass"]).passed is True


# --- Evidence.from_dict(): missing 'passed' rehydrates fail-closed ----------------
def test_from_dict_missing_passed_fails_closed():
    # An older/partial/corrupt checkpoint missing the 'passed' field must rehydrate as
    # False (fail-closed). The `d.get("passed", True)` mutant would forge every criterion
    # green on resume, letting all_passing/stop_condition declare a false DoD-SATISFIED.
    assert evidence.Evidence.from_dict({"criterion_id": "c1", "cmd": ["x"]}).passed is False
    assert evidence.Evidence.from_dict(
        {"criterion_id": "c1", "cmd": ["x"], "passed": False}).passed is False
    # control: an explicitly-green dict still rehydrates True (default isn't a constant False)
    assert evidence.Evidence.from_dict(
        {"criterion_id": "c1", "cmd": ["x"], "passed": True}).passed is True


# --- _passed(): raw (un-rehydrated) dict missing 'passed' fails closed -------------
def test_passed_dict_missing_key_fails_closed():
    # all_passing()/gate.stop_condition() call _passed() directly on ledger values, which
    # may still be raw dicts. A dict missing 'passed' must read False; the
    # `e.get("passed", True)` mutant would count a garbled per-criterion record as green.
    assert evidence._passed({}) is False
    assert evidence._passed({"passed": False}) is False
    # control: a green dict reads True (default isn't a constant False)
    assert evidence._passed({"passed": True}) is True


# --- run(): default-timeout fallback is wired (non-termination guard) --------------
def test_run_applies_default_timeout_when_unset():
    # run() with no explicit timeout must fall back to evidence_timeout_s(). The
    # `timeout = timeout` mutant would pass timeout=None to subprocess.run, so a hung
    # verification command blocks the autonomous loop forever (loop.py calls run() w/o timeout).
    orig = evidence.subprocess.run
    captured = {}

    def spy(*a, **k):
        captured.update(k)
        return orig(*a, **k)

    evidence.subprocess.run = spy
    try:
        evidence.run("c1", ["true"])   # NO explicit timeout -> must use the fallback
    finally:
        evidence.subprocess.run = orig
    assert captured.get("timeout") is not None
    assert captured["timeout"] == evidence.evidence_timeout_s()
    # control: an explicit timeout is honored (pins the FALLBACK above, not a constant)
    captured.clear()
    evidence.subprocess.run = spy
    try:
        evidence.run("c1", ["true"], timeout=123)
    finally:
        evidence.subprocess.run = orig
    assert captured["timeout"] == 123


# --- evidence_timeout_s(): default timeout floor (policy: never lower) -------------
def test_evidence_timeout_floor():
    # Project policy (MEMORY: feedback_tokens_and_timeouts) forbids lowering the
    # verification timeout to "fix" a slow model. The `return 1` mutant (<600) prematurely
    # SIGKILLs slow-but-legit runs -> spurious passed=False -> churn.
    assert evidence.evidence_timeout_s() >= 600


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
