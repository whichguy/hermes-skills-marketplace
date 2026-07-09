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
import json
import os
import time
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
                     judge_a: Callable[[dict, Sequence[str]], bool | tuple[bool, str]],
                     judge_b: Callable[[dict, Sequence[str]], bool | tuple[bool, str]],
                     max_workers: int = 8, *, run_dir: str | None = None,
                     judge_a_model: str = "", judge_b_model: str = "",
                     tiebreaker: Callable[[dict, Sequence[str]], bool | tuple[bool, str]] | None = None,
                     tiebreaker_model: str = "") -> list[dict]:
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

    `tiebreaker` (optional, advisor review 2026-07-09): when judge_a and judge_b DISAGREE on a
    criterion, the tiebreaker judge is called to break the tie. The majority (2-of-3) wins:
    if the tiebreaker agrees with either judge, that side wins and encodes is set by the
    majority. If no tiebreaker is provided, the original fail-closed behavior is kept
    (disagreement -> escalate -> HUMAN_REVIEW). This adds cost ONLY on split votes, not on
    every criterion.

    Returns per-criterion verdicts:
    [{criterion_id, test_ids, judge_a, judge_b, judge_a_reason, judge_b_reason,
      encodes, escalate, reason, tiebreaker, tiebreaker_reason}]. Deterministic escalation:
    escalate when the two judges DISAGREE AND no tiebreaker resolved it (or no tiebreaker
    was provided); an unknown criterion fail-closes.
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
    # Collect split-vote criteria for the tiebreaker (advisor review 2026-07-09).
    # The tiebreaker is called ONLY when judge_a and judge_b disagree — adding cost
    # only on split votes, not on every criterion.
    split_cids: list[str] = []
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
        if a_vote != b_vote:
            split_cids.append(cid)
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

    # TIEBREAKER PHASE (advisor review 2026-07-09): on split votes, call the tiebreaker
    # judge to break the tie. Majority (2-of-3) wins. This runs concurrently across all
    # split-vote criteria to minimize latency.
    if tiebreaker and split_cids:
        tie_bits: dict[str, tuple] = {}  # cid -> (vote, reason)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(split_cids))) as ex:
            t_futs = {}
            for cid in split_cids:
                t_futs[cid] = ex.submit(tiebreaker, criteria_by_id[cid], by_crit[cid])
            tie_bits = {cid: _unwrap(f.result()) for cid, f in t_futs.items()}
        # Apply tiebreaker results to the verdicts
        for v in out:
            cid = v["criterion_id"]
            if cid not in tie_bits:
                continue
            t_vote, t_reason = tie_bits[cid]
            a_vote = v["judge_a"]
            b_vote = v["judge_b"]
            # Majority: if tiebreaker agrees with either judge, that side wins
            if t_vote == a_vote:
                # tiebreaker agrees with judge_a
                v["encodes"] = bool(a_vote)  # majority YES if a_vote is True
                v["escalate"] = False  # resolved by tiebreaker
                v["reason"] = f"tiebreaker agreed with judge_a ({'YES' if a_vote else 'NO'}); {v['reason']}"
            elif t_vote == b_vote:
                # tiebreaker agrees with judge_b
                v["encodes"] = bool(b_vote)  # majority YES if b_vote is True
                v["escalate"] = False  # resolved by tiebreaker
                v["reason"] = f"tiebreaker agreed with judge_b ({'YES' if b_vote else 'NO'}); {v['reason']}"
            # t_vote can only be True or False, so it MUST agree with one of them
            # Store tiebreaker details for logging
            v["tiebreaker"] = t_vote
            v["tiebreaker_reason"] = t_reason
    elif split_cids:
        # No tiebreaker provided — mark as unresolved
        for v in out:
            if v["criterion_id"] in split_cids:
                v["tiebreaker"] = None
                v["tiebreaker_reason"] = ""
    # Per-judge verdict logging (advisor review 2026-07-09): write structured records to
    # judge_verdicts.jsonl for the diagnostic sprint. Each record carries: run_id (if available
    # from the loop's global), criterion, both judges' votes + reasons + model names, the
    # split-vote outcome (encodes/escalate), and a timestamp. This is the data the 20-run
    # diagnostic will use to categorize split votes by prompt section, file count, etc.
    if run_dir:
        _log_judge_verdicts(run_dir, out, judge_a_model, judge_b_model, tiebreaker_model)
    return out


def _log_judge_verdicts(run_dir: str, verdicts: list[dict],
                        judge_a_model: str, judge_b_model: str,
                        tiebreaker_model: str = "") -> None:
    """Write per-judge verdict records to <run_dir>/judge_verdicts.jsonl for diagnostic analysis.
    Each line is a JSON record with: ts, run_id, criterion_id, test_ids, judge_a (vote, reason,
    model), judge_b (vote, reason, model), encodes, escalate, split_vote, prompt_version.

    Also appends to a persistent diagnostic log at <write-safe>/devloop-diagnostics/
    judge_verdicts.jsonl so data survives worktree cleanup (the run_dir is inside the worktree
    and gets removed on finalize)."""
    try:
        # Read run_id from the loop's global if available
        run_id = None
        try:
            import loop
            run_id = getattr(loop, "_PROGRESS_RUN_ID", None)
        except Exception:  # noqa: BLE001
            pass

        records = []
        for v in verdicts:
            record = {
                "ts": round(time.time(), 3),
                "run_id": run_id,
                "criterion_id": v["criterion_id"],
                "test_ids": v.get("test_ids", []),
                "judge_a": {
                    "vote": v.get("judge_a"),
                    "reason": v.get("judge_a_reason", ""),
                    "model": judge_a_model,
                },
                "judge_b": {
                    "vote": v.get("judge_b"),
                    "reason": v.get("judge_b_reason", ""),
                    "model": judge_b_model,
                },
                "encodes": v.get("encodes"),
                "escalate": v.get("escalate"),
                "split_vote": v.get("judge_a") != v.get("judge_b"),
                "tiebreaker": {
                    "vote": v.get("tiebreaker"),
                    "reason": v.get("tiebreaker_reason", ""),
                    "model": tiebreaker_model,
                } if v.get("tiebreaker") is not None else None,
                "prompt_version": "v1-judge-assertion",
            }
            records.append(record)

        # Write to run_dir (inside worktree — may not survive cleanup)
        path = os.path.join(str(run_dir), "judge_verdicts.jsonl")
        with open(path, "a") as f:
            for record in records:
                f.write(json.dumps(record, default=str) + "\n")

        # Also append to persistent diagnostic log (survives worktree cleanup)
        diag_dir = os.path.join(
            os.environ.get("HERMES_WRITE_SAFE_ROOT", "/opt/data"),
            "devloop-diagnostics"
        )
        os.makedirs(diag_dir, exist_ok=True)
        diag_path = os.path.join(diag_dir, "judge_verdicts.jsonl")
        with open(diag_path, "a") as f:
            for record in records:
                f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass  # logging is best-effort, never crashes the run


