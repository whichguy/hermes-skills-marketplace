"""gate.py — the gates the agent cannot argue with.

(a) ambiguity_gate    — BOOLEAN headless decision (no score arithmetic / pseudo-precision).
                        Validates Charter shape first, then blocking-question / confidence.
(a2) vague_goal_gate  — deterministic screen for unmeasurable quality goals ("make it faster"):
                        a marker without a measurable target in the REQUEST, or a criterion
                        quoting a number the request never stated, routes to HUMAN_REVIEW.
(b) council_gate      — wraps the advisors skill; requires all seats present + distinct-seat
                        quorum; checks completeness AND satisfaction; FAIL-CLOSED on
                        None/partial/exception. (Available but NOT wired into the stop.)
(c) stop_condition    — REFUSES COMPLETE unless every DoD criterion has (1) coverage, (2) a
                        passing assertion judge, (3) a passing evidence record. Consumes the
                        DoD-oracle results so the "tests encode the DoD" guarantee is
                        code-enforced, not prose.
(d) backoff_exhausted — code-enforced termination backstop reading the persisted run counters.
(e) regression_gate   — the would-be-COMPLETE must also leave the WHOLE repo suite green
                        (modify tasks must not break pre-existing tests).
"""
from __future__ import annotations

import math
import re
from typing import Callable, Sequence

import config
import evidence as _evidence
import state as _state


# --- (a) ambiguity gate -------------------------------------------------------
def ambiguity_gate(charter: dict) -> tuple[str, str]:
    """Return (decision, reason) where decision is config.DECISION_PROCEED or
    config.DECISION_ROUTE_HUMAN_REVIEW.

    Order: (0) Charter must be structurally valid; (1) no blocking open-question;
    (2) min(assumption.confidence) >= CONFIDENCE_FLOOR. Correctness-biased (decision 2):
    a malformed/empty/low-confidence Charter routes to human, never auto-PROCEEDs.
    Boolean by design — confidences are non-deterministic model outputs; arithmetic on
    them is pseudo-precision.
    """
    hr = config.DECISION_ROUTE_HUMAN_REVIEW
    errs = _state.validate_charter(charter)
    if errs:
        return hr, f"invalid Charter: {errs[:3]}"
    blocking = [q for q in charter.get("open_questions", []) if q.get("blocking")]
    if blocking:
        return hr, f"{len(blocking)} blocking open question(s): {blocking[0].get('text', '')[:120]}"
    # Coerce confidences; a missing/null/non-numeric confidence is treated as 0.0 (below floor),
    # and an empty assumptions list is treated as below-floor (cannot vacuously PROCEED).
    raw = [a.get("confidence") for a in charter.get("assumptions", [])]
    # A finite number is required; NaN/±Inf (json.loads accepts bare NaN) and non-numbers
    # coerce to 0.0 (below floor) so a malformed confidence can never auto-PROCEED.
    confs = [c if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c)
             else 0.0 for c in raw]
    low = min(confs) if confs else 0.0
    if low < config.CONFIDENCE_FLOOR:
        return hr, f"min assumption confidence {low:.2f} < floor {config.CONFIDENCE_FLOOR}"
    return config.DECISION_PROCEED, "valid Charter; no blocking questions; confidence above floor"


# --- (a2) vague-goal gate -------------------------------------------------------
# Vague quality-goal markers. Deliberately a DUMB word list (no LLM classifier): the only
# job is to detect the dangerous request shape; over-matching routes to a human (safe),
# never to COMPLETE.
_VAGUE_MARKERS = re.compile(
    r"\b(?:faster|slower|cleaner|better|optimi[sz]|improv|robust|efficien|"
    r"speed[\s._-]?up|performan)", re.IGNORECASE)
_NUMBERS = re.compile(r"\d+(?:\.\d+)?")


