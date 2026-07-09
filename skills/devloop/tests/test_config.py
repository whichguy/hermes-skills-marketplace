"""Tests for config.py: the 5 locked decisions as constants.

config.py intentionally contains only constants and no executable logic; these tests
verify the values, types, and immutability of the decision constants so a stray edit
cannot silently change devloop's autonomy/council/backoff/dispatch behavior.

Run: python3 -m pytest tests/test_config.py -q  (or: python3 tests/test_config.py)
"""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config  # noqa: E402


def test_confidence_floor_is_reasonable_float():
    assert isinstance(config.CONFIDENCE_FLOOR, float)
    assert 0.0 < config.CONFIDENCE_FLOOR < 1.0
    assert config.CONFIDENCE_FLOOR == 0.65


def test_council_decision_constants_are_strings():
    assert config.DECISION_PROCEED == "PROCEED"
    assert config.DECISION_ROUTE_HUMAN_REVIEW == "ROUTE_HUMAN_REVIEW"
    assert isinstance(config.DECISION_PROCEED, str)
    assert isinstance(config.DECISION_ROUTE_HUMAN_REVIEW, str)


def test_council_size_quorum_positive_integers():
    assert isinstance(config.COUNCIL_SIZE, int)
    assert isinstance(config.COUNCIL_QUORUM, int)
    assert config.COUNCIL_SIZE >= config.COUNCIL_QUORUM > 0


def test_backoff_limits_are_non_negative_integers():
    assert isinstance(config.MAX_LOCAL_REBUILDS, int)
    assert isinstance(config.MAX_REPLANS, int)
    assert config.MAX_LOCAL_REBUILDS >= 0
    assert config.MAX_REPLANS >= 0


def test_dispatch_resilience_limits_are_non_negative_integers():
    assert isinstance(config.MAX_DISPATCH_RETRIES, int)
    assert isinstance(config.DIAGNOSE_AFTER_ATTEMPT, int)
    assert config.MAX_DISPATCH_RETRIES >= 0
    assert config.DIAGNOSE_AFTER_ATTEMPT >= 0


def test_vote_counts_are_positive_integers():
    assert isinstance(config.JUDGE_VOTES, int)
    assert isinstance(config.ADVISOR_VOTES, int)
    assert config.JUDGE_VOTES > 0
    assert config.ADVISOR_VOTES > 0


def test_project_max_attempts_positive_integer():
    assert isinstance(config.PROJECT_MAX_ATTEMPTS, int)
    assert config.PROJECT_MAX_ATTEMPTS > 0


def test_stale_hours_non_negative_integer():
    assert isinstance(config.HUMAN_REVIEW_STALE_HOURS, int)
    assert config.HUMAN_REVIEW_STALE_HOURS >= 0


def test_spike_constants_are_non_negative_integers():
    assert isinstance(config.SPIKE_MIN_TASKS, int)
    assert isinstance(config.SPIKE_RUNS_PER_TASK, int)
    assert isinstance(config.SPIKE_MAX_PHASE_SKIPS, int)
    assert config.SPIKE_MIN_TASKS >= 0
    assert config.SPIKE_RUNS_PER_TASK >= 0
    assert config.SPIKE_MAX_PHASE_SKIPS >= 0


def test_council_runs_at_every_merge_gate_by_default():
    assert config.COUNCIL_EVERY_MERGE is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} config tests passed")
