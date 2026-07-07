"""dod_oracle.py — makes the Definition of Done the test oracle.

The test's authority must derive from the human-anchored DoD, not from possibly-buggy
code. One deterministic guard + one judged guard:

  * check_structural_coverage() — every DoD criterion must own >=1 test, FAIL CLOSED
    before any code is trusted. Coverage-of-ORACLE, not coverage-of-code.
  * judge_assertions() — a JUDGE model (!= implementer) confirms each test's assertion
    actually encodes its criterion. Gut-check tweak: 2-MODEL AGREEMENT + deterministic
    escalation (NOT self-reported-confidence gating).

(A holdout split used to live here, permanently OFF. Deleted 2026-07-01: the coder holds
file+terminal tools in the worktree where the designer already wrote every test FILE, so
prompt-side hiding could never deliver the anti-gaming property it promised. Overfit is
covered presence-based instead: 2 distinct judges + per-criterion evidence + the
whole-suite regression gate.)

Borrowed concepts: hermes-agent-self-evolution (structured judge feedback).
"""
from __future__ import annotations

import concurrent.futures
from typing import Callable, Sequence


def check_structural_coverage(criteria: Sequence[dict],
                              test_to_criterion: dict[str, str]) -> tuple[bool, list[str]]:
    """Return (ok, uncovered_ids). ok is True only if EVERY criterion id is covered by
    >=1 test. Fail-closed: an uncovered criterion blocks trusting any code."""
    covered = set(test_to_criterion.values())
    required = [c["id"] for c in criteria if c.get("id")]
    uncovered = [cid for cid in required if cid not in covered]
    return (len(uncovered) == 0, uncovered)


def judge_assertions(tests: Sequence[dict], criteria_by_id: dict[str, dict],
                     judge_a: Callable[[dict, Sequence[str]], bool],
                     judge_b: Callable[[dict, Sequence[str]], bool],
                     max_workers: int = 8) -> list[dict]:
    """For each CRITERION, ask TWO independent judges (different models, both != implementer)
    whether that criterion's tests, TAKEN TOGETHER, verify it.

    Judged per-criterion, NOT per-test, on purpose: a good designer SPLITS a criterion across
    several focused test functions (e.g. one for the True cases, one for the False cases). Judging
    each test alone against the whole criterion rejects every partial test and fail-closes a
    correct build (a real failure mode we hit). Judging the whole set instead credits the split
    suite — and still catches a compound criterion missing a sub-test, because the judges see the
    set lacks it. The Evidence gate separately requires every one of those tests to pass green.

    `judge(criterion, test_ids) -> bool | (bool, str)`. Judges may return a (vote, reason)
    tuple where reason is a short explanation of WHY the test was rejected (Minimax P4:
    without reason text the redesigner is blind — it knows judges voted NO but not what to fix).
    Legacy bool returns are wrapped as (vote, "") for backward compatibility.

    Returns per-criterion verdicts:
    [{criterion_id, test_ids, judge_a, judge_b, judge_a_reason, judge_b_reason,
      encodes, escalate, reason}]. Deterministic escalation: escalate when the two judges
    DISAGREE (NOT on self-reported confidence); an unknown criterion fail-closes.
    """
    by_crit: dict[str, list[str]] = {}
    order: list[str] = []
    for t in tests:
        cid = t.get("criterion_id")
        if cid not in by_crit:
            by_crit[cid] = []
            order.append(cid)
        by_crit[cid].append(t.get("test_id"))

    def _unwrap(result):
        """Normalize a judge return: bool -> (bool, ''), (bool, str) -> (bool, str)."""
        if isinstance(result, tuple) and len(result) == 2:
            return bool(result[0]), str(result[1] or "")
        return bool(result), ""

    # The judge calls are independent and IO-bound (each is a cloud round-trip), so fire them all
    # CONCURRENTLY: a 5-criterion charter costs ~one judge round-trip, not ten sequential ones
    # (the latency that was making real multi-criterion runs exceed the wall-clock budget).
    known = [cid for cid in order if criteria_by_id.get(cid) is not None]
    bits: dict[tuple, tuple] = {}     # (bool, str)
    if known:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, 2 * len(known))) as ex:
            futs = {}
            for cid in known:
                crit = criteria_by_id[cid]
                futs[(cid, "a")] = ex.submit(judge_a, crit, by_crit[cid])
                futs[(cid, "b")] = ex.submit(judge_b, crit, by_crit[cid])
            bits = {k: _unwrap(f.result()) for k, f in futs.items()}

    out: list[dict] = []
    for cid in order:
        crit = criteria_by_id.get(cid)
        test_ids = by_crit[cid]
        if crit is None:
            out.append({"criterion_id": cid, "test_ids": test_ids, "judge_a": None, "judge_b": None,
                        "judge_a_reason": "", "judge_b_reason": "",
                        "encodes": False, "escalate": True, "reason": "tests map to unknown criterion"})
            continue
        a_vote, a_reason = bits[(cid, "a")]
        b_vote, b_reason = bits[(cid, "b")]
        # Compose a combined reason: if both reject, merge their reasons; if split, show both.
        if not a_vote and not b_vote:
            parts = []
            if a_reason:
                parts.append(f"judge_a: {a_reason}")
            if b_reason:
                parts.append(f"judge_b: {b_reason}")
            combined = "; ".join(parts) if parts else "both judges rejected the test"
        elif a_vote != b_vote:
            parts = []
            if not a_vote and a_reason:
                parts.append(f"judge_a rejected: {a_reason}")
            if not b_vote and b_reason:
                parts.append(f"judge_b rejected: {b_reason}")
            combined = "; ".join(parts) if parts else "judge disagreement"
        else:
            combined = "both judges agree"
        out.append({
            "criterion_id": cid,
            "test_ids": test_ids,
            "judge_a": a_vote,               # per-judge votes retained (trace/post-hoc diagnosis)
            "judge_b": b_vote,
            "judge_a_reason": a_reason,       # WHY the judge voted the way it did (Minimax P4)
            "judge_b_reason": b_reason,
            "encodes": a_vote and b_vote,     # both must agree the set verifies it -> trusted
            "escalate": a_vote != b_vote,     # disagreement -> escalate
            "reason": combined,
        })
    return out