def vague_goal_gate(request: str, charter: dict) -> tuple[str, str]:
    """Code-enforce the unmeasurable-goal rule that previously lived ONLY in the charter/refine
    prompts — and provably failed there (spike_recal: 'Make the app faster.' reached COMPLETE
    twice off a planner-fabricated benchmark; the later GO runs were saved only by an
    accidental empty DoD).

    Deterministic, marker-scoped:
      (1) no vague marker in the request           -> PROCEED (concrete tasks untouched);
      (2) marker + NO number in the request        -> ROUTE_HUMAN_REVIEW (nothing measurable
          was requested; a model must not invent the target);
      (3) marker + request numbers                 -> any number in a DoD criterion that the
          request never stated (float-set compare) is a fabricated benchmark
                                                   -> ROUTE_HUMAN_REVIEW.
    By construction this gate only ADDS routes to a human — it has no COMPLETE path.
    Known over-route (accepted, correctness-biased): over-matching a marker costs a human
    look, never a false COMPLETE. (Folded project lessons no longer reach this gate —
    runner.py strips everything under config.LESSONS_HEADER before gating.)
    """
    hr = config.DECISION_ROUTE_HUMAN_REVIEW
    hits = _VAGUE_MARKERS.findall(request or "")
    if not hits:
        return config.DECISION_PROCEED, "no vague quality-goal marker in request"
    req_nums = {float(n) for n in _NUMBERS.findall(request or "")}
    if not req_nums:
        return hr, (f"vague quality goal ({hits[0]!r}) with no measurable target in the request; "
                    "refusing to let a model fabricate a benchmark")
    fabricated = []
    for c in charter.get("dod") or []:
        if not isinstance(c, dict):
            continue     # malformed criteria are validate_charter's job, not this gate's
        text = f"{c.get('criterion', '')} {c.get('verify_intent', '')}"
        fabricated += [(c.get("id"), n) for n in _NUMBERS.findall(text)
                       if float(n) not in req_nums]
    if fabricated:
        cid, n = fabricated[0]
        return hr, (f"criterion {cid} quotes a number ({n}) not present in the request "
                    f"(fabricated benchmark; {len(fabricated)} such value(s))")
    return config.DECISION_PROCEED, "quality goal quotes only targets stated in the request"


# --- (b) council gate ---------------------------------------------------------
def council_gate(criteria: Sequence[dict], interpreted_intent: str,
                 dispatch_advisors: Callable[[Sequence[dict], str], list[dict]]) -> tuple[bool, str]:
    """Run the advisors council as a HARD gate. Checks completeness AND satisfaction
    (not just "are these criteria met" but "do they fully deliver the interpreted intent,
    is any required criterion missing?").

    `dispatch_advisors(criteria, interpreted_intent)` returns per-seat verdicts:
    [{seat, affirm: bool|None, missing: [...], note}]. A None/absent vote is a FAILURE.

    Returns (affirmed, reason). Fail-closed on exception, fewer than COUNCIL_SIZE distinct
    seats, sub-quorum affirmations, or any flagged-missing criterion.
    """
    try:
        verdicts = dispatch_advisors(criteria, interpreted_intent)
    except Exception as e:  # noqa: BLE001 — any dispatch failure must fail closed
        return False, f"advisors dispatch failed ({type(e).__name__}); fail-closed -> not affirmed"
    if not verdicts:
        return False, "no advisor verdicts returned; fail-closed"
    try:   # verdict-shape parsing is INSIDE a guard: a non-dict verdict must fail closed, not crash
        seats_present = {v.get("seat") for v in verdicts if v.get("seat")}
        affirm_seats = {v.get("seat") for v in verdicts if v.get("affirm") is True and v.get("seat")}
        missing = [m for v in verdicts for m in (v.get("missing") or [])]
    except (AttributeError, TypeError) as e:  # malformed (non-dict) verdict shape -> fail closed
        return False, f"advisor verdicts malformed ({type(e).__name__}); fail-closed -> not affirmed"
    if len(seats_present) < config.COUNCIL_SIZE:
        return False, f"only {len(seats_present)}/{config.COUNCIL_SIZE} distinct advisor seats present; fail-closed"
    if len(affirm_seats) < config.COUNCIL_QUORUM:
        return False, f"council quorum not met ({len(affirm_seats)}/{config.COUNCIL_QUORUM}); missing={missing[:5]}"
    if missing:
        return False, f"council flagged missing criteria (incomplete DoD): {missing[:5]}"
    return True, f"council affirmed {len(affirm_seats)}/{len(seats_present)} seats, no missing criteria"


# --- (c) stop condition -------------------------------------------------------
def _judges_ok(required_ids: Sequence[str], judge_verdicts: Sequence[dict]) -> tuple[bool, str]:
    """Each required criterion needs >=1 TRUSTED test verdict — both judges agree it encodes the
    criterion (encodes True, escalate False). Extra tests the judges reject or split on neither
    help nor hurt: a criterion is verified by the PRESENCE of one trusted test, and the Evidence
    gate separately requires ALL of its tests to pass green. (We do NOT fail a criterion just
    because a thorough designer added edge-case tests a judge nitpicks as not "encoding" the
    narrow verify_intent — that only manufactures false-negatives; the trusted-test requirement
    below + all-green evidence already hold the fail-closed line.) Fail-closed on a criterion with
    no verdict at all, or with no trusted test among its verdicts."""
    by_crit: dict[str, list[dict]] = {}
    for v in judge_verdicts or []:
        by_crit.setdefault(v.get("criterion_id"), []).append(v)
    for cid in required_ids:
        vs = by_crit.get(cid, [])
        if not vs:
            return False, f"criterion {cid} has no assertion-judge verdict"
        if not any(v.get("encodes") is True and not v.get("escalate") for v in vs):
            return False, f"criterion {cid} has no trusted (encodes & !escalate) test"
    return True, "every criterion has a trusted test that encodes it"


def untrusted_criteria(charter: dict, judge_verdicts: Sequence[dict]) -> list:
    """Criteria whose tests are NOT judge-trusted (no verdict with encodes True & escalate False) —
    a TEST fault, not a code fault: the judges read the test SOURCE (unchanged across rebuilds), so
    re-IMPLEMENTing the code can never make these criteria pass. The loop uses this to ROUTE
    (re-IMPLEMENT a code fault vs route a test fault to a human / project re-attempt that re-DESIGNs),
    instead of burning the rebuild budget on a test the code can't fix (#18)."""
    by_crit: dict[str, list[dict]] = {}
    for v in judge_verdicts or []:
        by_crit.setdefault(v.get("criterion_id"), []).append(v)
    return [c["id"] for c in charter.get("dod", []) if c.get("id") and not any(
        v.get("encodes") is True and not v.get("escalate") for v in by_crit.get(c["id"], []))]


def stop_condition(charter: dict, evidence_ledger: dict,
                   coverage_ok: bool, judge_verdicts: Sequence[dict]) -> tuple[bool, str]:
    """COMPLETE iff: every DoD criterion has an id (fail-closed on any id-less criterion);
    structural coverage holds; the assertion judge trusts a test per criterion; and every
    criterion has a passing Evidence record. The single semantic stop replacing all stagnation
    machinery. (A final advisors COUNCIL is NOT part of the stop today — council_gate exists but
    is not wired; the coverage + distinct-model judge + real-evidence trio is the verification.)"""
    dod = charter.get("dod", [])
    if not dod:
        return False, "no DoD criteria; cannot be COMPLETE"
    if any(not c.get("id") for c in dod):
        return False, "a DoD criterion has no id and cannot be verified; fail-closed"
    required_ids = [c["id"] for c in dod]
    if not coverage_ok:
        return False, "DoD structural coverage failed (a criterion has no covering test)"
    judges_ok, jreason = _judges_ok(required_ids, judge_verdicts)
    if not judges_ok:
        return False, jreason
    if not _evidence.all_passing(evidence_ledger, required_ids):
        unmet = [cid for cid in required_ids
                 if cid not in evidence_ledger or not _evidence._passed(evidence_ledger[cid])]
        return False, f"criteria without passing evidence: {unmet[:8]}"
    return True, "DoD-SATISFIED: coverage + judged tests + passing evidence"


# --- (c2) judged mid-run test repair: the audit (user decision 2026-07-02) -----
def audit_tests(charter: dict, evidence_ledger: dict, tests_by_criterion: dict,
                audit_a, audit_b) -> tuple[list, list]:
    """Step 1 of the judged mid-run TEST REPAIR: for each criterion with RED evidence, ask two
    independent auditors whether the TEST asserts the wrong output (a designer mistake the coder
    can never code past). Fail-CLOSED toward the oracle: only a UNANIMOUS two-auditor indictment
    flags a test as wrong — dissent, a missing auditor, or a crashed auditor leaves the test
    trusted (the run then routes to a human exactly as before). Criteria with green or missing
    evidence are NEVER audited (green tests are working oracles; only a red grind can indict).
    Returns (wrong_ids, details)."""
    wrong, details = [], []
    for c in charter.get("dod", []):
        cid = c.get("id")
        if not cid:
            continue
        ev = evidence_ledger.get(cid)
        if ev is None or _evidence._passed(ev):
            continue
        tail = (getattr(ev, "stderr_tail", "") or "")[-800:]
        tids = tests_by_criterion.get(cid, [])
        votes = []
        for fn in (audit_a, audit_b):
            try:
                votes.append(bool(fn(c, tids, tail)))
            except Exception:   # noqa: BLE001 — a crashed auditor never indicts the oracle
                votes.append(False)
        is_wrong = len(votes) == 2 and all(votes)
        details.append({"criterion_id": cid, "audit_a": votes[0], "audit_b": votes[1],
                        "wrong": is_wrong})
        if is_wrong:
            wrong.append(cid)
    return wrong, details


# --- (d) termination backstop -------------------------------------------------
def backoff_exhausted(run_state: dict) -> tuple[str, str]:
    """Code-enforced termination backstop the agent cannot iterate past. Reads the
    persisted run counters. Returns (action, reason) where action is one of
    'CONTINUE' | 'REPLAN' | 'HUMAN_REVIEW'."""
    rebuilds = run_state.get("rebuild_count", 0)
    replans = run_state.get("replan_count", 0)
    if replans >= config.MAX_REPLANS:
        return "HUMAN_REVIEW", f"replan_count {replans} >= MAX_REPLANS {config.MAX_REPLANS}"
    if rebuilds >= config.MAX_LOCAL_REBUILDS:
        return "REPLAN", f"rebuild_count {rebuilds} >= MAX_LOCAL_REBUILDS {config.MAX_LOCAL_REBUILDS}"
    return "CONTINUE", "within rebuild/replan caps"


# --- (e) whole-suite regression gate --------------------------------------------
def regression_gate(ev) -> tuple[bool, str]:
    """A would-be-COMPLETE must ALSO leave the repo's WHOLE test suite green — the per-criterion
    verify commands run only the DoD's own test nodes, so without this a modify task could break
    pre-existing tests and still COMPLETE (regression-blind).

    `ev` is the Evidence record of a full-suite run (e.g. `pytest -q` at the worktree root).
    Pass on exit 0 (green) or pytest exit 5 (NO TESTS COLLECTED — a repo with no suite has
    nothing to regress; the vacuous pass is safe because the DoD tests themselves are separately
    coverage-gated and evidence-gated). Fail-closed on None / timeout / any other exit.
    """
    if ev is None:
        return False, "no regression evidence; fail-closed"
    code = getattr(ev, "exit_code", None)
    if code in (0, 5):
        return True, ("whole-suite green" if code == 0
                      else "no tests collected (pytest exit 5); nothing to regress")
    return False, f"whole-suite regression red (exit {code})"
